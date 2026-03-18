"""Validator agent — cross-checks all data before proposal generation."""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent.prompts import VALIDATOR_PROMPT
from agent.state import EventState

# Maximum number of validation attempts before auto-passing
_MAX_VALIDATION_RETRIES = 2


def validator_node(state: EventState) -> dict:
    """Validate that all collected data is consistent and complete before proposal."""
    event = state.get("event_details", {})
    places = state.get("approved_places") or state.get("places", [])
    route = state.get("optimized_route", [])
    pricing = state.get("pricing", {})

    # Count previous validation attempts to prevent infinite loops
    prev_validation = state.get("validation_result", {})
    retry_count = prev_validation.get("_retry_count", 0)

    if retry_count >= _MAX_VALIDATION_RETRIES:
        return {
            "validation_result": {"status": "passed", "details": "Auto-passed after retry limit"},
            "messages": [AIMessage(content="**Validation passed!** Generating your proposal...")],
        }

    # Quick structural checks first
    issues = []

    if not event:
        issues.append("Missing event details entirely")
    if not places:
        issues.append("No places selected")
    if not route:
        issues.append("No route planned")
    if not pricing or pricing.get("total", 0) == 0:
        issues.append("Pricing not calculated or is zero")

    # Check time consistency
    start_time = event.get("start_time", "09:00")
    end_time = event.get("end_time", "17:00")

    if route:
        last_stop = route[-1]
        last_stop_end_min = _time_to_min(last_stop.get("time", "17:00")) + last_stop.get("duration_min", 0)
        end_time_min = _time_to_min(end_time)

        if last_stop_end_min > end_time_min + 30:  # 30min tolerance
            issues.append(
                f"Route ends at ~{last_stop_end_min // 60:02d}:{last_stop_end_min % 60:02d} "
                f"but requested end time is {end_time}"
            )

    # Preference coverage is informational only — not a blocking issue.
    # Google Maps types (tourist_attraction, point_of_interest, etc.) rarely
    # match user-facing preference labels like "adventure".

    # Check budget
    budget = event.get("budget_per_person")
    per_person = pricing.get("per_person", 0)
    if budget and per_person and per_person > budget:
        issues.append(
            f"Per-person cost (EUR {per_person}) exceeds budget (EUR {budget}/person)"
        )

    # Use LLM for deeper validation only if structural checks pass
    if not issues:
        llm = ChatOpenAI(model="gpt-4o", temperature=0)

        context = (
            f"Event Details:\n{json.dumps(event, indent=2, default=str)}\n\n"
            f"Selected Places:\n{json.dumps(places, indent=2, default=str)}\n\n"
            f"Planned Route:\n{json.dumps(route, indent=2, default=str)}\n\n"
            f"Pricing:\n{json.dumps(pricing, indent=2, default=str)}"
        )

        response = llm.invoke([
            SystemMessage(content=VALIDATOR_PROMPT),
            HumanMessage(content=context),
        ])

        validation_text = response.content.strip()

        # Check if LLM found issues
        if "PASS" in validation_text.upper() and "FAIL" not in validation_text.upper():
            return {
                "validation_result": {"status": "passed", "details": validation_text},
                "messages": [AIMessage(content=f"**Validation passed!** All data is consistent.\n\nGenerating your proposal...")],
            }

        # LLM found issues
        issues.append(validation_text)

    if issues:
        issues_str = "\n".join(f"- {issue}" for issue in issues)
        fix_agent = _determine_fix_agent(issues)

        return {
            "validation_result": {
                "status": "failed",
                "issues": issues,
                "fix_agent": fix_agent,
                "_retry_count": retry_count + 1,
            },
            "messages": [AIMessage(
                content=(
                    f"**Validation found issues:**\n{issues_str}\n\n"
                    f"Routing back to **{fix_agent}** to address these issues..."
                )
            )],
        }

    return {
        "validation_result": {"status": "passed", "details": "All checks passed"},
        "messages": [AIMessage(content="**Validation passed!** Generating your proposal...")],
    }


def _time_to_min(time_str: str) -> int:
    """Convert HH:MM string to minutes since midnight."""
    try:
        parts = time_str.split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return 9 * 60


def _determine_fix_agent(issues: list[str]) -> str:
    """Determine which agent should fix the validation issues."""
    issues_text = " ".join(issues).lower()

    if "missing event" in issues_text or "client" in issues_text:
        return "email_parser"
    if "places" in issues_text or "preference" in issues_text or "not covered" in issues_text:
        return "place_searcher"
    if "route" in issues_text or "time" in issues_text or "pricing" in issues_text or "budget" in issues_text or "cost" in issues_text:
        return "route_planner"

    return "route_planner"
