import json
import logging
from typing import Any, Dict, List
from server.agents.base import BaseAgent, AgentResult, PipelineContext, PipelineStage, registry
from google import genai
from pydantic import BaseModel, Field

class ReferenceModel(BaseModel):
    authors: str = Field(description="Author names (e.g., 'Smith et al.')")
    title: str | None = Field(default=None, description="Paper title if mentioned")
    year: int = Field(description="Publication year")
    venue: str | None = Field(default=None, description="Conference/journal if mentioned")

class CitationModel(BaseModel):
    id: int = Field(description="Sequential identifier")
    claim: str = Field(description="What the paper claims about this citation.")
    context: str | None = Field(default=None, description="Original sentence containing citation")
    reference: ReferenceModel

class ExtractorAgent(BaseAgent):
    name = "extractor"
    stage = PipelineStage.EXTRACTING
    description = "Extract citations using LLM"
    requires_tokens = True

    def __init__(self, model_name="gemini-2.5-flash"):
        super().__init__()
        try:
            self.client = genai.Client()
        except Exception as e:
            logging.error(f"Failed to init GenAI client: {e}")
            self.client = None
        self.model_name = model_name

    def _preprocess_text(self, text: str, max_chars: int = 50000) -> str:
        if not text:
            return ""
        if len(text) > max_chars:
            return text[:max_chars]
        return text
        
    def _validate_extraction(self, citations_from_llm: List[CitationModel]) -> List[Dict]:
        valid = []
        seen_refs = set()
        for i, c in enumerate(citations_from_llm):
            if not c.claim or len(c.claim) < 10:
                continue
            if not c.reference.authors and not c.reference.year:
                continue
                
            if c.reference.title:
                ref_key = c.reference.title.lower().strip()
            elif c.reference.authors and c.reference.year:
                ref_key = f"{c.reference.authors}_{c.reference.year}".lower().strip()
            else:
                ref_key = str(i)
                
            if ref_key in seen_refs:
                continue
            seen_refs.add(ref_key)

            valid.append({
                "id": len(valid) + 1,
                "claim": c.claim.strip(),
                "context": c.context,
                "reference": {
                    "authors": c.reference.authors,
                    "title": c.reference.title,
                    "year": c.reference.year,
                    "venue": c.reference.venue
                }
            })
        return valid

    async def process(self, ctx: PipelineContext) -> AgentResult:
        if not self.client:
            return AgentResult(agent_name=self.name, status="error", error="GenAI client missing. GEMINI_API_KEY needed.")
            
        text = ctx.paper_text
        if not text:
            return AgentResult(agent_name=self.name, status="error", error="No paper text available for extraction")

        processed_text = self._preprocess_text(text)
        system_instruction = '''
You are an expert academic research assistant extracting citations from academic papers.
CRITICAL INSTRUCTIONS:
1. Extract EVERY SINGLE unique reference from the paper. Cross-check with references section.
2. For each, provide ONE JSON object.
3. The "claim" must be what THIS paper says ABOUT the cited work.
4. If a paper is cited multiple times, summarize the most important claim.
5. Return a JSON array only.
        '''

        try:
            # Note: The generation is synchronous in the python SDK often unless mapped to async
            # Since this is an async framework, we should properly wrap this
            import asyncio
            loop = asyncio.get_event_loop()
            
            def run_genai():
                return self.client.models.generate_content(
                    model=self.model_name,
                    contents=processed_text,
                    config={
                        "system_instruction": system_instruction,
                        "response_mime_type": "application/json",
                        "response_schema": list[CitationModel],
                        "temperature": 0.1,
                    }
                )

            response = await loop.run_in_executor(None, run_genai)
            
            if hasattr(response, "parsed") and response.parsed:
                citations = response.parsed
            else:
                citations_raw = json.loads(response.text)
                citations = [CitationModel(**c) for c in citations_raw]
            
            valid_citations = self._validate_extraction(citations)
            
            tokens_used = 0 
            if response.usage_metadata:
                tokens_used = response.usage_metadata.prompt_token_count + response.usage_metadata.candidates_token_count
                
            return AgentResult(
                agent_name=self.name,
                status="success",
                data={"citations": valid_citations},
                tokens_used=tokens_used,
            )
        except Exception as e:
            logging.error(f"LLM extraction failed: {e}")
            raise Exception("EXTRACT_FAILED: " + str(e))

registry.register(ExtractorAgent())
