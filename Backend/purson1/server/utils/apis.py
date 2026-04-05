import asyncio
import html as html_module
import re
import ssl
import certifi
import aiohttp
import xml.etree.ElementTree as ET
from typing import Optional, List, Dict, Any
from urllib.parse import quote_plus

class APIError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code

class APIClientManager:
    """Manages a single global aiohttp session for connection pooling."""
    _session: Optional[aiohttp.ClientSession] = None

    @classmethod
    def get_session(cls) -> aiohttp.ClientSession:
        if cls._session is None or cls._session.closed:
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(limit=100, limit_per_host=20, ssl=ssl_ctx)
            cls._session = aiohttp.ClientSession(connector=connector)
        return cls._session

    @classmethod
    async def close_session(cls):
        if cls._session and not cls._session.closed:
            await cls._session.close()

class SemanticScholarAPI:
    BASE_URL = "https://api.semanticscholar.org/graph/v1"
    _last_request_time: float = 0.0
    _min_interval: float = 0.35  # ~3 req/sec max to stay under rate limits

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.headers = {"x-api-key": api_key} if api_key else {}
        self.fields = "title,authors,year,abstract,paperId,externalIds,citationCount,tldr,openAccessPdf"

    async def _throttle(self):
        """Simple rate limiter shared across all instances."""
        now = asyncio.get_event_loop().time()
        wait = SemanticScholarAPI._min_interval - (now - SemanticScholarAPI._last_request_time)
        if wait > 0:
            await asyncio.sleep(wait)
        SemanticScholarAPI._last_request_time = asyncio.get_event_loop().time()

    async def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        await self._throttle()
        url = f"{self.BASE_URL}/paper/search?query={quote_plus(query)}&limit={limit}&fields={self.fields}"
        return await self._get(url, is_search=True)

    async def get_paper(self, paper_id: str) -> Optional[Dict[str, Any]]:
        await self._throttle()
        url = f"{self.BASE_URL}/paper/{paper_id}?fields={self.fields}"
        return await self._get(url)

    async def get_paper_by_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        await self._throttle()
        url = f"{self.BASE_URL}/paper/DOI:{doi}?fields={self.fields}"
        return await self._get(url)

    async def _get(self, url: str, is_search: bool = False, max_retries: int = 3) -> Any:
        session = APIClientManager.get_session()
        for attempt in range(max_retries):
            try:
                # Need to merge instance headers with session headers manually per request
                async with session.get(url, headers=self.headers, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        if is_search:
                            return data.get("data", [])
                        return data
                    elif response.status == 429:
                        if attempt == max_retries - 1:
                            raise APIError("Semantic Scholar rate limited.", 429)
                        await asyncio.sleep(2 ** attempt)
                    elif response.status == 404:
                        return None if not is_search else []
                    else:
                        if attempt == max_retries - 1:
                            raise APIError(f"HTTP Error {response.status}", response.status)
                        await asyncio.sleep(2 ** attempt)
            except asyncio.TimeoutError:
                if attempt == max_retries - 1:
                    raise APIError("Timeout connecting to Semantic Scholar")
                await asyncio.sleep(2 ** attempt)

class ArXivAPI:
    BASE_URL = "http://export.arxiv.org/api/query"

    async def get_paper(self, arxiv_id: str) -> Optional[Dict[str, Any]]:
        url = f"{self.BASE_URL}?id_list={arxiv_id}"
        session = APIClientManager.get_session()
        try:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    text = await response.text()
                    return self._parse_xml(text)
                return None
        except Exception as e:
            raise APIError(f"ArXiv Error: {str(e)}")

    def _parse_xml(self, xml_string: str) -> Optional[Dict[str, Any]]:
        try:
            root = ET.fromstring(xml_string)
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            entry = root.find('atom:entry', ns)
            if entry is None:
                return None

            title = entry.find('atom:title', ns).text.strip().replace('\n', ' ')
            summary = entry.find('atom:summary', ns).text.strip().replace('\n', ' ')
            published = entry.find('atom:published', ns).text
            year = int(published[:4]) if published else None
            
            authors = []
            for author in entry.findall('atom:author', ns):
                name = author.find('atom:name', ns).text
                if name:
                    authors.append(name)
            
            pdf_link = None
            for link in entry.findall('atom:link', ns):
                if link.get('type') == 'application/pdf':
                    pdf_link = link.get('href')

            return {
                "title": title,
                "authors": authors,
                "year": year,
                "abstract": summary,
                "pdf_url": pdf_link
            }
        except ET.ParseError:
            return None

class OpenAlexAPI:
    """
    OpenAlex — free, no auth, 200M+ works.
    https://docs.openalex.org/api-entities/works/search-works
    """
    BASE_URL = "https://api.openalex.org"
    _last_request_time: float = 0.0
    _min_interval: float = 0.12  # generous – OpenAlex allows 10 req/sec

    async def _throttle(self):
        now = asyncio.get_event_loop().time()
        wait = OpenAlexAPI._min_interval - (now - OpenAlexAPI._last_request_time)
        if wait > 0:
            await asyncio.sleep(wait)
        OpenAlexAPI._last_request_time = asyncio.get_event_loop().time()

    @staticmethod
    def _parse_work(work: Dict) -> Dict[str, Any]:
        authors = []
        for auth in work.get("authorships", []):
            name = auth.get("author", {}).get("display_name", "")
            if name:
                authors.append(name)
        pub_year = work.get("publication_year")
        title = work.get("title", "") or ""
        abstract = work.get("abstract_inverted_index")
        # Reconstruct abstract from inverted index if present
        if abstract:
            try:
                words = sorted(
                    [(pos, word) for word, positions in abstract.items() for pos in positions]
                )
                abstract = " ".join(w for _, w in words[:120])
            except Exception:
                abstract = ""
        # Open access PDF URL
        oa_url = work.get("open_access", {}).get("oa_url") or ""
        # arXiv ID from ids dict
        arxiv_id = work.get("ids", {}).get("arxiv", "")
        if arxiv_id and not oa_url:
            # Build arXiv PDF link directly
            arxiv_clean = arxiv_id.replace("https://arxiv.org/abs/", "").strip()
            oa_url = f"https://arxiv.org/pdf/{arxiv_clean}"

        return {
            "title": title,
            "authors": authors,
            "year": pub_year,
            "abstract": abstract or "",
            "paperId": work.get("id", ""),
            "openAccessPdf": {"url": oa_url} if oa_url else None,
            "externalIds": {"ArXiv": arxiv_id} if arxiv_id else {},
        }

    async def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        await self._throttle()
        url = (
            f"{self.BASE_URL}/works?search={quote_plus(query)}"
            f"&per-page={limit}"
            f"&select=id,title,authorships,publication_year,abstract_inverted_index,open_access,ids"
            f"&mailto=resify@example.com"
        )
        session = APIClientManager.get_session()
        try:
            async with session.get(url, timeout=12) as response:
                if response.status == 200:
                    data = await response.json()
                    return [self._parse_work(w) for w in data.get("results", [])]
                return []
        except Exception:
            return []

    async def search_by_title(self, title: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Exact title filter — more precise than keyword search."""
        await self._throttle()
        url = (
            f"{self.BASE_URL}/works?filter=title.search:{quote_plus(title)}"
            f"&per-page={limit}"
            f"&select=id,title,authorships,publication_year,abstract_inverted_index,open_access,ids"
            f"&mailto=resify@example.com"
        )
        session = APIClientManager.get_session()
        try:
            async with session.get(url, timeout=12) as response:
                if response.status == 200:
                    data = await response.json()
                    return [self._parse_work(w) for w in data.get("results", [])]
                return []
        except Exception:
            return []


class CrossRefAPI:
    BASE_URL = "https://api.crossref.org/works"

    @staticmethod
    def _parse_work(msg: Dict) -> Dict[str, Any]:
        authors = []
        for author in msg.get("author", []):
            family = author.get("family", "")
            given = author.get("given", "")
            name = f"{given} {family}".strip()
            if name:
                authors.append(name)

        title = msg.get("title", [""])[0] if msg.get("title") else ""
        published = msg.get("published", msg.get("published-print", msg.get("issued", {})))
        date_parts = published.get("date-parts", [[]])[0] if published else []
        year = date_parts[0] if date_parts else None

        return {
            "title": title,
            "authors": authors,
            "year": year,
            "abstract": msg.get("abstract", ""),
        }

    async def get_paper_by_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        url = f"{self.BASE_URL}/{quote_plus(doi)}"
        session = APIClientManager.get_session()
        try:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._parse_work(data.get("message", {}))
                return None
        except Exception as e:
            raise APIError(f"CrossRef Error: {str(e)}")

    async def search(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Search CrossRef by title/author query."""
        url = f"{self.BASE_URL}?query={quote_plus(query)}&rows={limit}&select=title,author,published,issued,published-print,abstract,DOI"
        session = APIClientManager.get_session()
        try:
            async with session.get(url, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    items = data.get("message", {}).get("items", [])
                    return [self._parse_work(item) for item in items]
                return []
        except Exception:
            return []


class DblpAPI:
    """
    DBLP Computer Science Bibliography — free, no auth required.
    Outstanding coverage of NLP/CL venues: ACL, EMNLP, NAACL, EACL, COLING,
    *SEM, TACL, CoNLL, and many more. ACL papers have open-access PDFs we
    can link directly.
    https://dblp.org/faq/How+can+I+use+the+dblp+search+API.html
    """
    SEARCH_URL = "https://dblp.org/search/publ/api"
    _last_request_time: float = 0.0
    _min_interval: float = 0.5  # polite rate limiting

    async def _throttle(self):
        now = asyncio.get_event_loop().time()
        wait = DblpAPI._min_interval - (now - DblpAPI._last_request_time)
        if wait > 0:
            await asyncio.sleep(wait)
        DblpAPI._last_request_time = asyncio.get_event_loop().time()

    async def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        await self._throttle()
        session = APIClientManager.get_session()
        params = {"q": query, "format": "json", "h": str(limit)}
        try:
            async with session.get(self.SEARCH_URL, params=params, timeout=12) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json(content_type=None)
                hits = data.get("result", {}).get("hits", {}).get("hit", [])
                if not hits:
                    return []
                if isinstance(hits, dict):
                    hits = [hits]
                papers = [self._parse_hit(h) for h in hits]
                papers = [p for p in papers if p]

                # Enrich ACL papers with abstract (cheap — one page fetch per paper)
                acl_papers = [p for p in papers if p.get("externalIds", {}).get("ACL")]
                if acl_papers:
                    abstracts = await asyncio.gather(
                        *[self._fetch_acl_abstract(p["externalIds"]["ACL"]) for p in acl_papers],
                        return_exceptions=True,
                    )
                    for paper, abstract in zip(acl_papers, abstracts):
                        if isinstance(abstract, str) and abstract:
                            paper["abstract"] = abstract

                return papers
        except Exception:
            return []

    @staticmethod
    def _parse_hit(hit: Dict) -> Optional[Dict[str, Any]]:
        info = hit.get("info", {})
        title = html_module.unescape(info.get("title", "") or "").rstrip(".")
        if not title:
            return None

        year = info.get("year")
        try:
            year = int(year) if year else None
        except (ValueError, TypeError):
            year = None

        # Authors: DBLP returns a dict for single author, list for multiple
        raw_authors = info.get("authors", {}).get("author", [])
        if isinstance(raw_authors, dict):
            raw_authors = [raw_authors]
        authors = [a.get("text", "") for a in raw_authors if isinstance(a, dict) and a.get("text")]

        # External URL — may be a list for papers with multiple versions
        ee = info.get("ee", "") or ""
        if isinstance(ee, list):
            ee = next((u for u in ee if "aclanthology" in u or "10.18653" in u), ee[0] if ee else "")

        # Extract ACL Anthology ID from DOI (10.18653/v1/{acl_id})
        acl_id = None
        oa_pdf_url = None
        acl_doi_match = re.search(r'10\.18653/v1/([^\s/"]+)', ee)
        if acl_doi_match:
            acl_id = acl_doi_match.group(1)
            oa_pdf_url = f"https://aclanthology.org/{acl_id}.pdf"

        return {
            "title": title,
            "authors": authors,
            "year": year,
            "abstract": "",
            "paperId": info.get("key", ""),
            "openAccessPdf": {"url": oa_pdf_url} if oa_pdf_url else None,
            "externalIds": {"ACL": acl_id} if acl_id else {},
            "tldr": None,
            "_source": "dblp",
            "_dblp_venue": info.get("venue", ""),
        }

    async def _fetch_acl_abstract(self, acl_id: str) -> str:
        """Fetch abstract by scraping the ACL Anthology paper page.
        The abstract is embedded in a JS object: abstract:"<text>"
        """
        url = f"https://aclanthology.org/{acl_id}/"
        session = APIClientManager.get_session()
        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return ""
                text = await resp.text()
                # The page embeds: abstract:"<text with escaped quotes>"
                m = re.search(r'abstract:"((?:[^"\\]|\\.)*)"', text)
                if m:
                    return m.group(1).replace('\\"', '"').replace("\\n", " ").strip()
                return ""
        except Exception:
            return ""
