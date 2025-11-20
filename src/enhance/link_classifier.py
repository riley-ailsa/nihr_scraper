"""
Classify links as relevant or irrelevant for following.
"""

import re
from urllib.parse import urlparse
from typing import Dict, List, Any


class LinkClassifier:
    """Determine which links are worth following."""

    # High-value URL patterns (always follow)
    HIGH_VALUE_PATTERNS = [
        r'/guidance/',
        r'/eligibility',
        r'/how-to-apply',
        r'/application',
        r'/specification',
        r'/requirements',
        r'/faqs?',
        r'/resources',
        r'/documents',
        r'/forms?',
        r'/timeline',
        r'/key-dates'
    ]

    # Low-value URL patterns (never follow)
    LOW_VALUE_PATTERNS = [
        r'/news/',
        r'/events/',
        r'/contact',
        r'/about',
        r'/careers',
        r'/privacy',
        r'/terms',
        r'/cookie',
        r'/accessibility',
        r'/sitemap',
        r'\.pdf$',  # PDFs handled separately
        r'\.(jpg|jpeg|png|gif|svg)$',  # Images
        r'/login',
        r'/register',
        r'/search\?',
        r'#'  # Anchors
    ]

    # High-value link text patterns
    HIGH_VALUE_LINK_TEXT = [
        'guidance',
        'eligibility',
        'application',
        'specification',
        'requirements',
        'how to apply',
        'download',
        'form',
        'template',
        'criteria',
        'assessment',
        'evaluation'
    ]

    def classify(self, url: str, link_text: str = "",
                 source_domain: str = "") -> Dict[str, Any]:
        """
        Classify a link's relevance for following.

        Returns dict with:
            - should_follow: bool
            - confidence: float (0-1)
            - reason: str
        """
        # Parse URL
        parsed = urlparse(url)
        path = parsed.path.lower()

        # Check if same domain (prefer same-domain links)
        same_domain = source_domain and parsed.netloc == source_domain

        # Check high-value patterns
        for pattern in self.HIGH_VALUE_PATTERNS:
            if re.search(pattern, path, re.IGNORECASE):
                return {
                    'should_follow': True,
                    'confidence': 0.9,
                    'reason': f'High-value URL pattern: {pattern}'
                }

        # Check low-value patterns
        for pattern in self.LOW_VALUE_PATTERNS:
            if re.search(pattern, path, re.IGNORECASE):
                return {
                    'should_follow': False,
                    'confidence': 0.9,
                    'reason': f'Low-value URL pattern: {pattern}'
                }

        # Check link text
        link_text_lower = link_text.lower()
        for keyword in self.HIGH_VALUE_LINK_TEXT:
            if keyword in link_text_lower:
                return {
                    'should_follow': True,
                    'confidence': 0.7,
                    'reason': f'High-value link text: {keyword}'
                }

        # Default: follow if same domain, skip if external
        if same_domain:
            return {
                'should_follow': True,
                'confidence': 0.4,
                'reason': 'Same domain link'
            }
        else:
            return {
                'should_follow': False,
                'confidence': 0.6,
                'reason': 'External domain, no clear value indicators'
            }