"""Proposal Writer agent — generates the final formatted proposal and PDF."""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from agent.prompts import PROPOSAL_WRITER_PROMPT
from agent.state import EventState
from agent.tools.google_maps import build_google_maps_url
from agent.tools.pdf_generator import generate_proposal_pdf


TOOLS = [build_google_maps_url]


def proposal_writer_node(state: EventState) -> dict:
    """Generate a polished event proposal with itinerary, pricing, maps link, and PDF."""
    event = state.get("event_details", {})
    route = state.get("optimized_route", [])
    pricing = state.get("pricing", {})

    if not route:
        return {
            "messages": [AIMessage(content="I need a planned route before writing the proposal. Let me optimize the route first.")],
        }

    llm = ChatOpenAI(model="gpt-4o", temperature=0.5).bind_tools(TOOLS)

    # Build the context for the proposal
    context = (
        f"## Event Details\n"
        f"- Client: {event.get('client_name', 'Client')}\n"
        f"- Date: {event.get('date', 'TBD')}\n"
        f"- Group Size: {event.get('group_size', '?')} people\n"
        f"- Location: {', '.join(event.get('locations', ['Porto']))}\n"
        f"- Start Time: {event.get('start_time', '09:00')}\n"
        f"- End Time: {event.get('end_time', '17:00')}\n"
        f"- Duration: {event.get('duration_hours', 8)} hours\n"
        f"- Preferences: {', '.join(event.get('preferences', ['adventure']))}\n"
        f"- Special Requests: {json.dumps(event.get('special_requests', {}), default=str)}\n\n"
        f"## Planned Route\n{json.dumps(route, indent=2, default=str)}\n\n"
        f"## Pricing\n{json.dumps(pricing, indent=2, default=str)}\n\n"
        f"Generate the full proposal. Use build_google_maps_url with the route stops "
        f"to create a directions link."
    )

    messages = [
        SystemMessage(content=PROPOSAL_WRITER_PROMPT),
        HumanMessage(content=context),
    ]

    # Run tool-calling loop
    google_maps_url = ""

    for _ in range(3):
        response = llm.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            break

        for tool_call in response.tool_calls:
            tool_fn = {t.name: t for t in TOOLS}.get(tool_call["name"])
            if tool_fn:
                result = tool_fn.invoke(tool_call["args"])
                messages.append(ToolMessage(content=str(result), tool_call_id=tool_call["id"]))

                if tool_call["name"] == "build_google_maps_url":
                    google_maps_url = result

    # The final response should be the proposal
    proposal = response.content if response.content else "Proposal generation failed."

    # Append Google Maps link if not already in proposal
    if google_maps_url and google_maps_url not in proposal:
        proposal += f"\n\n---\n**[View Route on Google Maps]({google_maps_url})**"

    # Generate PDF
    pdf_path = ""
    try:
        pdf_path = generate_proposal_pdf(
            event_details=event,
            optimized_route=route,
            pricing=pricing,
            google_maps_url=google_maps_url,
            executive_summary="",  # Let the template generate its own
        )
    except Exception as e:
        proposal += f"\n\n*Note: PDF generation encountered an issue: {e}*"

    # Build final message
    final_msg = proposal
    if pdf_path:
        final_msg += (
            f"\n\n---\n"
            f"**[Download PDF Proposal]({pdf_path})**"
        )

    return {
        "proposal": proposal,
        "google_maps_url": google_maps_url,
        "proposal_pdf_path": pdf_path,
        "messages": [AIMessage(content=final_msg)],
    }
