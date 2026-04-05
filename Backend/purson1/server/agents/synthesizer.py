"""
Synthesizer Agent
=================
Stage: SYNTHESIZING

Merges all pipeline stage outputs into the final integrity report.
Every citation verdict includes:
  - Where the source was found (Semantic Scholar / CrossRef / OpenAlex)
  - The evidence quote from the source abstract
  - The method used (embedding / llm)
  - A plain-English explanation

This is the "show your work" layer that makes the tool trustworthy.
"""

from __future__ import annotations

import logging
from server.agents.base import BaseAgent, AgentResult, PipelineContext, PipelineStage, registry

logger = logging.getLogger("citesafe.synthesizer")


class SynthesizerAgent(BaseAgent):
    name = "synthesizer"
    stage = PipelineStage.SYNTHESIZING
    description = "Merges all stage results into a transparent final report"
    requires_tokens = False

    async def process(self, ctx: PipelineContext) -> AgentResult:
        await ctx.send_progress("Synthesizing report...", 88)

        # Build a fast lookup: citation_id → verification result
        verif_by_id: dict[int, dict] = {}

        # Embedding-resolved citations
        for entry in ctx.embedding_resolved:
            cit = entry.get("citation", {})
            cid = cit.get("id")
            if cid is not None:
                verif_by_id[cid] = entry

        # LLM-verified citations (overwrite embedding if present — LLM is more authoritative)
        for entry in ctx.llm_results:
            cit = entry.get("citation", {})
            cid = cit.get("id")
            if cid is not None:
                verif_by_id[cid] = entry

        # Build final citation list
        final_citations = []
        counts = {"supported": 0, "contradicted": 0, "uncertain": 0, "not_found": 0}

        for cit in ctx.citations:
            cid = cit["id"]
            existence = ctx.existence_results.get(cid, {})
            existence_status = existence.get("status", "not_found")
            source_paper = existence.get("paper")
            metadata_status = existence.get("metadata_status")
            metadata_errors = existence.get("metadata_errors", [])

            entry: dict = {
                "id": cid,
                "claim": cit.get("claim", ""),
                "context": cit.get("context", ""),
                "reference": cit.get("reference", {}),
                "existence_status": existence_status,
                "source": existence.get("source", "unknown"),  # which DB found it
                "match_score": existence.get("match_score", 0),
                "source_found": None,
                "metadata_status": metadata_status,
                "metadata_errors": metadata_errors,
                "verification": None,
            }

            if source_paper:
                entry["source_found"] = {
                    "title":   source_paper.get("title"),
                    "authors": source_paper.get("authors", []),
                    "year":    source_paper.get("year"),
                    "paper_id": source_paper.get("paper_id", ""),
                    "_source": source_paper.get("_source", existence.get("source", "")),
                }

            if existence_status == "not_found":
                counts["not_found"] += 1
                final_citations.append(entry)
                continue

            # Attach verification
            verif = verif_by_id.get(cid)
            if verif:
                verdict = verif.get("verdict", "uncertain")
                entry["verification"] = {
                    "verdict":     verdict,
                    "confidence":  verif.get("confidence", 0.0),
                    "evidence":    verif.get("evidence", ""),
                    "explanation": verif.get("explanation", ""),
                    "method":      verif.get("method", "unknown"),
                }
                counts[verdict if verdict in counts else "uncertain"] += 1
            else:
                # Found but no verification ran (e.g. all stages skipped)
                entry["verification"] = {
                    "verdict":    "uncertain",
                    "confidence": 0.0,
                    "evidence":   "",
                    "explanation": "Verification did not run for this citation.",
                    "method":     "none",
                }
                counts["uncertain"] += 1

            final_citations.append(entry)

        # Integrity score: supported / (supported + contradicted + uncertain)
        verifiable = counts["supported"] + counts["contradicted"] + counts["uncertain"]
        integrity_score = round(
            (counts["supported"] / verifiable * 100) if verifiable > 0 else 0.0, 1
        )

        # Paper metadata
        paper_meta = {}
        if ctx.fetcher_result:
            paper_meta = {
                "title":   ctx.fetcher_result.get("title", ""),
                "authors": ctx.fetcher_result.get("authors", []),
                "year":    ctx.fetcher_result.get("year"),
                "source":  ctx.fetcher_result.get("source", ""),
            }

        # Cost estimate (Gemini 2.0 Flash: ~$0.10/1M input tokens)
        tokens = ctx.stats.get("total_tokens", 0)
        estimated_cost = round(tokens * 0.0000001, 5)

        report = {
            "integrity_score": integrity_score,
            "total_citations": len(final_citations),
            "summary": {
                "supported":       counts["supported"],
                "contradicted":    counts["contradicted"],
                "uncertain":       counts["uncertain"],
                "not_found":       counts["not_found"],
                "metadata_errors": sum(
                    1 for c in final_citations
                    if c.get("metadata_status") == "has_errors"
                ),
            },
            "paper": paper_meta,
            "citations": final_citations,
            "stats": {
                "total_tokens":    tokens,
                "total_api_calls": ctx.stats.get("total_api_calls", 0),
                "cache_hits":      ctx.stats.get("cache_hits", 0),
                "latency_ms":      ctx.stats.get("latency_total_ms", 0),
                "estimated_cost":  estimated_cost,
                "processing_time_ms": ctx.stats.get("latency_total_ms", 0),
                "agents_invoked":  len(ctx.agent_timings),
                "embedding_resolved": len(ctx.embedding_resolved),
                "llm_verified":    len(ctx.llm_results),
            },
        }

        logger.info(
            f"Report: score={integrity_score}% | "
            f"supported={counts['supported']} contradicted={counts['contradicted']} "
            f"uncertain={counts['uncertain']} not_found={counts['not_found']}"
        )

        return AgentResult(
            agent_name=self.name,
            status="success",
            data=report,
            tokens_used=0,
        )


registry.register(SynthesizerAgent())
