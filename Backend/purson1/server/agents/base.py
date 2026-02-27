"""
CiteSafe Agent Foundation
=========================
Core abstractions that all agents build on.

Contract compliance:
  - Every agent returns an AgentResult envelope:
    {"agent_name": str, "status": "success"|"error", "data": dict, "tokens_used": int, "latency_ms": float}
  - PipelineContext tracks the state machine:
    FETCHING → EXTRACTING → CHECKING_EXISTENCE → EMBEDDING_GATE → LLM_VERIFICATION → SYNTHESIZING → COMPLETE
  - Registry allows plug-and-play agent registration
  - Circuit breaker disables repeatedly-failing agents
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger("citesafe.agents")


# ---------------------------------------------------------------------------
# Pipeline Stages (State Machine from I/O Contract)
# ---------------------------------------------------------------------------

class PipelineStage(str, Enum):
    """Matches the state machine in the I/O contract exactly."""
    IDLE = "idle"
    FETCHING = "fetching"
    EXTRACTING = "extracting"
    CHECKING_EXISTENCE = "checking_existence"
    EMBEDDING_GATE = "embedding_gate"
    LLM_VERIFICATION = "llm_verification"
    SYNTHESIZING = "synthesizing"
    COMPLETE = "complete"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Agent Result Envelope (standardized agent output)
# ---------------------------------------------------------------------------

@dataclass
class AgentResult:
    """
    Every agent returns this envelope.
    Matches the contract:
      {"agent_name", "status", "data", "tokens_used", "latency_ms"}
    """
    agent_name: str
    status: str = "success"           # "success" | "error"
    data: dict = field(default_factory=dict)
    tokens_used: int = 0
    latency_ms: float = 0.0
    error: Optional[str] = None       # populated when status="error"

    def to_dict(self) -> dict:
        d = {
            "agent_name": self.agent_name,
            "status": self.status,
            "data": self.data,
            "tokens_used": self.tokens_used,
            "latency_ms": round(self.latency_ms, 1),
        }
        if self.error:
            d["error"] = self.error
        return d


# ---------------------------------------------------------------------------
# Token Budget
# ---------------------------------------------------------------------------

@dataclass
class TokenBudget:
    """Track token consumption across the pipeline."""
    limit: int = 100_000
    used: int = 0
    by_agent: dict[str, int] = field(default_factory=dict)

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def consume(self, agent_name: str, tokens: int):
        self.used += tokens
        self.by_agent[agent_name] = self.by_agent.get(agent_name, 0) + tokens

    @property
    def exhausted(self) -> bool:
        return self.remaining <= 0


# ---------------------------------------------------------------------------
# Pipeline Context — shared state flowing through all agents
# ---------------------------------------------------------------------------

@dataclass
class PipelineContext:
    """
    Shared mutable state for the analysis pipeline.

    Fields match the I/O contract's data flow:
      - paper_input → fetcher_result → extractor_result → existence_results
        → embedding_results → llm_results → final_report
    """

    # --- Original input ---
    paper_url: str = ""
    paper_doi: str = ""
    paper_text: str = ""

    # --- Current stage ---
    stage: PipelineStage = PipelineStage.IDLE

    # --- Stage 1: Fetcher output ---
    # Contract: {text, title, authors, year, abstract, source, url, arxiv_id, doi}
    fetcher_result: Optional[dict] = None

    # --- Stage 2: Extractor output ---
    # Contract: {citations: [{id, claim, context, reference: {authors, title, year, venue}}]}
    citations: list[dict] = field(default_factory=list)

    # --- Stage 3: Existence output (per-citation) ---
    # Contract: {status: "found"|"not_found", paper?: {paper_id, title, authors, year, abstract, doi}, match_score, cached}
    existence_results: dict[int, dict] = field(default_factory=dict)  # keyed by citation id

    # --- Stage 4: Embedding gate output ---
    # Contract: {resolved: [...], needs_llm: [...]}
    embedding_resolved: list[dict] = field(default_factory=list)
    embedding_needs_llm: list[dict] = field(default_factory=list)

    # --- Stage 5: LLM verification output ---
    # Contract: [{citation, source, verdict, confidence, evidence, method}]
    llm_results: list[dict] = field(default_factory=list)

    # --- Final merged results for report ---
    final_citation_results: list[dict] = field(default_factory=list)

    # --- Final report ---
    report: Optional[dict] = None

    # --- Token accounting ---
    token_budget: TokenBudget = field(default_factory=TokenBudget)

    # --- Pipeline stats (matches contract) ---
    stats: dict[str, Any] = field(default_factory=lambda: {
        "total_tokens": 0,
        "total_api_calls": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "latency_fetch_ms": 0.0,
        "latency_extract_ms": 0.0,
        "latency_existence_ms": 0.0,
        "latency_embedding_ms": 0.0,
        "latency_llm_ms": 0.0,
        "latency_total_ms": 0.0,
        "citations_total": 0,
        "citations_found": 0,
        "citations_not_found": 0,
        "citations_resolved_embedding": 0,
        "citations_sent_to_llm": 0,
    })

    # --- Error tracking ---
    errors: list[dict] = field(default_factory=list)
    agent_timings: dict[str, float] = field(default_factory=dict)

    # --- WebSocket progress callback ---
    _progress_callback: Optional[Callable] = field(default=None, repr=False)

    async def send_progress(self, message: str, progress: float):
        """
        Send progress update in the exact frontend contract format:
          {"type": "progress", "message": "...", "progress": 25}
        Progress is 0-100 (percentage).
        """
        if self._progress_callback:
            try:
                await self._progress_callback(message, progress)
            except Exception:
                pass

    async def send_error(self, code: str, message: str, details: str = "",
                         stage: str = "", recoverable: bool = False):
        """
        Send error in contract format:
          {"status": "error", "error": {"code", "message", "details", "stage", "recoverable"}}
        """
        error_data = {
            "code": code,
            "message": message,
            "details": details,
            "stage": stage or self.stage.value,
            "recoverable": recoverable,
        }
        self.errors.append(error_data)
        if self._progress_callback:
            try:
                await self._progress_callback(f"Error: {message}", -1)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Base Agent
# ---------------------------------------------------------------------------

class BaseAgent(ABC):
    """
    Contract every CiteSafe agent must fulfill.

    Subclasses set:
      - name:          unique identifier (e.g. "fetcher", "extractor", "existence")
      - stage:         which PipelineStage this agent handles
      - description:   human-readable purpose (shown in GET /api/agents)
      - requires_tokens: if True, agent is skipped when token budget exhausted
    """

    name: str = "unnamed"
    stage: PipelineStage = PipelineStage.IDLE
    description: str = ""
    requires_tokens: bool = False

    async def pre_check(self, ctx: PipelineContext) -> bool:
        """
        Optional guard. Return False to skip this agent.
        Default: skip token-consuming agents when budget exhausted.
        """
        if self.requires_tokens and ctx.token_budget.exhausted:
            logger.warning(f"[{self.name}] skipped — token budget exhausted")
            return False
        return True

    @abstractmethod
    async def process(self, ctx: PipelineContext) -> AgentResult:
        """
        Core logic.

        Read from ctx (the fields relevant to your stage),
        do your work, return an AgentResult envelope.

        The pipeline will store your result back into ctx.

        Return:
            AgentResult with:
              - agent_name: self.name
              - status: "success" or "error"
              - data: your output dict (matching the I/O contract)
              - tokens_used: LLM tokens consumed (0 for free agents)
        """
        ...

    def info(self) -> dict:
        """Serializable metadata for GET /api/agents."""
        return {
            "name": self.name,
            "stage": self.stage.value,
            "description": self.description,
            "requires_tokens": self.requires_tokens,
        }


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

@dataclass
class CircuitBreaker:
    """
    Per-agent circuit breaker.
    After `threshold` consecutive failures, the agent is disabled
    for `cooldown_seconds`. Prevents one broken API from stalling everything.
    """
    threshold: int = 3
    cooldown_seconds: float = 60.0
    _failure_counts: dict[str, int] = field(default_factory=dict)
    _open_until: dict[str, float] = field(default_factory=dict)

    def is_open(self, agent_name: str) -> bool:
        if agent_name in self._open_until:
            if time.time() < self._open_until[agent_name]:
                return True
            del self._open_until[agent_name]
            self._failure_counts.pop(agent_name, None)
        return False

    def record_success(self, agent_name: str):
        self._failure_counts.pop(agent_name, None)

    def record_failure(self, agent_name: str):
        count = self._failure_counts.get(agent_name, 0) + 1
        self._failure_counts[agent_name] = count
        if count >= self.threshold:
            self._open_until[agent_name] = time.time() + self.cooldown_seconds
            logger.error(
                f"[CircuitBreaker] {agent_name} disabled for "
                f"{self.cooldown_seconds}s after {count} consecutive failures"
            )


# ---------------------------------------------------------------------------
# Agent Registry
# ---------------------------------------------------------------------------

# Stage execution order (matches the state machine)
STAGE_ORDER = [
    PipelineStage.FETCHING,
    PipelineStage.EXTRACTING,
    PipelineStage.CHECKING_EXISTENCE,
    PipelineStage.EMBEDDING_GATE,
    PipelineStage.LLM_VERIFICATION,
    PipelineStage.SYNTHESIZING,
]


class AgentRegistry:
    """
    Stores registered agents, organized by stage.

    Usage:
        from server.agents.base import registry
        registry.register(MyAgent())
        registry.list_agents()
    """

    def __init__(self):
        self._agents: dict[str, BaseAgent] = {}
        self.circuit_breaker = CircuitBreaker()

    def register(self, agent: BaseAgent):
        """Register an agent. Replaces any existing agent with same name."""
        if not isinstance(agent, BaseAgent):
            raise TypeError(f"Expected BaseAgent subclass, got {type(agent).__name__}")
        if agent.name in self._agents:
            logger.info(f"Replacing agent '{agent.name}'")
        self._agents[agent.name] = agent
        logger.info(f"Registered agent '{agent.name}' at stage {agent.stage.value}")

    def remove(self, name: str) -> bool:
        """Remove agent by name. Returns True if it existed."""
        return self._agents.pop(name, None) is not None

    def get_pipeline(self) -> list[BaseAgent]:
        """Return agents in stage execution order."""
        order = {s: i for i, s in enumerate(STAGE_ORDER)}
        return sorted(
            self._agents.values(),
            key=lambda a: order.get(a.stage, 99),
        )

    def get_agents_for_stage(self, stage: PipelineStage) -> list[BaseAgent]:
        """Get all agents registered for a specific stage."""
        return [a for a in self._agents.values() if a.stage == stage]

    def list_agents(self) -> list[dict]:
        """Serializable list for GET /api/agents."""
        return [a.info() for a in self.get_pipeline()]

    def get(self, name: str) -> Optional[BaseAgent]:
        return self._agents.get(name)

    def clear(self):
        self._agents.clear()

    def __len__(self) -> int:
        return len(self._agents)

    def __contains__(self, name: str) -> bool:
        return name in self._agents


# Module-level singleton
registry = AgentRegistry()
