"""
Tab-aware section parsing for NIHR funding pages.

This module adds methods to detect and extract content from tab-based navigation,
solving the embedding imbalance issue where NIHR grants have 50x fewer embeddings
than Innovate UK grants due to missing tab content.

PROBLEM: NIHR pages use JavaScript tabs (e.g., #tab-overview, #tab-applications)
         The current scraper only gets the first/default tab content.
         
SOLUTION: Detect tab navigation and explicitly extract content from each tab panel.

Usage:
    Add these methods to NihrFundingScraper class in src/ingest/nihr_funding.py
"""

from typing import List, Optional, Tuple
from bs4 import BeautifulSoup, Tag
import re
import logging

logger = logging.getLogger(__name__)


# Add this import to the NihrSection dataclass area
from dataclasses import dataclass

@dataclass
class NihrSection:
    """Parsed section from NIHR page."""
    name: str
    slug: str
    html: str
    text: str
    source_url: str


def _slugify(text: str) -> str:
    """Convert text to URL-safe slug."""
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


# ============================================================================
# NEW TAB-AWARE METHODS - Add these to NihrFundingScraper class
# ============================================================================

def _find_tab_navigation(self, soup: BeautifulSoup) -> List[Tuple[str, str]]:
    """
    Detect tab-based navigation in NIHR pages.
    
    NIHR pages often use tabs with structure like:
        <ul class="nav nav-tabs" or similar>
          <li><a href="#tab-overview">Overview</a></li>
          <li><a href="#tab-applications">Applications</a></li>
          <li><a href="#tab-eligibility">Eligibility</a></li>
        </ul>
    
    Returns:
        List of (tab_name, tab_id) tuples, e.g.:
        [("Overview", "tab-overview"), ("Applications", "tab-applications")]
    """
    tabs = []
    
    # Strategy 1: Look for <ul> with class containing "tab" or "nav"
    tab_containers = soup.find_all("ul", class_=re.compile(r"(tab|nav)", re.I))
    
    for container in tab_containers:
        # Find all links that start with #tab- or just #
        for link in container.find_all("a", href=True):
            href = link.get("href", "").strip()
            
            # Must be a fragment link
            if not href.startswith("#"):
                continue
            
            # Extract tab ID (remove #)
            tab_id = href[1:]
            
            # Get tab name from link text
            tab_name = link.get_text(strip=True)
            
            # Skip empty names or IDs
            if not tab_name or not tab_id:
                continue
            
            tabs.append((tab_name, tab_id))
            logger.debug(f"Found tab: {tab_name} -> #{tab_id}")
    
    # Strategy 2: Look for links with href="#tab-*" pattern anywhere in page
    if not tabs:
        for link in soup.find_all("a", href=re.compile(r"^#tab-")):
            href = link.get("href", "").strip()
            tab_id = href[1:]
            tab_name = link.get_text(strip=True)
            
            if tab_name and tab_id:
                tabs.append((tab_name, tab_id))
                logger.debug(f"Found tab (pattern match): {tab_name} -> #{tab_id}")
    
    # Deduplicate by tab_id while preserving order
    seen_ids = set()
    unique_tabs = []
    for name, tid in tabs:
        if tid not in seen_ids:
            seen_ids.add(tid)
            unique_tabs.append((name, tid))
    
    if unique_tabs:
        logger.info(f"Detected {len(unique_tabs)} tabs on page")
    
    return unique_tabs


def _extract_tab_content(self, soup: BeautifulSoup, tab_id: str) -> Optional[dict]:
    """
    Extract HTML and text content from a specific tab panel.
    
    Tab content is typically in a <div> with id="tab-overview" or similar.
    
    Structure:
        <div id="tab-overview" class="tab-pane" ...>
          <h2>Some heading</h2>
          <p>Content here...</p>
        </div>
    
    Args:
        soup: Parsed HTML
        tab_id: Tab panel ID (without #), e.g., "tab-overview"
    
    Returns:
        dict with 'html' and 'text' keys, or None if not found
    """
    # Find element with this ID
    tab_panel = soup.find(id=tab_id)
    
    if not tab_panel:
        logger.warning(f"Tab panel not found: #{tab_id}")
        return None
    
    # Extract HTML (everything inside the tab panel)
    html = str(tab_panel)
    
    # Extract text (cleaned)
    # Use BeautifulSoup's stripped_strings to get clean text
    text_parts = []
    for element in tab_panel.stripped_strings:
        text_parts.append(element)
    
    text = " ".join(text_parts)
    
    # Log content size
    logger.debug(f"Tab #{tab_id}: {len(html)} chars HTML, {len(text)} chars text")
    
    return {
        "html": html,
        "text": text
    }


def _parse_sections_with_tabs(self, soup: BeautifulSoup, page_url: str) -> List:
    """
    NEW MAIN METHOD: Parse sections with tab awareness.
    
    This replaces _parse_sections_from_headings as the primary parser.
    
    Strategy:
    1. Detect if page has tab navigation
    2. If yes: Extract content from each tab panel
    3. If no: Fall back to h2 heading-based parsing
    
    Args:
        soup: Parsed HTML
        page_url: Base URL for constructing section URLs
    
    Returns:
        List of NihrSection objects
    """
    # Try to detect tabs
    tabs = self._find_tab_navigation(soup)
    
    if tabs:
        logger.info(f"Using tab-based section extraction ({len(tabs)} tabs)")
        return self._parse_sections_from_tabs(soup, page_url, tabs)
    else:
        logger.info("No tabs detected, using h2-based section extraction")
        return self._parse_sections_from_headings(soup, page_url)


def _parse_sections_from_tabs(
    self, 
    soup: BeautifulSoup, 
    page_url: str, 
    tabs: List[Tuple[str, str]]
) -> List:
    """
    Extract sections by walking through each tab panel.
    
    Args:
        soup: Parsed HTML
        page_url: Base URL
        tabs: List of (tab_name, tab_id) tuples
    
    Returns:
        List of NihrSection objects
    """
    sections = []
    
    for tab_name, tab_id in tabs:
        # Extract content from this tab
        content = self._extract_tab_content(soup, tab_id)
        
        if not content:
            logger.warning(f"Skipping tab {tab_name} (no content found)")
            continue
        
        # Create section
        slug = _slugify(tab_name)
        source_url = f"{page_url}#{tab_id}"
        
        section = NihrSection(
            name=tab_name,
            slug=slug,
            html=content["html"],
            text=content["text"],
            source_url=source_url
        )
        
        sections.append(section)
        logger.debug(f"Extracted tab section: {tab_name} ({len(content['text'])} chars)")
    
    return sections


# ============================================================================
# UPDATED _parse_sections_from_nav - Replace existing method
# ============================================================================

def _parse_sections_from_nav(self, base_url: str, soup: BeautifulSoup) -> List[dict]:
    """
    Main entry point for section parsing (called by _scrape_funding_page).
    
    NOW TAB-AWARE: Detects and handles tabbed content.
    
    Returns dict format for backward compatibility with normalizer.
    """
    # Use new tab-aware parser
    sections = self._parse_sections_with_tabs(soup, base_url)
    
    # Convert NihrSection objects to dicts for backward compatibility
    return [
        {
            "title": s.name,
            "url": s.source_url,
            "text": s.text,
            "html": s.html,
            "slug": s.slug
        }
        for s in sections
    ]


# ============================================================================
# INTEGRATION INSTRUCTIONS
# ============================================================================

"""
STEP 1: Add these methods to NihrFundingScraper class in src/ingest/nihr_funding.py

STEP 2: Replace the existing _parse_sections_from_nav method with the new version above

STEP 3: Test with a known tabbed NIHR URL:
    
    from src.ingest.nihr_funding import NihrFundingScraper
    
    scraper = NihrFundingScraper()
    url = "https://www.nihr.ac.uk/funding/nihr-james-lind-alliance-priority-setting-partnerships-rolling-funding-opportunity-hsdr-programme/2025331"
    
    opp = scraper.scrape(url)
    
    print(f"Sections found: {len(opp.sections)}")
    for section in opp.sections:
        print(f"  - {section['title']:30s} ({len(section['text']):6d} chars)")
    
    # You should now see multiple sections with substantial content!

STEP 4: After testing one URL, run a full re-scrape:
    
    # Delete old NIHR data
    python3 scripts/reset_nihr_data.py --db grants.db --confirm
    
    # Re-scrape with new tab-aware parser
    python3 -m src.scripts.backfill_nihr_production --input nihr_links.txt

EXPECTED RESULTS:
- BEFORE: ~18 embeddings per grant
- AFTER: ~150-200 embeddings per grant (closer to IUK's 900, but NIHR pages are genuinely shorter)
- Each grant should have 4-8 sections instead of 1-2

WHY THIS WORKS:
- Innovate UK scraper already uses navigation-based extraction (finds sections by nav links)
- NIHR scraper was only walking visible h2 tags (missing hidden tab content)
- This implementation mirrors IUK's approach: find navigation → extract each section explicitly
- Falls back gracefully for non-tabbed pages (older NIHR formats)
"""
