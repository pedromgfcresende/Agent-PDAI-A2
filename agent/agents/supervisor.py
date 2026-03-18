"""Supervisor agent — decides which sub-agent runs next."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent.prompts import SUPERVISOR_PROMPT
from agent.state import EventState
from agent.utils import get_text

AGENTS = ["email_parser", "place_searcher", "route_planner", "validator", "proposal_writer", "FINISH"]

# Map awaiting_approval values to the agent that should handle the response
APPROVAL_AGENT_MAP = {
    "event_details": "email_parser",
    "places": "place_searcher",
    "route": "route_planner",
}


def supervisor_node(state: EventState) -> dict:
    """Analyze the current state and decide which agent should act next.

    Key logic:
    - If awaiting_approval is set, route to the approval-handling agent
    - Otherwise, follow the normal pipeline
    """
    # Priority: if we're awaiting user approval, route to the corresponding agent
    awaiting = state.get("awaiting_approval", "")
    if awaiting and awaiting in APPROVAL_AGENT_MAP:
        # Check if the user has sent a new message (their approval response)
        user_msgs = [m for m in state.get("messages", []) if isinstance(m, HumanMessage)]
        ai_msgs = [m for m in state.get("messages", []) if hasattr(m, "type") and m.type == "ai"]

        if user_msgs and ai_msgs:
            # If the last message is from the user, route to approval handler
            all_msgs = state.get("messages", [])
            last_msg = all_msgs[-1] if all_msgs else None
            if last_msg and isinstance(last_msg, HumanMessage):
                return {"next_agent": APPROVAL_AGENT_MAP[awaiting]}

        # User hasn't responded yet — wait (go to END)
        return {"next_agent": "FINISH"}

    # Normal pipeline routing
    return {"next_agent": _determine_next_agent(state)}


def _determine_next_agent(state: EventState) -> str:
    """Determine next agent based on pipeline state."""
    # Use LLM for nuanced decisions
    llm = ChatOpenAI(model="gpt-4o", temperature=0)

    context_parts = []
    if state.get("event_details"):
        context_parts.append(f"Event details extracted: {state['event_details']}")
    if state.get("approved_places"):
        context_parts.append(f"Approved places: {len(state['approved_places'])} venues")
    elif state.get("places"):
        context_parts.append(f"Places found (not yet approved): {len(state['places'])} venues")
    if state.get("optimized_route"):
        context_parts.append(f"Route optimized: {len(state['optimized_route'])} stops")
    if state.get("pricing"):
        context_parts.append(f"Pricing calculated: total EUR {state['pricing'].get('total', '?')}")
    if state.get("validation_result"):
        vr = state["validation_result"]
        context_parts.append(f"Validation: {vr.get('status', 'unknown')}")
        if vr.get("fix_agent"):
            context_parts.append(f"Validation fix agent: {vr['fix_agent']}")
    if state.get("proposal"):
        context_parts.append("Proposal already generated")
    if state.get("proposal_pdf_path"):
        context_parts.append("PDF generated")

    context_summary = "\n".join(context_parts) if context_parts else "No data yet — this is the start."

    messages = [
        SystemMessage(content=SUPERVISOR_PROMPT),
        HumanMessage(content=(
            f"Current workflow state:\n{context_summary}\n\n"
            f"Recent conversation:\n"
            + "\n".join(
                f"[{m.type}]: {get_text(m.content)[:200]}"
                for m in state.get("messages", [])[-5:]
                if hasattr(m, "content") and m.content
            )
            + "\n\nWhich agent should act next?"
        )),
    ]

    response = llm.invoke(messages)
    next_agent = response.content.strip().lower()

    # Normalize the response
    for agent_name in AGENTS:
        if agent_name.lower() in next_agent:
            return agent_name

    # Fallback routing
    return _fallback_routing(state)


def _fallback_routing(state: EventState) -> str:
    """Deterministic fallback routing based on state completion."""
    if state.get("proposal"):
        return "FINISH"

    if not state.get("event_details"):
        user_msgs = [m for m in state.get("messages", []) if isinstance(m, HumanMessage)]
        if user_msgs:
            last_msg = get_text(user_msgs[-1].content) if hasattr(user_msgs[-1], "content") else ""
            if len(last_msg) < 50 and not any(
                kw in last_msg.lower()
                for kw in ["people", "group", "team", "event", "plan", "porto", "budget", "date"]
            ):
                return "FINISH"
        return "email_parser"

    if not state.get("approved_places"):
        return "place_searcher"

    if not state.get("optimized_route"):
        return "route_planner"

    # Check validation
    validation = state.get("validation_result", {})
    if not validation:
        return "validator"
    if validation.get("status") == "failed":
        # Route to validator to re-check (not directly to fix_agent,
        # which would loop). The validator_route conditional edge handles
        # routing to fix agents when needed.
        return "validator"

    return "proposal_writer"
