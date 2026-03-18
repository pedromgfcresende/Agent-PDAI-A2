# ExtremoAmbiente — Multi-Agent Event Planner

AI-powered corporate event planning system for [Extremo Ambiente](https://www.extremoambiente.pt/), a Portuguese adventure tourism company. Built with **LangGraph** multi-agent orchestration and a **Next.js** chat UI.

> **Assignment 2** — Prototyping Products with AI (PDAI) | ESADE MiBA
> Pedro Resende

## What it does

Paste a client email → get a complete event proposal with optimized route, pricing, and Google Maps link.

The system uses 4 specialized AI agents orchestrated by a supervisor:

| Agent | Role |
|-------|------|
| **Email Parser** | Extracts structured data (client, group size, date, preferences, budget) |
| **Place Searcher** | Discovers venues via Google Maps Places API |
| **Route Planner** | Optimizes stop order, calculates travel times & pricing |
| **Proposal Writer** | Generates formatted proposal with Google Maps route link |

## Architecture

```
User (Chat UI) → LangGraph Server → Supervisor → Sub-Agents → Tools (Google Maps, Pricing)
```

## Setup

### Prerequisites
- Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 18+, pnpm
- OpenAI API key, Google Maps API key

### Backend

```bash
# Configure environment
cp .env.example .env
# Edit .env with your API keys

# Install dependencies
echo 'export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/extremo-ambiente"' > .envrc
direnv allow
uv sync

# Start LangGraph dev server
uv run langgraph dev
```

### Frontend

```bash
cd ui
cp .env.example .env
pnpm install
pnpm dev
```

Open http://localhost:3000 and start chatting!

## Example Input

```
Hi, I'm Sarah from InnovaTech Solutions. We're planning a team-building day
in Porto for 20 people on April 15th. We'd love a mix of adventure and
cultural activities, plus a nice lunch. Budget is around €180 per person.
We have 2 vegetarians and 1 person in a wheelchair.
```

## Tech Stack

- **LangGraph** — Multi-agent orchestration
- **OpenAI GPT-4o** — LLM backbone
- **Google Maps APIs** — Places, Routes, Geocoding
- **Next.js + React** — Chat UI (agent-chat-ui template)
- **LangSmith** — Observability (optional)
