"""
Dummy Agents — Full Pipeline Testing
======================================
Produces contract-compliant output at every stage so the pipeline
can be tested end-to-end before real agents are built.

Each agent's output matches the I/O contract shapes exactly:
  - Fetcher:       {text, title, authors, year, abstract, source, url, arxiv_id, doi}
  - Extractor:     {citations: [{id, claim, context, reference: {authors, title, year, venue}}]}
  - Existence:     {results: {cid: {status, paper?, match_score, cached}}}
  - EmbeddingGate: {resolved: [...], needs_llm: [...]}
  - SemanticLLM:   [{citation, source, verdict, confidence, evidence, method}]

All agents auto-register on import.
"""

from __future__ import annotations

import hashlib
import random
import re

from server.agents.base import (
    AgentResult,
    BaseAgent,
    PipelineContext,
    PipelineStage,
    registry,
)


# ---------------------------------------------------------------------------
# Stage 1: Fetcher — extract text from URL/DOI/raw text
# ---------------------------------------------------------------------------

class DummyFetcher(BaseAgent):
    name = "fetcher"
    stage = PipelineStage.FETCHING
    description = "Fetch and extract paper text (dummy: passes through input)"
    requires_tokens = False

    async def process(self, ctx: PipelineContext) -> AgentResult:
        # In real agent: fetch from arxiv/doi, extract PDF text
        # Dummy: use whatever text is available
        text = ctx.paper_text or f"[Dummy paper text for {ctx.paper_url or ctx.paper_doi}]"

        return AgentResult(
            agent_name=self.name,
            status="success",
            data={
                "text": text,
                "title": "Sample Paper Title",
                "authors": ["Author One", "Author Two"],
                "year": 2024,
                "abstract": text[:500] if len(text) > 500 else text,
                "source": "arxiv" if "arxiv" in (ctx.paper_url or "") else "unknown",
                "url": ctx.paper_url,
                "arxiv_id": _extract_arxiv_id(ctx.paper_url),
                "doi": ctx.paper_doi or None,
            },
            tokens_used=0,
        )


# ---------------------------------------------------------------------------
# Stage 2: Extractor — parse citations from paper text
# ---------------------------------------------------------------------------

class DummyExtractor(BaseAgent):
    name = "extractor"
    stage = PipelineStage.EXTRACTING
    description = "Extract citations from paper text (dummy: regex-based)"
    requires_tokens = False

    # Regex patterns for common citation styles
    INLINE_PATTERNS = [
        # [1], [2,3], [1-5]
        r'\[(\d+(?:\s*[,\-–]\s*\d+)*)\]',
        # (Author et al., 2023)
        r'\(([A-Z][a-z]+(?:\s+et\s+al\.?)?,?\s*\d{4}[a-z]?)\)',
    ]

    # Reference list: [1] Title. Author. Year.
    REF_PATTERN = re.compile(
        r'^\[(\d+)\]\s*(.+?)(?:,\s*(\d{4}))?\.?\s*$',
        re.MULTILINE,
    )

    async def process(self, ctx: PipelineContext) -> AgentResult:
        text = ctx.paper_text
        if not text:
            return AgentResult(
                agent_name=self.name,
                status="success",
                data={"citations": []},
                tokens_used=0,
            )

        citations = []
        seen_ids = set()
        next_id = 1

        # Parse reference list at end of paper
        ref_map = {}
        for match in self.REF_PATTERN.finditer(text):
            ref_num = int(match.group(1))
            title_author = match.group(2).strip()
            year = match.group(3)
            ref_map[ref_num] = {
                "title": title_author.split(".")[0].strip() if "." in title_author else title_author,
                "authors": _guess_authors(title_author),
                "year": int(year) if year else None,
                "venue": None,
            }

        # Extract inline citations and build entries
        for pattern in self.INLINE_PATTERNS:
            for match in re.finditer(pattern, text):
                raw = match.group(0)
                # Extract citation number(s)
                nums = re.findall(r'\d+', match.group(1))
                for num_str in nums:
                    num = int(num_str)
                    if num in seen_ids:
                        continue
                    seen_ids.add(num)

                    claim = _extract_claim(text, match.start())
                    context = _extract_context(text, match.start())
                    reference = ref_map.get(num, {
                        "authors": f"Author{num} et al.",
                        "title": f"Referenced Work {num}",
                        "year": 2020 + (num % 5),
                        "venue": None,
                    })

                    citations.append({
                        "id": num,
                        "claim": claim,
                        "context": context,
                        "reference": reference,
                    })

        # Sort by ID for consistency
        citations.sort(key=lambda c: c["id"])

        return AgentResult(
            agent_name=self.name,
            status="success",
            data={"citations": citations},
            tokens_used=0,
        )


# ---------------------------------------------------------------------------
# Stage 3: Existence — check if cited sources exist
# ---------------------------------------------------------------------------

class DummyExistence(BaseAgent):
    name = "existence"
    stage = PipelineStage.CHECKING_EXISTENCE
    description = "Check citation existence (dummy: random found/not_found)"
    requires_tokens = False

    async def process(self, ctx: PipelineContext) -> AgentResult:
        results = {}

        for cit in ctx.citations:
            cid = cit["id"]
            ref = cit.get("reference", {})

            # Dummy: 85% chance of "found"
            found = random.random() < 0.85

            if found:
                paper_id = hashlib.sha256(
                    f"{ref.get('title', '')}{ref.get('year', '')}".encode()
                ).hexdigest()[:20]

                results[str(cid)] = {
                    "status": "found",
                    "paper": {
                        "paper_id": paper_id,
                        "title": ref.get("title", "Found Paper"),
                        "authors": (
                            [ref["authors"]] if isinstance(ref.get("authors"), str)
                            else ref.get("authors", [])
                        ),
                        "year": ref.get("year"),
                        "abstract": f"This is a dummy abstract for citation {cid}. "
                                    f"The paper discusses findings related to the cited claim.",
                        "doi": None,
                    },
                    "match_score": random.randint(80, 99),
                    "cached": False,
                }
            else:
                results[str(cid)] = {
                    "status": "not_found",
                    "reason": "No matching paper in Semantic Scholar",
                    "query_used": f"{ref.get('title', '')} {ref.get('authors', '')} {ref.get('year', '')}",
                }

        return AgentResult(
            agent_name=self.name,
            status="success",
            data={"results": results},
            tokens_used=0,
        )


# ---------------------------------------------------------------------------
# Stage 4: Embedding Gate — resolve clear cases without LLM
# ---------------------------------------------------------------------------

class DummyEmbeddingGate(BaseAgent):
    name = "embedding_gate"
    stage = PipelineStage.EMBEDDING_GATE
    description = "Embedding-based verification gate (dummy: random split)"
    requires_tokens = False

    async def process(self, ctx: PipelineContext) -> AgentResult:
        resolved = []
        needs_llm = []

        for cit in ctx.citations:
            cid = cit["id"]
            existence = ctx.existence_results.get(cid)
            if not existence or existence.get("status") != "found":
                continue  # skip not-found citations

            source = existence.get("paper", {})
            entry = {
                "citation": cit,
                "source": source,
            }

            # Dummy: 70% resolved by embedding, 30% needs LLM
            if random.random() < 0.70:
                verdict = random.choices(
                    ["supported", "contradicted"],
                    weights=[0.85, 0.15],
                    k=1
                )[0]
                claim_sim = round(random.uniform(0.75, 0.95), 2)
                neg_sim = round(random.uniform(0.2, 0.45), 2)

                entry.update({
                    "verdict": verdict,
                    "confidence": claim_sim,
                    "method": "embedding",
                    "needs_llm": False,
                    "details": {
                        "claim_similarity": claim_sim,
                        "negation_similarity": neg_sim,
                        "margin": round(claim_sim - neg_sim, 2),
                        "negated_claim": f"did not {cit.get('claim', '')}",
                    },
                })
                resolved.append(entry)
            else:
                claim_sim = round(random.uniform(0.5, 0.65), 2)
                neg_sim = round(random.uniform(0.48, 0.63), 2)

                entry.update({
                    "verdict": "uncertain",
                    "confidence": 0.5,
                    "method": "embedding",
                    "needs_llm": True,
                    "details": {
                        "claim_similarity": claim_sim,
                        "negation_similarity": neg_sim,
                        "margin": round(claim_sim - neg_sim, 2),
                        "reason": "Similarities too close to decide",
                    },
                })
                needs_llm.append(entry)

        return AgentResult(
            agent_name=self.name,
            status="success",
            data={
                "resolved": resolved,
                "needs_llm": needs_llm,
            },
            tokens_used=0,
        )


# ---------------------------------------------------------------------------
# Stage 5: Semantic LLM — deep verification for ambiguous cases
# ---------------------------------------------------------------------------

class DummySemanticVerifier(BaseAgent):
    name = "llm_verifier"
    stage = PipelineStage.LLM_VERIFICATION
    description = "LLM-based semantic verification (dummy: random verdicts)"
    requires_tokens = True  # would use tokens in real implementation

    async def process(self, ctx: PipelineContext) -> AgentResult:
        results = []
        dummy_tokens = 0

        for item in ctx.embedding_needs_llm:
            cit = item.get("citation", {})
            source = item.get("source", {})

            verdict = random.choices(
                ["supported", "contradicted", "uncertain"],
                weights=[0.5, 0.3, 0.2],
                k=1
            )[0]

            results.append({
                "citation": cit,
                "source": source,
                "verdict": verdict,
                "confidence": round(random.uniform(0.7, 0.95), 2),
                "evidence": f"[Dummy evidence for citation {cit.get('id')}]",
                "method": "llm",
            })
            dummy_tokens += random.randint(30, 80)

        return AgentResult(
            agent_name=self.name,
            status="success",
            data=results,
            tokens_used=dummy_tokens,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_arxiv_id(url: str) -> str | None:
    if not url:
        return None
    match = re.search(r'arxiv\.org/abs/(\d+\.\d+)', url)
    return match.group(1) if match else None


def _extract_claim(text: str, pos: int, window: int = 200) -> str:
    """Extract the sentence containing the citation as the claim."""
    start = max(0, pos - window)
    end = min(len(text), pos + window)
    chunk = text[start:end]
    sentences = re.split(r'(?<=[.!?])\s+', chunk)
    for sent in sentences:
        if text[pos:pos + 5] in sent:
            # Strip the citation marker from the claim
            claim = re.sub(r'\[\d+(?:\s*[,\-–]\s*\d+)*\]', '', sent).strip()
            return claim[:200]
    return chunk[max(0, pos - start - 80):min(len(chunk), pos - start + 80)].strip()


def _extract_context(text: str, pos: int, window: int = 150) -> str:
    """Extract surrounding context for the citation."""
    start = max(0, pos - window)
    end = min(len(text), pos + window)
    return text[start:end].strip()


def _guess_authors(text: str) -> str:
    """Extract author-like string from a reference line."""
    # Simple heuristic: take text before first period
    parts = text.split(".")
    if len(parts) > 1:
        return parts[-1].strip() if parts[-1].strip() else parts[0].strip()
    return text.strip()[:50]


# ---------------------------------------------------------------------------
# Auto-register all dummy agents on import
# ---------------------------------------------------------------------------

# Only register dummies for stages that don't have real agents yet
# Real agents (fetcher, extractor, existence, embedding_gate, llm_verifier, synthesizer)
# override these when imported in main.py
registry.register(DummyFetcher())
registry.register(DummyExtractor())
registry.register(DummyExistence())
registry.register(DummyEmbeddingGate())
registry.register(DummySemanticVerifier())
