"""
Orchestrate intelligent link following with depth control.
"""

from typing import List, Dict, Any, Optional
from urllib.parse import urlparse, urljoin
from src.core.domain_models import IndexableDocument
from src.ingest.resource_fetcher import ResourceFetcher
from src.enhance.link_classifier import LinkClassifier
from src.enhance.content_extractor import ContentExtractor
from src.enhance.relevance_scorer import RelevanceScorer
import hashlib
import logging

logger = logging.getLogger(__name__)


class LinkFollower:
    """Follow relevant links from grant pages."""

    def __init__(self, fetcher: ResourceFetcher, max_links: int = 10):
        self.fetcher = fetcher
        self.classifier = LinkClassifier()
        self.extractor = ContentExtractor()
        self.scorer = RelevanceScorer()
        self.max_links = max_links

    def follow_links(self, grant_id: str, resources: List[Dict],
                    source_url: str) -> List[IndexableDocument]:
        """
        Follow relevant webpage links from resources.

        Args:
            grant_id: Grant identifier
            resources: List of resource dicts from scraper
            source_url: Original grant page URL

        Returns:
            List of IndexableDocument objects from followed links
        """
        documents = []
        source_domain = urlparse(source_url).netloc

        # Get webpage resources
        webpage_resources = [
            r for r in resources
            if r.get('type') == 'webpage'
        ]

        # Classify and sort by relevance
        classified = []
        for resource in webpage_resources:
            url = resource.get('url')
            title = resource.get('title', '')

            if not url:
                continue

            # Make URL absolute
            url = urljoin(source_url, url)

            # Classify
            classification = self.classifier.classify(
                url, title, source_domain
            )

            if classification['should_follow']:
                classified.append({
                    'resource': resource,
                    'url': url,
                    'confidence': classification['confidence'],
                    'reason': classification['reason']
                })

        # Sort by confidence and take top N
        classified.sort(key=lambda x: x['confidence'], reverse=True)
        to_follow = classified[:self.max_links]

        logger.info(f"Following {len(to_follow)} links for grant {grant_id}")

        # Follow each link
        for item in to_follow:
            doc = self._follow_single_link(
                grant_id,
                item['url'],
                item['resource'].get('title', 'Linked Page')
            )

            if doc:
                documents.append(doc)
                logger.info(f"Added {len(doc.text)} chars from: {item['url']}")

        return documents

    def _follow_single_link(self, grant_id: str, url: str,
                           title: str) -> Optional[IndexableDocument]:
        """Follow a single link and create document if relevant."""

        # Fetch webpage
        html = self.fetcher.fetch_webpage(url)
        if not html:
            logger.warning(f"Failed to fetch webpage: {url}")
            return None

        # Extract content
        text = self.extractor.extract(html, url)
        if not text:
            logger.warning(f"Failed to extract content from: {url}")
            return None

        # Score relevance
        relevance = self.scorer.score(text, url)
        if not relevance['is_relevant']:
            logger.info(f"Content not relevant: {url} ({relevance['reason']})")
            return None

        # Create document
        doc_id = hashlib.sha256(f"{grant_id}:{url}".encode()).hexdigest()[:16]

        doc = IndexableDocument(
            id=f"{grant_id}_link_{doc_id}",
            grant_id=grant_id,
            doc_type="linked_page",
            text=text,
            source_url=url,
            section_name=title,
            citation_text=f"Linked page: {title}",
            scope="competition"
        )

        return doc