from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from person2.utils.embeddings import get_embedding_model, best_span_similarity


# Try to import team base classes; fallback if missing.
try:
	from server.core.agent_base import BaseAgent, AgentResult  # type: ignore
except Exception:
	class BaseAgent:
		name: str = "base"

		async def run(self, input_data: dict) -> Any:
			raise NotImplementedError

	@dataclass
	class AgentResult:
		agent_name: str
		status: str
		data: Any
		tokens_used: int = 0


def _safe_get(d: Dict[str, Any], path: str, default: Any = "") -> Any:
	"""
	Safe nested dict getter.
	path like "citation.claim" or "source.abstract"
	"""
	cur: Any = d
	for key in path.split("."):
		if not isinstance(cur, dict) or key not in cur:
			return default
		cur = cur[key]
	return cur


def _word_count(text: str) -> int:
	return len([w for w in (text or "").strip().split() if w])


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
	return max(lo, min(hi, x))


class EmbeddingGateAgent(BaseAgent):
	"""
	Commit 1 verifier:
	  - Finds the best matching evidence span in the source abstract
	  - Returns supported / uncertain only (conservative)
	  - No negation and no LLM yet
	"""
	name = "embedding_gate"

	def __init__(
			self,
			model_name: str = "all-MiniLM-L6-v2",
			device: Optional[str] = None,
			support_threshold: float = 0.78,
			min_claim_len_words: int = 5,
			span_max_chars: int = 300,
			span_overlap_chars: int = 60,
	):
		self.model_name = model_name
		self.device = device
		self.support_threshold = support_threshold
		self.min_claim_len_words = min_claim_len_words
		self.span_max_chars = span_max_chars
		self.span_overlap_chars = span_overlap_chars

		self.model = get_embedding_model(model_name=model_name, device=device)

	def verify(self, claim: str, abstract: str) -> Dict[str, Any]:
		claim = (claim or "").strip()
		abstract = (abstract or "").strip()

		# Short claim => always uncertain (not enough info)
		if _word_count(claim) < self.min_claim_len_words:
			sim_info = best_span_similarity(
				self.model,
				claim,
				abstract,
				max_chars=self.span_max_chars,
				overlap_chars=self.span_overlap_chars,
			)
			return {
				"verdict": "uncertain",
				"confidence": 0.2,
				"method": "embedding",
				"needs_llm": False,
				"evidence": sim_info.get("best_span", ""),
				"details": {
					"best_similarity": float(sim_info.get("best_similarity", 0.0)),
					"support_threshold": self.support_threshold,
					"reason": "claim_too_short",
				},
			}

		sim_info = best_span_similarity(
			self.model,
			claim,
			abstract,
			max_chars=self.span_max_chars,
			overlap_chars=self.span_overlap_chars,
		)

		best_sim = float(sim_info.get("best_similarity", 0.0))
		evidence = sim_info.get("best_span", "")

		if best_sim >= self.support_threshold:
			verdict = "supported"
		else:
			verdict = "uncertain"

		# Confidence mapping: conservative and monotonic
		# Below 0.40 => ~0; at threshold => ~1
		denom = max(1e-6, (self.support_threshold - 0.40))
		confidence = _clamp((best_sim - 0.40) / denom, 0.0, 1.0)
		if verdict == "uncertain":
			confidence = min(confidence, 0.7)  # don't overconfidence on uncertain

		return {
			"verdict": verdict,
			"confidence": float(confidence),
			"method": "embedding",
			"needs_llm": False,
			"evidence": evidence,
			"details": {
				"best_similarity": best_sim,
				"support_threshold": self.support_threshold,
			},
		}

	async def run(self, input_data: dict) -> AgentResult:
		# Expecting:
		# input_data["citation"]["claim"]
		# input_data["source"]["abstract"]
		citation = _safe_get(input_data, "citation", default={}) or {}
		source = _safe_get(input_data, "source", default={}) or {}

		claim = _safe_get(input_data, "citation.claim", default="") or ""
		abstract = _safe_get(input_data, "source.abstract", default="") or ""

		result = self.verify(claim, abstract)

		data = {
			"citation": citation,
			"source": source,
			"verdict": result["verdict"],
			"confidence": result["confidence"],
			"evidence": result["evidence"],
			"method": result["method"],
			"needs_llm": result["needs_llm"],
			"details": result["details"],
		}

		return AgentResult(
			agent_name=self.name,
			status="success",
			data=data,
			tokens_used=0,
		)