"""
LLM Verifier Agent
==================
Stage: LLM_VERIFICATION

For each citation the embedding gate flagged as uncertain or possibly contradicted:
  - Sends claim + context + source abstract to Gemini
  - Gets back a structured verdict: supported / contradicted / uncertain
  - Includes a quoted evidence snippet and a plain-English explanation

This is the core "show your work" layer — every verdict is grounded
in a specific passage from the source paper's abstract.
"""

from __future__ import annotations

import asyncio
import json
import logging

from google import genai
from pydantic import BaseModel, Field

from server.agents.base import BaseAgent, AgentResult, PipelineContext, PipelineStage, registry
from server.config import settings

logger = logging.getLogger("citesafe.llm_verifier")


# ── Structured output schema ───────────────────────────────────────────────────

class VerificationResult(BaseModel):
    verdict: str = Field(
        description="One of: 'supported', 'contradicted', 'uncertain'"
    )
    confidence: float = Field(
        description="Confidence in the verdict, 0.0 to 1.0"
    )
    evidence: str = Field(
        description="A direct quote or close paraphrase from the source abstract that most supports the verdict. Max 2 sentences."
    )
    explanation: str = Field(
        description="One concise sentence explaining why this verdict was assigned."
    )


SYSTEM_PROMPT = """You are a rigorous academic citation verifier. Your job is to check whether a cited claim is actually supported by the source paper.

You will be given:
1. CLAIM: What the citing paper asserts about the cited work
2. CONTEXT: The sentence in which the citation appears (may be empty)
3. SOURCE ABSTRACT: The abstract of the cited paper

Your task:
- Read the claim carefully. What is the citing paper asserting?
- Check the source abstract. Does it actually say that?
- Assign a verdict:
  - "supported": The abstract clearly supports or is consistent with the claim
  - "contradicted": The abstract contradicts, conflicts with, or says something meaningfully different from the claim
  - "uncertain": The abstract is too vague, off-topic, or doesn't contain enough information to judge

Rules:
- Be strict. If the claim makes a specific quantitative assertion not in the abstract, that is "uncertain" not "supported"
- If the claim is a general description of what the paper does and the abstract confirms it, that is "supported"
- Minor year/author errors do not affect the verdict — only content accuracy matters
- Always extract a specific evidence quote from the abstract, not from the claim
- Never hallucinate. If the abstract is empty or too short, return "uncertain"
"""


class LLMVerifierAgent(BaseAgent):
    name = "llm_verifier"
    stage = PipelineStage.LLM_VERIFICATION
    description = "Gemini-powered deep citation claim verification with evidence"
    requires_tokens = True

    def __init__(self, model_name: str = "gemini-2.0-flash"):
        super().__init__()
        self.model_name = model_name
        try:
            self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
        except Exception as e:
            logger.error(f"Failed to init Gemini client: {e}")
            self.client = None

    async def pre_check(self, ctx: PipelineContext) -> bool:
        if not self.client:
            logger.warning("LLM verifier skipped — no Gemini client")
            return False
        if not ctx.embedding_needs_llm:
            logger.info("No citations need LLM verification")
            return False
        return await super().pre_check(ctx)

    async def process(self, ctx: PipelineContext) -> AgentResult:
        citations_to_verify = ctx.embedding_needs_llm
        total = len(citations_to_verify)
        await ctx.send_progress(f"Deep verification on {total} citation(s)...", 68)

        loop = asyncio.get_event_loop()
        results = []
        total_tokens = 0

        # Process in batches of 5 to avoid overwhelming the API
        batch_size = 5
        for i in range(0, total, batch_size):
            batch = citations_to_verify[i:i + batch_size]
            progress = 68 + int((i / total) * 15)
            await ctx.send_progress(f"Verifying citations {i+1}–{min(i+batch_size, total)} of {total}...", progress)

            tasks = [self._verify_one(entry, loop) for entry in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for entry, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    logger.error(f"Verification failed for cid {entry['citation'].get('id')}: {result}")
                    results.append(_uncertain_result(entry, str(result)))
                else:
                    verdict_data, tokens = result
                    total_tokens += tokens
                    results.append(verdict_data)

        logger.info(f"LLM verifier: {total} citations processed, {total_tokens} tokens used")

        return AgentResult(
            agent_name=self.name,
            status="success",
            data={"results": results},
            tokens_used=total_tokens,
        )

    async def _verify_one(self, entry: dict, loop: asyncio.AbstractEventLoop) -> tuple[dict, int]:
        cit = entry["citation"]
        source = entry["source"]
        embedding_hint = entry.get("embedding_hint", "")

        claim = (cit.get("claim") or "").strip()
        context = (cit.get("context") or "").strip()
        # Use full_text if available, fall back to abstract
        source_text = (source.get("full_text") or source.get("abstract") or "").strip()
        text_source = source.get("text_source", "abstract")
        source_title = (source.get("title") or "Unknown").strip()

        if not claim:
            return _uncertain_result(entry, "No claim text available"), 0

        if not source_text:
            # Last-chance fallback: try abstract directly from existence result
            source_text = (source.get("abstract") or "").strip()
            if source_text:
                text_source = "abstract"
                max_source_chars = 1500
            else:
                return _uncertain_result(entry, "The source paper was found but no readable text is available to verify this claim against."), 0

        # Truncate — use more chars when we have full text vs just abstract
        max_source_chars = 8000 if text_source in ("full_pdf", "arxiv_pdf") else 1500
        source_excerpt = source_text[:max_source_chars]

        # Build the user message
        hint_note = ""
        if embedding_hint == "possible_contradiction":
            hint_note = "\nNote: Semantic similarity between claim and source is very low — pay extra attention to potential contradictions.\n"

        source_label = "SOURCE ABSTRACT" if text_source == "abstract" else "SOURCE TEXT (full paper excerpt)"

        user_message = f"""CLAIM: {claim}

CONTEXT (sentence containing citation): {context or "Not available"}

SOURCE PAPER TITLE: {source_title}

{source_label}:
{source_excerpt}
{hint_note}"""

        def call_gemini():
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=user_message,
                config={
                    "system_instruction": SYSTEM_PROMPT,
                    "response_mime_type": "application/json",
                    "response_schema": VerificationResult,
                    "temperature": 0.05,
                    "max_output_tokens": 512,
                },
            )
            return response

        response = await loop.run_in_executor(None, call_gemini)

        tokens = 0
        if response.usage_metadata:
            tokens = (response.usage_metadata.prompt_token_count or 0) + \
                     (response.usage_metadata.candidates_token_count or 0)

        # Parse result
        try:
            if hasattr(response, "parsed") and response.parsed:
                v = response.parsed
                verdict = v.verdict if v.verdict in ("supported", "contradicted", "uncertain") else "uncertain"
                confidence = max(0.0, min(1.0, float(v.confidence)))
                evidence = v.evidence or ""
                explanation = v.explanation or ""
            else:
                raw = json.loads(response.text)
                verdict = raw.get("verdict", "uncertain")
                if verdict not in ("supported", "contradicted", "uncertain"):
                    verdict = "uncertain"
                confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.5))))
                evidence = raw.get("evidence", "")
                explanation = raw.get("explanation", "")
        except Exception as parse_err:
            logger.warning(f"Failed to parse Gemini response: {parse_err}")
            return _uncertain_result(entry, f"Parse error: {parse_err}"), tokens

        return {
            "citation": cit,
            "source": source,
            "verdict": verdict,
            "confidence": confidence,
            "evidence": evidence,
            "explanation": explanation,
            "method": "llm",
            "embedding_hint": embedding_hint,
        }, tokens


def _uncertain_result(entry: dict, reason: str) -> dict:
    return {
        "citation": entry["citation"],
        "source": entry.get("source", {}),
        "verdict": "uncertain",
        "confidence": 0.0,
        "evidence": "",
        "explanation": reason,
        "method": "llm_fallback",
        "embedding_hint": entry.get("embedding_hint", ""),
    }


registry.register(LLMVerifierAgent())
