"""
Fetch resources (PDFs, webpages) with caching and rate limiting.
"""

import requests
import hashlib
import time
from typing import Optional, Dict, Any
from datetime import datetime
from urllib.parse import urlparse
import logging

logger = logging.getLogger(__name__)


class ResourceFetcher:
    """Fetch external resources with caching and rate limiting."""

    def __init__(self, cache: Optional['FetchCache'] = None):
        self.cache = cache
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
        self.last_request_time = {}  # Domain-based rate limiting

    def fetch_pdf(self, url: str) -> Optional[bytes]:
        """
        Fetch PDF from URL.

        Returns PDF bytes or None if fetch fails.
        """
        # Check cache first
        if self.cache:
            cached = self.cache.get(url)
            if cached and cached.get('content_type') == 'application/pdf':
                logger.debug(f"PDF cache hit: {url}")
                return cached['content']

        # Rate limit
        self._rate_limit(url)

        try:
            response = self.session.get(
                url,
                timeout=30,
                stream=True
            )
            response.raise_for_status()

            # Verify it's actually a PDF
            content_type = response.headers.get('content-type', '')
            if 'pdf' not in content_type.lower():
                logger.warning(f"Not a PDF: {url} ({content_type})")
                return None

            # Read content (max 50MB)
            max_size = 50 * 1024 * 1024
            content = b''
            for chunk in response.iter_content(chunk_size=1024*1024):
                content += chunk
                if len(content) > max_size:
                    logger.warning(f"PDF too large: {url}")
                    return None

            # Cache the result
            if self.cache:
                self.cache.set(url, content, 'application/pdf')

            logger.info(f"Fetched PDF: {url} ({len(content)} bytes)")
            return content

        except Exception as e:
            logger.error(f"Failed to fetch PDF {url}: {e}")
            return None

    def fetch_webpage(self, url: str) -> Optional[str]:
        """
        Fetch webpage HTML.

        Returns HTML string or None if fetch fails.
        """
        # Check cache
        if self.cache:
            cached = self.cache.get(url)
            if cached and cached.get('content_type') == 'text/html':
                logger.debug(f"Webpage cache hit: {url}")
                return cached['content'].decode('utf-8')

        # Rate limit
        self._rate_limit(url)

        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()

            html = response.text

            # Cache the result
            if self.cache:
                self.cache.set(url, html.encode('utf-8'), 'text/html')

            logger.info(f"Fetched webpage: {url}")
            return html

        except Exception as e:
            logger.error(f"Failed to fetch webpage {url}: {e}")
            return None

    def _rate_limit(self, url: str):
        """Apply rate limiting per domain."""
        domain = urlparse(url).netloc

        if domain in self.last_request_time:
            elapsed = time.time() - self.last_request_time[domain]
            if elapsed < 1.0:  # 1 second per domain
                time.sleep(1.0 - elapsed)

        self.last_request_time[domain] = time.time()