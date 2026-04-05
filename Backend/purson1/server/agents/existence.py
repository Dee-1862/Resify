import asyncio
import aiosqlite
import hashlib
import json
import logging
import os
import re
from typing import Any, Dict, Optional
from server.agents.base import BaseAgent, AgentResult, PipelineContext, PipelineStage, registry
from server.utils.apis import SemanticScholarAPI, CrossRefAPI, OpenAlexAPI, DblpAPI, APIError

_here = os.path.dirname(os.path.abspath(__file__))
_default_existence_db = os.path.join(_here, "..", "..", "existence_cache.db")

logger = logging.getLogger("citesafe.existence")

# Stop words to strip before title comparison
_STOP = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or",
    "with", "by", "from", "is", "are", "was", "be", "as", "into", "via",
}


# ── Cache ──────────────────────────────────────────────────────────────────────

class ExistenceCache:
    def __init__(self, db_path=_default_existence_db):
        self.db_path = db_path

    async def init_db(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    lookup_key TEXT PRIMARY KEY,
                    paper_id   TEXT,
                    data       TEXT,
                    cached_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS paper_citations (
                    paper_key   TEXT    NOT NULL,
                    citation_id INTEGER NOT NULL,
                    lookup_key  TEXT    NOT NULL,
                    PRIMARY KEY (paper_key, citation_id)
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_pc_paper_key ON paper_citations(paper_key)"
            )
            await db.commit()

    async def record_paper_citations(self, paper_key: str, citation_links: list[tuple[int, str]]):
        async with aiosqlite.connect(self.db_path) as db:
            await db.executemany(
                "INSERT OR REPLACE INTO paper_citations (paper_key, citation_id, lookup_key) VALUES (?,?,?)",
                [(paper_key, cid, lk) for cid, lk in citation_links],
            )
            await db.commit()

    def _generate_key(self, title: str, author: str, year: Any) -> str:
        s = f"{title}_{author}_{year}".lower()
        return hashlib.sha256(s.encode()).hexdigest()

    async def get(self, title: str, author: str, year: Any) -> Optional[Dict]:
        key = self._generate_key(title, author, year)
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT data FROM cache WHERE lookup_key = ?", (key,)) as cur:
                row = await cur.fetchone()
                return json.loads(row[0]) if row else None

    async def set(self, title: str, author: str, year: Any, paper_id: str, data: Dict):
        key = self._generate_key(title, author, year)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO cache (lookup_key, paper_id, data) VALUES (?,?,?)",
                (key, paper_id, json.dumps(data)),
            )
            await db.commit()


# ── Text helpers ───────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def token_overlap(a: str, b: str) -> float:
    """Jaccard similarity on non-stop word tokens."""
    ta = {t for t in normalize(a).split() if t not in _STOP and len(t) > 1}
    tb = {t for t in normalize(b).split() if t not in _STOP and len(t) > 1}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def clean_title(title: str) -> str:
    """Strip subtitle after colon/dash and common noise."""
    title = re.sub(r"\s*[:\-–—]\s+.*$", "", title).strip()
    title = re.sub(r"\(.*?\)", "", title).strip()
    return title


def first_author_lastname(authors_str: str) -> str:
    if not authors_str:
        return ""
    cleaned = re.sub(r"\bet al\.?\b", "", authors_str, flags=re.I).strip()
    # Handle "Smith, J." or "John Smith"
    parts = re.split(r"[,\s]+", cleaned)
    parts = [p for p in parts if p]
    if not parts:
        return ""
    # Prefer last token of first segment (last name usually last in "First Last" or first in "Last, First")
    first_seg = cleaned.split(",")[0].strip().split()
    return normalize(first_seg[-1]) if first_seg else normalize(parts[0])


def extract_authors_list(authors_field) -> list[str]:
    """Normalise authors from either str or list[str|dict]."""
    result = []
    if isinstance(authors_field, str):
        result = [normalize(authors_field)]
    elif isinstance(authors_field, list):
        for a in authors_field:
            if isinstance(a, str):
                result.append(normalize(a))
            elif isinstance(a, dict):
                result.append(normalize(a.get("name", "") or a.get("display_name", "")))
    return [r for r in result if r]


# ── Scorer ─────────────────────────────────────────────────────────────────────

def score_match(reference: dict, paper: dict) -> float:
    """
    Score 0–100 for how well a search result matches a reference.

    Weights:
      Title similarity   — up to 55 pts  (using stop-word-filtered token overlap)
      Year match         — up to 25 pts  (exact=25, ±1=12, ±2=5)
      Author match       — up to 20 pts  (first author last name present anywhere)
    """
    ref_title   = reference.get("title",   "") or ""
    ref_year    = reference.get("year")
    ref_authors = reference.get("authors", "") or ""
    ref_author_ln = first_author_lastname(ref_authors)
    has_title = len(ref_title.strip()) > 3

    score = 0.0

    # ── Title ──
    paper_title = paper.get("title", "") or ""
    if has_title and paper_title:
        raw_sim = token_overlap(ref_title, paper_title)
        # Bonus for cleaned-title match (strips subtitles)
        clean_sim = token_overlap(clean_title(ref_title), clean_title(paper_title))
        score += max(raw_sim, clean_sim) * 55

    # ── Year ──
    paper_year = paper.get("year")
    if paper_year and ref_year:
        try:
            diff = abs(int(paper_year) - int(ref_year))
            if diff == 0:
                score += 25
            elif diff == 1:
                score += 12
            elif diff == 2:
                score += 5
        except (ValueError, TypeError):
            pass

    # ── Author ──
    paper_authors = extract_authors_list(paper.get("authors", []))
    if ref_author_ln and paper_authors:
        if any(ref_author_ln in a for a in paper_authors):
            score += 20
        # Partial: first 4 chars of last name
        elif len(ref_author_ln) >= 4 and any(ref_author_ln[:4] in a for a in paper_authors):
            score += 8

    return round(score, 1)


def best_match(reference: dict, results: list) -> tuple[Optional[dict], float]:
    """Return (best_paper, score) or (None, best_score) if below threshold."""
    if not results:
        return None, 0.0

    ref_title = reference.get("title", "") or ""
    has_title = len(ref_title.strip()) > 3
    scored = [(score_match(reference, p), p) for p in results]
    scored.sort(key=lambda x: x[0], reverse=True)
    top_score, top_paper = scored[0]

    # Adaptive threshold:
    #   - Long title present → 45 (title alone can clear 55*0.82≈45)
    #   - Short/no title     → 38 (author+year=45 is the ceiling)
    threshold = 45 if has_title else 38
    if top_score >= threshold:
        return top_paper, top_score
    return None, top_score


# ── Agent ──────────────────────────────────────────────────────────────────────

class ExistenceAgent(BaseAgent):
    name = "existence"
    stage = PipelineStage.CHECKING_EXISTENCE
    description = "Check citation existence via S2 → CrossRef → OpenAlex → DBLP"
    requires_tokens = False

    def __init__(self, db_path=_default_existence_db, concurrency_limit=3):
        super().__init__()
        from server.config import settings
        self.s2 = SemanticScholarAPI(api_key=settings.S2_API_KEY or None)
        self.crossref = CrossRefAPI()
        self.openalex = OpenAlexAPI()
        self.dblp = DblpAPI()
        self.cache = ExistenceCache(db_path)
        self.concurrency_limit = concurrency_limit

    def _verify_metadata(self, reference: dict, matched_paper: dict) -> dict:
        errors = []
        ref_year = reference.get("year")
        try:
            if ref_year and matched_paper.get("year"):
                if abs(int(ref_year) - int(matched_paper["year"])) > 1:
                    errors.append({
                        "field": "year",
                        "claimed": ref_year,
                        "actual": matched_paper["year"],
                        "message": f"Year mismatch: cited as {ref_year}, actual {matched_paper['year']}",
                    })
        except (ValueError, TypeError):
            pass
        return {
            "metadata_status": "has_errors" if errors else "correct",
            "metadata_errors": errors,
        }

    async def _lookup(self, reference: dict, cit: dict) -> tuple[Optional[dict], float, str]:
        """
        Multi-strategy lookup: try progressively simpler queries across three
        databases before giving up.

        Returns (matched_paper | None, score, source_name).
        """
        ref_title   = (reference.get("title",   "") or "").strip()
        ref_year    = str(reference.get("year",  "") or "").strip()
        ref_authors = (reference.get("authors", "") or "").strip()
        first_author = first_author_lastname(ref_authors)
        clean = clean_title(ref_title)

        # Build a prioritised list of query strings to try on S2
        queries = []
        if ref_title:
            queries.append(f"{ref_title} {first_author} {ref_year}".strip())  # full
            if clean != ref_title:
                queries.append(f"{clean} {first_author} {ref_year}".strip())   # cleaned title
            queries.append(ref_title)                                           # title only
        if first_author and ref_year:
            claim_hint = (cit.get("claim", "") or "")[:60]
            queries.append(f"{first_author} {ref_year} {claim_hint}".strip())  # author+year
        # Deduplicate while preserving order
        seen, unique_queries = set(), []
        for q in queries:
            if q and q not in seen:
                seen.add(q)
                unique_queries.append(q)

        # ── Pass 1: Semantic Scholar (multiple queries) ──────────────────────
        for query in unique_queries:
            try:
                results = await self.s2.search(query, limit=8)
                m, sc = best_match(reference, results)
                if m:
                    return m, sc, "semantic_scholar"
            except APIError as e:
                if e.status_code == 429:
                    await asyncio.sleep(2)
                logger.warning(f"S2 error on query '{query[:50]}': {e}")
                break  # don't keep hammering on rate-limit errors

        # ── Pass 2: CrossRef (title-based) ───────────────────────────────────
        if ref_title:
            for q in [ref_title, clean]:
                try:
                    results = await self.crossref.search(q, limit=5)
                    m, sc = best_match(reference, results)
                    if m:
                        m["_source"] = "crossref"
                        return m, sc, "crossref"
                except Exception as e:
                    logger.warning(f"CrossRef error: {e}")
                    break

        # ── Pass 3: OpenAlex (title filter, then keyword search) ─────────────
        if ref_title:
            try:
                results = await self.openalex.search_by_title(ref_title, limit=5)
                m, sc = best_match(reference, results)
                if m:
                    return m, sc, "openalex"
            except Exception as e:
                logger.warning(f"OpenAlex title filter error: {e}")

            try:
                q = f"{ref_title} {first_author}".strip()
                results = await self.openalex.search(q, limit=8)
                m, sc = best_match(reference, results)
                if m:
                    return m, sc, "openalex"
            except Exception as e:
                logger.warning(f"OpenAlex search error: {e}")

        # ── Pass 4: DBLP (excellent NLP/CL venue coverage + ACL Anthology) ──
        if ref_title:
            for q in [
                f"{ref_title} {first_author} {ref_year}".strip(),
                ref_title,
            ]:
                try:
                    results = await self.dblp.search(q, limit=8)
                    m, sc = best_match(reference, results)
                    if m:
                        return m, sc, m.get("_source", "dblp")
                except Exception as e:
                    logger.warning(f"DBLP search error: {e}")
                    break

        return None, 0.0, "none"

    async def _process_single_citation(
        self, cit: dict, semaphore: asyncio.Semaphore
    ) -> tuple[int, dict, str]:
        async with semaphore:
            cid = cit["id"]
            reference = cit.get("reference", {})
            if not reference:
                return cid, {"status": "error", "reason": "No reference data"}, ""

            ref_title   = (reference.get("title",   "") or "").strip()
            ref_year    = reference.get("year", "") or ""
            first_author = first_author_lastname(reference.get("authors", "") or "")
            lookup_key  = self.cache._generate_key(ref_title, first_author, ref_year)

            # ── Cache hit ────────────────────────────────────────────────────
            cached = await self.cache.get(ref_title, first_author, ref_year)
            if cached:
                cached["cached"] = True
                return cid, cached, lookup_key

            # ── Live lookup ──────────────────────────────────────────────────
            try:
                matched, score, source = await self._lookup(reference, cit)
            except Exception as e:
                logger.error(f"[cid {cid}] Unhandled lookup error: {e}")
                return cid, {"status": "error", "reason": str(e)}, lookup_key

            if not matched:
                response_data = {
                    "status": "not_found",
                    "reason": "Not found after exhaustive search (S2 + CrossRef + OpenAlex)",
                    "cached": False,
                }
                # Cache not-found too (TTL 7 days) so we don't re-hammer APIs
                await self.cache.set(ref_title, first_author, ref_year, "", response_data)
                return cid, response_data, lookup_key

            paper_obj = {
                "paper_id":       matched.get("paperId", matched.get("id", "")),
                "title":          matched.get("title"),
                "authors":        extract_authors_list(matched.get("authors", [])),
                "year":           matched.get("year"),
                "abstract":       matched.get("abstract", ""),
                "tldr":           matched.get("tldr"),
                "openAccessPdf":  matched.get("openAccessPdf"),
                "externalIds":    matched.get("externalIds", {}),
                "_source":        source,
            }

            # Enrich with full text if available
            try:
                from server.utils.text_enricher import enrich_source_text
                enriched = await enrich_source_text(paper_obj)
                paper_obj["full_text"]    = enriched["text"]
                paper_obj["text_source"]  = enriched["source"]
            except Exception as e:
                logger.warning(f"[cid {cid}] Text enrichment failed: {e}")
                paper_obj["full_text"]   = paper_obj.get("abstract", "")
                paper_obj["text_source"] = "abstract"

            meta = self._verify_metadata(reference, paper_obj)
            response_data = {
                "status":           "found",
                "paper":            paper_obj,
                "match_score":      score,
                "metadata_status":  meta["metadata_status"],
                "metadata_errors":  meta["metadata_errors"],
                "source":           source,
                "cached":           False,
            }
            await self.cache.set(ref_title, first_author, ref_year, paper_obj["paper_id"], response_data)
            return cid, response_data, lookup_key

    async def process(self, ctx: PipelineContext) -> AgentResult:
        await self.cache.init_db()
        semaphore = asyncio.Semaphore(self.concurrency_limit)

        tasks = [self._process_single_citation(cit, semaphore) for cit in ctx.citations]
        results_tuples = await asyncio.gather(*tasks)

        # Record paper → citation links
        from server.core.cache import CiteSafeCache
        paper_key = CiteSafeCache.make_paper_key(
            url=ctx.paper_url or "",
            doi=ctx.paper_doi or "",
            text=ctx.paper_text or "",
        )
        citation_links = [(cid, lk) for cid, _, lk in results_tuples if lk]
        if citation_links:
            await self.cache.record_paper_citations(paper_key, citation_links)

        all_results = {str(cid): res for cid, res, _ in results_tuples}

        found = sum(1 for r in all_results.values() if r.get("status") == "found")
        logger.info(f"Existence check complete: {found}/{len(all_results)} found")

        return AgentResult(
            agent_name=self.name,
            status="success",
            data={"results": all_results},
            tokens_used=0,
        )


registry.register(ExistenceAgent())
