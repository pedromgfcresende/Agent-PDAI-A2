"""Shared state schema for the multi-agent event planner."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class EventState(TypedDict):
    """State shared across all agents in the graph."""

    # Conversation messages (accumulates via add_messages reducer)
    messages: Annotated[list[AnyMessage], add_messages]

    # Parsed email data — filled by email_parser agent
    event_details: dict

    # Discovered venues/activities — filled by place_searcher agent
    places: list[dict]

    # User-approved places (after human-in-the-loop selection)
    approved_places: list[dict]

    # Optimized route with travel times — filled by route_planner agent
    optimized_route: list[dict]

    # Cost breakdown — filled by route_planner agent
    pricing: dict

    # Validator feedback — filled by validator agent
    validation_result: dict

    # Final formatted proposal text — filled by proposal_writer agent
    proposal: str

    # Google Maps directions URL — filled by proposal_writer agent
    google_maps_url: str

    # Path to the rendered PDF proposal
    proposal_pdf_path: str

    # Controls which agent runs next
    next_agent: str

    # Tracks which step is awaiting user confirmation
    # Values: "" | "event_details" | "places" | "route"
    awaiting_approval: str
