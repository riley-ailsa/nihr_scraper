"""
Extract main content from HTML pages, removing navigation/footer.
"""

from bs4 import BeautifulSoup
import re
from typing import Optional


class ContentExtractor:
    """Extract main content from webpages."""

    # Elements that typically contain main content
    CONTENT_SELECTORS = [
        'main',
        'article',
        '[role="main"]',
        '#main-content',
        '#content',
        '.main-content',
        '.content',
        '.article-content',
        '.page-content'
    ]

    # Elements to remove (navigation, ads, etc.)
    REMOVE_SELECTORS = [
        'nav',
        'header',
        'footer',
        'aside',
        '.sidebar',
        '.navigation',
        '.menu',
        '.breadcrumb',
        '.social-share',
        '.related-links',
        '.advertisement',
        '#cookie-banner',
        '.newsletter-signup',
        'script',
        'style',
        'noscript'
    ]

    def extract(self, html: str, url: str = "") -> Optional[str]:
        """
        Extract main content from HTML.

        Returns extracted text or None if extraction fails.
        """
        soup = BeautifulSoup(html, 'html.parser')

        # Remove unwanted elements
        for selector in self.REMOVE_SELECTORS:
            for element in soup.select(selector):
                element.decompose()

        # Try to find main content container
        main_content = None
        for selector in self.CONTENT_SELECTORS:
            elements = soup.select(selector)
            if elements:
                main_content = elements[0]
                break

        # Fallback: use body
        if not main_content:
            main_content = soup.body or soup

        # Extract text
        text = self._extract_text_with_structure(main_content)

        # Clean up
        text = self._clean_text(text)

        # Validate minimum content
        if len(text) < 200:  # Too short to be useful
            return None

        return text

    def _extract_text_with_structure(self, element) -> str:
        """Extract text preserving some structure."""
        lines = []

        for elem in element.find_all(['h1', 'h2', 'h3', 'h4', 'p', 'li', 'td']):
            text = elem.get_text(strip=True)
            if text:
                # Add appropriate spacing for headers
                if elem.name.startswith('h'):
                    lines.append(f"\n{text}\n")
                else:
                    lines.append(text)

        return "\n".join(lines)

    def _clean_text(self, text: str) -> str:
        """Clean extracted text."""
        # Remove excessive whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text)

        # Remove common boilerplate
        boilerplate = [
            r'Cookie settings',
            r'Accept cookies',
            r'Skip to main content',
            r'JavaScript is disabled',
            r'Back to top'
        ]

        for pattern in boilerplate:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)

        return text.strip()