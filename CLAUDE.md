# CLAUDE.md — ExtremoAmbiente Multi-Agent Event Planner

## Project Overview

**Assignment 2** for PDAI (Prototyping Products with AI) at ESADE MiBA.
Built on top of the ExtremoAmbiente-A1 Streamlit prototype (corporate event quoting tool for a Portuguese adventure tourism company).

This project replaces the manual Streamlit workflow with a **LangGraph multi-agent system** that interactively processes client emails and produces complete event proposals — powered by specialized sub-agents with tools and **human-in-the-loop** approval at every step.

**Student**: Pedro Resende

---

## Architecture

### Multi-Agent Graph (LangGraph)

```
                    ┌─────────────┐
     Email Input →  │  Supervisor │  ← Orchestrates workflow
                    └──────┬──────┘
                           │
         ┌─────────────────┼──────────────────┐
         ▼                 ▼                   ▼
   ┌──────────┐     ┌──────────┐        ┌──────────┐
   │  Email   │     │  Place   │        │  Route   │
   │  Parser  │     │ Searcher │        │ Planner  │
   │ (confirm)│     │ (select) │        │ (approve)│
   └──────────┘     └──────────┘        └──────────┘
                                              │
                                              ▼
                                       ┌──────────┐
                                       │ Validator │ ← Cross-checks all data
                                       └─────┬────┘
                                              │ (can route back to fix)
                                              ▼
                                    ┌──────────────────┐
                                    │  Proposal Writer  │
                                    │  (+ PDF render)   │
                                    └──────────────────┘
                                              │
                                              ▼
                                      Final Proposal
                                     (Markdown + PDF)
```

### Agents

| Agent | Role | Tools | Human-in-the-Loop |
|-------|------|-------|--------------------|
| **Supervisor** | Routes tasks to sub-agents, manages state transitions | None (routing only) | No |
| **Email Parser** | Extracts structured event data from raw client emails | None (LLM-only) | Yes — asks for missing fields, confirms extracted data |
| **Place Searcher** | Finds relevant activities/venues based on preferences & location | Google Maps Places API, Geocoding | Yes — user selects/removes/searches places |
| **Route Planner** | Optimizes stop order, calculates durations & pricing | Google Maps Routes API, pricing calculator | Yes — user approves/swaps/removes stops |
| **Validator** | Cross-checks all data before proposal generation | None (LLM-only) | No — auto-routes back to fix agent if issues found |
| **Proposal Writer** | Generates formatted proposal + renders PDF via Quarto | Google Maps link builder, Quarto PDF | No |

### State Schema

```python
class EventState(TypedDict):
    messages: Annotated[list, add_messages]
    event_details: dict          # Parsed email data (expanded: start/end time, special_requests dict)
    places: list[dict]           # Discovered venues/activities
    approved_places: list[dict]  # User-approved places
    optimized_route: list[dict]  # Ordered stops with times & durations
    pricing: dict                # Cost breakdown
    validation_result: dict      # Validator output (pass/fail + issues)
    proposal: str                # Final formatted proposal
    google_maps_url: str         # Route link
    proposal_pdf_path: str       # Path to rendered PDF
    next_agent: str              # Routing control
    awaiting_approval: str       # "" | "event_details" | "places" | "route"
```

---

## Tech Stack

- **LangGraph** — Multi-agent orchestration with message-based human-in-the-loop
- **LangChain** — Tool definitions, chat models
- **OpenAI GPT-4o** — LLM backbone for all agents
- **Google Maps APIs** — Places, Routes, Geocoding
- **Quarto** — PDF proposal rendering (white theme + EA branding)
- **LangGraph Server** — Serves the agent via API
- **Agent Chat UI** — Next.js frontend (from LangChain Academy template)

---

## Project Structure

```
Agent-PDAI-A2/
├── CLAUDE.md
├── README.md
├── .env.example
├── .gitignore
│
├── agent/                    # LangGraph multi-agent backend
│   ├── __init__.py
│   ├── graph.py              # Main graph definition
│   ├── state.py              # Shared state schema
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── supervisor.py     # Supervisor routing logic
│   │   ├── email_parser.py   # Email → structured data (with interrupt)
│   │   ├── place_searcher.py # Google Maps place discovery (with interrupt)
│   │   ├── route_planner.py  # Route optimization + pricing (with interrupt)
│   │   ├── validator.py      # Quality check before proposal
│   │   └── proposal_writer.py# Final proposal + PDF generation
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── google_maps.py    # Places, Routes, Geocoding tools
│   │   ├── pricing.py        # Pricing calculator tool
│   │   └── pdf_generator.py  # Quarto PDF rendering
│   ├── templates/
│   │   ├── proposal_template.qmd  # Quarto template (white + EA branding)
│   │   └── assets/
│   │       └── logo.png      # Extremo Ambiente logo
│   └── prompts.py            # System prompts for each agent
│
├── langgraph.json            # LangGraph server config
├── pyproject.toml            # Python dependencies
│
└── ui/                       # Next.js chat frontend
    ├── package.json
    ├── next.config.mjs
    ├── .env.example
    ├── src/
    │   ├── app/
    │   ├── providers/
    │   ├── components/
    │   └── hooks/
    └── ...
```

---

## Commands

```bash
# Backend
pip install -e .
langgraph dev                 # Start LangGraph dev server on :2024

# Frontend
cd ui && pnpm install && pnpm dev   # Start Next.js on :3000

# Requires: quarto CLI (brew install --cask quarto)
```

---

## Environment Variables

```bash
# Required
OPENAI_API_KEY=sk-...
GOOGLE_MAPS_API_KEY=...

# Optional (for LangSmith tracing)
LANGSMITH_API_KEY=lsv2_...
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=extremoambiente-a2
```

---

## Key Design Decisions

1. **Supervisor pattern** (not sequential) — allows re-routing if an agent needs more info
2. **Human-in-the-loop** via `awaiting_approval` state — user confirms/selects at every major step (message-based, no interrupt)
3. **Validator agent** — cross-checks all data before proposal, routes back to fix issues
4. **Expanded event details** — start/end times, special_requests as structured dict
5. **Structured outputs** for email parsing — ensures reliable JSON extraction
6. **Google Maps tools as LangChain tools** — agents can call them dynamically
7. **Pricing logic ported from A1** — reuses proven business rules (group discounts, catalog)
8. **PDF via Quarto** — professional proposal document with EA branding (white theme, orange accents, logo)
9. **Agent Chat UI** — production-grade chat interface with streaming, tool call visualization
