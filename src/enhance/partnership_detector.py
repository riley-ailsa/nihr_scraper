"""
Detect partnership grants and extract partner information.
"""

import re
from typing import Optional, Dict, List
from bs4 import BeautifulSoup


class PartnershipDetector:
    """Detect and extract partnership information from grants."""

    # Patterns that indicate a partnership
    PARTNERSHIP_INDICATORS = [
        r'partnership',
        r'collaboration',
        r'joint',
        r'consortium',
        r'co-fund',
        r'match fund',
        r'partner organisation',
        r'lead organisation'
    ]

    # Known partner organizations
    KNOWN_PARTNERS = {
        'mrc': {
            'name': 'Medical Research Council',
            'domain': 'mrc.ukri.org',
            'url_pattern': r'mrc\.ukri\.org'
        },
        'wellcome': {
            'name': 'Wellcome Trust',
            'domain': 'wellcome.org',
            'url_pattern': r'wellcome\.org'
        },
        'cruk': {
            'name': 'Cancer Research UK',
            'domain': 'cancerresearchuk.org',
            'url_pattern': r'cancerresearchuk\.org'
        },
        'bhf': {
            'name': 'British Heart Foundation',
            'domain': 'bhf.org.uk',
            'url_pattern': r'bhf\.org\.uk'
        },
        'epsrc': {
            'name': 'EPSRC',
            'domain': 'epsrc.ukri.org',
            'url_pattern': r'epsrc\.ukri\.org'
        }
    }

    def detect(self, title: str, html: str, resources: List[Dict]) -> Optional[Dict]:
        """
        Detect if grant is a partnership and extract partner info.

        Returns dict with:
            - is_partnership: bool
            - confidence: float
            - partner_name: str
            - partner_url: str (if found)
            - indicators: List of matched patterns
        """
        soup = BeautifulSoup(html, 'html.parser')
        text = soup.get_text().lower()
        title_lower = title.lower()

        # Check for partnership indicators
        indicators = []
        for pattern in self.PARTNERSHIP_INDICATORS:
            if re.search(pattern, title_lower) or re.search(pattern, text[:2000]):
                indicators.append(pattern)

        if not indicators:
            return None

        # Look for partner organization
        partner_info = self._find_partner_org(soup, resources)

        if partner_info:
            return {
                'is_partnership': True,
                'confidence': 0.9,
                'partner_name': partner_info['name'],
                'partner_url': partner_info.get('url'),
                'indicators': indicators
            }

        # Partnership likely but partner not identified
        return {
            'is_partnership': True,
            'confidence': 0.6,
            'partner_name': None,
            'partner_url': None,
            'indicators': indicators
        }

    def _find_partner_org(self, soup: BeautifulSoup,
                         resources: List[Dict]) -> Optional[Dict]:
        """Find partner organization from links and text."""

        # Check resources for partner links
        for resource in resources:
            url = resource.get('url', '')
            for partner_key, partner_info in self.KNOWN_PARTNERS.items():
                if re.search(partner_info['url_pattern'], url):
                    return {
                        'name': partner_info['name'],
                        'url': url
                    }

        # Check all links in HTML
        for link in soup.find_all('a', href=True):
            href = link['href']
            for partner_key, partner_info in self.KNOWN_PARTNERS.items():
                if re.search(partner_info['url_pattern'], href):
                    return {
                        'name': partner_info['name'],
                        'url': href
                    }

        return None