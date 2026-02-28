import asyncio
import os
import json
from dotenv import load_dotenv

load_dotenv()

# Ensure GEMINI_API_KEY is available or output a warning.
if not os.getenv("GEMINI_API_KEY"):
    print("WARNING: GEMINI_API_KEY not set in environment or .env file. Extraction might fail.")

from server.core.pipeline import PipelineOrchestrator
from server.agents import registry  # Forces __init__.py to run

async def main():
    print(f"Loaded agents in order:")
    for a in registry.get_pipeline():
        print(f"  - {a.name} [{a.stage}]")

    orchestrator = PipelineOrchestrator()
    
    # We will test a specific, relatively short or famous paper
    url = "https://arxiv.org/abs/1706.03762"
    print(f"\nRunning pipeline on {url} ...\n")
    
    # To monitor progress...
    async def on_progress(msg, pct):
        print(f"[{pct}%] {msg}")
        
    report = await orchestrator.run(url=url, on_progress=on_progress)
    
    print("\n=================== REPORT PIPELINE STATS ===================")
    print(json.dumps({
        "integrity_score": report.get("integrity_score"),
        "total_citations": report.get("total_citations"),
        "summary": report.get("summary"),
        "stats": report.get("stats")
    }, indent=2))
    
    print("\n=================== SAMPLE CITATIONS ===================")
    for cit in report.get("citations", [])[:3]: # print first 3 to avoid spam
        print(json.dumps(cit, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
