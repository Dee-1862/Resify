"""
Unit Tests for Pipeline Orchestrator
====================================
Tests the specific logic of the PipelineOrchestrator class in isolation,
including stage transitions, error handling, retries, timeout, and metrics.

Run with:
    python tests/test_pipeline_unit.py
"""

import sys
from pathlib import Path

# Add project root to python path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import traceback
from unittest.mock import MagicMock, AsyncMock

from server.core.pipeline import PipelineOrchestrator
from server.agents.base import (
    BaseAgent, 
    AgentResult, 
    PipelineStage, 
    PipelineContext, 
    TokenBudget
)

# ---------------------------------------------------------------------------
# Mocks
# ---------------------------------------------------------------------------

class MockAgent(BaseAgent):
    def __init__(self, name="TestAgent", stage=PipelineStage.FETCHING):
        self._name = name
        self._stage = stage
        self.pre_check_result = True
        self.process_result = AgentResult(agent_name=self._name, status="success", data={}, tokens_used=0)
        self.process_delay = 0
        self.process_raise = None

    @property
    def name(self):
        return self._name

    @property
    def stage(self):
        return self._stage

    async def pre_check(self, ctx: PipelineContext) -> bool:
        return self.pre_check_result

    async def process(self, ctx: PipelineContext) -> AgentResult:
        if self.process_delay:
            await asyncio.sleep(self.process_delay)
        if self.process_raise:
            raise self.process_raise
        return self.process_result


def get_mock_registry():
    registry = MagicMock()
    registry.circuit_breaker = MagicMock()
    registry.circuit_breaker.is_open.return_value = False
    return registry


def get_orchestrator_and_context():
    registry = get_mock_registry()
    orchestrator = PipelineOrchestrator(agent_registry=registry)
    context = PipelineContext(
        paper_url="http://test",
        token_budget=TokenBudget(limit=1000)
    )
    return orchestrator, context, registry

# ---------------------------------------------------------------------------
# Test Functions
# ---------------------------------------------------------------------------

async def test_run_agent_success():
    orchestrator, context, registry = get_orchestrator_and_context()
    agent = MockAgent(name="SuccessAgent")
    agent.process_result = AgentResult(agent_name=agent.name, status="success", data={"foo": "bar"}, tokens_used=10)
    
    result = await orchestrator._run_agent(agent, context)
    
    assert result is not None, "Expected result to not be None"
    assert result.status == "success", "Expected status 'success'"
    assert result.data == {"foo": "bar"}, "Expected matching data"
    registry.circuit_breaker.record_success.assert_called_once_with("SuccessAgent")
    assert "SuccessAgent" in context.agent_timings
    print("  [OK] test_run_agent_success")


async def test_run_agent_cb_open():
    orchestrator, context, registry = get_orchestrator_and_context()
    agent = MockAgent(name="CBBlockedAgent")
    registry.circuit_breaker.is_open.return_value = True
    
    result = await orchestrator._run_agent(agent, context)
    
    assert result is None, "Expected None from _run_agent if CB is open"
    registry.circuit_breaker.record_success.assert_not_called()
    print("  [OK] test_run_agent_cb_open")


async def test_run_agent_pre_check_fails():
    orchestrator, context, registry = get_orchestrator_and_context()
    agent = MockAgent(name="PreCheckFails")
    agent.pre_check_result = False
    
    result = await orchestrator._run_agent(agent, context)
    
    assert result is None, "Expected None if pre_check fails"
    print("  [OK] test_run_agent_pre_check_fails")


async def test_run_agent_timeout():
    orchestrator, context, registry = get_orchestrator_and_context()
    context.send_error = AsyncMock()
    context.stage = PipelineStage.FETCHING
    agent = MockAgent(name="TimeoutAgent")
    
    # We enforce a tiny timeout to simulate the 120s timeout safely
    agent.process = AsyncMock(side_effect=asyncio.TimeoutError)
    
    result = await orchestrator._run_agent(agent, context)
        
    assert result is None, "Expected None on timeout"
    registry.circuit_breaker.record_failure.assert_called_once_with("TimeoutAgent")
    context.send_error.assert_called_once()
    args, kwargs = context.send_error.call_args
    assert kwargs.get("code") == "AGENT_TIMEOUT", "Should send AGENT_TIMEOUT error"
    print("  [OK] test_run_agent_timeout")


async def test_run_agent_exception():
    orchestrator, context, registry = get_orchestrator_and_context()
    context.send_error = AsyncMock()
    context.stage = PipelineStage.FETCHING
    agent = MockAgent(name="ErrorAgent")
    agent.process_raise = ValueError("Test Error")
    
    result = await orchestrator._run_agent(agent, context)
        
    assert result is None, "Expected None on exception"
    registry.circuit_breaker.record_failure.assert_called_once_with("ErrorAgent")
    context.send_error.assert_called_once()
    args, kwargs = context.send_error.call_args
    assert kwargs.get("code") == "FETCH_FAILED", "Should map FETCHING exception to FETCH_FAILED"
    assert "Test Error" in kwargs.get("message", ""), "Error message should be included"
    print("  [OK] test_run_agent_exception")


async def test_apply_result_tokens_accumulated():
    orchestrator, context, _ = get_orchestrator_and_context()
    agent = MockAgent()
    result = AgentResult(agent_name="Test", status="success", data={}, tokens_used=42)
    orchestrator._apply_result(agent, result, context)
    
    assert context.stats["total_tokens"] == 42
    assert context.token_budget.used == 42
    print("  [OK] test_apply_result_tokens_accumulated")


async def test_apply_result_fetching():
    orchestrator, context, _ = get_orchestrator_and_context()
    agent = MockAgent(stage=PipelineStage.FETCHING)
    result = AgentResult(agent_name="Test", status="success", data={"text": "Paper content", "title": "Test Title"}, tokens_used=0)
    result.latency_ms = 100
    
    orchestrator._apply_result(agent, result, context)
    
    assert context.paper_text == "Paper content"
    assert context.fetcher_result["title"] == "Test Title"
    assert context.stats["latency_fetch_ms"] == 100
    print("  [OK] test_apply_result_fetching")


async def test_apply_result_extracting():
    orchestrator, context, _ = get_orchestrator_and_context()
    agent = MockAgent(stage=PipelineStage.EXTRACTING)
    result = AgentResult(agent_name="Test", status="success", data={"citations": [{"id": 1, "claim": "x"}]}, tokens_used=0)
    
    orchestrator._apply_result(agent, result, context)
    
    assert len(context.citations) == 1
    assert context.stats["citations_total"] == 1
    print("  [OK] test_apply_result_extracting")


async def test_apply_result_existence_dict():
    orchestrator, context, _ = get_orchestrator_and_context()
    agent = MockAgent(stage=PipelineStage.CHECKING_EXISTENCE)
    result = AgentResult(agent_name="Test", status="success", data={
        "results": {
            "1": {"status": "found"},
            "2": {"status": "not_found"}
        }
    }, tokens_used=0)
    context.stats["citations_total"] = 2
    
    orchestrator._apply_result(agent, result, context)
    
    assert context.existence_results[1]["status"] == "found"
    assert context.existence_results[2]["status"] == "not_found"
    assert context.stats["citations_found"] == 1
    assert context.stats["citations_not_found"] == 1
    print("  [OK] test_apply_result_existence_dict")


async def test_build_report_integrity_score_math():
    orchestrator, context, _ = get_orchestrator_and_context()
    # Setup context with precise results to test the math
    context.citations = [
        {"id": 1, "claim": "Supported"},
        {"id": 2, "claim": "Contradicted"},
        {"id": 3, "claim": "Uncertain"},
        {"id": 4, "claim": "Not Found"},
    ]
    
    context.existence_results = {
        1: {"status": "found"},
        2: {"status": "found"},
        3: {"status": "found"},
        4: {"status": "not_found"}
    }
    
    context.embedding_resolved = [
        {"citation": {"id": 1}, "verdict": "supported", "method": "embedding"},
        {"citation": {"id": 2}, "verdict": "contradicted", "method": "embedding"},
    ]
    context.llm_results = [
        {"citation": {"id": 3}, "verdict": "uncertain", "method": "llm"},
    ]
    
    # Generate report
    report = orchestrator._build_report(context)
    
    # Calculations: Total 4, Found 3, Supported 1 -> score 33.3
    
    assert report["total_citations"] == 4
    assert report["summary"]["supported"] == 1
    assert report["summary"]["contradicted"] == 1
    assert report["summary"]["uncertain"] == 1
    assert report["summary"]["not_found"] == 1
    assert report["integrity_score"] == 33.3
    assert len(report["citations"]) == 4
    print("  [OK] test_build_report_integrity_score_math")


async def test_pipeline_run_skips_llm_if_not_needed():
    orchestrator, _, registry = get_orchestrator_and_context()
    
    # Setup agents
    fetch_agent = MockAgent(stage=PipelineStage.FETCHING)
    extract_agent = MockAgent(stage=PipelineStage.EXTRACTING)
    exist_agent = MockAgent(stage=PipelineStage.CHECKING_EXISTENCE)
    embed_agent = MockAgent(stage=PipelineStage.EMBEDDING_GATE)
    llm_agent = MagicMock()  # We don't want this to ever be called
    synth_agent = MockAgent(stage=PipelineStage.SYNTHESIZING)
    
    def get_agents(stage):
        return {
            PipelineStage.FETCHING: [fetch_agent],
            PipelineStage.EXTRACTING: [extract_agent],
            PipelineStage.CHECKING_EXISTENCE: [exist_agent],
            PipelineStage.EMBEDDING_GATE: [embed_agent],
            PipelineStage.LLM_VERIFICATION: [llm_agent],
            PipelineStage.SYNTHESIZING: [synth_agent]
        }.get(stage, [])
        
    registry.get_agents_for_stage.side_effect = get_agents
    
    # Embed agent resolving everything
    embed_agent.process_result = AgentResult(agent_name="Embed", status="success", data={"resolved": [{"citation": {"id": 1}}], "needs_llm": []}, tokens_used=0)
    
    report = await orchestrator.run(url="http://test")
    
    assert "integrity_score" in report
    assert report["stats"]["agents_invoked"] > 0
    # ensure LLM agent was never called
    llm_agent.process.assert_not_called()
    print("  [OK] test_pipeline_run_skips_llm_if_not_needed")


async def main():
    print("Running PipelineOrchestrator Unit Tests")
    print("-" * 60)
    tests = [
        test_run_agent_success,
        test_run_agent_cb_open,
        test_run_agent_pre_check_fails,
        test_run_agent_timeout,
        test_run_agent_exception,
        test_apply_result_tokens_accumulated,
        test_apply_result_fetching,
        test_apply_result_extracting,
        test_apply_result_existence_dict,
        test_build_report_integrity_score_math,
        test_pipeline_run_skips_llm_if_not_needed
    ]
    for test_fn in tests:
        try:
            await test_fn()
        except Exception as e:
            print(f"  [FAIL] {test_fn.__name__}: {str(e)}")
            traceback.print_exc()

    print("-" * 60)
    print("All unit tests finished.")


if __name__ == "__main__":
    asyncio.run(main())
