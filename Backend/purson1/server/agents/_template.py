"""
Agent Template — Copy this to create a new agent
==================================================

Steps:
  1. Copy this file to server/agents/your_agent.py
  2. Rename the class, set name/stage/description
  3. Implement process() — return an AgentResult with contract-compliant data
  4. Add `from server.agents import your_agent` in server/main.py
  5. Done. Pipeline picks it up automatically.

I/O Contract reference:
  - Fetcher (FETCHING):          returns {text, title, authors, year, abstract, source, url, arxiv_id, doi}
  - Extractor (EXTRACTING):      returns {citations: [{id, claim, context, reference: {authors, title, year, venue}}]}
  - Existence (CHECKING_EXISTENCE): returns {results: {cid: {status, paper?, match_score, cached}}}
  - EmbeddingGate (EMBEDDING_GATE): returns {resolved: [...], needs_llm: [...]}
  - Semantic (LLM_VERIFICATION): returns [{citation, source, verdict, confidence, evidence, method}]
  - Synthesizer (SYNTHESIZING):  returns the final report dict
"""

from __future__ import annotations
from server.agents.base import (
    AgentResult, BaseAgent, PipelineContext, PipelineStage, registry,
)


class MyAgent(BaseAgent):
    # --- Identity ---
    name = "my_agent"
    stage = PipelineStage.EMBEDDING_GATE   # set your stage
    description = "What this agent does in one sentence"

    # --- Set True if this agent calls an LLM ---
    requires_tokens = False

    async def pre_check(self, ctx: PipelineContext) -> bool:
        """Optional: return False to skip this agent for this run."""
        if not ctx.citations:
            return False
        return await super().pre_check(ctx)

    async def process(self, ctx: PipelineContext) -> AgentResult:
        """
        Core logic. Read from ctx, return AgentResult.

        The pipeline will store your result.data into the right ctx field.

        Tips:
          - Send progress: await ctx.send_progress("Working...", 50)
          - Track tokens: include tokens_used in your AgentResult
          - Access cache: from server.core.cache import CiteSafeCache
        """
        await ctx.send_progress(f"Processing {len(ctx.citations)} citations...", 50)

        resolved = []
        needs_llm = []

        for cit in ctx.citations:
            cid = cit["id"]
            existence = ctx.existence_results.get(cid)
            if not existence or existence.get("status") != "found":
                continue

            source = existence.get("paper", {})

            # --- Your verification logic here ---
            # Example: compute embeddings, compare similarities, decide verdict

            resolved.append({
                "citation": cit,
                "source": source,
                "verdict": "uncertain",
                "confidence": 0.5,
                "method": self.name,
                "needs_llm": True,  # or False if resolved
                "details": {},
            })

        return AgentResult(
            agent_name=self.name,
            status="success",
            data={
                "resolved": [r for r in resolved if not r["needs_llm"]],
                "needs_llm": [r for r in resolved if r["needs_llm"]],
            },
            tokens_used=0,
        )


# Auto-register when imported
# registry.register(MyAgent())
