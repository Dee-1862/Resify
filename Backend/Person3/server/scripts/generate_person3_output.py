import asyncio
import os
import sys
import json
from dotenv import load_dotenv

# Add parent dir to path so we can import server
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from server.agents.fetcher import FetcherAgent
from server.agents.extractor import ExtractorAgent
from server.agents.existence import ExistenceAgent

# 1. Load the .env file explicitly from the Backend directory
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
load_dotenv(dotenv_path=env_path)

async def generate_pipeline_output(url: str, output_file: str = "person2_input.json"):
    print(f"--- 🚀 Starting Full Data Pipeline for: {url} ---")
    
    # Ensure Gemini API Key is loaded
    if not os.environ.get("GEMINI_API_KEY"):
        print("❌ CRITICAL ERROR: GEMINI_API_KEY is completely missing in your .env file!")
        print("Please open the .env file, add 'GEMINI_API_KEY=your_real_key_here', and try again.")
        return

    # 1. Fetcher
    print("\n[1] Fetching paper text and metadata...")
    fetcher = FetcherAgent()
    fetch_result = await fetcher.run({"input": url})
    
    if fetch_result.status == "error":
        print(f"❌ Fetch failed: {fetch_result.error}")
        return
        
    paper_data = fetch_result.data
    text = paper_data.get("text")
    if not text:
        print("❌ Could not extract full text from this paper URL.")
        return
        
    print(f"✅ Fetched successfully! Length: {len(text)} characters.")
    
    # 2. Extractor
    print("\n[2] Sending text to Gemini LLM to extract citations...")
    extractor = ExtractorAgent(model_name="gemini-2.5-flash")
    extract_result = await extractor.run({"text": text})
    
    if extract_result.status == "error":
        print(f"❌ Extraction failed: {extract_result.error}")
        return
        
    citations = extract_result.data.get("citations", [])
    print(f"✅ Extracted {len(citations)} citations from paper.")
    
    if not citations:
        print("❌ No citations found to process.")
        return
        
    # 3. Existence Checker
    print("\n[3] Verifying existence of all citations against Semantic Scholar...")
    existence = ExistenceAgent()
    
    # This list exactly matches what Person 2 expects from the IO Contract
    final_output = []
    
    for i, citation in enumerate(citations):
        print(f"   [{i+1}/{len(citations)}] Checking: '{citation['reference']['title'] or citation['reference']['authors']}'...")
        
        exist_result = await existence.run({"citation": citation})
        exist_data = exist_result.data if exist_result.data else {}
        
        # Build the exact contract dictionary
        output_object = {
            "citation": citation,
            "source": exist_data.get("paper", {}),
            "existence_status": exist_data.get("status", "error"),
            "metadata_status": exist_data.get("metadata_status", "N/A"),
            "metadata_errors": exist_data.get("metadata_errors", [])
        }
        final_output.append(output_object)
        
        # Slight delay to prevent rate limiting if you process lots of citations without an API key
        if not os.environ.get("SEMANTIC_SCHOLAR_API_KEY"):
            await asyncio.sleep(1)
            
    # Save Output
    print(f"\n[4] Writing Final JSON array to {output_file}...")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(final_output, f, indent=4, ensure_ascii=False)
        
    print(f"✅ Finished! Hand over {output_file} to Person 2!")


if __name__ == "__main__":
    print("Welcome to the Resify Data Lead Pipeline!")
    
    if len(sys.argv) > 1:
        test_url = sys.argv[1]
    else:
        test_url = input("Enter an ArXiv URL, DOI, or PDF link: ").strip()
        
    if test_url:
        asyncio.run(generate_pipeline_output(test_url))
    else:
        print("No URL provided!")
