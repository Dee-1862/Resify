import re
from typing import Any, Dict
from server.core.agent_base import BaseAgent
from server.utils.apis import SemanticScholarAPI, ArXivAPI, CrossRefAPI, APIError
from server.utils.pdf import PDFScraper

class FetcherAgent(BaseAgent):
    name = "fetcher"

    def __init__(self):
        super().__init__()
        self.arxiv_api = ArXivAPI()
        self.crossref_api = CrossRefAPI()
        self.semantic_scholar = SemanticScholarAPI()

    def _detect_input_type(self, input_str: str) -> str:
        if "arxiv.org" in input_str or re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", input_str):
            return "arxiv"
        elif input_str.startswith("10.") or "doi.org" in input_str:
            return "doi"
        elif input_str.endswith(".pdf"):
            return "pdf"
        elif input_str.startswith("http://") or input_str.startswith("https://"):
            return "url" # fallback generic URL, maybe text
        else:
            return "direct"

    def _extract_arxiv_id(self, input_str: str) -> str:
        match = re.search(r"(\d{4}\.\d{4,5}(v\d+)?)", input_str)
        return match.group(1) if match else input_str

    def _extract_doi(self, input_str: str) -> str:
        # 10.\d{4,9}/[-._;()/:A-Z0-9]+
        match = re.search(r"(10\.\d{4,9}/[-._;()/:a-zA-Z0-9]+)", input_str)
        return match.group(1) if match else input_str

    async def _run_logic(self, input_data: dict) -> tuple[Dict[str, Any], int]:
        input_str = input_data.get("input", "")
        if not input_str:
            raise ValueError("Input string is required")

        input_type = self._detect_input_type(input_str)
        
        data = {
            "text": None,
            "title": None,
            "authors": None,
            "year": None,
            "abstract": None,
            "source": input_type,
            "url": input_str if input_str.startswith("http") else None,
            "arxiv_id": None,
            "doi": None,
            "pdf_url": None
        }

        if input_type == "arxiv":
            arxiv_id = self._extract_arxiv_id(input_str)
            data["arxiv_id"] = arxiv_id
            try:
                paper_metadata = await self.arxiv_api.get_paper(arxiv_id)
                if not paper_metadata:
                    raise APIError("Paper not found on ArXiv", 404)
                
                # Merge metadata
                data.update(paper_metadata)
                data["doi"] = f"10.48550/arXiv.{arxiv_id}"
                
                # Fetch full text if pdf url exists
                if data["pdf_url"]:
                    data["text"] = await PDFScraper.extract_text_from_url(data["pdf_url"])
            except APIError as e:
                if e.status_code == 404:
                    raise Exception("FETCH_404: " + str(e))
                raise Exception("FETCH_FAILED: " + str(e))
                
        elif input_type == "doi":
            doi = self._extract_doi(input_str)
            data["doi"] = doi
            try:
                # Try CrossRef first, often more reliable for initial DOI lookup
                paper_metadata = await self.crossref_api.get_paper_by_doi(doi)
                if not paper_metadata:
                    raise APIError("Paper not found on CrossRef", 404)
                
                data.update(paper_metadata)
                
                # abstract from SemanticScholar if missing
                if not data["abstract"]:
                    ss_data = await self.semantic_scholar.get_paper_by_doi(doi)
                    if ss_data and ss_data.get("abstract"):
                        data["abstract"] = ss_data["abstract"]
                        
            except APIError as e:
                raise Exception("FETCH_FAILED: " + str(e))

        elif input_type == "pdf":
            try:
                data["text"] = await PDFScraper.extract_text_from_url(input_str)
            except Exception as e:
                raise Exception("PDF_PARSE_FAILED: " + str(e))

        elif input_type == "direct":
            data["text"] = input_str
            
        else:
            raise Exception("INVALID_URL: Could not determine input type")

        return data, 0
