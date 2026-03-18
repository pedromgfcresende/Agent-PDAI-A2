# ExtremoAmbiente — Multi-Agent Event Planner

AI-powered corporate event planning system for [Extremo Ambiente], a Portuguese adventure tourism company. Built with **LangGraph** multi-agent orchestration and a **Next.js** chat UI.

> **Assignment 2** — Prototyping Products with AI (PDAI) | ESADE MiBA
> Pedro Resende

---

## What It Does

Paste a client email into the chat and receive a complete event proposal - with an optimized route, real travel times, pricing, a Google Maps link, and a professionally branded PDF.

The system uses **5 specialized AI agents** orchestrated by a supervisor, each with human-in-the-loop approval:

```
User (Chat UI) → Supervisor → Email Parser → Place Searcher → Route Planner → Validator → Proposal Writer → PDF
```

### Example Input

```
Hi, I'm Sarah from InnovaTech Solutions. We're planning a team-building day
in Porto for 20 people on April 15th. We'd love a mix of adventure and
cultural activities, plus a nice lunch. Budget is around €180 per person.
We have 2 vegetarians and 1 person in a wheelchair.
```

### What Happens

1. **Email Parser** extracts: client name, group size, date, location, preferences, budget, special requests
2. **Place Searcher** discovers 5-8 real venues via Google Maps
3. **Route Planner** optimizes the stop order, calculates actual driving times, and prices everything
4. **Validator** cross-checks all data (time consistency, budget compliance, completeness)
5. **Proposal Writer** generates a formatted proposal + branded PDF with Google Maps directions

At each step, the user can review, edit, or approve before moving forward.

---

## Architecture

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
| **Email Parser** | Extracts structured event data from raw client emails | None (LLM-only) | Yes — confirms extracted data, asks for missing fields |
| **Place Searcher** | Finds relevant activities/venues based on preferences & location | Google Maps Places API, Geocoding | Yes — user selects/removes/searches places |
| **Route Planner** | Optimizes stop order, calculates durations & pricing | Google Maps Routes API, Pricing Calculator | Yes — user approves/swaps/removes stops |
| **Validator** | Cross-checks all data before proposal generation | None (LLM-only) | No — auto-routes back to fix agent if issues found |
| **Proposal Writer** | Generates formatted proposal + renders PDF via Quarto | Google Maps URL builder, Quarto PDF renderer | No |

### Tools

| Tool | API | Purpose |
|------|-----|---------|
| `search_places` | Google Maps Places (New) | Text search with 15 km radius bias around event location |
| `geocode_address` | Google Geocoding | Convert addresses to lat/lng coordinates |
| `get_travel_time` | Google Maps Routes v2 | Actual driving/walking time between consecutive stops |
| `build_google_maps_url` | Google Maps URLs | Generate directions link with all waypoints |
| `calculate_pricing` | Internal catalog | Activity-based pricing with group discounts (ported from A1) |
| `generate_proposal_pdf` | Quarto + LaTeX | Professional PDF with EA branding (white + orange theme) |

### State Schema

```python
class EventState(TypedDict):
    messages: Annotated[list, add_messages]  # Conversation history
    event_details: dict          # Parsed email data (client, date, group size, preferences, budget, special requests)
    places: list[dict]           # Discovered venues/activities from Google Maps
    approved_places: list[dict]  # User-approved places
    optimized_route: list[dict]  # Ordered stops with times, durations & travel times
    pricing: dict                # Cost breakdown (line items, subtotal, discount, total, per person)
    validation_result: dict      # Validator output (pass/fail + issues + fix_agent)
    proposal: str                # Final formatted markdown proposal
    google_maps_url: str         # Route directions link
    proposal_pdf_path: str       # Path to rendered PDF
    next_agent: str              # Routing control
    awaiting_approval: str       # "" | "event_details" | "places" | "route"
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Agent Orchestration** | LangGraph (StateGraph, supervisor pattern) |
| **LLM** | OpenAI GPT-4o |
| **Tools** | Google Maps APIs (Places, Routes, Geocoding) |
| **PDF Generation** | Quarto + LaTeX (branded template) |
| **Backend Server** | LangGraph API Server |
| **Frontend** | Next.js + React (Agent Chat UI) |
| **Observability** | LangSmith (tracing & debugging) |
| **Deployment** | Docker Compose on AWS EC2 + GitHub Actions CI/CD |
| **Database** | PostgreSQL (LangGraph state persistence) |

---

## Project Structure

```
Agent-PDAI-A2/
├── agent/
│   ├── graph.py              # Main LangGraph StateGraph definition
│   ├── state.py              # EventState schema
│   ├── prompts.py            # System prompts for all agents
│   ├── utils.py              # Shared utilities
│   ├── agents/
│   │   ├── supervisor.py     # Orchestrator (LLM + deterministic routing)
│   │   ├── email_parser.py   # Email → structured data (2-mode: extract + approve)
│   │   ├── place_searcher.py # Google Maps discovery (2-mode: search + select)
│   │   ├── route_planner.py  # Route optimization + pricing (2-mode: plan + approve)
│   │   ├── validator.py      # Quality checks + feedback routing
│   │   └── proposal_writer.py# Markdown + PDF generation
│   ├── tools/
│   │   ├── google_maps.py    # Places, Routes, Geocoding, URL builder
│   │   ├── pricing.py        # Activity catalog + group discount logic
│   │   └── pdf_generator.py  # Quarto template rendering
│   └── templates/
│       ├── proposal_template.qmd  # Professional PDF template (white + orange)
│       └── assets/
│           └── logo.png      # Extremo Ambiente logo
├── ui/                       # Next.js chat frontend
│   ├── src/
│   │   ├── app/              # Next.js pages
│   │   ├── components/       # Chat UI components
│   │   ├── providers/        # LangGraph stream provider
│   │   ├── hooks/            # Custom React hooks
│   │   └── lib/              # Utilities
│   └── public/proposals/     # Generated PDFs (served as static files)
├── docker-compose.yml        # Postgres + Redis + Backend + Frontend
├── Dockerfile                # LangGraph API server + Quarto/LaTeX
├── langgraph.json            # LangGraph server config
├── pyproject.toml            # Python dependencies
├── .github/workflows/
│   └── deploy.yml            # Auto-deploy to EC2 on push to main
└── scripts/
    └── ec2-setup.sh          # One-time EC2 server setup
```

---

## Setup

### Prerequisites

- Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 20+, pnpm
- OpenAI API key, Google Maps API key (Places, Routes, Geocoding enabled)
- Optional: [Quarto CLI](https://quarto.org/docs/get-started/) for PDF generation

### Environment Variables

```bash
cp .env.example .env
# Edit .env:
OPENAI_API_KEY=sk-...
GOOGLE_MAPS_API_KEY=...

# Optional (LangSmith tracing)
LANGSMITH_API_KEY=lsv2_...
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=extremoambiente-a2
```

### Backend (LangGraph Server)

```bash
# Install dependencies
echo 'export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/extremo-ambiente"' > .envrc
direnv allow
uv sync

# Start dev server
uv run langgraph dev
# → Running on http://localhost:2024
```

### Frontend (Chat UI)

```bash
cd ui
cp .env.example .env
pnpm install
pnpm dev
# → Running on http://localhost:3000
```

Open http://localhost:3000 and start chatting!

---

## Deployment (AWS EC2)

The project includes a full Docker-based deployment with auto-deploy on push.

### Services

| Service | Image | Port |
|---------|-------|------|
| **postgres** | postgres:16-alpine | 5432 (internal) |
| **redis** | redis:7-alpine | 6379 (internal) |
| **backend** | LangGraph API + Quarto/LaTeX | 8123 |
| **frontend** | Next.js standalone | 3000 |

### Deploy

```bash
# On EC2 (Ubuntu 24.04, t3.small+)
# 1. Install Docker (see scripts/ec2-setup.sh)
# 2. Clone repo & create .env
# 3. Start services:
export NEXT_PUBLIC_API_URL=http://<EC2_PUBLIC_IP>:8123
docker compose up -d --build
```

---

## Pricing Catalog

Still hardcoded:

`note`: in production the objective is to have this in a RAG based on past events data

| Activity | Pricing Model | Cost |
|----------|--------------|------|
| Jeep Tour | Per vehicle (6 pax) / 4h block | €400/jeep |
| Walking Tour | Per person / hour | €10/person/hour |
| RZR Adventure | Per vehicle (2 pax) / 2h block | €200/car |
| Food Experience | Per person | €35/person |
| Cultural Tour | Per person | €15/person |
| Entrance Fee | Per person | €5/person |
| Guide Fee | Flat rate per event | €150 |

**Group discount**: 5% off for groups > 10 people.

---

## Evolution from Assignment 1

| Aspect | A1 (Streamlit) | A2 (LangGraph) |
|--------|----------------|----------------|
| **UI** | Streamlit dashboard with manual controls | Chat-based UI with natural language |
| **Workflow** | Manual step-by-step (user drives each action) | Automated multi-agent pipeline with approvals |
| **Email Parsing** | Single LLM call with keyword fallback | Structured extraction + interactive confirmation |
| **Places** | Manual entry | Google Maps Places API with preference-driven search |
| **Routes** | Manual drag-and-drop in AgGrid table | Auto-optimized with real Google Maps travel times |
| **Pricing** | Manual billing table | Automatic calculation via tool |
| **Validation** | None | Dedicated validator agent with feedback loops |
| **Output** | Dashboard view | Formatted proposal + branded PDF |
| **Deployment** | Local only | Docker on AWS EC2 with CI/CD |

---
