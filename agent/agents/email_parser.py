"""Email Parser agent — extracts structured event data from client emails."""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent.prompts import EMAIL_PARSER_PROMPT
from agent.state import EventState
from agent.utils import get_text as _get_text


REQUIRED_FIELDS = {
    "client_name": "Client / company name",
    "group_size": "Number of attendees",
    "date": "Event date (YYYY-MM-DD)",
    "locations": "Location(s) in Portugal",
    "start_time": "Preferred start time (HH:MM)",
    "end_time": "Preferred end time (HH:MM)",
    "duration_hours": "Total event duration in hours",
}


def _format_event_summary(details: dict) -> str:
    """Build a markdown summary of the extracted event details."""
    special = details.get("special_requests", {})
    if isinstance(special, dict) and special:
        special_str = "\n".join(f"  - **{k}**: {v}" for k, v in special.items())
    elif isinstance(special, str) and special:
        special_str = f"  - {special}"
    else:
        special_str = "  None"

    return (
        f"**Event Details Extracted:**\n"
        f"- **Client:** {details.get('client_name', 'Unknown')}\n"
        f"- **Contact:** {details.get('contact_email', 'Not provided')}\n"
        f"- **Group Size:** {details.get('group_size', '?')} people\n"
        f"- **Date:** {details.get('date', 'TBD')}\n"
        f"- **Location(s):** {', '.join(details.get('locations', ['Porto']))}\n"
        f"- **Start Time:** {details.get('start_time', '09:00')}\n"
        f"- **End Time:** {details.get('end_time', '17:00')}\n"
        f"- **Duration:** {details.get('duration_hours', 8)} hours\n"
        f"- **Preferences:** {', '.join(details.get('preferences', ['adventure']))}\n"
        f"- **Budget:** {'EUR ' + str(details['budget_per_person']) + '/person' if details.get('budget_per_person') else 'Not specified'}\n"
        f"- **Special Requests:**\n{special_str}"
    )


def _find_missing_fields(event_details: dict) -> list[str]:
    """Identify required fields that are missing or have default/empty values."""
    missing = []
    if not event_details.get("client_name") or event_details["client_name"] in ("Unknown", "Unknown Client", ""):
        missing.append("client_name")
    if not event_details.get("group_size") or event_details["group_size"] == 0:
        missing.append("group_size")
    if not event_details.get("date") or event_details["date"] == "TBD":
        missing.append("date")
    if not event_details.get("locations"):
        missing.append("locations")
    if not event_details.get("start_time"):
        missing.append("start_time")
    if not event_details.get("end_time"):
        missing.append("end_time")
    if not event_details.get("duration_hours"):
        missing.append("duration_hours")
    return missing


def _normalize_event_details(event_details: dict) -> dict:
    """Normalize types and set defaults for event details."""
    if isinstance(event_details.get("locations"), str):
        event_details["locations"] = [event_details["locations"]]
    if isinstance(event_details.get("preferences"), str):
        event_details["preferences"] = [event_details["preferences"]]
    if isinstance(event_details.get("special_requests"), str):
        sr = event_details["special_requests"]
        event_details["special_requests"] = {"general": sr} if sr else {}
    if not isinstance(event_details.get("special_requests"), dict):
        event_details["special_requests"] = {}
    try:
        event_details["group_size"] = int(event_details.get("group_size", 0))
    except (ValueError, TypeError):
        event_details["group_size"] = 0

    event_details.setdefault("start_time", "")
    event_details.setdefault("end_time", "")
    event_details.setdefault("duration_hours", 0)
    event_details.setdefault("budget_per_person", None)
    event_details.setdefault("special_requests", {})
    event_details.setdefault("contact_email", "")
    return event_details


def email_parser_node(state: EventState) -> dict:
    """Parse the user's email/message and extract structured event details.

    Two modes:
    1. First pass: extract from email, ask user to confirm/provide missing info
    2. Approval mode: user responded to confirmation prompt, merge their input
    """
    # Check if we're in approval mode (awaiting user confirmation of details)
    if state.get("awaiting_approval") == "event_details" and state.get("event_details"):
        return _handle_approval(state)

    # First pass: extract from the user's message
    llm = ChatOpenAI(model="gpt-4o", temperature=0.1)

    user_messages = [m for m in state.get("messages", []) if isinstance(m, HumanMessage)]
    if not user_messages:
        return {
            "messages": [AIMessage(content="I need an email or event request to parse. Please provide one.")],
        }

    email_text = _get_text(user_messages[-1].content)

    messages = [
        SystemMessage(content=EMAIL_PARSER_PROMPT + "\n\nRespond with a valid JSON object containing the extracted fields. No markdown fences."),
        HumanMessage(content=f"Parse this email:\n\n{email_text}"),
    ]

    response = llm.invoke(messages)

    # Parse the JSON response
    try:
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            raw = raw.rsplit("```", 1)[0]
        event_details = json.loads(raw)
    except (json.JSONDecodeError, IndexError):
        return {
            "messages": [AIMessage(content=f"I couldn't structure the information properly. Here's what I found:\n\n{response.content}\n\nCould you try rephrasing or providing more details?")],
        }

    event_details = _normalize_event_details(event_details)

    # Check for missing fields
    missing = _find_missing_fields(event_details)

    summary = _format_event_summary(event_details)

    if missing:
        missing_list = "\n".join(f"  - **{REQUIRED_FIELDS[f]}**" for f in missing)
        prompt = (
            f"{summary}\n\n"
            f"---\n"
            f"I'm missing some information to plan your event properly. "
            f"Please provide the following:\n{missing_list}\n\n"
            f"You can reply with the missing values, for example:\n"
            f"*\"Start at 10:00, end at 18:00, 25 people, date is 2025-04-15\"*"
        )
    else:
        prompt = (
            f"{summary}\n\n"
            f"---\n"
            f"**Does everything look correct?** Reply **yes** to proceed, "
            f"or tell me what to change."
        )

    return {
        "event_details": event_details,
        "awaiting_approval": "event_details",
        "validation_result": {},  # clear any previous validation
        "messages": [AIMessage(content=prompt)],
    }


def _handle_approval(state: EventState) -> dict:
    """Handle user's response to the event details confirmation."""
    event_details = state["event_details"]

    user_messages = [m for m in state.get("messages", []) if isinstance(m, HumanMessage)]
    if not user_messages:
        return {"messages": [AIMessage(content="Please confirm the details or tell me what to change.")]}

    user_response = _get_text(user_messages[-1].content).strip()

    # Check if user confirmed
    if user_response.lower() in ("yes", "y", "ok", "looks good", "correct", "confirm", "proceed", "approved", "approve"):
        # Fill defaults for any remaining empty fields
        event_details.setdefault("start_time", "09:00")
        if not event_details.get("start_time"):
            event_details["start_time"] = "09:00"
        event_details.setdefault("end_time", "17:00")
        if not event_details.get("end_time"):
            event_details["end_time"] = "17:00"
        event_details.setdefault("duration_hours", 8)
        if not event_details.get("duration_hours"):
            event_details["duration_hours"] = 8
        event_details.setdefault("locations", ["Porto"])
        if not event_details.get("locations"):
            event_details["locations"] = ["Porto"]
        event_details.setdefault("preferences", ["adventure"])
        if not event_details.get("preferences"):
            event_details["preferences"] = ["adventure"]

        summary = _format_event_summary(event_details)
        return {
            "event_details": event_details,
            "awaiting_approval": "",
            "messages": [AIMessage(content=f"{summary}\n\nGreat! Now searching for the best venues and activities...")],
        }

    # User wants changes — merge their corrections via LLM
    llm = ChatOpenAI(model="gpt-4o", temperature=0)

    current = json.dumps(event_details, indent=2, default=str)
    merge_prompt = (
        f"Current event details:\n{current}\n\n"
        f"The user provided this update:\n\"{user_response}\"\n\n"
        f"Merge the user's response into the existing event details. "
        f"Return the complete updated JSON object. Keep all existing values "
        f"unless the user explicitly changed them. "
        f"Ensure special_requests is a dictionary (key-value pairs). "
        f"Respond with only the JSON, no markdown fences."
    )

    response = llm.invoke([
        SystemMessage(content="You merge user corrections into event detail JSON. Return only valid JSON."),
        HumanMessage(content=merge_prompt),
    ])

    try:
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            raw = raw.rsplit("```", 1)[0]
        updated = json.loads(raw)
    except (json.JSONDecodeError, IndexError):
        updated = event_details

    updated = _normalize_event_details(updated)

    # Check if there are still missing fields
    missing = _find_missing_fields(updated)
    summary = _format_event_summary(updated)

    if missing:
        missing_list = "\n".join(f"  - **{REQUIRED_FIELDS[f]}**" for f in missing)
        prompt = (
            f"{summary}\n\n"
            f"---\n"
            f"I still need:\n{missing_list}\n\n"
            f"Please provide the remaining details."
        )
        return {
            "event_details": updated,
            "awaiting_approval": "event_details",
            "messages": [AIMessage(content=prompt)],
        }

    # All fields filled — ask for final confirmation
    prompt = (
        f"{summary}\n\n"
        f"---\n"
        f"**Updated! Does everything look correct now?** Reply **yes** to proceed, "
        f"or tell me what else to change."
    )
    return {
        "event_details": updated,
        "awaiting_approval": "event_details",
        "messages": [AIMessage(content=prompt)],
    }
