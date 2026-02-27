"""
CiteSafe Pipeline E2E Tests
============================
Validates:
  1. Cache layer (all 3 tables)
  2. Circuit breaker
  3. Agent registry
  4. Full pipeline with contract-compliant output
  5. Report shape matches frontend contract exactly

Run:
    python tests/test_pipeline.py
    python -m pytest tests/test_pipeline.py -v
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


SAMPLE_PAPER = """
Attention mechanisms have become a fundamental component of sequence modeling.
The Transformer architecture [1] introduced self-attention as a replacement for
recurrence. Vaswani et al. (2017) demonstrated that attention alone is sufficient
for achieving state-of-the-art results in machine translation.

Several works have extended this approach. BERT [2] showed that bidirectional
pre-training leads to significant improvements on downstream tasks (Devlin et al., 2019).
GPT-2 [3] demonstrated that language models can generate coherent long-form text
(Radford et al., 2019).

More recently, scaling laws (Kaplan et al., 2020) have shown predictable relationships
between model size and performance [4]. This has been confirmed by subsequent work
including Chinchilla [5] which argues for data-scaling over parameter-scaling
(Hoffmann et al., 2022).

References:
[1] Vaswani et al. Attention Is All You Need, 2017.
[2] Devlin et al. BERT: Pre-training of Deep Bidirectional Transformers, 2019.
[3] Radford et al. Language Models are Unsupervised Multitask Learners, 2019.
[4] Kaplan et al. Scaling Laws for Neural Language Models, 2020.
[5] Hoffmann et al. Training Compute-Optimal Large Language Models, 2022.
"""


# ===========================================================================
# Test 1: Cache
# ===========================================================================

async def test_cache():
    import numpy as np
    from server.core.cache import CiteSafeCache

    cache = CiteSafeCache(":memory:")

    # --- Source cache ---
    cache.set_source("paper_123", {
        "title": "Attention Is All You Need",
        "authors": ["Vaswani"],
        "year": 2017,
        "abstract": "The dominant sequence...",
    }, np.random.rand(384).astype(np.float32))

    result = cache.get_source("paper_123")
    assert result is not None, "Source cache miss"
    assert result["title"] == "Attention Is All You Need"
    assert "embedding" in result
    assert result["embedding"].shape == (384,)
    print("  ✓ Source cache: store + retrieve + embedding")

    # --- Verification cache ---
    cache.set_verification(
        "attention replaces recurrence",
        "paper_123",
        {"verdict": "supported", "confidence": 0.89, "method": "embedding"},
    )
    result = cache.get_verification("attention replaces recurrence", "paper_123")
    assert result is not None, "Verification cache miss"
    assert result["verdict"] == "supported"
    print("  ✓ Verification cache: store + retrieve")

    # --- Paper analysis cache ---
    cache.set_analysis(
        cache.hash_paper("test paper text"),
        {"integrity_score": 85, "total_citations": 10},
    )
    result = cache.get_analysis(cache.hash_paper("test paper text"))
    assert result is not None, "Paper analysis cache miss"
    assert result["integrity_score"] == 85
    print("  ✓ Paper analysis cache: store + retrieve")

    # --- Stats ---
    stats = cache.get_stats()
    assert stats["hits"] == 3
    print(f"  ✓ Cache stats: {stats['hits']} hits, {stats['misses']} misses")

    cache.close()


# ===========================================================================
# Test 2: Circuit Breaker
# ===========================================================================

async def test_circuit_breaker():
    import time
    from server.agents.base import CircuitBreaker

    cb = CircuitBreaker(threshold=2, cooldown_seconds=0.5)

    cb.record_failure("bad_agent")
    assert not cb.is_open("bad_agent"), "Should not be open after 1 failure"

    cb.record_failure("bad_agent")
    assert cb.is_open("bad_agent"), "Should be open after 2 failures"

    time.sleep(0.6)
    assert not cb.is_open("bad_agent"), "Should reset after cooldown"

    # Success resets counter
    cb.record_failure("flaky_agent")
    cb.record_success("flaky_agent")
    cb.record_failure("flaky_agent")
    assert not cb.is_open("flaky_agent"), "Success should reset failure count"

    print("  ✓ Circuit breaker: threshold, cooldown, reset on success")


# ===========================================================================
# Test 3: Agent Registry
# ===========================================================================

async def test_registry():
    from server.agents.base import registry, PipelineStage
    from server.agents import dummy  # noqa: F401

    agents = registry.list_agents()
    assert len(agents) >= 5, f"Expected at least 5 dummy agents, got {len(agents)}"

    # Verify all stages are covered
    stages = {a["stage"] for a in agents}
    expected_stages = {"fetching", "extracting", "checking_existence", "embedding_gate", "llm_verification"}
    assert expected_stages.issubset(stages), f"Missing stages: {expected_stages - stages}"

    # Verify pipeline order
    pipeline = registry.get_pipeline()
    stage_order = [a.stage for a in pipeline]
    assert stage_order == sorted(stage_order, key=lambda s: list(PipelineStage).index(s) if s in list(PipelineStage) else 99)

    for a in agents:
        print(f"  ✓ [{a['stage']}] {a['name']} — {a['description']}")


# ===========================================================================
# Test 4: Full Pipeline E2E
# ===========================================================================

async def test_pipeline_e2e():
    from server.agents import dummy  # noqa: F401
    from server.core.pipeline import PipelineOrchestrator

    # Capture WS progress messages
    progress_messages = []

    async def capture_progress(message: str, progress: float):
        progress_messages.append({"message": message, "progress": progress})

    pipeline = PipelineOrchestrator()
    report = await pipeline.run(
        text=SAMPLE_PAPER,
        on_progress=capture_progress,
    )

    # --- Validate report matches frontend contract ---
    assert "integrity_score" in report, "Missing integrity_score"
    assert "total_citations" in report, "Missing total_citations"
    assert "summary" in report, "Missing summary"
    assert "paper" in report, "Missing paper"
    assert "citations" in report, "Missing citations"
    assert "stats" in report, "Missing stats"

    assert isinstance(report["integrity_score"], (int, float))
    assert report["total_citations"] > 0, f"Expected citations, got {report['total_citations']}"

    # --- Validate summary ---
    summary = report["summary"]
    for key in ("supported", "contradicted", "uncertain", "not_found", "metadata_errors"):
        assert key in summary, f"Missing summary.{key}"
    total_accounted = sum(summary[k] for k in ("supported", "contradicted", "uncertain", "not_found"))
    assert total_accounted == report["total_citations"], \
        f"Summary counts ({total_accounted}) != total ({report['total_citations']})"

    # --- Validate each citation ---
    for cit in report["citations"]:
        assert "id" in cit, "Citation missing id"
        assert "claim" in cit, "Citation missing claim"
        assert "reference" in cit, "Citation missing reference"
        assert "existence_status" in cit, "Citation missing existence_status"
        assert cit["existence_status"] in ("found", "not_found")

        if cit["existence_status"] == "found":
            assert cit.get("source_found") is not None or cit.get("verification") is not None

    # --- Validate stats ---
    stats = report["stats"]
    for key in ("total_tokens", "total_api_calls", "cache_hits", "latency_ms"):
        assert key in stats, f"Missing stats.{key}"

    # --- Validate progress messages ---
    assert len(progress_messages) > 0, "No progress messages received"
    # Should end with "Analysis complete!" at 100
    last = progress_messages[-1]
    assert last["progress"] == 100, f"Last progress should be 100, got {last['progress']}"

    print(f"  ✓ Report: {report['total_citations']} citations, score={report['integrity_score']}%")
    print(f"  ✓ Summary: {summary}")
    print(f"  ✓ Stats: {stats['total_tokens']} tokens, {stats['latency_ms']:.0f}ms")
    print(f"  ✓ Progress: {len(progress_messages)} messages sent")

    return report


# ===========================================================================
# Test 5: Report matches frontend derived format
# ===========================================================================

async def test_frontend_compatibility(report: dict):
    """Verify the report works with the frontend's reportToSynthesisData()."""
    # This mimics what the frontend does:
    # trustScore: Number(report.integrity_score)
    # totalCitations: report.total_citations
    # verified: report.supported → report.summary.supported
    # suspicious: report.uncertain → report.summary.uncertain
    # fabricated: report.not_found + report.contradicted → summary.not_found + summary.contradicted

    trust_score = float(report["integrity_score"])
    total_citations = report["total_citations"]

    # Frontend reads these from top-level OR summary
    summary = report["summary"]
    verified = summary["supported"]
    suspicious = summary["uncertain"]
    fabricated = summary["not_found"] + summary["contradicted"]

    assert trust_score >= 0 and trust_score <= 100
    assert total_citations > 0
    assert verified + suspicious + fabricated == total_citations

    # Frontend also reads these for the result WS message
    ws_result = {"type": "result", "report": report}
    assert ws_result["type"] == "result"
    assert "integrity_score" in ws_result["report"]
    assert "citations" in ws_result["report"]

    print(f"  ✓ Frontend compatible: trust={trust_score}, verified={verified}, suspicious={suspicious}, fabricated={fabricated}")


# ===========================================================================
# Test 6: WebSocket message format
# ===========================================================================

async def test_ws_message_format():
    """Verify WS messages match the frontend contract."""
    # Progress message format
    progress_msg = {"type": "progress", "message": "Extracting citations...", "progress": 25}
    assert progress_msg["type"] == "progress"
    assert isinstance(progress_msg["progress"], int)
    assert 0 <= progress_msg["progress"] <= 100

    # Result message format
    result_msg = {"type": "result", "report": {"integrity_score": 85, "total_citations": 10}}
    assert result_msg["type"] == "result"
    assert "report" in result_msg

    # Error message format
    error_msg = {"type": "error", "message": "Rate limit exceeded."}
    assert error_msg["type"] == "error"
    assert "message" in error_msg

    # Verify JSON serializable
    for msg in (progress_msg, result_msg, error_msg):
        json.dumps(msg)

    print("  ✓ WS message formats: progress, result, error all valid")


# ===========================================================================
# Test 7: Input validation
# ===========================================================================

async def test_input_validation():
    from server.api.schemas import PaperInput
    from pydantic import ValidationError

    # Valid inputs
    PaperInput(url="https://arxiv.org/abs/2301.00001")
    PaperInput(doi="10.48550/arXiv.1706.03762")
    PaperInput(text="Some paper text here")
    print("  ✓ Valid inputs accepted")

    # Invalid: nothing provided
    try:
        PaperInput()
        assert False, "Should have rejected empty input"
    except ValidationError:
        print("  ✓ Empty input rejected")

    # Invalid: bad URL
    try:
        PaperInput(url="not-a-url")
        assert False, "Should have rejected bad URL"
    except ValidationError:
        print("  ✓ Bad URL rejected")

    # Invalid: bad DOI
    try:
        PaperInput(doi="not-a-doi")
        assert False, "Should have rejected bad DOI"
    except ValidationError:
        print("  ✓ Bad DOI rejected")


# ===========================================================================
# Test 8: FastAPI app loads
# ===========================================================================

async def test_app_loads():
    from server.main import app
    from server.agents.base import registry

    routes = [r.path for r in app.routes]
    assert "/api/analyze" in routes, f"Missing /api/analyze in {routes}"
    assert "/api/agents" in routes, f"Missing /api/agents in {routes}"
    assert "/api/health" in routes, f"Missing /api/health in {routes}"
    assert "/ws/analyze" in routes, f"Missing /ws/analyze in {routes}"
    assert "/health" in routes, f"Missing /health in {routes}"

    print(f"  ✓ App loaded with routes: {sorted(r for r in routes if not r.startswith('/open') and not r.startswith('/docs') and not r.startswith('/redoc'))}")


# ===========================================================================
# Main
# ===========================================================================

async def main():
    print("=" * 64)
    print("  CiteSafe Foundation Tests")
    print("=" * 64)

    print("\n[1] Cache Layer")
    await test_cache()

    print("\n[2] Circuit Breaker")
    await test_circuit_breaker()

    print("\n[3] Agent Registry")
    await test_registry()

    print("\n[4] Full Pipeline E2E")
    report = await test_pipeline_e2e()

    print("\n[5] Frontend Compatibility")
    await test_frontend_compatibility(report)

    print("\n[6] WebSocket Message Format")
    await test_ws_message_format()

    print("\n[7] Input Validation")
    await test_input_validation()

    print("\n[8] FastAPI App")
    await test_app_loads()

    print("\n" + "=" * 64)
    print("  ALL TESTS PASSED ✓")
    print("=" * 64)


if __name__ == "__main__":
    asyncio.run(main())
