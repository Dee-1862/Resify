import asyncio
import os
import sys

# Add parent dir to path so we can import server
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from server.agents.fetcher import FetcherAgent
from server.agents.extractor import ExtractorAgent
from server.agents.existence import ExistenceAgent

async def run_pipeline(url: str):
    print(f"--- 🚀 Starting Pipeline for: {url} ---")
    
    # 1. Fetcher
    print("\n[1] Fetching paper...")
    fetcher = FetcherAgent()
    fetch_result = await fetcher.run({"input": url})
    
    if fetch_result.status == "error":
        print(f"❌ Fetch failed: {fetch_result.error}")
        return
        
    paper_data = fetch_result.data
    print(f"✅ Fetched successfully! Title: {paper_data.get('title')}")
    print(f"   Source: {paper_data.get('source')}")
    print(f"   Abstract length: {len(paper_data.get('abstract', ''))} chars")
    
    # Check if we have text to extract from
    if not paper_data.get("text"):
        print("❌ No text available for extraction. (Maybe it was a DOI without open access text?)")
        return
        
    print(f"   Text length: {len(paper_data.get('text', ''))} chars")
    
    # 2. Extractor
    print("\n[2] Extracting citations...")
    print("   (This will use LLM - assuming GEMINI_API_KEY is available in env)")
    
    # Check for API KEY
    if not os.environ.get("GEMINI_API_KEY"):
        print("⚠️ Warning: GEMINI_API_KEY environment variable is missing. Using MOCK citation data to test ExistenceAgent.")
        citations = [
            {
                "id": 1,
                "claim": "demonstrated that attention mechanisms can replace recurrence entirely",
                "context": "Vaswani et al. demonstrated that attention mechanisms can replace recurrence entirely [2].",
                "reference": {
                    "authors": "Vaswani et al.",
                    "title": "Attention Is All You Need",
                    "year": 2017,
                    "venue": "NeurIPS"
                }
            },
            {
                "id": 2,
                "claim": "Fake hallucinated paper that doesn't exist to test failure cases.",
                "context": "...",
                "reference": {
                    "authors": "DoesNotExist et al.",
                    "title": "A completely fake paper title",
                    "year": 2024,
                    "venue": "Nature"
                }
            }
        ]
    else:
        extractor = ExtractorAgent(model_name="gemma-3-27b")
        extract_result = await extractor.run({"text": paper_data["text"]})
        
        if extract_result.status == "error":
            print(f"❌ Extraction failed: {extract_result.error}")
            return
            
        citations = extract_result.data.get("citations", [])
    
    print(f"✅ Extracted/Mocked {len(citations)} citations")
    
    if not citations:
        print("❌ No citations found.")
        return
        
    # Show first 2 citations to keep output clean
    for i, c in enumerate(citations[:2]):
        print(f"   [{c['id']}] Claim: {c['claim']}")
        print(f"       Ref: {c['reference']['authors']} ({c['reference']['year']})")
    if len(citations) > 2:
        print(f"   ... and {len(citations) - 2} more")
        
    # 3. Existence Checker
    print("\n[3] Verifying existence of first 3 citations...")
    existence = ExistenceAgent()
    
    for c in citations[:3]:
        print(f"\n   Checking: {c['reference']['title'] or c['reference']['authors'] + ' ' + str(c['reference']['year'])}")
        exist_result = await existence.run({"citation": c})
        
        if exist_result.status == "error":
            print(f"   ❌ Error: {exist_result.error}")
            continue
            
        exist_data = exist_result.data
        if exist_data.get("status") == "found":
            print(f"   ✅ Found! Match Score: {exist_data.get('match_score')}")
            paper = exist_data.get("paper", {})
            print(f"      Matched Title: {paper.get('title')}")
            print(f"      Metadata Status: {exist_data.get('metadata_status')}")
            if exist_data.get("metadata_errors"):
                for err in exist_data.get("metadata_errors"):
                    print(f"      ⚠️ Error: {err['message']}")
        else:
            print(f"   ❌ Not Found: {exist_data.get('reason')}")

if __name__ == "__main__":
    test_url = "https://arxiv.org/abs/1706.03762" # Attention is all you need
    if len(sys.argv) > 1:
        test_url = sys.argv[1]
        
    asyncio.run(run_pipeline(test_url))
