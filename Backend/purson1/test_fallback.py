import asyncio
import json
from server.agents.existence import ExistenceAgent
from server.agents.base import PipelineContext, PipelineStage

async def test_existence_fallback():
    agent = ExistenceAgent()
    
    # Mock context with the Netflix Prize citation
    # The extractor should now (hypothetically) produce this:
    citations = [
        {
            "id": 1,
            "claim": "The Netflix Prize dataset was shown to be de-anonymized.",
            "reference": {
                "authors": "Arvind Narayanan and Vitaly Shmatikov",
                "title": "How to break anonymity of the netflix prize dataset",
                "year": 2006,
                "arxiv_id": "cs/0610105",
                "doi": None
            }
        }
    ]
    
    ctx = PipelineContext(paper_text="Dummy text", citations=citations)
    result = await agent.process(ctx)
    
    print(json.dumps(result.data, indent=2))

if __name__ == "__main__":
    asyncio.run(test_existence_fallback())
