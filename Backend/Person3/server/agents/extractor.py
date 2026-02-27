import json
import logging
from typing import Any, Dict, List
from server.core.agent_base import BaseAgent
from google import genai
from pydantic import BaseModel, Field

class ReferenceModel(BaseModel):
    authors: str = Field(description="Author names (e.g., 'Smith et al.')")
    title: str | None = Field(default=None, description="Paper title if mentioned")
    year: int = Field(description="Publication year")
    venue: str | None = Field(default=None, description="Conference/journal if mentioned")

class CitationModel(BaseModel):
    id: int = Field(description="Sequential identifier")
    claim: str = Field(description="What the paper claims about this citation. e.g. 'demonstrated 40% improvement on benchmarks'")
    context: str | None = Field(default=None, description="Original sentence containing citation")
    reference: ReferenceModel

class ExtractorAgent(BaseAgent):
    name = "extractor"

    def __init__(self, model_name="gemma-3-27b"):
        super().__init__()
        # Initializing client (assumes GEMINI_API_KEY environment variable is set)
        self.client = genai.Client()
        self.model_name = model_name

    def _preprocess_text(self, text: str, max_chars: int = 50000) -> str:
        """Truncate to approximately ~12,000 tokens / 50,000 characters."""
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
                
            # Deduplication logic to avoid repeating papers like Wikipedia or Sweeney
            if c.reference.title:
                ref_key = c.reference.title.lower().strip()
            elif c.reference.authors and c.reference.year:
                ref_key = f"{c.reference.authors}_{c.reference.year}".lower().strip()
            else:
                ref_key = str(i) # Fallback if we somehow have bizarre empty title/author
                
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

    async def _run_logic(self, input_data: dict) -> tuple[Dict[str, Any], int]:
        text = input_data.get("text", "")
        if not text:
            raise ValueError("Paper text is required")

        processed_text = self._preprocess_text(text)
        
        system_instruction = '''
You are an expert academic research assistant extracting citations from academic papers.

CRITICAL INSTRUCTIONS:
1. Extract EVERY SINGLE unique reference from the paper. Cross-check with the References/Bibliography section at the end of the text to ensure none are missed.
2. For each unique reference, provide ONE single JSON object. DO NOT output duplicate objects for the same referenced paper.
3. The "claim" must be what THIS paper says ABOUT the cited work. 
4. If a paper is cited multiple times in the text, summarize the most important claim made about it. Do NOT output multiple JSON objects for it.
5. If there is no explicit claim made about it, instead describe the context in which it was cited (e.g. "cited as an example of x").
6. Return a JSON array only.

Example good claim: "demonstrated that attention mechanisms outperform recurrence"
Example bad claim: "Smith et al. 2023" (this is just the reference, not a claim)
        '''

        try:
            # We use gemini API for structured output
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=processed_text,
                config={
                    "system_instruction": system_instruction,
                    "response_mime_type": "application/json",
                    "response_schema": list[CitationModel],
                    "temperature": 0.1,
                }
            )
            
            # The response is validated automatically against the Pydantic schema by google-genai
            # and returns a list of CitationModel instances if response_schema is passed in properly.
            # However `response.parsed` might be null or string based on version, so we handle json manually to be safe.
            if hasattr(response, "parsed") and response.parsed:
                citations = response.parsed
            else:
                citations_raw = json.loads(response.text)
                citations = [CitationModel(**c) for c in citations_raw]
            
            valid_citations = self._validate_extraction(citations)
            
            tokens_used = 0 
            if response.usage_metadata:
                tokens_used = response.usage_metadata.prompt_token_count + response.usage_metadata.candidates_token_count
                
            return {"citations": valid_citations}, tokens_used

        except Exception as e:
            logging.error(f"LLM extraction failed: {e}")
            raise Exception("EXTRACT_FAILED: " + str(e))
