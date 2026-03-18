"""Main LangGraph graph — multi-agent event planner for Extremo Ambiente."""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph

from agent.agents.email_parser import email_parser_node
from agent.agents.place_searcher import place_searcher_node
from agent.agents.proposal_writer import proposal_writer_node
from agent.agents.route_planner import route_planner_node
from agent.agents.supervisor import supervisor_node
from agent.agents.validator import validator_node
from agent.state import EventState

WELCOME_MESSAGE = (
    "Welcome to **Extremo Ambiente** — your AI-powered corporate event planner!\n\n"
    "I can help you plan an unforgettable team event in Portugal. "
    "Just paste a client email or tell me about the event you'd like to plan.\n\n"
    "I'll need details like:\n"
    "- **Group size** — How many people?\n"
    "- **Location** — Porto, Sintra, Algarve, or elsewhere in Portugal?\n"
    "- **Date** — When is the event?\n"
    "- **Start & end time** — When should the day begin and end?\n"
    "- **Preferences** — Adventure, cultural, food, nature, team-building?\n"
    "- **Budget** — Any budget per person?\n"
    "- **Special requests** — Dietary needs, accessibility, transport preferences, etc.\n\n"
    "Go ahead — paste the email or describe what you need!"
)


def greeter_node(state: EventState) -> dict:
    """Respond with a welcome message or ask for missing information."""
    if state.get("proposal"):
        return {}
    if state.get("event_details"):
        return {}

    return {
        "messages": [AIMessage(content=WELCOME_MESSAGE)],
    }


def route_next(state: EventState) -> str:
    """Route to the next agent based on supervisor's decision."""
    next_agent = state.get("next_agent", "greeter")
    if next_agent == "FINISH":
        if not state.get("proposal") and not state.get("event_details"):
            return "greeter"
        return END
    return next_agent


def validator_route(state: EventState) -> str:
    """Route after validator — either to proposal_writer or back to fix agent."""
    validation = state.get("validation_result", {})
    if validation.get("status") == "failed":
        fix_agent = validation.get("fix_agent", "route_planner")
        # Clear validation so it can be re-run after fix
        return fix_agent
    return "supervisor"


# Build the graph
builder = StateGraph(EventState)

# Add nodes
builder.add_node("supervisor", supervisor_node)
builder.add_node("greeter", greeter_node)
builder.add_node("email_parser", email_parser_node)
builder.add_node("place_searcher", place_searcher_node)
builder.add_node("route_planner", route_planner_node)
builder.add_node("validator", validator_node)
builder.add_node("proposal_writer", proposal_writer_node)

# Entry point: supervisor decides first
builder.set_entry_point("supervisor")

# Supervisor routes to the appropriate agent
builder.add_conditional_edges(
    "supervisor",
    route_next,
    {
        "greeter": "greeter",
        "email_parser": "email_parser",
        "place_searcher": "place_searcher",
        "route_planner": "route_planner",
        "validator": "validator",
        "proposal_writer": "proposal_writer",
        END: END,
    },
)

# Greeter ends the turn (user needs to provide input)
builder.add_edge("greeter", END)

# Each agent returns to supervisor for next decision
builder.add_edge("email_parser", "supervisor")
builder.add_edge("place_searcher", "supervisor")
builder.add_edge("route_planner", "supervisor")

# Validator has conditional routing — can send back to fix agents or proceed
builder.add_conditional_edges(
    "validator",
    validator_route,
    {
        "email_parser": "email_parser",
        "place_searcher": "place_searcher",
        "route_planner": "route_planner",
        "supervisor": "supervisor",
    },
)

builder.add_edge("proposal_writer", "supervisor")

# Compile the graph
graph = builder.compile()
