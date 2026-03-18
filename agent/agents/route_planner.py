"""Route Planner agent — optimizes stop order and calculates pricing."""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from agent.prompts import ROUTE_PLANNER_PROMPT
from agent.state import EventState
from agent.tools.google_maps import get_travel_time
from agent.tools.pricing import calculate_pricing
from agent.utils import get_text


TOOLS = [get_travel_time, calculate_pricing]


def _get_real_travel_time(origin: dict, destination: dict) -> int:
    """Get real driving time between two places via Google Maps Routes API.

    Returns duration in minutes. Falls back to 10 min if API fails or coords missing.
    """
    origin_lat = origin.get("latitude")
    origin_lng = origin.get("longitude")
    dest_lat = destination.get("latitude")
    dest_lng = destination.get("longitude")

    if not all([origin_lat, origin_lng, dest_lat, dest_lng]):
        return 10  # fallback — no coordinates

    try:
        result = get_travel_time.invoke({
            "origin_lat": float(origin_lat),
            "origin_lng": float(origin_lng),
            "dest_lat": float(dest_lat),
            "dest_lng": float(dest_lng),
            "travel_mode": "DRIVE",
        })
        parsed = json.loads(result)
        travel_min = parsed.get("duration_minutes", 10)
        return max(int(round(travel_min)), 1)
    except Exception:
        return 10  # fallback


def route_planner_node(state: EventState) -> dict:
    """Optimize route order, calculate travel times, and compute pricing.

    Two modes:
    1. First pass: build route + pricing, present for approval
    2. Approval mode: process user's response (approve, swap, remove, etc.)
    """
    event = state.get("event_details", {})
    places = state.get("approved_places") or state.get("places", [])

    if not places:
        return {
            "validation_result": {},
            "messages": [AIMessage(content="I need places to plan a route. Let me search for venues first.")],
        }

    # Approval mode
    if state.get("awaiting_approval") == "route" and state.get("optimized_route"):
        return _handle_route_approval(state)

    # First pass — build route and pricing
    llm = ChatOpenAI(model="gpt-4o", temperature=0.2).bind_tools(TOOLS)

    places_desc = json.dumps(places, indent=2, default=str)
    group_size = event.get("group_size", 10)
    duration = event.get("duration_hours", 8)
    preferences = event.get("preferences", ["adventure"])
    budget = event.get("budget_per_person")
    start_time = event.get("start_time", "09:00")
    end_time = event.get("end_time", "17:00")

    task = (
        f"Plan an optimized route for {group_size} people over {duration} hours.\n"
        f"Start time: {start_time} | End time: {end_time}\n"
        f"Preferences: {', '.join(preferences)}\n"
        f"Budget per person: {'EUR ' + str(budget) if budget else 'Not specified'}\n"
        f"Special requests: {json.dumps(event.get('special_requests', {}), default=str)}\n\n"
        f"Available stops:\n{places_desc}\n\n"
        f"Instructions:\n"
        f"1. Reorder stops to minimize total travel time (don't zigzag)\n"
        f"2. Use calculate_pricing to compute total costs. Choose appropriate activity types:\n"
        f"   - Use 'jeeps' for adventure/transport if group > 6, else 'walking'\n"
        f"   - Use 'food_experience' for food stops\n"
        f"   - Use 'cultural_tour' + 'entrance_fee' for cultural stops\n"
        f"3. Include lunch break if event > 5 hours\n"
        f"4. After getting the pricing, summarize the full plan with times and costs\n\n"
        f"NOTE: Travel times between stops will be calculated automatically using "
        f"Google Maps. You do NOT need to call get_travel_time — just focus on ordering "
        f"and pricing."
    )

    messages = [
        SystemMessage(content=ROUTE_PLANNER_PROMPT),
        HumanMessage(content=task),
    ]

    # Run tool-calling loop (pricing only — travel times are calculated separately)
    pricing = {}
    for _ in range(8):
        response = llm.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            break

        for tool_call in response.tool_calls:
            tool_fn = {t.name: t for t in TOOLS}.get(tool_call["name"])
            if tool_fn:
                result = tool_fn.invoke(tool_call["args"])
                messages.append(ToolMessage(content=str(result), tool_call_id=tool_call["id"]))

                if tool_call["name"] == "calculate_pricing":
                    try:
                        pricing = json.loads(result)
                    except (json.JSONDecodeError, TypeError):
                        pass

    # Build optimized route with real travel times from Google Maps
    optimized_route = _build_route(places, start_time, duration)

    # Format for user review
    approval_msg = _format_route_approval(optimized_route, pricing, start_time, end_time)

    return {
        "optimized_route": optimized_route,
        "pricing": pricing or {"total": 0, "per_person": 0, "note": "Pricing not calculated"},
        "awaiting_approval": "route",
        "validation_result": {},  # clear any previous validation
        "messages": [AIMessage(content=approval_msg)],
    }


def _handle_route_approval(state: EventState) -> dict:
    """Handle user's response to the route/itinerary confirmation."""
    event = state.get("event_details", {})
    optimized_route = state.get("optimized_route", [])
    pricing = state.get("pricing", {})
    start_time = event.get("start_time", "09:00")
    end_time = event.get("end_time", "17:00")

    user_messages = [m for m in state.get("messages", []) if isinstance(m, HumanMessage)]
    if not user_messages:
        return {"messages": [AIMessage(content="Please approve the route or tell me what to change.")]}

    user_response = get_text(user_messages[-1].content).strip()
    response_lower = user_response.lower()

    # User approves
    if response_lower in ("yes", "y", "ok", "approve", "looks good", "proceed", "approved"):
        route_summary = _format_route_summary(optimized_route)
        return {
            "awaiting_approval": "",
            "messages": [AIMessage(content=f"**Route approved!**\n\n{route_summary}\n\nRunning final validation before generating the proposal...")],
        }

    # Handle swap
    if response_lower.startswith("swap"):
        try:
            nums = [int(n) for n in response_lower.replace("swap", "").strip().split() if n.isdigit()]
            if len(nums) == 2:
                a, b = nums[0] - 1, nums[1] - 1
                if 0 <= a < len(optimized_route) and 0 <= b < len(optimized_route):
                    optimized_route[a], optimized_route[b] = optimized_route[b], optimized_route[a]
                    optimized_route = _recalculate_times(optimized_route, start_time)
        except (ValueError, IndexError):
            pass

        approval_msg = _format_route_approval(optimized_route, pricing, start_time, end_time)
        return {
            "optimized_route": optimized_route,
            "awaiting_approval": "route",
            "messages": [AIMessage(content=f"**Updated route (swapped):**\n\n{approval_msg}")],
        }

    # Handle remove
    if response_lower.startswith("remove"):
        try:
            nums = {int(n) - 1 for n in response_lower.replace("remove", "").strip().split() if n.strip().isdigit()}
            optimized_route = [s for i, s in enumerate(optimized_route) if i not in nums]
            optimized_route = _recalculate_times(optimized_route, start_time)
        except (ValueError, IndexError):
            pass

        approval_msg = _format_route_approval(optimized_route, pricing, start_time, end_time)
        return {
            "optimized_route": optimized_route,
            "awaiting_approval": "route",
            "messages": [AIMessage(content=f"**Updated route (stops removed):**\n\n{approval_msg}")],
        }

    # Generic change request — use LLM to interpret
    route_summary = _format_route_summary(optimized_route)
    return {
        "awaiting_approval": "route",
        "messages": [AIMessage(content=(
            f"I understand you'd like changes. The current route is:\n\n{route_summary}\n\n"
            f"You can:\n"
            f"- **swap N M** to swap two stops (e.g., *swap 1 3*)\n"
            f"- **remove N** to remove a stop (e.g., *remove 2*)\n"
            f"- **yes** to approve as-is\n\n"
            f"What would you like to change?"
        ))],
    }


def _build_route(places: list[dict], start_time: str, duration: float) -> list[dict]:
    """Build a timed route from the list of places, using real Google Maps travel times."""
    try:
        parts = start_time.split(":")
        start_hour = int(parts[0])
        start_min = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        start_hour, start_min = 9, 0

    current_time = start_hour * 60 + start_min
    optimized_route = []
    lunch_inserted = False

    for i, place in enumerate(places):
        duration_min = place.get("suggested_duration_min", 20)

        # Calculate real travel time to next stop using Google Maps
        travel_min = 0
        if i < len(places) - 1:
            travel_min = _get_real_travel_time(place, places[i + 1])

        hours = current_time // 60
        mins = current_time % 60

        optimized_route.append({
            "order": i + 1,
            "time": f"{hours:02d}:{mins:02d}",
            "name": place["name"],
            "address": place.get("address", ""),
            "latitude": place.get("latitude"),
            "longitude": place.get("longitude"),
            "duration_min": duration_min,
            "travel_to_next_min": travel_min,
            "types": place.get("types", []),
        })

        current_time += duration_min + travel_min

        # Insert lunch break around midday
        if not lunch_inserted and 720 <= current_time <= 810 and i < len(places) - 1 and duration > 5:
            hours_l = current_time // 60
            mins_l = current_time % 60
            optimized_route.append({
                "order": i + 1.5,
                "time": f"{hours_l:02d}:{mins_l:02d}",
                "name": "Lunch Break",
                "address": "",
                "latitude": None,
                "longitude": None,
                "duration_min": 60,
                "travel_to_next_min": 0,
                "types": ["food"],
            })
            current_time += 60
            lunch_inserted = True

    return optimized_route


def _recalculate_times(route: list[dict], start_time: str) -> list[dict]:
    """Recalculate times after reordering stops, using real Google Maps travel times."""
    try:
        parts = start_time.split(":")
        start_hour = int(parts[0])
        start_min = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        start_hour, start_min = 9, 0

    current_time = start_hour * 60 + start_min
    for i, stop in enumerate(route):
        hours = current_time // 60
        mins = current_time % 60
        stop["time"] = f"{hours:02d}:{mins:02d}"
        stop["order"] = i + 1

        # Calculate real travel time to next stop
        travel_min = 0
        if i < len(route) - 1:
            travel_min = _get_real_travel_time(stop, route[i + 1])
        stop["travel_to_next_min"] = travel_min

        current_time += stop.get("duration_min", 20) + travel_min
    return route


def _format_route_summary(route: list[dict]) -> str:
    """Format route as a simple summary."""
    return "\n".join(
        f"  {s['time']} — **{s['name']}** ({s['duration_min']}min)"
        for s in route
    )


def _format_route_approval(route: list[dict], pricing: dict, start_time: str, end_time: str) -> str:
    """Format route + pricing for user approval."""
    route_summary = "\n".join(
        f"  {s['time']} — **{s['name']}** ({s['duration_min']}min)"
        + (f" + {s['travel_to_next_min']}min travel" if s.get('travel_to_next_min') else "")
        for s in route
    )

    pricing_summary = ""
    if pricing and pricing.get("line_items"):
        items_str = "\n".join(
            f"  - {item.get('activity', '?').replace('_', ' ').title()}: EUR {item.get('cost', 0)} ({item.get('note', '')})"
            for item in pricing.get("line_items", [])
        )
        pricing_summary = (
            f"\n\n**Pricing Breakdown:**\n{items_str}\n"
            f"- Subtotal: EUR {pricing.get('subtotal', '?')}\n"
            f"- Group Discount: -EUR {pricing.get('group_discount', 0)}\n"
            f"- **Total: EUR {pricing.get('total', '?')}**\n"
            f"- Per Person: EUR {pricing.get('per_person', '?')}\n"
        )

    return (
        f"**Proposed Itinerary ({start_time} - {end_time}):**\n\n"
        f"{route_summary}"
        f"{pricing_summary}\n\n"
        f"---\n"
        f"**Does this itinerary look good?**\n"
        f"- Reply **yes** to approve and generate the proposal\n"
        f"- Reply **swap N M** to swap two stops (e.g., *swap 1 3*)\n"
        f"- Reply **remove N** to remove a stop\n"
        f"- Or describe any other changes you'd like"
    )
