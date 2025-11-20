"""
Handle partnership grants by fetching partner requirements.
"""

from typing import List, Optional, Dict, Any
from src.core.domain_models import IndexableDocument
from src.ingest.resource_fetcher import ResourceFetcher
from src.enhance.partnership_detector import PartnershipDetector
from src.enhance.content_extractor import ContentExtractor
import hashlib
import logging

logger = logging.getLogger(__name__)


class PartnershipHandler:
    """Handle partnership grants by fetching partner pages."""

    def __init__(self, fetcher: ResourceFetcher):
        self.fetcher = fetcher
        self.detector = PartnershipDetector()
        self.extractor = ContentExtractor()

    def enhance_partnership_grant(
        self,
        grant_id: str,
        title: str,
        html: str,
        resources: List[Dict]
    ) -> List[IndexableDocument]:
        """
        Enhance partnership grants with partner information.

        Returns list of documents from partner pages.
        """
        # Detect partnership
        partnership = self.detector.detect(title, html, resources)

        if not partnership or not partnership['is_partnership']:
            return []

        logger.info(f"Partnership detected for grant {grant_id}: {partnership}")

        documents = []

        # If partner URL found, fetch it
        if partnership.get('partner_url'):
            doc = self._fetch_partner_page(
                grant_id,
                partnership['partner_url'],
                partnership.get('partner_name', 'Partner Organization')
            )
            if doc:
                documents.append(doc)

        # Create a summary document about the partnership
        if partnership.get('partner_name'):
            summary_doc = self._create_partnership_summary(
                grant_id,
                partnership
            )
            documents.append(summary_doc)

        return documents

    def _fetch_partner_page(self, grant_id: str, url: str,
                           partner_name: str) -> Optional[IndexableDocument]:
        """Fetch and process partner organization page."""

        html = self.fetcher.fetch_webpage(url)
        if not html:
            logger.warning(f"Failed to fetch partner page: {url}")
            return None

        text = self.extractor.extract(html, url)
        if not text:
            logger.warning(f"Failed to extract partner content: {url}")
            return None

        # Create document
        doc_id = hashlib.sha256(f"{grant_id}:partner:{url}".encode()).hexdigest()[:16]

        doc = IndexableDocument(
            id=f"{grant_id}_partner_{doc_id}",
            grant_id=grant_id,
            doc_type="partner_page",
            text=text,
            source_url=url,
            section_name=f"{partner_name} Requirements",
            citation_text=f"Partner: {partner_name}",
            scope="competition"
        )

        logger.info(f"Fetched partner page: {partner_name} ({len(text)} chars)")
        return doc

    def _create_partnership_summary(self, grant_id: str,
                                   partnership: Dict) -> IndexableDocument:
        """Create a summary document about the partnership."""

        summary_text = f"""
Partnership Grant Information

This is a partnership grant with {partnership['partner_name']}.

Key Information:
- Partner Organization: {partnership['partner_name']}
- Partnership Type: Collaborative funding opportunity
- Confidence: {partnership['confidence']}

Important Note:
This grant involves collaboration between NIHR and {partnership['partner_name']}.
Applicants should review requirements from both organizations.
There may be additional eligibility criteria or application processes
specific to the partner organization.

Partnership Indicators Found:
{', '.join(partnership['indicators'])}
"""

        doc_id = hashlib.sha256(f"{grant_id}:partnership:summary".encode()).hexdigest()[:16]

        return IndexableDocument(
            id=f"{grant_id}_partnership_{doc_id}",
            grant_id=grant_id,
            doc_type="partnership_summary",
            text=summary_text.strip(),
            source_url="",
            section_name="Partnership Information",
            citation_text="Partnership Summary",
            scope="competition"
        )