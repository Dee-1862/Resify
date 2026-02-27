import time
from typing import Any, Dict, Optional
from pydantic import BaseModel

class AgentResult(BaseModel):
    agent_name: str
    status: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    tokens_used: int = 0
    latency_ms: float = 0.0
    warning: Optional[str] = None

class BaseAgent:
    name: str = "base"

    async def run(self, input_data: dict) -> AgentResult:
        start_time = time.time()
        try:
            result_data, tokens = await self._run_logic(input_data)
            latency = (time.time() - start_time) * 1000
            return AgentResult(
                agent_name=self.name,
                status="success",
                data=result_data,
                tokens_used=tokens,
                latency_ms=latency
            )
        except Exception as e:
            latency = (time.time() - start_time) * 1000
            return AgentResult(
                agent_name=self.name,
                status="error",
                error={"message": str(e), "type": type(e).__name__},
                tokens_used=0,
                latency_ms=latency
            )
            
    async def _run_logic(self, input_data: dict) -> tuple[Dict[str, Any], int]:
        """Override this method. Returns (data_dict, tokens_used)"""
        raise NotImplementedError
