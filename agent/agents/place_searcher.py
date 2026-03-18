"""Place Searcher agent — discovers venues and places using Google Maps."""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from agent.prompts import PLACE_SEARCHER_PROMPT
from agent.state import EventState
from agent.tools.google_maps import geocode_address, search_places, _geocode_location, _haversine_km, _MAX_RADIUS_KM
from agent.utils import get_text

_TARGET_PLACE_COUNT = 8

TOOLS = [search_places, geocode_address]

# Google Maps place types considered as food/dining
_FOOD_TYPES = frozenset({
    "food", "restaurant", "meal_delivery", "meal_takeaway", "cafe", "bar",
    "bakery", "wine_bar", "food_court", "italian_restaurant",
    "portuguese_restaurant", "seafood_restaurant", "steak_house",
    "breakfast_restaurant", "brunch_restaurant",
})


def _is_food_place(types: list[str]) -> bool:
    """Check if a place's types indicate it's food/dining related."""
    for t in types:
        t_lower = t.lower().replace(" ", "_")
        if t_lower in _FOOD_TYPES or "restaurant" in t_lower or "food" in t_lower or "wine" in t_lower:
            return True
    return False


def _get_suggested_duration(types: list[str]) -> int:
    """Return suggested visit duration: 35min for food/dining, 20min for everything else."""
    return 35 if _is_food_place(types) else 20


def place_searcher_node(state: EventState) -> dict:
    """Search for relevant places, then ask user to approve.

    Two modes:
    1. First pass: search for places, present to user for selection
    2. Approval mode: process user's selection (all, numbers, remove, search)
    """
    event = state.get("event_details", {})
    if not event:
        return {
            "messages": [AIMessage(content="I need event details before searching for places. Please provide your event information first.")],
        }

    # If already approved, skip
    if state.get("approved_places"):
        return {"validation_result": {}}

    # Approval mode — user is responding to place selection
    if state.get("awaiting_approval") == "places" and state.get("places"):
        return _handle_place_approval(state)

    # First pass — search for places
    llm = ChatOpenAI(model="gpt-4o", temperature=0.3).bind_tools(TOOLS)

    location = ", ".join(event.get("locations", ["Porto"]))
    preferences = ", ".join(event.get("preferences", ["adventure"]))
    group_size = event.get("group_size", 10)

    # Geocode the center of the target location once
    center = _geocode_location(location)
    center_lat, center_lng = center if center else (0.0, 0.0)

    task = (
        f"Find exactly {_TARGET_PLACE_COUNT} great places to visit for a corporate event "
        f"in {location} for {group_size} people.\n"
        f"Preferences: {preferences}.\n"
        f"Special requests: {json.dumps(event.get('special_requests', {}), default=str)}\n\n"
        f"Use the search_places tool to find real places, landmarks, and venues. "
        f"All places MUST be within 15 km of the center of {location}.\n"
    )
    if center_lat:
        task += (
            f"Pass center_lat={center_lat} and center_lng={center_lng} to every "
            f"search_places call to enforce the radius filter.\n\n"
        )
    task += (
        f"Search by specific category — for example:\n"
        f"- For food: search 'restaurants in {location}' or 'wine cellars in {location}'\n"
        f"- For cultural: search 'museums in {location}' or 'historic sites in {location}'\n"
        f"- For nature: search 'parks in {location}' or 'viewpoints in {location}'\n"
        f"- For adventure: search 'outdoor activities in {location}' or 'kayak in {location}'\n"
        f"- For team_building: search 'escape rooms in {location}' or 'cooking schools in {location}'\n\n"
        f"Do NOT search for generic terms like 'activities'. Search for specific place types."
    )

    messages = [
        SystemMessage(content=PLACE_SEARCHER_PROMPT),
        HumanMessage(content=task),
    ]

    # Run the agent loop (up to 6 tool calls)
    places = []
    for _ in range(6):
        response = llm.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            break

        for tool_call in response.tool_calls:
            tool_fn = {t.name: t for t in TOOLS}.get(tool_call["name"])
            if tool_fn:
                result = tool_fn.invoke(tool_call["args"])
                messages.append(ToolMessage(content=str(result), tool_call_id=tool_call["id"]))

                try:
                    parsed = json.loads(result)
                    if isinstance(parsed, list):
                        for p in parsed:
                            if p.get("name") and p.get("latitude"):
                                place_types = p.get("types", [])
                                places.append({
                                    "name": p["name"],
                                    "address": p.get("address", ""),
                                    "latitude": p["latitude"],
                                    "longitude": p["longitude"],
                                    "types": place_types,
                                    "rating": p.get("rating"),
                                    "summary": p.get("summary", ""),
                                    "suggested_duration_min": _get_suggested_duration(place_types),
                                })
                except (json.JSONDecodeError, TypeError):
                    pass

    # Deduplicate by name
    seen = set()
    unique_places = []
    for p in places:
        if p["name"] not in seen:
            seen.add(p["name"])
            unique_places.append(p)

    # Filter out places beyond 15 km from center
    if center_lat and center_lng:
        unique_places = [
            p for p in unique_places
            if not (p.get("latitude") and p.get("longitude"))
            or _haversine_km(center_lat, center_lng, p["latitude"], p["longitude"]) <= _MAX_RADIUS_KM
        ]

    # Cap at exactly _TARGET_PLACE_COUNT places
    unique_places = unique_places[:_TARGET_PLACE_COUNT]

    # Fallback if no places found
    if not unique_places:
        unique_places = _fallback_places(location, preferences)

    # Present places to user for approval
    place_list = _format_place_list(unique_places)

    approval_msg = (
        f"**Found {len(unique_places)} places in {location} (within {_MAX_RADIUS_KM:.0f} km):**\n\n"
        f"{place_list}\n\n"
        f"---\n"
        f"**How would you like to proceed?**\n"
        f"- Reply **all** to keep all places\n"
        f"- Reply with numbers to select specific places (e.g., **1, 3, 5**)\n"
        f"- Reply **remove 2, 4** to remove specific places\n"
        f"- Reply **search [query]** to search for something specific (e.g., *search wine tasting in Douro*)"
    )

    return {
        "places": unique_places,
        "awaiting_approval": "places",
        "messages": [AIMessage(content=approval_msg)],
    }


def _handle_place_approval(state: EventState) -> dict:
    """Process the user's place selection response."""
    places = state.get("places", [])
    event = state.get("event_details", {})
    location = ", ".join(event.get("locations", ["Porto"]))

    user_messages = [m for m in state.get("messages", []) if isinstance(m, HumanMessage)]
    if not user_messages:
        return {"messages": [AIMessage(content="Please select which places to keep.")]}

    user_response = get_text(user_messages[-1].content).strip()
    response_lower = user_response.lower()

    # User approves all
    if response_lower in ("all", "yes", "ok", "approve", "keep all", "looks good"):
        return _approve_places(places, location)

    # User wants to remove specific places
    if response_lower.startswith("remove"):
        nums_str = response_lower.replace("remove", "").strip()
        try:
            remove_indices = {int(n.strip()) - 1 for n in nums_str.replace(",", " ").split() if n.strip().isdigit()}
            selected = [p for i, p in enumerate(places) if i not in remove_indices]
            if selected:
                return _approve_places(selected, location)
        except ValueError:
            pass
        return _approve_places(places, location)

    # User wants to search for something new
    if response_lower.startswith("search"):
        query = user_response[6:].strip()
        if query:
            result = search_places.invoke({"query": query, "location_bias": location})
            try:
                new_places = json.loads(result)
                if isinstance(new_places, list):
                    for p in new_places:
                        if p.get("name") and p.get("latitude"):
                            place_types = p.get("types", [])
                            places.append({
                                "name": p["name"],
                                "address": p.get("address", ""),
                                "latitude": p["latitude"],
                                "longitude": p["longitude"],
                                "types": place_types,
                                "rating": p.get("rating"),
                                "summary": p.get("summary", ""),
                                "suggested_duration_min": _get_suggested_duration(place_types),
                            })
            except (json.JSONDecodeError, TypeError):
                pass

            # Deduplicate
            seen = set()
            unique = []
            for p in places:
                if p["name"] not in seen:
                    seen.add(p["name"])
                    unique.append(p)

            place_list = _format_place_list(unique)
            msg = (
                f"**Updated list ({len(unique)} places):**\n\n{place_list}\n\n"
                f"---\n"
                f"Reply **all** to keep all, numbers to select (e.g., **1, 3, 5**), "
                f"**remove N** to drop, or **search [query]** for more."
            )
            return {
                "places": unique,
                "awaiting_approval": "places",
                "messages": [AIMessage(content=msg)],
            }

        return _approve_places(places, location)

    # User selected specific numbers
    try:
        indices = [int(n.strip()) - 1 for n in response_lower.replace(",", " ").split() if n.strip().isdigit()]
        if indices:
            selected = [places[i] for i in indices if 0 <= i < len(places)]
            if selected:
                return _approve_places(selected, location)
    except (ValueError, IndexError):
        pass

    # Couldn't parse — ask again
    place_list = _format_place_list(places)
    return {
        "awaiting_approval": "places",
        "messages": [AIMessage(content=(
            f"I didn't quite understand your selection. Here are the places again:\n\n"
            f"{place_list}\n\n"
            f"Reply **all**, specific numbers (e.g., **1, 3, 5**), **remove N**, or **search [query]**."
        ))],
    }


def _format_place_list(places: list[dict]) -> str:
    """Format places as a numbered list."""
    lines = []
    for i, p in enumerate(places):
        types_str = ", ".join(p.get("types", [])[:3]) or "N/A"
        lines.append(
            f"**{i+1}.** **{p['name']}** — {p.get('address', '')}\n"
            f"   Rating: {p.get('rating', 'N/A')} | Types: {types_str} | "
            f"~{p.get('suggested_duration_min', 45)}min\n"
            f"   _{p.get('summary', '')}_"
        )
    return "\n\n".join(lines)


def _approve_places(places: list[dict], location: str) -> dict:
    """Finalize the approved places."""
    place_list = "\n".join(
        f"  {i+1}. **{p['name']}** — {p.get('address', '')}"
        for i, p in enumerate(places)
    )
    summary = (
        f"**Approved {len(places)} places in {location}:**\n{place_list}\n\n"
        f"Now optimizing the route and calculating pricing..."
    )

    return {
        "places": places,
        "approved_places": places,
        "awaiting_approval": "",
        "messages": [AIMessage(content=summary)],
    }


def _fallback_places(location: str, preferences: str) -> list[dict]:
    """Return sensible default places when Google Maps search fails (8 places)."""
    defaults = {
        "Porto": [
            {"name": "Ribeira District", "address": "Ribeira, Porto", "latitude": 41.1403, "longitude": -8.6131, "types": ["cultural"], "suggested_duration_min": 20, "summary": "Historic riverside district, UNESCO World Heritage Site"},
            {"name": "Livraria Lello", "address": "R. das Carmelitas 144, Porto", "latitude": 41.1467, "longitude": -8.6148, "types": ["cultural"], "suggested_duration_min": 20, "summary": "Iconic bookstore with stunning neo-Gothic interior"},
            {"name": "Dom Luis I Bridge", "address": "Ponte Luis I, Porto", "latitude": 41.1395, "longitude": -8.6094, "types": ["adventure"], "suggested_duration_min": 20, "summary": "Iconic double-deck bridge with panoramic views"},
            {"name": "Matosinhos Beach & Seafood", "address": "Matosinhos, Porto", "latitude": 41.1847, "longitude": -8.6898, "types": ["food", "restaurant"], "suggested_duration_min": 35, "summary": "Beach area famous for fresh seafood restaurants"},
            {"name": "Parque da Cidade", "address": "Parque da Cidade, Porto", "latitude": 41.1665, "longitude": -8.6758, "types": ["nature", "team_building"], "suggested_duration_min": 20, "summary": "Largest urban park in Portugal"},
            {"name": "Caves Porto (Wine Cellars)", "address": "Vila Nova de Gaia, Porto", "latitude": 41.1372, "longitude": -8.6128, "types": ["food", "wine_bar"], "suggested_duration_min": 35, "summary": "Port wine cellars with tastings"},
            {"name": "Jardins do Palacio de Cristal", "address": "R. de Dom Manuel II, Porto", "latitude": 41.1481, "longitude": -8.6255, "types": ["nature", "park"], "suggested_duration_min": 20, "summary": "Beautiful gardens with stunning Douro river views"},
            {"name": "Mercado do Bolhao", "address": "R. de Fernandes Tomás, Porto", "latitude": 41.1498, "longitude": -8.6063, "types": ["food", "market"], "suggested_duration_min": 35, "summary": "Iconic traditional market recently restored"},
        ],
    }
    return defaults.get(location.split(",")[0].strip(), defaults["Porto"])
