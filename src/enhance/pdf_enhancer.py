"""
Orchestrate PDF fetching and parsing for grant enhancement.
"""

from typing import List, Dict, Any
from src.core.domain_models import IndexableDocument
from src.ingest.resource_fetcher import ResourceFetcher
from src.ingest.pdf_parser import PDFParser
import logging
import hashlib

logger = logging.getLogger(__name__)


class PDFEnhancer:
    """Enhance grants by fetching and parsing linked PDFs."""

    def __init__(self, fetcher: ResourceFetcher):
        self.fetcher = fetcher
        self.parser = PDFParser(use_ocr=False)  # OCR too slow for bulk

    def enhance(self, grant_id: str, resources: List[Dict]) -> List[IndexableDocument]:
        """
        Fetch and parse all PDF resources for a grant.

        Args:
            grant_id: Grant identifier
            resources: List of resource dicts from scraper

        Returns:
            List of IndexableDocument objects from PDFs
        """
        documents = []
        pdf_resources = [r for r in resources if r.get('type') == 'pdf']

        logger.info(f"Processing {len(pdf_resources)} PDFs for grant {grant_id}")

        for resource in pdf_resources:
            url = resource.get('url')
            title = resource.get('title', 'PDF Document')

            if not url:
                continue

            # Fetch PDF
            pdf_bytes = self.fetcher.fetch_pdf(url)
            if not pdf_bytes:
                logger.warning(f"Failed to fetch PDF: {url}")
                continue

            # Parse PDF
            text = self.parser.extract_text(pdf_bytes)
            if not text:
                logger.warning(f"Failed to extract text from PDF: {url}")
                continue

            # Create document
            doc_id = hashlib.sha256(f"{grant_id}:{url}".encode()).hexdigest()[:16]

            doc = IndexableDocument(
                id=f"{grant_id}_pdf_{doc_id}",
                grant_id=grant_id,
                doc_type="pdf",
                text=text,
                source_url=url,
                section_name=title,
                citation_text=f"PDF: {title}",
                scope="competition"
            )

            documents.append(doc)
            logger.info(f"Extracted {len(text)} chars from PDF: {title}")

        return documents