from __future__ import annotations

import re
from typing import Optional, Dict, Tuple, List, Any

import numpy as np
from sentence_transformers import SentenceTransformer

# Cache: (model_name, device) -> SentenceTransformer
_MODEL_CACHE: Dict[Tuple[str, Optional[str]], SentenceTransformer] = {}


def get_embedding_model(
		model_name: str = "all-MiniLM-L6-v2",
		device: Optional[str] = None,
) -> SentenceTransformer:
	"""
	Load and return a cached SentenceTransformer model.

	- Caches by (model_name, device) to avoid repeated loads.
	- Raises RuntimeError with a helpful message if loading fails.
	"""
	key = (model_name, device)
	if key in _MODEL_CACHE:
		return _MODEL_CACHE[key]

	try:
		if device is None:
			model = SentenceTransformer(model_name)
		else:
			model = SentenceTransformer(model_name, device=device)
	except Exception as e:
		raise RuntimeError(
			f"Failed to load embedding model '{model_name}' on device '{device}'. "
			f"Original error: {e}"
		) from e

	_MODEL_CACHE[key] = model
	return model


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
	"""
	Safe cosine similarity. If either vector is zero-norm, returns 0.0.
	"""
	a = np.asarray(a, dtype=float)
	b = np.asarray(b, dtype=float)

	denom = float(np.linalg.norm(a) * np.linalg.norm(b))
	if denom == 0.0:
		return 0.0
	return float(np.dot(a, b) / denom)


def _safe_text(x: Any) -> str:
	"""
	Convert unknown input into a safe string.
	"""
	if x is None:
		return ""
	if isinstance(x, str):
		return x
	return str(x)


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def split_into_spans(
		text: str,
		*,
		max_chars: int = 300,
		overlap_chars: int = 60,
) -> List[str]:
	"""
	Split text into evidence spans.

	Strategy:
	  1) Try sentence splitting using punctuation boundaries.
	  2) If sentences are too long or text has no punctuation, use sliding window chunking.

	Returns:
	  - list[str] spans, each non-empty.
	"""
	text = _safe_text(text).strip()
	if not text:
		return []

	# 1) Sentence-ish split
	sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]

	# If sentence split produced reasonable chunks, use them.
	# If there are no sentences or we have giant sentences, fallback to chunking.
	if sentences:
		# If most sentences are not absurdly long, keep them.
		long_count = sum(1 for s in sentences if len(s) > max_chars * 2)
		if long_count == 0:
			# Still enforce max_chars: further chunk any single long sentence
			spans: List[str] = []
			for s in sentences:
				if len(s) <= max_chars:
					spans.append(s)
				else:
					spans.extend(_chunk_text(s, max_chars=max_chars, overlap_chars=overlap_chars))
			return spans

	# 2) Chunk fallback
	return _chunk_text(text, max_chars=max_chars, overlap_chars=overlap_chars)


def _chunk_text(text: str, *, max_chars: int, overlap_chars: int) -> List[str]:
	"""
	Sliding window chunking over raw characters.
	"""
	text = text.strip()
	if not text:
		return []

	max_chars = max(50, int(max_chars))
	overlap_chars = max(0, int(overlap_chars))
	step = max(1, max_chars - overlap_chars)

	spans: List[str] = []
	start = 0
	n = len(text)

	while start < n:
		end = min(n, start + max_chars)
		chunk = text[start:end].strip()
		if chunk:
			spans.append(chunk)
		if end == n:
			break
		start += step

	return spans


def encode(model: SentenceTransformer, text: str) -> np.ndarray:
	"""
	Encode text into an embedding vector.
	Returns a zero-vector if text is empty/whitespace.
	"""
	text = _safe_text(text).strip()
	if not text:
		# Determine embedding dim by encoding a tiny string once (cached by model internally).
		dim_vec = model.encode(" ").astype(float)
		return np.zeros_like(dim_vec, dtype=float)

	vec = model.encode(text)
	return np.asarray(vec, dtype=float)


def best_span_similarity(
		model: SentenceTransformer,
		query: str,
		source_text: str,
		*,
		max_chars: int = 300,
		overlap_chars: int = 60,
) -> Dict[str, Any]:
	"""
	Compute best similarity between query and any span in source_text.

	Returns:
	  {
		"best_similarity": float,
		"best_span": str,
		"all_similarities": list[float],
		"spans": list[str],  # useful for debugging
	  }
	"""
	query = _safe_text(query).strip()
	source_text = _safe_text(source_text).strip()

	if not query or not source_text:
		return {
			"best_similarity": 0.0,
			"best_span": "",
			"all_similarities": [],
			"spans": [],
		}

	spans = split_into_spans(source_text, max_chars=max_chars, overlap_chars=overlap_chars)
	if not spans:
		return {
			"best_similarity": 0.0,
			"best_span": "",
			"all_similarities": [],
			"spans": [],
		}

	q_vec = encode(model, query)

	best_sim = -1.0
	best_span = ""
	sims: List[float] = []

	for span in spans:
		s_vec = encode(model, span)
		sim = cosine_similarity(q_vec, s_vec)
		sims.append(sim)
		if sim > best_sim:
			best_sim = sim
			best_span = span

	# Clip best_sim into [-1, 1], but MiniLM usually yields [0,1] for typical text
	best_sim = float(max(-1.0, min(1.0, best_sim)))

	return {
		"best_similarity": best_sim,
		"best_span": best_span,
		"all_similarities": sims,
		"spans": spans,
	}