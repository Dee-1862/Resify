"""
CiteSafe API Schemas
====================
Pydantic models matching the I/O contract exactly.

Input:  {url?, doi?, text?} — at least one required
Output: {integrity_score, total_citations, summary, paper, citations, stats}
WS:     {type: "progress"|"result"|"error", ...}
"""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------

class PaperInput(BaseModel):
    """
    POST /api/analyze input.
    Contract: at least ONE of url, doi, text must be provided.
    """
    url: Optional[str] = None
    doi: Optional[str] = None
    text: Optional[str] = None

    @model_validator(mode="after")
    def at_least_one_input(self):
        if not self.url and not self.doi and not self.text:
            raise ValueError("At least one of url, doi, or text must be provided")
        if self.url and not self.url.startswith(("http://", "https://")):
            raise ValueError("url must be a valid HTTP/HTTPS URL")
        if self.doi and not self.doi.startswith("10."):
            raise ValueError("doi must start with '10.'")
        if self.text and len(self.text) > 100_000:
            raise ValueError("text must be at most 100,000 characters")
        return self


# ---------------------------------------------------------------------------
# Response Models (matches contract output exactly)
# ---------------------------------------------------------------------------

class ReferenceInfo(BaseModel):
    """Citation's claimed reference."""
    authors: str = ""
    title: str = ""
    year: Optional[int] = None
    venue: Optional[str] = None


class SourceFound(BaseModel):
    """Actual source found by existence checker."""
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: Optional[int] = None


class VerificationDetail(BaseModel):
    """Verification result for a single citation."""
    verdict: str = "uncertain"         # supported | contradicted | uncertain
    confidence: float = 0.0
    evidence: Optional[str] = None
    method: str = ""                   # embedding | llm | llm_cross_check


class CitationResult(BaseModel):
    """Single citation in the final report. Matches contract exactly."""
    id: int
    claim: str = ""
    context: str = ""
    reference: ReferenceInfo = Field(default_factory=ReferenceInfo)
    source_found: Optional[SourceFound] = None
    existence_status: str = "not_found"    # found | not_found
    metadata_status: Optional[str] = None  # correct | incorrect | null
    verification: Optional[VerificationDetail] = None


class ReportSummary(BaseModel):
    supported: int = 0
    contradicted: int = 0
    uncertain: int = 0
    not_found: int = 0
    metadata_errors: int = 0


class PaperInfo(BaseModel):
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: Optional[int] = None
    source: str = ""


class ReportStats(BaseModel):
    total_tokens: int = 0
    total_api_calls: int = 0
    cache_hits: int = 0
    latency_ms: float = 0.0
    estimated_cost: float = 0.0
    processing_time_ms: float = 0.0
    agents_invoked: int = 0


class AnalysisReport(BaseModel):
    """
    Final report — matches the frontend contract exactly.
    This is what POST /api/analyze returns and what the WS
    sends as {"type": "result", "report": <this>}.
    """
    integrity_score: float = 0.0
    total_citations: int = 0
    summary: ReportSummary = Field(default_factory=ReportSummary)
    paper: PaperInfo = Field(default_factory=PaperInfo)
    citations: list[CitationResult] = Field(default_factory=list)
    stats: ReportStats = Field(default_factory=ReportStats)


# ---------------------------------------------------------------------------
# Error Response (matches contract error format)
# ---------------------------------------------------------------------------

class ErrorDetail(BaseModel):
    code: str                              # INVALID_INPUT, FETCH_FAILED, etc.
    message: str
    details: str = ""
    stage: str = ""
    recoverable: bool = False


class ErrorResponse(BaseModel):
    status: str = "error"
    error: ErrorDetail


# ---------------------------------------------------------------------------
# Agent Info (for GET /api/agents)
# ---------------------------------------------------------------------------

class AgentInfo(BaseModel):
    name: str
    stage: str
    description: str
    requires_tokens: bool = False


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str = "ok"
    agents_registered: int = 0
    cache_stats: dict[str, Any] = Field(default_factory=dict)
