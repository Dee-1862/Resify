# Resify — AI Research Integrity Scanner

> **PaperShield** | Verify every citation, cross-reference every claim, detect AI-generated sections — in under 15 seconds.

Resify is an end-to-end research-integrity verification platform built around a **six-stage multi-agent AI pipeline**. Paste any ArXiv URL or DOI into the frontend; a coordinated fleet of backend agents fetches the paper, extracts and cross-checks each citation against Semantic Scholar, runs local embedding similarity, escalates ambiguous cases to an LLM, and synthesises a scored integrity report — all streamed live to the browser over WebSockets.

---

## Table of Contents

1. [Features](#features)
2. [Architecture Overview](#architecture-overview)
3. [Tech Stack](#tech-stack)
4. [Repository Structure](#repository-structure)
5. [Getting Started](#getting-started)
   - [Prerequisites](#prerequisites)
   - [Backend Setup](#backend-setup)
   - [Frontend Setup](#frontend-setup)
   - [Running the Full Stack](#running-the-full-stack)
6. [Pipeline Stages](#pipeline-stages)
7. [API Reference](#api-reference)
8. [WebSocket Protocol](#websocket-protocol)
9. [Frontend Components](#frontend-components)
10. [Configuration](#configuration)
11. [Extending the Pipeline](#extending-the-pipeline)
12. [Caching](#caching)
13. [Testing](#testing)
14. [Contributing](#contributing)

---

## Features

- 🔍 **Citation Integrity Verification** — Every citation is checked against Semantic Scholar to confirm existence and match metadata (title, authors, year).
- 🧠 **Embedding Gate** — Local `all-MiniLM-L6-v2` sentence-transformer embeddings resolve 60–70 % of citations instantly, with no API cost.
- 🤖 **LLM Deep Verification** — Ambiguous citations escalate to a Gemini/Gemma LLM for semantic claim-vs-source comparison.
- ⚡ **Real-time streaming** — Live progress (0–100 %) and per-agent status messages pushed over WebSockets.
- 📊 **Integrity Score** — A 0–100 score derived from the ratio of supported vs. found citations, with per-citation verdicts (`supported`, `contradicted`, `uncertain`, `not_found`).
- 🔌 **Pluggable agent registry** — Drop in a new agent by implementing one Python class and adding one import line.
- 🗄️ **SQLite caching** — Source fetches, existence results, and full analysis results are cached to avoid redundant network calls.
- 🛡️ **Circuit breaker** — Repeatedly-failing agents are automatically skipped after a configurable failure threshold.
- 🏗️ **Token budget** — Hard cap on LLM token consumption per run; LLM stage is gracefully skipped when budget is exhausted.

---

## Architecture Overview

```
Browser (React/Vite)
       │  WebSocket  /ws/analyze
       ▼
 ┌─────────────────────────────────────────────────────────┐
 │             FastAPI  (uvicorn, port 8000)                │
 │                                                         │
 │  PipelineOrchestrator (state machine)                   │
 │                                                         │
 │  FETCHING ──► EXTRACTING ──► CHECKING_EXISTENCE         │
 │                                     │                   │
 │                              EMBEDDING_GATE             │
 │                             ╱             ╲             │
 │                      [resolved]       [needs_llm]       │
 │                        (≈70%)           (≈30%)          │
 │                           │        LLM_VERIFICATION     │
 │                           │               │             │
 │                           └──── SYNTHESIZING ──► report │
 └─────────────────────────────────────────────────────────┘
          │
          ▼  JSON
 { integrity_score, total_citations, summary,
   paper, citations[], stats }
```

Progress messages (0–100 %) and the final report are both delivered over the same WebSocket connection, so the UI updates continuously while the pipeline runs.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript, Vite 7 |
| Backend | Python 3.11+, FastAPI, Uvicorn |
| Validation | Pydantic v2 |
| Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`) |
| LLM | Gemini API (Gemma 3 for dev, Gemini Flash for prod) |
| Citation DB | Semantic Scholar API |
| Caching | SQLite (`cache.db`) |
| Transport | WebSockets (native browser API ↔ FastAPI) |
| HTTP Client | `httpx`, `aiohttp` |

---

## Repository Structure

```
Resify/
├── Backend/
│   ├── embeddings.py           # Shared sentence-transformer utilities
│   ├── embeddings_gate.py      # Embedding gate scoring logic
│   ├── purson1/                # Core pipeline server (Person 1 — orchestration)
│   │   ├── requirements.txt
│   │   ├── server/
│   │   │   ├── main.py         # FastAPI app entry point + agent registration
│   │   │   ├── config.py       # Settings (pydantic-settings, reads .env)
│   │   │   ├── api/
│   │   │   │   ├── routes.py   # REST + WebSocket handlers
│   │   │   │   └── schemas.py  # Contract-matching Pydantic models
│   │   │   ├── core/
│   │   │   │   ├── pipeline.py # State-machine orchestrator + report builder
│   │   │   │   └── cache.py    # SQLite cache (source / verification / analysis)
│   │   │   ├── agents/
│   │   │   │   ├── base.py     # BaseAgent, AgentResult, PipelineContext, Registry
│   │   │   │   ├── _template.py# Starter template for new agents
│   │   │   │   └── dummy.py    # Full dummy pipeline (5 agents) for testing
│   │   │   └── utils/
│   │   └── tests/
│   └── Person3/                # Fetcher / Extractor / Existence agents (Person 3)
│       └── server/
│           └── ...
└── Frontend/
    ├── index.html
    ├── vite.config.ts
    ├── package.json
    └── src/
        ├── App.tsx             # Root app state, WebSocket logic, phase management
        ├── index.css           # Global styles / design tokens
        ├── App.css             # App-shell layout
        └── components/
            ├── ResearchHeader  # Top nav + compact search bar
            ├── KnowledgeGraph  # Animated SVG pipeline graph
            ├── AgentStream     # Live scrolling agent log feed
            ├── SynthesisPanel  # Final integrity score + verdict card
            └── StatCards       # Hero-section evidence/statistics cards
```

---

## Getting Started

### Prerequisites

| Requirement | Version |
|---|---|
| Python | ≥ 3.11 |
| Node.js | ≥ 18 |
| npm | ≥ 9 |
| Gemini API key | any free-tier account |

### Backend Setup

```bash
cd Backend/purson1

# Create and activate a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create the .env file
cp .env.example .env   # then add your keys (see Configuration section)
```

### Frontend Setup

```bash
cd Frontend
npm install
```

### Running the Full Stack

**Terminal 1 — Backend:**
```bash
cd Backend/purson1
uvicorn server.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`.  
Interactive docs: `http://localhost:8000/docs`.

**Terminal 2 — Frontend:**
```bash
cd Frontend
npm run dev
```

The frontend dev server starts at `http://localhost:5173` and proxies WebSocket connections to port 8000 automatically via the Vite config.

---

## Pipeline Stages

Each stage is handled by one or more registered agents. Agents are run **concurrently** within a stage via `asyncio.gather`.

| # | Stage | Default Agent | LLM Cost | Description |
|---|---|---|---|---|
| 1 | `FETCHING` | `fetcher` (Person 3) | Free | Fetch paper from ArXiv URL / DOI; extract full text |
| 2 | `EXTRACTING` | `extractor` (Person 3) | LLM tokens | Parse all inline citations + the claim they support |
| 3 | `CHECKING_EXISTENCE` | `existence` (Person 3) | Free | Query Semantic Scholar for each cited paper |
| 4 | `EMBEDDING_GATE` | `embedding_gate` (Person 2) | Free | Local cosine similarity resolves clear-cut citations |
| 5 | `LLM_VERIFICATION` | `semantic` (Person 2) | LLM tokens | Deep LLM comparison for ambiguous citation cases |
| 6 | `SYNTHESIZING` | auto-built by pipeline | Free | Merge verdicts → integrity score + full report |

**Stage skipping rules:**
- Any stage with no registered agents is skipped gracefully.
- `LLM_VERIFICATION` is skipped entirely if the embedding gate resolved every citation.
- Individual agents are skipped if the circuit breaker is open or the token budget is exhausted.

**Progress milestones emitted by the backend:**
```
FETCHING          →  5 %  →  15 %
EXTRACTING        → 15 %  →  25 %
CHECKING_EXISTENCE→ 25 %  →  45 %
EMBEDDING_GATE    → 45 %  →  65 %
LLM_VERIFICATION  → 65 %  →  85 %
SYNTHESIZING      → 85 %  →  95 %
COMPLETE          → 100 %
```

---

## API Reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/analyze` | Analyze a paper by URL / DOI / raw text. Returns full report JSON. |
| `POST` | `/api/analyze/upload` | Upload a PDF and receive the analysis report. |
| `WS` | `/ws/analyze` | Real-time WebSocket analysis (frontend path). |
| `WS` | `/api/analyze/ws` | Real-time WebSocket analysis (contract path). |
| `GET` | `/api/agents` | List all currently registered agents and their stages. |
| `GET` | `/api/health` | Health check + SQLite cache statistics. |
| `GET` | `/health` | Simple liveness probe (for Kubernetes / monitoring). |

### POST `/api/analyze` — Request Body

```json
{
  "url": "https://arxiv.org/abs/2602.04561",
  "doi": null,
  "text": null
}
```

At least one of `url`, `doi`, or `text` must be provided. `url` must start with `http(s)://`; `doi` must start with `10.`.

### POST `/api/analyze` — Response Shape

```json
{
  "integrity_score": 84.5,
  "total_citations": 30,
  "summary": {
    "supported": 22,
    "contradicted": 1,
    "uncertain": 4,
    "not_found": 3,
    "metadata_errors": 0
  },
  "paper": {
    "title": "...",
    "authors": ["..."],
    "year": 2024,
    "source": "arxiv"
  },
  "citations": [
    {
      "id": 1,
      "claim": "...",
      "reference": { "authors": [], "title": "...", "year": 2019, "venue": "NeurIPS" },
      "source_found": { "title": "...", "authors": [], "year": 2019 },
      "existence_status": "found",
      "metadata_status": "correct",
      "verification": {
        "verdict": "supported",
        "confidence": 0.91,
        "evidence": "exact supporting quote...",
        "method": "embedding"
      }
    }
  ],
  "stats": {
    "total_tokens": 12400,
    "total_api_calls": 30,
    "cache_hits": 7,
    "latency_ms": 8320,
    "estimated_cost": 0.0019
  }
}
```

---

## WebSocket Protocol

Connect to `ws://localhost:8000/ws/analyze`.

### Send (client → server)

```json
{ "paper_input": "https://arxiv.org/abs/2602.04561" }
```

`paper_input` is auto-detected as a URL, DOI, or raw text.

### Receive — Progress

```json
{ "type": "progress", "message": "Fetching paper...", "progress": 5 }
```

### Receive — Result

```json
{ "type": "result", "report": { /* same shape as POST /api/analyze */ } }
```

### Receive — Error

```json
{ "type": "error", "message": "FETCH_FAILED: Could not retrieve paper." }
```

---

## Frontend Components

| Component | File | Purpose |
|---|---|---|
| `ResearchHeader` | `components/ResearchHeader.tsx` | Sticky nav with compact inline search (appears when hero scrolls out of view) |
| `KnowledgeGraph` | `components/KnowledgeGraph.tsx` | Animated SVG graph showing agent nodes & edges as the pipeline progresses |
| `AgentStream` | `components/AgentStream.tsx` | Auto-scrolling timestamped log of all agent events |
| `SynthesisPanel` | `components/SynthesisPanel.tsx` | Final verdict card: integrity score, citation breakdown, risk label |
| `StatCards` | `components/StatCards.tsx` | Hero-section cards surfacing retractions stats and reproducibility crisis data |

The app has three phases managed in `App.tsx`:
- **`idle`** — Hero landing page with search bar
- **`analyzing`** — Live KnowledgeGraph + AgentStream dashboard
- **`synthesis`** — KnowledgeGraph freezes; SynthesisPanel overlays the result

---

## Configuration

Create `Backend/purson1/.env` from this template:

```env
# Required
GEMINI_API_KEY=your_gemini_api_key_here

# Optional overrides
CORS_ORIGINS=["http://localhost:5173"]
TOKEN_LIMIT=100000
CACHE_DB_PATH=cache.db
LOG_LEVEL=INFO
```

All settings are validated by `pydantic-settings` in `server/config.py`.

---

## Extending the Pipeline

Adding a new agent takes three steps:

### 1. Create your agent file

Copy `Backend/purson1/server/agents/_template.py` and implement the `process` method:

```python
from server.agents.base import AgentResult, BaseAgent, PipelineContext, PipelineStage, registry

class MyAgent(BaseAgent):
    name = "my_agent"
    stage = PipelineStage.FETCHING   # choose your stage
    description = "What my agent does"
    requires_tokens = False

    async def process(self, ctx: PipelineContext) -> AgentResult:
        # ctx.paper_url, ctx.paper_doi, ctx.paper_text, ctx.citations, etc.
        return AgentResult(
            agent_name=self.name,
            status="success",
            data={ ... },           # stage-specific output shape
            tokens_used=0,
        )

registry.register(MyAgent())
```

### 2. Register the agent

Add one import in `server/main.py` inside `_register_default_agents()`:

```python
from server.agents import my_agent  # noqa: F401
```

### 3. That's it

The pipeline picks it up automatically. If another agent with the same `name` was already registered (e.g. the dummy), it is replaced.

### Pipeline context fields

| Available after stage | `ctx` field | Type |
|---|---|---|
| `FETCHING` | `ctx.paper_text`, `ctx.fetcher_result` | `str`, `dict` |
| `EXTRACTING` | `ctx.citations` | `list[dict]` — `[{id, claim, context, reference}]` |
| `CHECKING_EXISTENCE` | `ctx.existence_results` | `dict[int, dict]` |
| `EMBEDDING_GATE` | `ctx.embedding_resolved`, `ctx.embedding_needs_llm` | `list[dict]` |
| `LLM_VERIFICATION` | `ctx.llm_results` | `list[dict]` |

---

## Caching

Three SQLite caches prevent redundant network and LLM calls:

| Cache | Key | Stores |
|---|---|---|
| Source cache | URL / DOI | Fetched paper text + metadata |
| Existence cache | Citation title + authors | Semantic Scholar lookup result |
| Analysis cache | Hash of paper input | Full analysis report |

Cache is stored in `cache.db` at the configured path. The `cache.py` module exposes:
- `get_source` / `set_source`
- `get_verification` / `set_verification`
- `get_analysis` / `set_analysis`

---

## Testing

```bash
cd Backend/purson1

# Run all test groups (requires backend to be running)
python tests/test_pipeline.py

# Test WebSocket connectivity only
python test_ws.py

# Test Gemini API key validity
python test_gemini.py

# Integration test (full round-trip)
python test_integration.py
```

Frontend linting:
```bash
cd Frontend
npm run lint
```

---

## Contributing

1. Fork the repository and create a feature branch.
2. Run the backend tests before opening a PR.
3. Follow the agent I/O contracts defined in `server/agents/base.py` and `server/api/schemas.py` — the frontend depends on these shapes exactly.
4. Keep LLM usage inside the `LLM_VERIFICATION` and `EXTRACTING` stages; all other stages must be free of LLM calls.
5. Open a pull request against `main` with a description of what your agent does and which pipeline stage it targets.

---

<div align="center">
  <sub>Built with ❤️ · Powered by Gemini · CiteSafe Pipeline v0.1.0</sub>
</div>
