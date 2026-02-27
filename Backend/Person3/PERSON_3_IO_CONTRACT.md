# Person 3: Data Lead - Input/Output Contracts

## 🎯 Your Role in the Pipeline

You fetch papers, extract citations, and verify existence. You provide the raw data that Person 2 verifies.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   FROM PERSON 1                                                             │
│   User's paper URL/DOI/text                                                 │
│        │                                                                    │
│        ▼                                                                    │
│   ╔═══════════════════════════════════════════════════════════════════╗    │
│   ║                     YOUR DOMAIN (Person 3)                        ║    │
│   ║                                                                   ║    │
│   ║   ┌─────────────────────────────────────────────────────────┐    ║    │
│   ║   │                    FETCHER                               │    ║    │
│   ║   │                                                         │    ║    │
│   ║   │  URL ──┬──▶ ArXiv API ──▶ paper data                   │    ║    │
│   ║   │        ├──▶ CrossRef  ──▶ metadata                      │    ║    │
│   ║   │        ├──▶ PDF parse ──▶ text                          │    ║    │
│   ║   │        └──▶ direct    ──▶ as-is                         │    ║    │
│   ║   └─────────────────────────────────────────────────────────┘    ║    │
│   ║                          │                                        ║    │
│   ║                          ▼                                        ║    │
│   ║   ┌─────────────────────────────────────────────────────────┐    ║    │
│   ║   │                   EXTRACTOR                              │    ║    │
│   ║   │                                                         │    ║    │
│   ║   │  paper text ──▶ LLM ──▶ structured citations           │    ║    │
│   ║   │                                                         │    ║    │
│   ║   └─────────────────────────────────────────────────────────┘    ║    │
│   ║                          │                                        ║    │
│   ║                          ▼                                        ║    │
│   ║   ┌─────────────────────────────────────────────────────────┐    ║    │
│   ║   │                 EXISTENCE CHECKER                        │    ║    │
│   ║   │                                                         │    ║    │
│   ║   │  citation ──▶ Semantic Scholar ──▶ source + abstract   │    ║    │
│   ║   │           ──▶ CrossRef (fallback)                       │    ║    │
│   ║   │                                                         │    ║    │
│   ║   └─────────────────────────────────────────────────────────┘    ║    │
│   ║                                                                   ║    │
│   ╚═══════════════════════════════════════════════════════════════════╝    │
│        │                                                                    │
│        ▼                                                                    │
│   TO PERSON 1 (then to Person 2)                                           │
│   Citations + Source Abstracts                                              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 📥 INPUTS YOU RECEIVE

### From Person 1 (Pipeline Orchestrator)

#### Input to Fetcher Agent

```json
{
    "input": "https://arxiv.org/abs/2301.00001"
}
```

**Possible Input Formats:**

| Format | Example | How to Detect |
|--------|---------|---------------|
| ArXiv URL | `https://arxiv.org/abs/2301.00001` | Contains `arxiv.org` |
| ArXiv PDF URL | `https://arxiv.org/pdf/2301.00001.pdf` | Contains `arxiv.org` + `.pdf` |
| ArXiv ID | `2301.00001` or `2301.00001v2` | Regex: `\d{4}\.\d{4,5}(v\d+)?` |
| DOI URL | `https://doi.org/10.1038/nature12373` | Contains `doi.org` |
| DOI | `10.1038/nature12373` | Starts with `10.` |
| PDF URL | `https://example.com/paper.pdf` | Ends with `.pdf` |
| Raw Text | `"In this paper we propose..."` | None of the above |

#### Input to Extractor Agent

```json
{
    "text": "Full paper text here...\n\nIntroduction\n\nRecent advances in deep learning have shown remarkable progress [1]. Vaswani et al. demonstrated that attention mechanisms can replace recurrence entirely [2]. Furthermore, Smith et al. showed 40% improvement on benchmarks [3].\n\n...\n\nReferences\n[1] LeCun et al., Deep Learning, Nature 2015\n[2] Vaswani et al., Attention Is All You Need, NeurIPS 2017\n[3] Smith et al., Transformer Improvements, 2023"
}
```

**Text Constraints:**
- Max length: ~50,000 characters (truncate if longer)
- For LLM: Send ~12,000 tokens (prioritize intro + references)

#### Input to Existence Agent

```json
{
    "citation": {
        "id": 2,
        "claim": "demonstrated that attention mechanisms can replace recurrence entirely",
        "context": "Vaswani et al. demonstrated that attention mechanisms can replace recurrence entirely [2].",
        "reference": {
            "authors": "Vaswani et al.",
            "title": "Attention Is All You Need",
            "year": 2017,
            "venue": "NeurIPS"
        }
    }
}
```

---

## 📤 OUTPUTS YOU SEND

### From Fetcher Agent

#### Success Case

```json
{
    "agent_name": "fetcher",
    "status": "success",
    "data": {
        "text": "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks that include an encoder and a decoder. The best performing models also connect the encoder and decoder through an attention mechanism. We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely...\n\n[Full paper text continues for ~20,000 characters]",
        "title": "Attention is All You Need",
        "authors": [
            "Ashish Vaswani",
            "Noam Shazeer",
            "Niki Parmar",
            "Jakob Uszkoreit",
            "Llion Jones",
            "Aidan N. Gomez",
            "Lukasz Kaiser",
            "Illia Polosukhin"
        ],
        "year": 2017,
        "abstract": "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks that include an encoder and a decoder...",
        "source": "arxiv",
        "url": "https://arxiv.org/abs/1706.03762",
        "arxiv_id": "1706.03762",
        "doi": "10.48550/arXiv.1706.03762",
        "pdf_url": "https://arxiv.org/pdf/1706.03762.pdf"
    },
    "tokens_used": 0,
    "latency_ms": 1250.5
}
```

#### Different Source Types

**ArXiv Paper:**
```json
{
    "data": {
        "text": "Full paper text...",
        "title": "Paper Title",
        "authors": ["Author 1", "Author 2"],
        "year": 2023,
        "abstract": "Abstract text...",
        "source": "arxiv",
        "arxiv_id": "2301.00001",
        "doi": null
    }
}
```

**DOI/CrossRef:**
```json
{
    "data": {
        "text": null,
        "title": "Paper Title",
        "authors": ["Author 1", "Author 2"],
        "year": 2023,
        "abstract": "Abstract from CrossRef or Semantic Scholar...",
        "source": "crossref",
        "arxiv_id": null,
        "doi": "10.1038/nature12373"
    }
}
```

**PDF:**
```json
{
    "data": {
        "text": "Extracted text from PDF...",
        "title": null,
        "authors": null,
        "year": null,
        "abstract": null,
        "source": "pdf",
        "url": "https://example.com/paper.pdf"
    }
}
```

**Raw Text:**
```json
{
    "data": {
        "text": "User provided text...",
        "title": null,
        "authors": null,
        "year": null,
        "abstract": null,
        "source": "direct"
    }
}
```

#### Error Cases

```json
{
    "agent_name": "fetcher",
    "status": "error",
    "data": null,
    "error": {
        "code": "FETCH_FAILED",
        "message": "Could not access URL",
        "details": "HTTP 404: Page not found"
    },
    "tokens_used": 0,
    "latency_ms": 3500.0
}
```

---

### From Extractor Agent

#### Success Case

```json
{
    "agent_name": "extractor",
    "status": "success",
    "data": {
        "citations": [
            {
                "id": 1,
                "claim": "showed remarkable progress in image recognition",
                "context": "Recent advances in deep learning have shown remarkable progress [1].",
                "reference": {
                    "authors": "LeCun et al.",
                    "title": "Deep Learning",
                    "year": 2015,
                    "venue": "Nature"
                }
            },
            {
                "id": 2,
                "claim": "demonstrated that attention mechanisms can replace recurrence entirely for sequence transduction",
                "context": "Vaswani et al. demonstrated that attention mechanisms can replace recurrence entirely [2].",
                "reference": {
                    "authors": "Vaswani et al.",
                    "title": "Attention Is All You Need",
                    "year": 2017,
                    "venue": "NeurIPS"
                }
            },
            {
                "id": 3,
                "claim": "achieved 40% improvement on language modeling benchmarks compared to previous approaches",
                "context": "Furthermore, Smith et al. showed 40% improvement on benchmarks [3].",
                "reference": {
                    "authors": "Smith et al.",
                    "title": "Transformer Improvements",
                    "year": 2023,
                    "venue": null
                }
            }
        ]
    },
    "tokens_used": 1450,
    "latency_ms": 3200.0
}
```

**Citation Object Schema:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | int | ✅ | Sequential identifier |
| `claim` | string | ✅ | What the paper claims about this citation |
| `context` | string | ❌ | Original sentence containing citation |
| `reference.authors` | string | ✅ | Author names (e.g., "Smith et al.") |
| `reference.title` | string | ❌ | Paper title if mentioned |
| `reference.year` | int | ✅ | Publication year |
| `reference.venue` | string | ❌ | Conference/journal if mentioned |

**Good vs Bad Claims:**

| ❌ Bad Claim | ✅ Good Claim |
|-------------|---------------|
| "Smith et al. 2023" | "demonstrated 40% improvement on benchmarks" |
| "[2]" | "showed that attention can replace recurrence" |
| "as shown in previous work" | "achieved state-of-the-art results on GLUE" |
| "Vaswani et al." | "proposed the Transformer architecture" |

#### Error/Empty Cases

```json
{
    "agent_name": "extractor",
    "status": "success",
    "data": {
        "citations": []
    },
    "tokens_used": 500,
    "latency_ms": 1500.0,
    "warning": "No citations found in paper"
}
```

---

### From Existence Agent

#### Found Case

```json
{
    "agent_name": "existence",
    "status": "success",
    "data": {
        "status": "found",
        "paper": {
            "paper_id": "204e3073870fae3d05bcbc2f6a8e263d9b72e776",
            "title": "Attention is All You Need",
            "authors": [
                "Ashish Vaswani",
                "Noam Shazeer",
                "Niki Parmar",
                "Jakob Uszkoreit",
                "Llion Jones",
                "Aidan N. Gomez",
                "Lukasz Kaiser",
                "Illia Polosukhin"
            ],
            "year": 2017,
            "abstract": "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks that include an encoder and a decoder. The best performing models also connect the encoder and decoder through an attention mechanism. We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely. Experiments on two machine translation tasks show these models to be superior in quality while being more parallelizable and requiring significantly less time to train.",
            "doi": "10.48550/arXiv.1706.03762",
            "url": "https://www.semanticscholar.org/paper/204e3073870fae3d05bcbc2f6a8e263d9b72e776",
            "citation_count": 95000
        },
        "match_score": 95,
        "match_details": {
            "title_similarity": 1.0,
            "year_match": true,
            "author_match": "vaswani"
        },
        "cached": false
    },
    "tokens_used": 0,
    "latency_ms": 450.2
}
```

#### Not Found Case

```json
{
    "agent_name": "existence",
    "status": "success",
    "data": {
        "status": "not_found",
        "reason": "No matching paper found in Semantic Scholar or CrossRef",
        "query_used": "Nonexistent Paper Title Fake Author 2024",
        "search_results": 0
    },
    "tokens_used": 0,
    "latency_ms": 380.5
}
```

#### Metadata Error Case

```json
{
    "agent_name": "existence",
    "status": "success",
    "data": {
        "status": "found",
        "paper": {
            "paper_id": "abc123",
            "title": "Actual Paper Title",
            "authors": ["Real Author"],
            "year": 2022,
            "abstract": "Abstract text..."
        },
        "match_score": 72,
        "metadata_status": "has_errors",
        "metadata_errors": [
            {
                "field": "year",
                "claimed": 2023,
                "actual": 2022,
                "message": "Year mismatch: citation says 2023, paper is from 2022"
            }
        ],
        "cached": false
    },
    "tokens_used": 0,
    "latency_ms": 520.0
}
```

#### API Error Case

```json
{
    "agent_name": "existence",
    "status": "error",
    "data": {
        "status": "error",
        "reason": "Semantic Scholar API rate limited",
        "retry_after": 60
    },
    "tokens_used": 0,
    "latency_ms": 150.0
}
```

---

## 🔄 Internal Processing

### Fetcher Flow

```
INPUT: "https://arxiv.org/abs/2301.00001"
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. DETECT INPUT TYPE                                        │
│                                                             │
│    if "arxiv.org" in input:                                 │
│        type = "arxiv"                                       │
│    elif input.startswith("10."):                            │
│        type = "doi"                                         │
│    elif input.endswith(".pdf"):                             │
│        type = "pdf"                                         │
│    else:                                                    │
│        type = "direct"                                      │
│                                                             │
│    Result: type = "arxiv"                                   │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. EXTRACT IDENTIFIER                                       │
│                                                             │
│    For ArXiv: extract "2301.00001" from URL                │
│    For DOI: extract "10.xxx/xxx" from URL                  │
│                                                             │
│    Result: arxiv_id = "2301.00001"                         │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. FETCH FROM API                                           │
│                                                             │
│    ArXiv API: GET http://export.arxiv.org/api/query?       │
│               id_list=2301.00001                            │
│                                                             │
│    Returns: XML with title, authors, abstract, etc.        │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. PARSE RESPONSE                                           │
│                                                             │
│    Extract from XML:                                        │
│    - title                                                  │
│    - authors (list)                                         │
│    - abstract/summary                                       │
│    - published date → year                                  │
│    - PDF link                                               │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. (OPTIONAL) FETCH FULL TEXT                               │
│                                                             │
│    Download PDF from pdf_link                               │
│    Extract text using PyMuPDF                               │
│                                                             │
│    Note: This is slow, only do if needed                   │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
OUTPUT: { text, title, authors, year, abstract, source, ... }
```

### Extractor Flow

```
INPUT: { text: "Full paper text..." }
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. PREPROCESS TEXT                                          │
│                                                             │
│    - Truncate to ~12,000 tokens if needed                  │
│    - Prioritize: Abstract > Intro > Methods > References   │
│    - Clean whitespace, fix encoding issues                  │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. BUILD PROMPT                                             │
│                                                             │
│    System: "Extract citations with claims and references"  │
│    User: [preprocessed paper text]                          │
│                                                             │
│    Model: gpt-4o-mini                                       │
│    Temperature: 0.1                                         │
│    Max tokens: 2000                                         │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. CALL LLM                                                 │
│                                                             │
│    Response: JSON array of citations                        │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. PARSE & VALIDATE                                         │
│                                                             │
│    - Parse JSON (with fallback strategies)                 │
│    - Validate each citation has claim + reference          │
│    - Assign sequential IDs                                  │
│    - Remove duplicates                                      │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
OUTPUT: { citations: [...] }
```

### Existence Checker Flow

```
INPUT: { citation: { reference: { authors, title, year } } }
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. CHECK CACHE                                              │
│                                                             │
│    key = hash(title + first_author + year)                 │
│    cached = cache.get(key)                                  │
│                                                             │
│    If cached: return cached data                           │
└─────────────────────────────────────────────────────────────┘
          │ (cache miss)
          ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. BUILD SEARCH QUERY                                       │
│                                                             │
│    query = f"{title} {first_author} {year}"                │
│                                                             │
│    Example: "Attention Is All You Need Vaswani 2017"       │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. SEARCH SEMANTIC SCHOLAR                                  │
│                                                             │
│    GET /paper/search?query={query}&limit=5                 │
│        &fields=title,authors,year,abstract,paperId         │
│                                                             │
│    Returns: List of candidate papers                        │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. FIND BEST MATCH                                          │
│                                                             │
│    For each candidate:                                      │
│      - Score title similarity (0-50 points)                │
│      - Score year match (0-30 points)                      │
│      - Score author match (0-20 points)                    │
│                                                             │
│    Select: highest score >= 60                             │
└─────────────────────────────────────────────────────────────┘
          │
          ├──▶ Match found: return paper data
          │
          ▼ (no match)
┌─────────────────────────────────────────────────────────────┐
│ 5. FALLBACK TO CROSSREF (if DOI available)                 │
│                                                             │
│    GET /works?query={query}                                │
│                                                             │
│    Try to find match there                                 │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. CACHE RESULT                                             │
│                                                             │
│    cache.set(paper_id, paper_data)                         │
│    cache.set(lookup_key, paper_id)                         │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
OUTPUT: { status: "found"/"not_found", paper?: {...} }
```

---

## 🌐 API Reference

### Semantic Scholar API

**Base URL:** `https://api.semanticscholar.org/graph/v1`

**Search Papers:**
```
GET /paper/search
    ?query=attention+transformer+vaswani
    &limit=5
    &fields=title,authors,year,abstract,paperId,externalIds,citationCount
```

**Get Paper by ID:**
```
GET /paper/{paper_id}
    ?fields=title,authors,year,abstract
```

**Get Paper by DOI:**
```
GET /paper/DOI:{doi}
    ?fields=title,authors,year,abstract
```

**Response Example:**
```json
{
    "data": [
        {
            "paperId": "204e3073870fae3d05bcbc2f6a8e263d9b72e776",
            "title": "Attention is All You Need",
            "authors": [
                {"authorId": "1234", "name": "Ashish Vaswani"},
                {"authorId": "5678", "name": "Noam Shazeer"}
            ],
            "year": 2017,
            "abstract": "The dominant sequence transduction models...",
            "externalIds": {
                "DOI": "10.48550/arXiv.1706.03762",
                "ArXiv": "1706.03762"
            },
            "citationCount": 95000
        }
    ]
}
```

**Rate Limits:**
- Without API key: 100 requests / 5 minutes
- With API key: 1000 requests / 5 minutes

### ArXiv API

**Base URL:** `http://export.arxiv.org`

**Query by ID:**
```
GET /api/query?id_list=1706.03762
```

**Response:** XML
```xml
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v5</id>
    <title>Attention Is All You Need</title>
    <summary>The dominant sequence transduction models...</summary>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
    <published>2017-06-12T17:57:34Z</published>
    <link href="http://arxiv.org/pdf/1706.03762v5" type="application/pdf"/>
  </entry>
</feed>
```

### CrossRef API

**Base URL:** `https://api.crossref.org`

**Get by DOI:**
```
GET /works/10.48550/arXiv.1706.03762
```

**Response:**
```json
{
    "message": {
        "DOI": "10.48550/arXiv.1706.03762",
        "title": ["Attention Is All You Need"],
        "author": [
            {"given": "Ashish", "family": "Vaswani"},
            {"given": "Noam", "family": "Shazeer"}
        ],
        "published": {"date-parts": [[2017, 6, 12]]}
    }
}
```

---

## ❌ Error Handling

### Error Codes

| Code | Agent | Meaning |
|------|-------|---------|
| `INVALID_URL` | fetcher | URL format not recognized |
| `FETCH_TIMEOUT` | fetcher | Request timed out |
| `FETCH_404` | fetcher | Paper not found at URL |
| `FETCH_FORBIDDEN` | fetcher | Access denied (paywall) |
| `PDF_PARSE_FAILED` | fetcher | Could not extract text from PDF |
| `EXTRACT_FAILED` | extractor | LLM call failed |
| `EXTRACT_INVALID_JSON` | extractor | LLM returned bad JSON |
| `EXISTENCE_RATE_LIMITED` | existence | API rate limited |
| `EXISTENCE_TIMEOUT` | existence | Search timed out |

### Retry Strategy

```python
RETRY_CONFIG = {
    "max_retries": 3,
    "backoff_base": 2,  # seconds
    "backoff_max": 60,  # seconds
    "retry_on": [
        "FETCH_TIMEOUT",
        "EXISTENCE_RATE_LIMITED",
        "EXISTENCE_TIMEOUT",
    ]
}
```

---

## 🔗 Integration with Other Persons

### To Person 1 (Pipeline Orchestrator)

You implement these agents:
```python
from server.core.agent_base import BaseAgent, AgentResult

class FetcherAgent(BaseAgent):
    name = "fetcher"
    
    async def run(self, input_data: dict) -> AgentResult:
        url = input_data["input"]
        paper = await self._fetch(url)
        
        return AgentResult(
            agent_name=self.name,
            status="success",
            data=paper,
            tokens_used=0,
            latency_ms=self._latency
        )

class ExtractorAgent(BaseAgent):
    name = "extractor"
    
    async def run(self, input_data: dict) -> AgentResult:
        text = input_data["text"]
        citations = await self._extract(text)
        
        return AgentResult(
            agent_name=self.name,
            status="success",
            data={"citations": citations},
            tokens_used=self._tokens,
            latency_ms=self._latency
        )

class ExistenceAgent(BaseAgent):
    name = "existence"
    
    async def run(self, input_data: dict) -> AgentResult:
        citation = input_data["citation"]
        result = await self._check(citation)
        
        return AgentResult(
            agent_name=self.name,
            status="success",
            data=result,
            tokens_used=0,
            latency_ms=self._latency
        )
```

### To Person 2 (Verification Lead)

Your existence checker output feeds directly to Person 2:

```python
# Person 1 combines your outputs into this structure for Person 2:
{
    "citations": [
        {
            "citation": {
                "id": 1,
                "claim": "...",  # From YOUR extractor
                "reference": {...}
            },
            "source": {
                "paper_id": "...",  # From YOUR existence checker
                "abstract": "...",  # From YOUR existence checker - CRITICAL
                "title": "...",
                "authors": [...]
            }
        }
    ]
}
```

**Person 2 depends on you for:**
- ✅ Good quality `claim` (meaningful, not just "Smith et al.")
- ✅ Complete `abstract` (the ground truth they verify against)
- ✅ Accurate `paper_id` (for caching)

---

## ✅ Validation Checklist

### Fetcher Output Validation

- [ ] `text` or `abstract` is non-empty (at least one)
- [ ] `source` is one of: "arxiv", "crossref", "pdf", "direct"
- [ ] If ArXiv: `arxiv_id` is set
- [ ] If DOI: `doi` is set

### Extractor Output Validation

- [ ] `citations` is an array
- [ ] Each citation has `id` (sequential int)
- [ ] Each citation has `claim` (non-empty string, >10 chars)
- [ ] Each citation has `reference.authors` or `reference.year`
- [ ] No duplicate citations

### Existence Output Validation

- [ ] `status` is one of: "found", "not_found", "error"
- [ ] If "found": `paper.paper_id` is set
- [ ] If "found": `paper.abstract` is set and non-empty
- [ ] `cached` boolean is set
- [ ] `tokens_used` is 0 (no LLM used)

---

**You are the foundation. Without your data, nothing else works. Build it solid! 🚀**
