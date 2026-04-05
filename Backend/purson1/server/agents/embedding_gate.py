"""
Embedding Gate Agent
====================
Stage: EMBEDDING_GATE

For every citation that was FOUND by the existence checker:
  1. Encode the claim (what the citing paper says) and the source abstract
  2. Compute cosine similarity
  3. High similarity  → resolve as "supported"  (no LLM needed)
  4. Very low but present abstract → resolve as "uncertain" and send to LLM
  5. Clear low + no abstract → send to LLM anyway

This cuts LLM calls dramatically — fast, cheap, and transparent.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import os
from typing import Optional

from server.agents.base import BaseAgent, AgentResult, PipelineContext, PipelineStage, registry
from server.config import settings

logger = logging.getLogger("citesafe.embedding_gate")

# Add Backend root to path so we can import embeddings.py
_backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)


def _load_model():
    try:
        from embeddings import get_embedding_model
        return get_embedding_model(settings.EMBEDDING_MODEL)
    except Exception as e:
        logger.error(f"Failed to load embedding model: {e}")
        return None


class EmbeddingGateAgent(BaseAgent):
    name = "embedding_gate"
    stage = PipelineStage.EMBEDDING_GATE
    description = "Fast embedding-based claim vs abstract similarity check"
    requires_tokens = False

    def __init__(self):
        super().__init__()
        self._model = None  # lazy-load on first use

    def _get_model(self):
        if self._model is None:
            self._model = _load_model()
        return self._model

    async def pre_check(self, ctx: PipelineContext) -> bool:
        found = [c for c in ctx.citations if ctx.existence_results.get(c["id"], {}).get("status") == "found"]
        if not found:
            logger.info("No found citations — skipping embedding gate")
            return False
        return True

    async def process(self, ctx: PipelineContext) -> AgentResult:
        await ctx.send_progress("Checking embeddings...", 50)

        model = self._get_model()
        if model is None:
            # No model — send everything to LLM
            needs_llm = self._build_needs_llm_list(ctx)
            return AgentResult(
                agent_name=self.name,
                status="success",
                data={"resolved": [], "needs_llm": needs_llm},
                tokens_used=0,
            )

        loop = asyncio.get_event_loop()
        resolved = []
        needs_llm = []

        support_threshold = settings.EMBEDDING_SUPPORT_THRESHOLD       # default 0.75
        contradict_threshold = settings.EMBEDDING_CONTRADICT_THRESHOLD  # default 0.75
        margin_threshold = settings.EMBEDDING_MARGIN_THRESHOLD          # default 0.2

        for cit in ctx.citations:
            cid = cit["id"]
            existence = ctx.existence_results.get(cid)
            if not existence or existence.get("status") != "found":
                continue

            paper = existence.get("paper", {})
            abstract = (paper.get("abstract") or "").strip()
            claim = (cit.get("claim") or "").strip()
            context = (cit.get("context") or "").strip()

            # Build a rich query: claim + context for better signal
            query_text = f"{claim} {context}".strip() if context else claim

            if not query_text:
                needs_llm.append(_make_entry(cit, paper, "uncertain", 0.0, "no_claim_text", send_to_llm=True))
                continue

            if not abstract:
                # No abstract — can't do embedding, send straight to LLM
                needs_llm.append(_make_entry(cit, paper, "uncertain", 0.0, "no_abstract", send_to_llm=True))
                continue

            # Run embedding in thread pool (CPU-bound)
            try:
                from embeddings import encode, best_span_similarity
                result = await loop.run_in_executor(
                    None,
                    lambda c=query_text, a=abstract: best_span_similarity(model, c, a)
                )
                sim = result["best_similarity"]
                best_span = result["best_span"]
            except Exception as e:
                logger.warning(f"[cid {cid}] Embedding error: {e}")
                needs_llm.append(_make_entry(cit, paper, "uncertain", 0.0, "embedding_error", send_to_llm=True))
                continue

            # Decision logic
            if sim >= support_threshold:
                # Strong semantic overlap → resolve as supported
                resolved.append(_make_entry(
                    cit, paper, "supported", round(sim, 3), "embedding",
                    send_to_llm=False, evidence=best_span
                ))

            elif sim < (1.0 - contradict_threshold):
                # Very low overlap — suspicious but not certain, send to LLM with flag
                needs_llm.append(_make_entry(
                    cit, paper, "uncertain", round(sim, 3), "embedding_low_similarity",
                    send_to_llm=True, evidence=best_span,
                    embedding_hint="possible_contradiction"
                ))

            else:
                # Middle zone — send to LLM to decide
                needs_llm.append(_make_entry(
                    cit, paper, "uncertain", round(sim, 3), "embedding_uncertain",
                    send_to_llm=True, evidence=best_span
                ))

        logger.info(
            f"Embedding gate: {len(resolved)} resolved, {len(needs_llm)} sent to LLM"
        )

        return AgentResult(
            agent_name=self.name,
            status="success",
            data={"resolved": resolved, "needs_llm": needs_llm},
            tokens_used=0,
        )

    def _build_needs_llm_list(self, ctx: PipelineContext) -> list:
        """Fallback when model unavailable — send everything found to LLM."""
        out = []
        for cit in ctx.citations:
            cid = cit["id"]
            existence = ctx.existence_results.get(cid)
            if existence and existence.get("status") == "found":
                out.append(_make_entry(
                    cit, existence.get("paper", {}),
                    "uncertain", 0.0, "no_embedding_model", send_to_llm=True
                ))
        return out


def _make_entry(
    cit: dict,
    paper: dict,
    verdict: str,
    confidence: float,
    method: str,
    *,
    send_to_llm: bool = False,
    evidence: str = "",
    embedding_hint: str = "",
) -> dict:
    return {
        "citation": cit,
        "source": paper,
        "verdict": verdict,
        "confidence": confidence,
        "method": method,
        "evidence": evidence,
        "embedding_hint": embedding_hint,
        "needs_llm": send_to_llm,
    }


registry.register(EmbeddingGateAgent())
