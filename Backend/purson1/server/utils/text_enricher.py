"""
Source Paper Text Enricher
===========================
Given a paper dict from the existence cache, attempts to fetch the best
available text content for verification — in order of richness:

  1. Full PDF text via open-access URL (S2 openAccessPdf or OpenAlex oa_url)
  2. Full PDF text via arXiv PDF (if externalIds.ArXiv is present)
  3. S2 TLDR (AI-generated summary — better than nothing)
  4. Abstract (fallback — already stored)

Returns a dict:
  {
    "text":   str,   # best available content, truncated to max_chars
    "source": str,   # "full_pdf" | "arxiv_pdf" | "tldr" | "abstract"
    "chars":  int,   # length of returned text
  }
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger("citesafe.text_enricher")

# Max chars to keep from a full PDF — enough for intro + related work
_PDF_MAX_CHARS = 12_000
# Max chars from abstract/tldr
_ABSTRACT_MAX_CHARS = 3_000


async def enrich_source_text(paper: dict) -> dict:
    """
    Fetch the richest available text for a found paper.
    `paper` is the dict stored under existence_result["paper"].
    """
    title = (paper.get("title") or "")[:60]

    # ── 1. Open-access PDF (S2 or OpenAlex) ──────────────────────────────
    oa_pdf = paper.get("openAccessPdf") or {}
    oa_url = oa_pdf.get("url") if isinstance(oa_pdf, dict) else None

    if oa_url:
        text = await _fetch_pdf_text(oa_url, _PDF_MAX_CHARS)
        if text:
            logger.info(f"[enricher] '{title}': full PDF via open access ({len(text)} chars)")
            return {"text": text, "source": "full_pdf", "chars": len(text)}

    # ── 2. arXiv PDF ──────────────────────────────────────────────────────
    external_ids = paper.get("externalIds") or {}
    arxiv_id = external_ids.get("ArXiv") or external_ids.get("arxiv") or ""
    if arxiv_id:
        # Strip URL prefix if present
        arxiv_id = re.sub(r"https?://arxiv\.org/abs/", "", arxiv_id).strip()
        if arxiv_id:
            arxiv_url = f"https://arxiv.org/pdf/{arxiv_id}"
            text = await _fetch_pdf_text(arxiv_url, _PDF_MAX_CHARS)
            if text:
                logger.info(f"[enricher] '{title}': full PDF via arXiv ({len(text)} chars)")
                return {"text": text, "source": "arxiv_pdf", "chars": len(text)}

    # ── 3. S2 TLDR (AI summary — richer than abstract alone) ─────────────
    tldr = paper.get("tldr") or {}
    tldr_text = tldr.get("text") if isinstance(tldr, dict) else None
    abstract = (paper.get("abstract") or "").strip()

    if tldr_text and abstract:
        combined = f"{abstract}\n\nSummary: {tldr_text}"[:_ABSTRACT_MAX_CHARS]
        logger.info(f"[enricher] '{title}': abstract + TLDR ({len(combined)} chars)")
        return {"text": combined, "source": "tldr", "chars": len(combined)}

    # ── 4. Abstract only ─────────────────────────────────────────────────
    if abstract:
        logger.info(f"[enricher] '{title}': abstract only ({len(abstract)} chars)")
        return {"text": abstract[:_ABSTRACT_MAX_CHARS], "source": "abstract", "chars": len(abstract)}

    return {"text": "", "source": "none", "chars": 0}


async def _fetch_pdf_text(url: str, max_chars: int) -> Optional[str]:
    """Download and extract text from a PDF URL. Returns None on any failure."""
    try:
        from server.utils.pdf import PDFScraper
        text = await PDFScraper.extract_text_from_url(url, max_chars=max_chars)
        if not text or len(text.strip()) < 200:
            return None
        # Clean up common PDF extraction noise
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{3,}", " ", text)
        return text.strip()[:max_chars]
    except Exception as e:
        logger.debug(f"PDF fetch failed for {url}: {e}")
        return None
