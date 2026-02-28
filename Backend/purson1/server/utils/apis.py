import asyncio
import aiohttp
import xml.etree.ElementTree as ET
from typing import Optional, List, Dict, Any
from urllib.parse import quote_plus

class APIError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code

class SemanticScholarAPI:
    BASE_URL = "https://api.semanticscholar.org/graph/v1"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.headers = {"x-api-key": api_key} if api_key else {}
        self.fields = "title,authors,year,abstract,paperId,externalIds,citationCount"

    async def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        url = f"{self.BASE_URL}/paper/search?query={quote_plus(query)}&limit={limit}&fields={self.fields}"
        return await self._get(url, is_search=True)

    async def get_paper(self, paper_id: str) -> Optional[Dict[str, Any]]:
        url = f"{self.BASE_URL}/paper/{paper_id}?fields={self.fields}"
        return await self._get(url)

    async def get_paper_by_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        url = f"{self.BASE_URL}/paper/DOI:{doi}?fields={self.fields}"
        return await self._get(url)

    async def _get(self, url: str, is_search: bool = False, max_retries: int = 3) -> Any:
        async with aiohttp.ClientSession(headers=self.headers) as session:
            for attempt in range(max_retries):
                try:
                    async with session.get(url, timeout=10) as response:
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
        async with aiohttp.ClientSession() as session:
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

class CrossRefAPI:
    BASE_URL = "https://api.crossref.org/works"

    async def get_paper_by_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        url = f"{self.BASE_URL}/{quote_plus(doi)}"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        msg = data.get("message", {})
                        
                        authors = []
                        for author in msg.get("author", []):
                            family = author.get("family", "")
                            given = author.get("given", "")
                            name = f"{given} {family}".strip()
                            if name:
                                authors.append(name)
                                
                        title = msg.get("title", [""])[0] if msg.get("title") else ""
                        published = msg.get("published", msg.get("published-print", msg.get("issued", {})))
                        date_parts = published.get("date-parts", [[]])[0]
                        year = date_parts[0] if date_parts else None

                        return {
                            "title": title,
                            "authors": authors,
                            "year": year,
                            "abstract": msg.get("abstract", "") # Abstract isn't always available here
                        }
                    return None
            except Exception as e:
                raise APIError(f"CrossRef Error: {str(e)}")

    async def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        url = f"{self.BASE_URL}?query={quote_plus(query)}&rows={limit}"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        items = data.get("message", {}).get("items", [])
                        results = []
                        for msg in items:
                            authors = []
                            for author in msg.get("author", []):
                                family = author.get("family", "")
                                given = author.get("given", "")
                                name = f"{given} {family}".strip()
                                if name:
                                    authors.append(name)

                            title = msg.get("title", [""])[0] if msg.get("title") else ""
                            published = msg.get("published", msg.get("published-print", msg.get("issued", {})))
                            date_parts = published.get("date-parts", [[]])[0]
                            year = date_parts[0] if date_parts else None

                            results.append({
                                "title": title,
                                "authors": authors,
                                "year": year,
                                "abstract": msg.get("abstract", ""),
                                "paperId": msg.get("DOI", "")
                            })
                        return results
                    return []
            except Exception as e:
                logging.error(f"CrossRef Search Error: {e}")
                return []
