"""
Scraper for NIHR (National Institute for Health and Care Research) funding opportunities.

This module handles:
1. Page type detection (FUNDING, NODE, UNKNOWN)
2. Parsing multiple page formats (standard pages, umbrella/node pages)
3. Extracting metadata, sections, resources, and sub-opportunities
4. Robust fallback strategies for edge cases
"""

import re
import logging
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse, urljoin
from dataclasses import dataclass, field

import requests
import dateutil.parser
from bs4 import BeautifulSoup, Tag

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}


def _slugify(text: str) -> str:
    """Convert text to URL-safe slug."""
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


class NihrPageType(str, Enum):
    """
    Types of NIHR funding pages we can encounter.

    FUNDING: Standard funding opportunity page (/funding/programme/opportunity)
    NODE: Drupal node page, often umbrella/programme pages (/node/12345)
    UNKNOWN: Unrecognized format (will attempt FUNDING scrape with warning)
    """
    FUNDING = "funding"
    NODE = "node"
    UNKNOWN = "unknown"


@dataclass
class NihrSection:
    """Parsed section from NIHR page."""
    name: str
    slug: str
    html: str
    text: str
    source_url: str


@dataclass
class NihrResource:
    """Resource link (PDF, webpage, video, etc.)."""
    title: str
    url: str
    kind: str   # "webpage", "pdf", "video", "other"
    scope: str  # always "competition"


@dataclass
class NihrFundingOpportunity:
    """
    Structured data for a NIHR funding opportunity.

    This is the raw scraped data before normalization to canonical Grant format.
    Follows similar pattern to ScrapedCompetition from Innovate UK.
    """
    source: str  # Always "nihr"
    url: str  # Canonical URL
    opportunity_id: str  # Unique identifier (nihr_xxx)

    # Core fields
    programme: Optional[str] = None  # Programme label (e.g., "Research for Patient Benefit")
    title: Optional[str] = None
    reference_id: Optional[str] = None  # Official NIHR reference (e.g., "22/173")
    description: Optional[str] = None  # Overview/description text

    # Status and type
    opportunity_status: Optional[str] = None  # "Open", "Closed", etc.
    opportunity_type: Optional[str] = None  # "Research grant", "Programme", etc.

    # Dates
    opening_date: Optional[datetime] = None
    closing_date: Optional[datetime] = None

    # Funding
    funding_text: Optional[str] = None  # Raw funding string

    # Content
    sections: List[Dict[str, Any]] = field(default_factory=list)  # Navigation sections
    key_dates: List[Dict[str, Any]] = field(default_factory=list)  # Key dates table
    resources: List[Dict[str, Any]] = field(default_factory=list)  # PDFs, docs

    # Extra metadata (including sub_opportunities for umbrella pages)
    extra: Dict[str, Any] = field(default_factory=dict)


class NihrFundingScraper:
    """
    Scraper for NIHR funding opportunities.

    Handles multiple page types:
    - Standard funding opportunity pages
    - Node/umbrella pages with multiple sub-opportunities
    - Edge cases like /na slugs
    """

    def __init__(self, session=None):
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def _detect_page_type(self, url: str) -> NihrPageType:
        """
        Detect NIHR page type from URL structure.

        Args:
            url: NIHR page URL

        Returns:
            NihrPageType: Detected page type

        Examples:
            /funding/programme/opportunity → FUNDING
            /node/12345 → NODE
            /funding/programme/na → FUNDING (handled gracefully)
        """
        path = urlparse(url).path.rstrip("/")
        parts = [p for p in path.split("/") if p]

        # /funding/.../... is the standard case
        if len(parts) >= 2 and parts[0] == "funding":
            return NihrPageType.FUNDING

        # /node/12345 style (umbrella pages)
        if len(parts) >= 2 and parts[0] == "node" and parts[1].isdigit():
            return NihrPageType.NODE

        # Unrecognized format
        return NihrPageType.UNKNOWN

    def scrape(self, url: str) -> NihrFundingOpportunity:
        """
        Main scraping entry point - routes to appropriate handler based on page type.

        Args:
            url: NIHR funding opportunity URL

        Returns:
            NihrFundingOpportunity: Scraped opportunity data

        Raises:
            requests.HTTPError: If page cannot be fetched
            ValueError: If page structure is unrecognizable
        """
        logger.info(f"Scraping NIHR funding page: {url}")

        # Fetch page
        html = self._fetch(url)
        soup = BeautifulSoup(html, "lxml")

        # Detect page type and route
        page_type = self._detect_page_type(url)
        logger.debug(f"Detected NIHR page type: {page_type} for {url}")

        if page_type == NihrPageType.FUNDING:
            return self._scrape_funding_page(url, soup)
        elif page_type == NihrPageType.NODE:
            return self._scrape_node_page(url, soup)
        else:
            # Unknown type - try FUNDING scrape with warning
            logger.warning(
                f"Unknown NIHR page type for {url}, "
                f"falling back to FUNDING scrape"
            )
            return self._scrape_funding_page(url, soup)

    def _fetch(self, url: str) -> str:
        """
        Fetch HTML content with error handling.

        Args:
            url: URL to fetch

        Returns:
            str: HTML content

        Raises:
            requests.HTTPError: If request fails
        """
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return response.text

    def _scrape_funding_page(self, url: str, soup: BeautifulSoup) -> NihrFundingOpportunity:
        """
        Scrape standard NIHR funding opportunity page.

        Extracts:
        - Programme label
        - Title
        - Overview metadata (status, type, dates, funding)
        - Key dates
        - Sections from navigation
        - Resources (PDFs, documents)

        Args:
            url: Page URL
            soup: Parsed HTML

        Returns:
            NihrFundingOpportunity: Structured opportunity data
        """
        # Get canonical URL (might differ from input URL)
        canonical_url = self._canonicalize_url(url, soup)

        # Extract core fields
        programme = self._extract_programme_label(soup)
        title = self._extract_title(soup)
        description = self._extract_description(soup)

        # Parse Overview section metadata
        overview_section = self._find_overview_section(soup)
        meta = self._parse_overview_meta(overview_section) if overview_section else {}

        # Fallback funding detection if not in Overview
        if "funding_text" not in meta:
            meta["funding_text"] = self._find_funding_text_fallback(soup)

        # Extract structured data
        key_dates = self._parse_key_dates(soup)
        sections = self._parse_sections_from_nav(canonical_url, soup)
        resources = self._extract_resources(canonical_url, soup, sections)

        # Generate opportunity ID
        opportunity_id = self._infer_opportunity_id(canonical_url, meta)

        # Separate known fields from extra metadata
        extra = {
            k: v for k, v in meta.items()
            if k not in {
                "status", "type", "opening_date", "closing_date",
                "reference_id", "funding_text"
            }
        }

        return NihrFundingOpportunity(
            source="nihr",
            url=canonical_url,
            opportunity_id=opportunity_id,
            reference_id=meta.get("reference_id"),
            programme=programme,
            title=title,
            description=description,
            opportunity_status=meta.get("status"),
            opportunity_type=meta.get("type"),
            opening_date=meta.get("opening_date"),
            closing_date=meta.get("closing_date"),
            funding_text=meta.get("funding_text"),
            sections=sections,
            key_dates=key_dates,
            resources=resources,
            extra=extra,
        )

    def _scrape_node_page(self, url: str, soup: BeautifulSoup) -> NihrFundingOpportunity:
        """
        Scrape NIHR node/umbrella page (often contains multiple sub-opportunities).

        Strategy:
        - Create single NihrFundingOpportunity for the umbrella
        - Extract sub-opportunities as metadata (not separate grants)
        - Downstream can split if needed

        Args:
            url: Node page URL (e.g., /node/12345)
            soup: Parsed HTML

        Returns:
            NihrFundingOpportunity: Umbrella opportunity with sub_opportunities in extra
        """
        canonical_url = self._canonicalize_url(url, soup)
        title = self._extract_title(soup)
        programme = self._extract_programme_label(soup)
        description = self._extract_description(soup)

        # Parse Overview if present
        overview_section = self._find_overview_section(soup)
        meta = self._parse_overview_meta(overview_section) if overview_section else {}

        # Extract standard data
        key_dates = self._parse_key_dates(soup)
        sections = self._parse_sections_from_nav(canonical_url, soup)
        resources = self._extract_resources(canonical_url, soup, sections)

        # NEW: Discover sub-opportunities listed on this umbrella page
        sub_calls = self._extract_sub_opportunities(soup, canonical_url)

        # Generate ID
        opportunity_id = self._infer_opportunity_id(canonical_url, meta)

        # Prepare extra metadata
        extra = {
            k: v for k, v in meta.items()
            if k not in {
                "status", "type", "opening_date", "closing_date",
                "reference_id", "funding_text"
            }
        }

        # Store sub-opportunities in extra for visibility
        if sub_calls:
            extra["sub_opportunities"] = sub_calls
            logger.info(
                f"Found {len(sub_calls)} sub-opportunities "
                f"on umbrella page: {url}"
            )

        return NihrFundingOpportunity(
            source="nihr",
            url=canonical_url,
            opportunity_id=opportunity_id,
            reference_id=meta.get("reference_id"),
            programme=programme,
            title=title,
            description=description,
            opportunity_status=meta.get("status"),
            opportunity_type=meta.get("type") or "Programme",  # Default for umbrellas
            opening_date=meta.get("opening_date"),
            closing_date=meta.get("closing_date"),
            funding_text=meta.get("funding_text"),
            sections=sections,
            key_dates=key_dates,
            resources=resources,
            extra=extra,
        )

    # ========================================================================
    # Helper methods for extraction
    # ========================================================================

    def _canonicalize_url(self, url: str, soup: BeautifulSoup) -> str:
        """Get canonical URL from link tag or use provided URL."""
        canonical = soup.find("link", rel="canonical")
        if canonical and canonical.get("href"):
            return canonical["href"]
        return url

    def _extract_programme_label(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract programme name from breadcrumb or page structure."""
        # Try breadcrumb
        breadcrumb = soup.find("nav", class_=re.compile(r"breadcrumb", re.I))
        if breadcrumb:
            links = breadcrumb.find_all("a")
            if len(links) >= 2:
                # Second-to-last link is often the programme
                return links[-2].get_text(strip=True)

        # Try page structure
        programme_elem = soup.find(class_=re.compile(r"programme", re.I))
        if programme_elem:
            return programme_elem.get_text(strip=True)

        return None

    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract page title from h1."""
        h1 = soup.find("h1")
        if h1:
            return " ".join(h1.get_text(" ", strip=True).split())
        return None

    def _extract_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract description/overview text from main content."""
        # Look for intro paragraph or summary
        main_content = soup.find("main") or soup.find("div", class_=re.compile(r"content", re.I))
        if not main_content:
            return None

        # Get first few paragraphs as description
        paragraphs = main_content.find_all("p", limit=3)
        if paragraphs:
            desc_parts = []
            for p in paragraphs:
                text = " ".join(p.get_text(" ", strip=True).split())
                if text and len(text) > 20:  # Skip very short paragraphs
                    desc_parts.append(text)
                if len(" ".join(desc_parts)) > 300:  # Limit length
                    break
            return " ".join(desc_parts) if desc_parts else None

        return None

    def _find_overview_section(self, soup: BeautifulSoup) -> Optional[Tag]:
        """Find Overview section element."""
        # Look for section with "Overview" heading
        for heading in soup.find_all(["h2", "h3"]):
            if "overview" in heading.get_text(strip=True).lower():
                # Return the parent section or next sibling container
                parent = heading.find_parent(["section", "div"])
                if parent:
                    return parent
                return heading.find_next_sibling()
        return None

    def _parse_overview_meta(self, overview_elem: Tag) -> Dict[str, Any]:
        """
        DEPRECATED: Use _parse_overview_metadata instead.
        Kept for backward compatibility.
        """
        # Get full page soup
        soup = overview_elem.find_parent() or overview_elem
        while soup.parent:
            soup = soup.parent

        # Call new parser
        status, opening, closing, ref_id = self._parse_overview_metadata(soup)

        meta = {}
        if status:
            meta["status"] = status
        if opening:
            meta["opening_date"] = opening
        if closing:
            meta["closing_date"] = closing
        if ref_id:
            meta["reference_id"] = ref_id

        return meta

    def _parse_overview_metadata(self, soup: BeautifulSoup) -> tuple[Optional[str], Optional[datetime], Optional[datetime], Optional[str]]:
        """
        Parse overview table for:
        - Opportunity status: Open / Closed / Opening soon / Closing soon
        - Opening date: 4 November 2025 at 1:00 pm
        - Closing date: 28 January 2026 at 1:00 pm
        - Reference ID: 2025/448

        Returns: (opportunity_status, opening_date, closing_date, reference_id)
        """
        status = None
        opening = None
        closing = None
        ref_id = None

        main = soup.find("main") or soup
        text = " ".join(main.stripped_strings)

        # Status
        m_status = re.search(
            r"Opportunity status:\s*(Open|Closed|Opening soon|Closing soon|Paused)",
            text,
            re.IGNORECASE
        )
        if m_status:
            status = m_status.group(1).strip()

        # Opening date
        m_open = re.search(
            r"Opening date:\s*([^\n]+?)\b(?:Reference ID|Closing date|$)",
            text
        )
        if m_open:
            try:
                opening = dateutil.parser.parse(m_open.group(1).strip(), dayfirst=True)
            except Exception:
                pass

        # Closing date
        m_close = re.search(
            r"Closing date:\s*([^\n]+?)\b(?:Reference ID|Opening date|$)",
            text
        )
        if m_close:
            try:
                closing = dateutil.parser.parse(m_close.group(1).strip(), dayfirst=True)
            except Exception:
                pass

        # Reference ID
        m_ref = re.search(r"Reference ID:\s*([0-9/]+)", text)
        if m_ref:
            ref_id = m_ref.group(1).strip()

        return status, opening, closing, ref_id

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse date string to datetime."""
        if not date_str:
            return None

        # Common NIHR date formats
        formats = [
            "%d %B %Y",  # 1 January 2025
            "%d %b %Y",  # 1 Jan 2025
            "%Y-%m-%d",  # 2025-01-01
            "%d/%m/%Y",  # 01/01/2025
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue

        logger.debug(f"Could not parse date: {date_str}")
        return None

    def _find_funding_text_fallback(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Fallback funding text detection for cases where Overview doesn't contain it.

        Searches main content for lines mentioning:
        - "up to £"
        - "share of up to £"
        - "prize pot"
        - "funding available"
        """
        body = soup.find("main") or soup.body
        if not body:
            return None

        # Get all text with newlines preserved
        text = body.get_text("\n", strip=True)

        # Scan line by line for funding indicators
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue

            lower = line.lower()

            # Check for common funding patterns
            if any(pattern in lower for pattern in [
                "up to £",
                "share of up to £",
                "prize pot",
                "funding available",
                "total funding",
                "£" + " million"  # catches "£5 million" style
            ]):
                return line

        return None

    def _infer_opportunity_id(self, url: str, meta: dict) -> str:
        """
        Generate unique opportunity ID from URL or metadata.

        Priority:
        1. reference_id from metadata
        2. Last URL path segment
        """
        # Use reference_id if available (most reliable)
        if meta.get("reference_id"):
            ref_id = meta["reference_id"].replace("/", "_").replace("-", "_")
            return f"nihr_{ref_id}"

        # Fall back to URL-based ID
        path = urlparse(url).path.rstrip("/")
        last_segment = path.split("/")[-1]

        # Clean segment for ID use (don't assume numeric)
        clean_segment = last_segment.replace("-", "_")

        return f"nihr_{clean_segment}"

    def _parse_key_dates(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Parse key dates section if present."""
        key_dates = []

        # Look for "Key dates" heading
        for heading in soup.find_all(["h2", "h3"]):
            if "key dates" in heading.get_text(strip=True).lower():
                # Find following list or table
                next_elem = heading.find_next_sibling()

                if next_elem and next_elem.name == "ul":
                    for li in next_elem.find_all("li"):
                        text = li.get_text(strip=True)
                        key_dates.append({"label": text, "date": text})

                elif next_elem and next_elem.name == "table":
                    for row in next_elem.find_all("tr"):
                        cells = row.find_all(["th", "td"])
                        if len(cells) >= 2:
                            label = cells[0].get_text(strip=True)
                            date = cells[1].get_text(strip=True)
                            key_dates.append({"label": label, "date": date})

                break

        return key_dates

    def _find_tab_navigation(self, soup: BeautifulSoup) -> List[tuple[str, str]]:
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

        # Strategy 1 (PRIORITY): Look for links with href="#tab-*" pattern in main content area
        # This is the most reliable indicator of content tabs (not nav/footer)
        main = soup.find("main") or soup
        for link in main.find_all("a", href=re.compile(r"^#tab-")):
            href = link.get("href", "").strip()
            tab_id = href[1:]
            tab_name = link.get_text(strip=True)

            if tab_name and tab_id:
                tabs.append((tab_name, tab_id))
                logger.debug(f"Found tab (main #tab-*): {tab_name} -> #{tab_id}")

        # Strategy 2: If no #tab-* found, look for tab containers in main content
        if not tabs:
            tab_containers = main.find_all("ul", class_=re.compile(r"(tab)", re.I))

            for container in tab_containers:
                # Skip if container is in footer or nav
                parent_classes = " ".join(container.get("class", []))
                if "footer" in parent_classes.lower() or "navbar" in parent_classes.lower():
                    continue

                for link in container.find_all("a", href=True):
                    href = link.get("href", "").strip()

                    # Must be a fragment link
                    if not href.startswith("#"):
                        continue

                    # Skip footer/nav patterns like #collapse-*, #panel-*
                    if href.startswith("#collapse-") or href.startswith("#panel-"):
                        continue

                    # Extract tab ID (remove #)
                    tab_id = href[1:]

                    # Get tab name from link text
                    tab_name = link.get_text(strip=True)

                    # Skip empty names or IDs
                    if not tab_name or not tab_id:
                        continue

                    tabs.append((tab_name, tab_id))
                    logger.debug(f"Found tab (container): {tab_name} -> #{tab_id}")

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

    def _parse_sections_with_tabs(self, soup: BeautifulSoup, page_url: str) -> List[NihrSection]:
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
        tabs: List[tuple[str, str]]
    ) -> List[NihrSection]:
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

    def _parse_sections_from_nav(self, base_url: str, soup: BeautifulSoup) -> List[Dict[str, Any]]:
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

    def _parse_sections_from_headings(self, soup: BeautifulSoup, page_url: str) -> List[NihrSection]:
        """
        Parse NIHR sections by walking <h2> headings in main content.

        Structure:
            <main>
              <h1>Page title</h1>
              <h2>Overview</h2>
              ...content...
              <h2>Strategic themes</h2>
              ...content...
              <h2>Application guidance</h2>
              ...content...
            </main>

        Each h2 + following siblings until next h2 = one section.
        """
        sections: List[NihrSection] = []

        # Locate main content
        main = soup.find("main")
        if main is None:
            main = soup

        h2s: List[Tag] = list(main.find_all("h2"))
        if not h2s:
            return sections

        for idx, h2 in enumerate(h2s):
            title = h2.get_text(strip=True)
            if not title:
                continue

            slug = _slugify(title)

            # Collect siblings until next h2
            content_nodes: List[Tag] = []
            for sib in h2.next_siblings:
                if isinstance(sib, Tag) and sib.name == "h2":
                    break
                if isinstance(sib, Tag):
                    content_nodes.append(sib)

            html = "".join(str(node) for node in content_nodes).strip()
            text = " ".join(BeautifulSoup(html, "lxml").stripped_strings) if html else ""

            if not text and not html:
                continue

            source_url = f"{page_url}#{slug}"
            sections.append(
                NihrSection(
                    name=title,
                    slug=slug,
                    html=html,
                    text=text,
                    source_url=source_url,
                )
            )

        return sections

    def _extract_resources(
        self,
        base_url: str,
        soup: BeautifulSoup,
        sections: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Extract all resources from sections.

        FIXED: Uses the sections that were already parsed (preserving tab content)
        instead of re-parsing with old h2 method.

        Args:
            base_url: Page URL
            soup: Parsed HTML (kept for backward compatibility, not used)
            sections: Already-parsed sections (from tab-aware parser)

        Returns:
            List of resource dicts
        """
        # Convert dict sections back to NihrSection objects
        # These sections already contain tab content from tab-aware parsing
        section_objs = []
        for s in sections:
            section_objs.append(
                NihrSection(
                    name=s["title"],
                    slug=s.get("slug", _slugify(s["title"])),
                    html=s["html"],
                    text=s["text"],
                    source_url=s["url"]
                )
            )

        # Extract resources from these sections (preserving tab content)
        resources = self._extract_resources_from_sections(section_objs, base_url)

        # Convert NihrResource objects to dicts for backward compatibility
        return [
            {
                "title": r.title,
                "url": r.url,
                "type": r.kind,
                "scope": r.scope,
                "text": ""  # To be filled by document processor
            }
            for r in resources
        ]

    def _infer_resource_kind(self, url: str) -> str:
        """Infer resource type from URL."""
        url_l = url.lower()
        if ".pdf" in url_l:
            return "pdf"
        if "youtube.com" in url_l or "youtu.be" in url_l or "vimeo.com" in url_l:
            return "video"
        return "webpage"

    def _extract_resources_from_sections(
        self,
        sections: List[NihrSection],
        page_url: str,
    ) -> List[NihrResource]:
        """
        Extract all links from all section HTML.
        """
        resources: List[NihrResource] = []
        seen: set[str] = set()

        for section in sections:
            if not section.html:
                continue

            sec_soup = BeautifulSoup(section.html, "lxml")
            for a in sec_soup.find_all("a"):
                href = (a.get("href") or "").strip()
                if not href:
                    continue
                if href.startswith(("#", "mailto:", "tel:", "javascript:")):
                    continue

                abs_url = urljoin(page_url, href)
                if abs_url in seen:
                    continue
                seen.add(abs_url)

                title = a.get_text(strip=True) or abs_url
                kind = self._infer_resource_kind(abs_url)

                resources.append(
                    NihrResource(
                        title=title,
                        url=abs_url,
                        kind=kind,
                        scope="competition",
                    )
                )

        return resources

    def _extract_sub_opportunities(
        self,
        soup: BeautifulSoup,
        base_url: str
    ) -> List[Dict[str, str]]:
        """
        Extract sub-opportunities from umbrella page.

        Looks for sections with headings like:
        - "PDG funding opportunities"
        - "RfPB funding opportunities"
        - "Active funding opportunities"
        """
        results: List[Dict[str, str]] = []

        # Find headings that indicate funding opportunity lists
        for heading in soup.find_all(["h2", "h3", "h4"]):
            heading_text = heading.get_text(strip=True).lower()

            # Skip if not a funding opportunities section
            if "funding opportunities" not in heading_text:
                continue

            # Scan siblings until next major heading
            node = heading
            while True:
                node = node.next_sibling

                # Stop at next major heading or end of content
                if node is None:
                    break
                if isinstance(node, Tag) and node.name in ("h2", "h3"):
                    break

                if not isinstance(node, Tag):
                    continue

                # Extract links from sub-headings
                for sub_heading in node.find_all(["h3", "h4"]):
                    link = sub_heading.find("a", href=True)
                    if not link:
                        continue

                    title = " ".join(link.get_text(" ", strip=True).split())
                    href = link["href"].strip()
                    full_url = urljoin(base_url, href)

                    results.append({
                        "title": title,
                        "url": full_url
                    })

                # Extract links from list items
                for list_item in node.find_all("li"):
                    link = list_item.find("a", href=True)
                    if not link:
                        continue

                    title = " ".join(link.get_text(" ", strip=True).split())
                    href = link["href"].strip()
                    full_url = urljoin(base_url, href)

                    results.append({
                        "title": title,
                        "url": full_url
                    })

        # Deduplicate by URL
        seen_urls = set()
        deduped = []
        for item in results:
            if item["url"] in seen_urls:
                continue
            seen_urls.add(item["url"])
            deduped.append(item)

        return deduped
