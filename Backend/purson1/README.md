# CiteSafe — Foundation Layer

Multi-agent citation integrity verification pipeline. This is the **infrastructure** that Person 2 and Person 3's agents plug into.

## Quick Start

```bash
cd citesafe
cp .env.example .env           # add your API keys
pip install -r requirements.txt
python tests/test_pipeline.py  # verify everything works (all 8 test groups)
uvicorn server.main:app --reload --port 8000
```

Visit `http://localhost:8000/docs` for the interactive API.

## I/O Contract Compliance

Every data shape matches the golden I/O contract exactly:

| Contract Requirement | Implementation |
|---|---|
| POST `/api/analyze` with `{url, doi, text}` | `schemas.PaperInput` with validator: at least one required, URL must be http(s), DOI must start with `10.` |
| WebSocket at `/ws/analyze` | Mounted at **both** `/ws/analyze` (frontend) and `/api/analyze/ws` (contract) |
| WS input: `{"paper_input": "..."}` | Parsed in `routes.py` → auto-detects URL vs DOI vs text |
| WS progress: `{"type": "progress", "message": "...", "progress": 25}` | Pipeline sends 0-100 integer progress via `ctx.send_progress()` |
| WS result: `{"type": "result", "report": {...}}` | Final report wrapped in this envelope |
| WS error: `{"type": "error", "message": "..."}` | All errors caught and sent in this format |
| Agent envelope: `{agent_name, status, data, tokens_used, latency_ms}` | `AgentResult` dataclass, populated automatically |
| Final report: `{integrity_score, total_citations, summary, paper, citations, stats}` | `_build_report()` in pipeline.py produces this exactly |
| Error codes: `FETCH_FAILED`, `EXTRACT_FAILED`, etc. | Mapped per-stage in `_error_code_for_stage()` |
| Cache: `get_source/set_source`, `get_verification/set_verification`, `get_analysis/set_analysis` | Exact method names in `cache.py` |

## Architecture

```
Frontend → POST /api/analyze {url, doi, text}
                    │
                    ▼
         ┌─ PipelineOrchestrator ──────────────────────────────┐
         │                                                       │
         │  FETCHING ─→ EXTRACTING ─→ CHECKING_EXISTENCE        │
         │                                    │                  │
         │                             EMBEDDING_GATE            │
         │                            ╱            ╲             │
         │                     [resolved]    [needs_llm]         │
         │                       (70%)          (30%)            │
         │                         │       LLM_VERIFICATION      │
         │                         │              │              │
         │                         └──── SYNTHESIZING ──→ report │
         └───────────────────────────────────────────────────────┘
                    │
                    ▼
         {"type": "result", "report": {integrity_score, citations, ...}}
```

### Pipeline State Machine

Each stage has registered agents. The pipeline runs them in order, skips empty stages, and skips LLM_VERIFICATION if the embedding gate resolved everything.

| Stage | Who Builds | Token Cost | What It Does |
|---|---|---|---|
| `FETCHING` | Person 3 | Free | Fetch paper from URL/DOI, extract PDF text |
| `EXTRACTING` | Person 3 | LLM tokens | Parse citations with claims from paper text |
| `CHECKING_EXISTENCE` | Person 3 | Free | Check Semantic Scholar for each cited source |
| `EMBEDDING_GATE` | Person 2 | Free | Local embeddings resolve 60-70% of citations |
| `LLM_VERIFICATION` | Person 2 | LLM tokens | Deep semantic check for ambiguous cases |
| `SYNTHESIZING` | Person 1 | Free | Build final report (auto-built if no agent) |

## How to Add Your Agent

### Person 2 (Embedding Gate / Semantic LLM)

Copy `server/agents/_template.py` and implement. Your agents must return data in the contract format:

**Embedding Gate** — returns `{resolved: [...], needs_llm: [...]}`:
```python
from server.agents.base import AgentResult, BaseAgent, PipelineContext, PipelineStage, registry

class EmbeddingGateAgent(BaseAgent):
    name = "embedding_gate"
    stage = PipelineStage.EMBEDDING_GATE
    description = "Resolve clear cases with local embeddings"
    requires_tokens = False

    async def process(self, ctx: PipelineContext) -> AgentResult:
        resolved = []
        needs_llm = []

        for cit in ctx.citations:
            cid = cit["id"]
            existence = ctx.existence_results.get(cid)
            if not existence or existence.get("status") != "found":
                continue

            source = existence["paper"]
            # Your embedding logic here...
            # If confident → add to resolved
            # If ambiguous → add to needs_llm

        return AgentResult(
            agent_name=self.name,
            status="success",
            data={"resolved": resolved, "needs_llm": needs_llm},
            tokens_used=0,
        )

registry.register(EmbeddingGateAgent())
```

**Semantic LLM** — reads `ctx.embedding_needs_llm`, returns list of verdict dicts:
```python
class SemanticAgent(BaseAgent):
    name = "semantic"
    stage = PipelineStage.LLM_VERIFICATION
    requires_tokens = True  # uses LLM

    async def process(self, ctx: PipelineContext) -> AgentResult:
        results = []
        total_tokens = 0

        for item in ctx.embedding_needs_llm:
            # Your LLM verification logic...
            results.append({
                "citation": item["citation"],
                "source": item["source"],
                "verdict": "supported",      # or "contradicted" / "uncertain"
                "confidence": 0.91,
                "evidence": "exact quote...",
                "method": "llm",
            })
            total_tokens += tokens_from_call

        return AgentResult(
            agent_name=self.name,
            status="success",
            data=results,
            tokens_used=total_tokens,
        )
```

### Person 3 (Fetcher / Extractor / Existence)

**Fetcher** — returns `{text, title, authors, year, abstract, source, url, arxiv_id, doi}`:
```python
class FetcherAgent(BaseAgent):
    name = "fetcher"
    stage = PipelineStage.FETCHING

    async def process(self, ctx: PipelineContext) -> AgentResult:
        # Fetch from ctx.paper_url or ctx.paper_doi
        return AgentResult(
            agent_name=self.name,
            status="success",
            data={
                "text": paper_text,
                "title": "...",
                "authors": ["..."],
                "year": 2024,
                "abstract": "...",
                "source": "arxiv",
                "url": ctx.paper_url,
                "arxiv_id": "2301.00001",
                "doi": None,
            },
        )
```

**Extractor** — returns `{citations: [{id, claim, context, reference: {authors, title, year, venue}}]}`:
```python
class ExtractorAgent(BaseAgent):
    name = "extractor"
    stage = PipelineStage.EXTRACTING

    async def process(self, ctx: PipelineContext) -> AgentResult:
        # Parse citations from ctx.paper_text
        return AgentResult(
            agent_name=self.name,
            status="success",
            data={"citations": [...]},
            tokens_used=token_count,
        )
```

**Existence** — returns `{results: {"1": {status, paper?, match_score, cached}}}`:
```python
class ExistenceAgent(BaseAgent):
    name = "existence"
    stage = PipelineStage.CHECKING_EXISTENCE

    async def process(self, ctx: PipelineContext) -> AgentResult:
        results = {}
        for cit in ctx.citations:
            # Check Semantic Scholar...
            results[str(cit["id"])] = {
                "status": "found",
                "paper": {"paper_id": "...", "title": "...", "authors": [...], "year": 2017, "abstract": "...", "doi": "..."},
                "match_score": 95,
                "cached": False,
            }
        return AgentResult(
            agent_name=self.name,
            status="success",
            data={"results": results},
        )
```

### Wiring It Up

After creating your agent file, just add one import line in `server/main.py`:

```python
def _register_default_agents():
    from server.agents import dummy       # test agents
    # from server.agents import fetcher   # uncomment when ready
    # from server.agents import extractor
    # from server.agents import existence
    # from server.agents import embedding_gate
    # from server.agents import semantic
```

**Important**: When your real agent replaces a dummy, it auto-replaces by name since both use the same `name` string.

## What The Pipeline Gives You (ctx fields)

| After Stage | Available in ctx | Type |
|---|---|---|
| FETCHING | `ctx.paper_text`, `ctx.fetcher_result` | str, dict |
| EXTRACTING | `ctx.citations` | `list[dict]` — `[{id, claim, context, reference}]` |
| CHECKING_EXISTENCE | `ctx.existence_results` | `dict[int, dict]` — keyed by citation id |
| EMBEDDING_GATE | `ctx.embedding_resolved`, `ctx.embedding_needs_llm` | `list[dict]` |
| LLM_VERIFICATION | `ctx.llm_results` | `list[dict]` |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/analyze` | `{url?, doi?, text?}` → report |
| POST | `/api/analyze/upload` | PDF upload → report |
| WS | `/ws/analyze` | Real-time analysis (frontend path) |
| WS | `/api/analyze/ws` | Real-time analysis (contract path) |
| GET | `/api/agents` | List registered agents |
| GET | `/api/health` | Health + cache stats |
| GET | `/health` | Simple health check |

## File Structure

```
server/
├── main.py                    # FastAPI app + agent registration
├── config.py                  # Settings (pydantic-settings, .env)
├── api/
│   ├── routes.py              # REST + WebSocket (both /ws paths)
│   └── schemas.py             # Contract-matching Pydantic models
├── core/
│   ├── pipeline.py            # State machine orchestrator + report builder
│   └── cache.py               # SQLite (get_source/set_source, get_verification/set_verification, get_analysis/set_analysis)
└── agents/
    ├── base.py                # BaseAgent, AgentResult, PipelineContext, Registry, CircuitBreaker
    ├── _template.py           # Copy-paste starter for new agents
    └── dummy.py               # Full dummy pipeline (5 agents) for testing
```
