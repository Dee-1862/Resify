# Person 3: Data Lead - Complete Guide

## 🎯 Your Mission

You build the **data pipeline** - fetching papers, extracting citations, and verifying existence via FREE APIs. Without your work, Person 2 has nothing to verify.

**You are the foundation. Everything depends on you getting good data.**

---

## 📁 Directory Structure

```
server/
├── agents/
│   ├── __init__.py
│   ├── fetcher.py            # Paper fetching (ArXiv, DOI, URL, PDF)
│   ├── extractor.py          # Citation extraction (1 LLM call)
│   └── existence.py          # API-based existence check (FREE)
└── utils/
    ├── __init__.py
    ├── pdf.py                # PDF text extraction
    └── apis.py               # Semantic Scholar, CrossRef wrappers
```

---

## 🔌 APIs You'll Use

### 1. Semantic Scholar (Primary - FREE)

| Endpoint | Purpose | Rate Limit |
|----------|---------|------------|
| `/paper/search` | Find papers by query | 100/5min (no key) |
| `/paper/{id}` | Get paper by ID | 100/5min (no key) |
| `/paper/DOI:{doi}` | Get paper by DOI | 100/5min (no key) |

**Base URL:** `https://api.semanticscholar.org/graph/v1`

**Useful Fields:** `title`, `authors`, `year`, `abstract`, `paperId`, `externalIds`, `citationCount`

### 2. ArXiv API (FREE)

| Endpoint | Purpose |
|----------|---------|
| `/api/query?id_list={id}` | Get paper by ArXiv ID |
| `/api/query?search_query={query}` | Search papers |

**Base URL:** `http://export.arxiv.org`

**Returns:** XML (use ElementTree to parse)

### 3. CrossRef API (FREE)

| Endpoint | Purpose |
|----------|---------|
| `/works/{doi}` | Get paper metadata by DOI |

**Base URL:** `https://api.crossref.org`

**Returns:** JSON

---

## ⏰ Hour-by-Hour Breakdown

### Hour 0-1: Semantic Scholar API Setup

**Task:** Get the primary API working

**Test Queries to Verify:**

| Query | Expected Result |
|-------|-----------------|
| "Attention Is All You Need" | Vaswani et al. 2017 |
| "BERT pre-training" | Devlin et al. 2018 |
| "GPT-3 language models" | Brown et al. 2020 |
| "Fake Paper That Doesn't Exist XYZ123" | No results |

**API Wrapper Structure:**
```
SemanticScholarAPI
├── search(query, limit=5)
│   → Returns list of papers matching query
│
├── get_paper(paper_id)
│   → Returns full paper details
│
├── get_paper_by_doi(doi)
│   → Returns paper by DOI
│
└── get_paper_by_title_author_year(title, author, year)
    → Returns best matching paper or None
```

**Error Handling:**
| Error | Response Code | Action |
|-------|---------------|--------|
| Rate limited | 429 | Wait 60s, retry |
| Not found | 404 | Return None |
| Server error | 500 | Retry 3x with backoff |
| Timeout | - | Retry with longer timeout |

**Response Normalization:**
```python
# Normalize Semantic Scholar response to standard format
def normalize_paper(ss_response: dict) -> dict:
    return {
        "paper_id": ss_response.get("paperId"),
        "title": ss_response.get("title"),
        "authors": [a["name"] for a in ss_response.get("authors", [])],
        "year": ss_response.get("year"),
        "abstract": ss_response.get("abstract", ""),
        "doi": ss_response.get("externalIds", {}).get("DOI"),
        "arxiv_id": ss_response.get("externalIds", {}).get("ArXiv"),
        "source": "semantic_scholar"
    }
```

**Deliverable:** Working Semantic Scholar wrapper with search + get

---

### Hour 1-2: Paper Fetcher Agent

**Task:** Build agent that handles all input types

**Input Type Detection:**

| Input | How to Detect | Example |
|-------|---------------|---------|
| ArXiv URL | Contains `arxiv.org` | `https://arxiv.org/abs/2301.00001` |
| ArXiv ID | Regex `\d{4}\.\d{4,5}(v\d+)?` | `2301.00001` or `2301.00001v2` |
| DOI | Starts with `10.` | `10.1038/nature12373` |
| DOI URL | Contains `doi.org` | `https://doi.org/10.1038/...` |
| PDF URL | Ends with `.pdf` | `https://example.com/paper.pdf` |
| Raw Text | Default (none of above) | Full paper text |

**Fetching Logic Flow:**
```
INPUT (string)
    │
    ├──▶ Is ArXiv URL/ID?
    │       │
    │       ▼
    │    Fetch from ArXiv API
    │    Parse XML for metadata
    │    Get abstract + PDF link
    │
    ├──▶ Is DOI?
    │       │
    │       ▼
    │    Fetch from CrossRef
    │    Get metadata
    │    Try Semantic Scholar for abstract
    │
    ├──▶ Is PDF URL?
    │       │
    │       ▼
    │    Download PDF
    │    Extract text with PyMuPDF
    │    (No metadata available)
    │
    └──▶ Is Raw Text?
            │
            ▼
         Use directly
         (No metadata available)
```

**ArXiv Parsing (XML):**
```
ArXiv XML Structure:
<feed>
  <entry>
    <id>http://arxiv.org/abs/2301.00001v1</id>
    <title>Paper Title Here</title>
    <summary>Abstract text here...</summary>
    <author>
      <name>Author Name</name>
    </author>
    <published>2023-01-01T00:00:00Z</published>
    <link href="http://arxiv.org/pdf/2301.00001v1" type="application/pdf"/>
  </entry>
</feed>
```

**Output Format:**
```python
{
    "text": "Full paper text or abstract",
    "title": "Paper Title",
    "authors": ["Author 1", "Author 2"],
    "year": 2023,
    "abstract": "Abstract if available",
    "source": "arxiv" | "crossref" | "pdf" | "direct",
    "url": "Original URL if any",
    "arxiv_id": "2301.00001",  # if applicable
    "doi": "10.xxxx/xxxxx",    # if applicable
}
```

**Deliverable:** Fetcher agent handling ArXiv, DOI, PDF, raw text

---

### Hour 2-3: Citation Extractor Agent

**Task:** Extract all citations using ONE LLM call

**The Challenge:**
- Papers have 20-50 citations
- Each citation has: claim (what paper says about it) + reference (metadata)
- Need structured output for downstream processing

**Prompt Engineering Strategy:**

System Prompt:
```
You extract citations from academic papers.

For each citation, return:
{
  "id": <sequential number>,
  "claim": "<what the paper claims this citation shows/proves>",
  "context": "<the sentence where citation appears>",
  "reference": {
    "authors": "<first author et al. or full list>",
    "title": "<paper title if mentioned>",
    "year": <publication year>,
    "venue": "<conference/journal if mentioned>"
  }
}

IMPORTANT:
- "claim" should be what THIS paper says ABOUT the cited work
- Not just "Smith et al. 2023" but "Smith et al. showed that X improves Y"
- Extract ALL citations, not just a few
- Return JSON array only, no explanation

Example good claim: "demonstrated that transformers outperform RNNs by 40%"
Example bad claim: "Smith et al. 2023" (this is just a reference, not a claim)
```

**Input Preprocessing:**
```
1. Truncate paper to ~12,000 tokens (leave room for output)
2. Prioritize: Abstract > Introduction > Methods > Results > Conclusion
3. Keep reference section for metadata extraction
```

**Output Validation:**
```python
def validate_extraction(citations: list) -> list:
    """Clean and validate extracted citations."""
    valid = []
    for c in citations:
        # Must have claim
        if not c.get("claim") or len(c["claim"]) < 10:
            continue
        
        # Must have some reference info
        ref = c.get("reference", {})
        if not ref.get("authors") and not ref.get("year"):
            continue
        
        # Clean up
        c["claim"] = c["claim"].strip()
        c["id"] = len(valid) + 1
        
        valid.append(c)
    
    return valid
```

**Expected Output Example:**
```python
[
    {
        "id": 1,
        "claim": "showed that attention mechanisms can replace recurrence entirely",
        "context": "Vaswani et al. [1] showed that attention mechanisms...",
        "reference": {
            "authors": "Vaswani et al.",
            "title": "Attention Is All You Need",
            "year": 2017,
            "venue": "NeurIPS"
        }
    },
    {
        "id": 2,
        "claim": "demonstrated 40% improvement on language modeling benchmarks",
        "context": "Recent work [2] demonstrated 40% improvement...",
        "reference": {
            "authors": "Smith et al.",
            "year": 2023
        }
    }
]
```

**Token Budget:**
- Input: ~12,000 tokens (paper text)
- Output: ~2,000 tokens (30-40 citations)
- Total: ~14,000 tokens
- Cost: ~$0.002 with gpt-4o-mini

**Deliverable:** Extractor agent with good prompts, returns structured citations

---

### Hour 3-4: Existence Checker Agent

**Task:** Verify each citation exists via Semantic Scholar (FREE)

**Flow per Citation:**
```
Citation Reference
    │
    ▼
┌─────────────────┐
│ 1. Check Cache  │──▶ HIT: Return cached paper data
└─────────────────┘
    │ MISS
    ▼
┌─────────────────┐
│ 2. Build Query  │
│                 │
│ Query = title + │
│ first_author +  │
│ year            │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│ 3. Search API   │
│                 │
│ Semantic Scholar│
│ limit=5         │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│ 4. Find Match   │
│                 │
│ • Title sim >50%│
│ • Year ±1       │
│ • Author match  │
└─────────────────┘
    │
    ├──▶ FOUND: Return paper data + abstract
    │
    └──▶ NOT FOUND: Try fallback (CrossRef)
              │
              └──▶ Still not found: Return "not_found"
```

**Matching Algorithm:**
```python
def find_best_match(reference: dict, results: list) -> dict | None:
    """
    Find best matching paper from search results.
    
    Scoring:
    - Title similarity: 0-50 points
    - Year match: 0-30 points  
    - Author match: 0-20 points
    
    Threshold: 60 points minimum
    """
    ref_title = reference.get("title", "").lower()
    ref_year = reference.get("year")
    ref_author = get_first_author_lastname(reference.get("authors", ""))
    
    best_score = 0
    best_match = None
    
    for paper in results:
        score = 0
        
        # Title similarity (word overlap)
        paper_title = paper.get("title", "").lower()
        title_sim = word_overlap(ref_title, paper_title)
        score += title_sim * 50
        
        # Year match
        paper_year = paper.get("year")
        if paper_year and ref_year:
            if paper_year == ref_year:
                score += 30
            elif abs(paper_year - ref_year) == 1:
                score += 15  # Off by one year is common
        
        # Author match
        paper_authors = [a["name"].lower() for a in paper.get("authors", [])]
        if ref_author and any(ref_author in a for a in paper_authors):
            score += 20
        
        if score > best_score:
            best_score = score
            best_match = paper
    
    return best_match if best_score >= 60 else None
```

**Return Values:**
```python
# Found
{
    "status": "found",
    "paper": {
        "paper_id": "abc123",
        "title": "Actual Paper Title",
        "authors": ["Real Author 1", "Real Author 2"],
        "year": 2023,
        "abstract": "The actual abstract text from the source..."
    },
    "match_score": 85,
    "cached": False
}

# Not found
{
    "status": "not_found",
    "reason": "No matching paper in Semantic Scholar",
    "query_used": "attention transformer vaswani 2017"
}

# API error
{
    "status": "error",
    "reason": "API rate limited",
    "retry_after": 60
}
```

**Caching Strategy:**
```
Cache Key Options:
1. paper_id (from Semantic Scholar) - for retrieval
2. hash(title + first_author + year) - for lookup
3. DOI if available - for exact match

Cache TTL: 30 days (abstracts don't change)

Cache Structure (SQLite):
┌──────────────┬─────────────────────┬───────────┐
│ paper_id     │ data (JSON)         │ cached_at │
├──────────────┼─────────────────────┼───────────┤
│ abc123       │ {title, authors...} │ 2024-02-27│
└──────────────┴─────────────────────┴───────────┘
```

**Deliverable:** Existence checker with caching, returns paper + abstract

---

### Hour 4-5: Metadata Verification

**Task:** Check if citation metadata is accurate (no LLM needed)

**Checks to Perform:**

| Field | Method | Tolerance |
|-------|--------|-----------|
| Title | Fuzzy word overlap | >50% similarity |
| Year | Exact comparison | ±1 year allowed |
| Authors | Last name matching | ≥1 author must match |
| Venue | Fuzzy match (optional) | >40% similarity |

**Author Normalization:**
```
Input Variations → Normalized
─────────────────────────────
"J. Smith"           → "smith"
"John Smith"         → "smith"
"Smith, John"        → "smith"
"Smith, J."          → "smith"
"John A. Smith"      → "smith"
"Smith et al."       → "smith"
"J Smith"            → "smith"
```

**Title Normalization:**
```
Input                                    → Normalized
─────────────────────────────────────────────────────
"Attention Is All You Need"              → "attention is all you need"
"Attention is All You Need."             → "attention is all you need"
"ATTENTION IS ALL YOU NEED"              → "attention is all you need"
"Attention Is All You Need (2017)"       → "attention is all you need"
```

**Fuzzy Matching Function:**
```python
def word_overlap(text1: str, text2: str) -> float:
    """
    Calculate word overlap between two texts.
    Returns 0.0 to 1.0
    """
    words1 = set(normalize(text1).split())
    words2 = set(normalize(text2).split())
    
    if not words1 or not words2:
        return 0.0
    
    intersection = words1 & words2
    union = words1 | words2
    
    return len(intersection) / len(union)
```

**Output Format:**
```python
{
    "metadata_status": "correct",  # or "has_errors"
    "checks": {
        "title": {
            "status": "match",
            "claimed": "Attention Is All You Need",
            "actual": "Attention is All You Need",
            "similarity": 1.0
        },
        "year": {
            "status": "match",
            "claimed": 2017,
            "actual": 2017
        },
        "authors": {
            "status": "match",
            "claimed": "Vaswani et al.",
            "actual": ["Ashish Vaswani", "Noam Shazeer", ...],
            "matched": "vaswani"
        }
    },
    "errors": []  # or list of error descriptions
}

# Example with errors
{
    "metadata_status": "has_errors",
    "checks": {...},
    "errors": [
        {"field": "year", "claimed": 2023, "actual": 2022},
        {"field": "title", "similarity": 0.45, "threshold": 0.50}
    ]
}
```

**Deliverable:** Metadata verifier with fuzzy matching

---

### Hour 5-6: Integration & Edge Cases

**Task:** Handle real-world messiness

**Edge Cases Table:**

| Edge Case | Detection | Solution |
|-----------|-----------|----------|
| Paper not in Semantic Scholar | No results | Try CrossRef, then ArXiv |
| ArXiv preprint vs published | Same paper, different venue | Match on title, ignore venue |
| Name variations | "J. Smith" vs "John Smith" | Normalize to last name only |
| Year off by one | 2023 vs 2022 | Allow ±1 tolerance |
| Title typo in citation | Low similarity | Lower threshold to 0.4 |
| Self-citation | Author = paper author | Flag but still verify |
| Citation to website | Non-academic URL | Mark as `non_academic` |
| Citation to book chapter | Different format | Extract book title |
| Non-English paper | Unicode characters | Still try, may fail |
| Withdrawn/retracted paper | Paper removed | Check retraction status |

**Parallel Execution:**
```
30 citations to check
        │
        ▼
┌───────────────────────────────────────┐
│ asyncio.gather() with semaphore      │
│                                       │
│ Max 10 concurrent requests            │
│ (respect API rate limits)             │
│                                       │
│ Task 1 ─┬─ Task 2 ─┬─ ... ─┬─ Task 10│
│         │          │       │          │
│         ▼          ▼       ▼          │
│    [Results collected as completed]   │
└───────────────────────────────────────┘
        │
        ▼
Total time: ~3-5 seconds for 30 citations
(vs 30-60 seconds sequential)
```

**Retry Logic:**
```python
async def check_with_retry(citation, max_retries=3):
    for attempt in range(max_retries):
        try:
            result = await existence_checker.run(citation)
            return result
        except RateLimitError:
            wait_time = 2 ** attempt  # 1, 2, 4 seconds
            await asyncio.sleep(wait_time)
        except TimeoutError:
            continue
        except Exception as e:
            if attempt == max_retries - 1:
                return {
                    "status": "error",
                    "message": str(e)
                }
    return {"status": "error", "message": "Max retries exceeded"}
```

**Deliverable:** Robust agents handling all edge cases

---

### Hour 6-7: Demo Preparation

**Task:** Ensure reliable demo with pre-cached papers

**Demo Papers to Prepare:**

| Paper | Purpose | What to Show |
|-------|---------|--------------|
| Paper A | Has hallucinated citation | Citation that doesn't exist |
| Paper B | Has misrepresented citation | Citation exists but says opposite |
| Paper C | Clean paper | All citations valid (baseline) |

**Pre-caching Script Tasks:**
```
1. Select 3 demo papers (find on ArXiv)
2. Run full extraction on each
3. Cache all source paper abstracts
4. Verify at least one has issues
5. Create fallback data if APIs fail
```

**Finding Demo Papers:**
- Look for ML papers on ArXiv from last 6 months
- Papers with 20-40 citations (not too few, not too many)
- Check that citations are to real papers (not fake)
- Ideal: Find one where you KNOW a claim is wrong

**Fallback Data Structure:**
```python
DEMO_FALLBACKS = {
    "arxiv_2301_00001": {
        "paper": {
            "title": "Demo Paper Title",
            "authors": ["Demo Author"],
            "abstract": "Demo abstract..."
        },
        "citations": [
            {
                "id": 1,
                "claim": "showed transformers are better",
                "reference": {"authors": "Smith", "year": 2023}
            },
            # ... pre-extracted citations
        ],
        "existence_results": [
            {"status": "found", "paper": {...}},
            {"status": "not_found"},  # This one doesn't exist!
            # ... pre-checked results
        ],
        "verification_results": [
            {"verdict": "supported", "confidence": 0.9},
            {"verdict": "contradicted", "confidence": 0.85},
            # ... pre-verified results (from Person 2)
        ]
    }
}
```

**Fallback Logic:**
```python
async def analyze_paper(input_url: str):
    # Check if it's a demo paper
    arxiv_id = extract_arxiv_id(input_url)
    if arxiv_id in DEMO_FALLBACKS:
        # Use cached data (instant, no API calls)
        return DEMO_FALLBACKS[arxiv_id]
    
    # Otherwise, run real pipeline
    return await real_pipeline(input_url)
```

**Deliverable:** Demo papers cached, fallbacks ready

---

## 📊 Output Format for Person 2

You provide Person 2 with this data structure for each citation:

```python
{
    "citation": {
        "id": 7,
        "claim": "Smith et al. demonstrated 40% improvement in accuracy",
        "context": "Recent work [7] demonstrated 40% improvement...",
        "reference": {
            "authors": "Smith et al.",
            "title": "Improving Neural Networks",
            "year": 2023,
            "venue": "NeurIPS"
        }
    },
    "source": {
        "paper_id": "abc123xyz",
        "title": "Improving Neural Networks with Novel Techniques",
        "authors": ["John Smith", "Jane Doe"],
        "year": 2023,
        "abstract": "We present a study comparing various neural network improvements. Our results show marginal gains of 5-10% on standard benchmarks, with no statistically significant difference on the main metric...",
        "doi": "10.1234/example"
    },
    "existence_status": "found",
    "metadata_status": "correct",
    "metadata_errors": []
}
```

**Person 2 uses:**
- `citation.claim` - What the paper claims
- `source.abstract` - To verify against
- `existence_status` - Only verifies if "found"

---

## 🔗 Integration with Other Team Members

### → Person 1 (Foundation Lead)

Your agents must implement this interface:
```python
from server.core.agent_base import BaseAgent, AgentResult

class FetcherAgent(BaseAgent):
    name = "fetcher"
    
    async def run(self, input_data: dict) -> AgentResult:
        # input_data = {"input": "https://arxiv.org/..."}
        paper = await self.fetch_paper(input_data["input"])
        
        return AgentResult(
            agent_name=self.name,
            status="success",
            data=paper,
            tokens_used=0
        )

class ExtractorAgent(BaseAgent):
    name = "extractor"
    
    async def run(self, input_data: dict) -> AgentResult:
        # input_data = {"text": "paper text..."}
        citations = await self.extract(input_data["text"])
        
        return AgentResult(
            agent_name=self.name,
            status="success",
            data={"citations": citations},
            tokens_used=1500  # Track LLM usage
        )

class ExistenceAgent(BaseAgent):
    name = "existence"
    
    async def run(self, input_data: dict) -> AgentResult:
        # input_data = {"citation": {...}}
        result = await self.check(input_data["citation"])
        
        return AgentResult(
            agent_name=self.name,
            status="success",
            data=result,
            tokens_used=0
        )
```

### → Person 2 (Verification Lead)

You send them:
```python
# List of citations with source data
[
    {
        "citation": {
            "id": 1,
            "claim": "...",
            "reference": {...}
        },
        "source": {
            "paper_id": "...",
            "abstract": "...",  # MOST IMPORTANT
            ...
        },
        "existence_status": "found"
    },
    ...
]
```

They use the `abstract` to verify if `claim` is accurate.

---

## 📦 Dependencies

```bash
# HTTP & Async
httpx>=0.24.0               # Async HTTP client
aiohttp>=3.8.0              # Alternative async client

# PDF Processing
PyMuPDF>=1.22.0             # PDF text extraction (install as 'fitz')

# Data Validation
pydantic>=2.0.0             # Data models

# LLM
openai>=1.0.0               # For extraction

# XML Parsing (stdlib)
# xml.etree.ElementTree    # For ArXiv API

# Utilities
python-dotenv>=1.0.0        # Environment variables
```

**Install:**
```bash
pip install httpx aiohttp PyMuPDF pydantic openai python-dotenv
```

---

## 🧪 Testing Checklist

### API Tests
| Test | Expected | Status |
|------|----------|--------|
| Search "Attention Is All You Need" | Returns Vaswani 2017 | ⬜ |
| Search "BERT pre-training" | Returns Devlin 2018 | ⬜ |
| Search fake paper "xyz123abc" | Returns not_found | ⬜ |
| Get paper by Semantic Scholar ID | Returns full data | ⬜ |
| Get paper by DOI | Returns full data | ⬜ |

### Fetcher Tests
| Test | Expected | Status |
|------|----------|--------|
| Fetch ArXiv URL | Returns paper data | ⬜ |
| Fetch ArXiv ID only | Returns paper data | ⬜ |
| Fetch DOI | Returns metadata | ⬜ |
| Fetch PDF URL | Returns extracted text | ⬜ |
| Fetch raw text | Returns as-is | ⬜ |

### Extractor Tests
| Test | Expected | Status |
|------|----------|--------|
| Extract from ML paper | Returns 20+ citations | ⬜ |
| Each citation has claim | Claims are meaningful | ⬜ |
| Each citation has reference | Has author/year | ⬜ |
| JSON is valid | Parses correctly | ⬜ |

### Existence Tests
| Test | Expected | Status |
|------|----------|--------|
| Real paper citation | Returns "found" + abstract | ⬜ |
| Fake paper citation | Returns "not_found" | ⬜ |
| Cached paper | Returns instantly | ⬜ |
| Rate limit handling | Retries work | ⬜ |

### Metadata Tests
| Test | Expected | Status |
|------|----------|--------|
| Exact title match | similarity = 1.0 | ⬜ |
| Fuzzy title match | similarity > 0.5 | ⬜ |
| Year off by 1 | Still matches | ⬜ |
| Author last name match | Finds match | ⬜ |

---

## ✅ Deliverables Checklist

### Hour 0-1
- [ ] Semantic Scholar API wrapper working
- [ ] Search endpoint tested
- [ ] Paper lookup tested
- [ ] Error handling in place

### Hour 1-2
- [ ] Fetcher agent complete
- [ ] ArXiv URL/ID fetching works
- [ ] DOI fetching works
- [ ] PDF extraction works
- [ ] Input type detection works

### Hour 2-3
- [ ] Extractor agent complete
- [ ] Prompt optimized for good claims
- [ ] JSON parsing with fallback
- [ ] Validation of extracted citations

### Hour 3-4
- [ ] Existence checker complete
- [ ] Caching layer working
- [ ] Matching algorithm accurate
- [ ] Fallback to CrossRef works

### Hour 4-5
- [ ] Metadata verification complete
- [ ] Fuzzy matching implemented
- [ ] Author normalization works
- [ ] Title normalization works

### Hour 5-6
- [ ] Parallel execution working
- [ ] Rate limit handling tested
- [ ] All edge cases handled
- [ ] Integration with Person 1's pipeline

### Hour 6-7
- [ ] Demo papers selected
- [ ] All sources pre-cached
- [ ] Fallback data created
- [ ] Full pipeline tested

---

## 📊 Success Metrics

| Metric | Target |
|--------|--------|
| Paper fetch success rate | >95% |
| Citation extraction accuracy | >90% |
| Existence check accuracy | >95% |
| API call latency | <500ms avg |
| Full pipeline (30 citations) | <10 seconds |
| Cache hit rate (demo) | 100% |

---

## 🆘 Troubleshooting

| Problem | Solution |
|---------|----------|
| Semantic Scholar rate limited | Wait 60s, use API key if available |
| ArXiv returns malformed XML | Use fallback parser, or skip |
| PDF extraction fails | Try different PDF library, or skip |
| LLM returns bad JSON | Use regex extraction fallback |
| Citation not found | Try alternative search terms |
| Wrong paper matched | Increase match threshold |
| Timeout on large paper | Truncate input, or increase timeout |

---

## 📞 Coordination Points

| Hour | Sync With | Purpose |
|------|-----------|---------|
| 1 | Person 1 | Confirm agent interface |
| 3 | Person 2 | Confirm output format they need |
| 5 | Person 1 | Test full pipeline integration |
| 6 | Everyone | End-to-end demo test |

---

## 🎯 The Demo Depends on You

Your work is invisible but critical:

> **Demo fails if:**
> - Paper can't be fetched → "Error loading paper"
> - Citations not extracted → "No citations found"
> - Sources not found → Person 2 has nothing to verify
> - APIs fail → Demo crashes

> **Demo succeeds if:**
> - Paper loads in <2 seconds ✓
> - 30 citations extracted ✓
> - All sources found and cached ✓
> - Person 2 can verify against real abstracts ✓

**You are the foundation. Build it solid! 🚀**
