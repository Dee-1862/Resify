import re
import time
from server.agents.base import BaseAgent, AgentResult, PipelineContext, PipelineStage, registry
from server.utils.apis import SemanticScholarAPI, ArXivAPI, CrossRefAPI, APIError
from server.utils.pdf import PDFScraper

class FetcherAgent(BaseAgent):
    name = "fetcher"
    stage = PipelineStage.FETCHING
    description = "Fetch and extract paper text"
    
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
        match = re.search(r"(10\.\d{4,9}/[-._;()/:a-zA-Z0-9]+)", input_str)
        return match.group(1) if match else input_str

    async def process(self, ctx: PipelineContext) -> AgentResult:
        # We can try paper_url, paper_doi, or paper_text
        input_str = ctx.paper_url or ctx.paper_doi or ctx.paper_text
        if not input_str:
            return AgentResult(agent_name=self.name, status="error", error="No input provided")
            
        input_type = self._detect_input_type(input_str)
        
        data = {
            "text": None,
            "title": "Document Title", # Fallback title
            "authors": [],
            "year": None,
            "abstract": None,
            "source": input_type,
            "url": ctx.paper_url,
            "arxiv_id": None,
            "doi": ctx.paper_doi,
            "pdf_url": None
        }

        if input_type == "arxiv":
            arxiv_id = self._extract_arxiv_id(input_str)
            data["arxiv_id"] = arxiv_id
            try:
                paper_metadata = await self.arxiv_api.get_paper(arxiv_id)
                if not paper_metadata:
                    raise Exception("FETCH_404: Paper not found on ArXiv")
                
                data.update(paper_metadata)
                data["doi"] = f"10.48550/arXiv.{arxiv_id}"
                
                if data["pdf_url"]:
                    data["text"] = await PDFScraper.extract_text_from_url(data["pdf_url"])
            except APIError as e:
                raise Exception("FETCH_FAILED: " + str(e))
                
        elif input_type == "doi":
            doi = self._extract_doi(input_str)
            data["doi"] = doi
            try:
                paper_metadata = await self.crossref_api.get_paper_by_doi(doi)
                if not paper_metadata:
                    raise Exception("FETCH_404: Paper not found on CrossRef")
                
                data.update(paper_metadata)
                
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

        elif input_type == "direct" or input_type == "url":
            # If it's pure text, just pass it through
            data["text"] = input_str
            data["source"] = "direct"
        
        return AgentResult(
            agent_name=self.name,
            status="success",
            data=data,
            tokens_used=0,
        )

registry.register(FetcherAgent())
