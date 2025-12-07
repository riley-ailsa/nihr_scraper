#!/usr/bin/env python3
"""
NIHR Grant Scraper - Pipeline v3.2 (Multi-Tab Extraction)

Key improvements in v3.2:
- Extracts content from ALL tabs (Overview, Research spec, Application guidance, etc.)
- Better funding amount detection
- Better document/link extraction
- Fixed :contains deprecation warning

Usage:
    python run_pipeline.py                    # Full pipeline
    python run_pipeline.py --limit 5          # Test with 5 grants
    python run_pipeline.py --dry-run          # Scrape but don't save
    python run_pipeline.py --skip-discovery   # Use cached URLs
"""

import re
import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import warnings

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from tqdm import tqdm

from ailsa_shared import (
    Grant, GrantSource, GrantStatus, GrantSections,
    SummarySection, EligibilitySection, ScopeSection,
    DatesSection, FundingSection, HowToApplySection,
    AssessmentSection, SupportingInfoSection, ContactsSection,
    SupportingDocument,
    ProgrammeInfo, ProcessingInfo, CompetitionType,
    MongoDBClient, PineconeClientV3,
    clean_html, parse_date, parse_money, infer_status_from_dates,
)

# Suppress the :contains deprecation warning
warnings.filterwarnings('ignore', category=FutureWarning, module='soupsieve')

load_dotenv()

# =============================================================================
# CONFIGURATION
# =============================================================================

NIHR_FUNDING_URL = "https://www.nihr.ac.uk/funding-opportunities"
NIHR_BASE_URL = "https://www.nihr.ac.uk"

DATA_DIR = Path(__file__).parent / "data"
LOG_DIR = Path(__file__).parent / "logs"
URLS_FILE = DATA_DIR / "nihr_urls.txt"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

log_file = LOG_DIR / f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# =============================================================================
# DISCOVERY
# =============================================================================

def discover_grant_urls() -> List[str]:
    """Discover all NIHR funding opportunity URLs."""
    logger.info("Discovering NIHR funding opportunities...")
    
    urls = set()
    page = 1
    
    while True:
        page_url = f"{NIHR_FUNDING_URL}?page={page}"
        logger.info(f"Fetching page {page}: {page_url}")
        
        try:
            response = requests.get(page_url, headers=HEADERS, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Error fetching page {page}: {e}")
            break
        
        soup = BeautifulSoup(response.text, 'lxml')
        
        # Find funding opportunity links
        links = soup.select('a[href*="/funding/"]')
        page_urls = set()
        
        for link in links:
            href = link.get('href', '')
            if '/funding/' in href and href not in ['/funding/', '/funding-opportunities']:
                full_url = href if href.startswith('http') else f"{NIHR_BASE_URL}{href}"
                if not any(x in full_url for x in ['/funding-opportunities', '/funding/how-to-apply', '/funding-programmes']):
                    page_urls.add(full_url)
        
        if not page_urls:
            logger.info(f"No more opportunities found on page {page}")
            break
        
        new_urls = page_urls - urls
        if not new_urls:
            logger.info("No new URLs found, stopping pagination")
            break
        
        urls.update(page_urls)
        logger.info(f"Found {len(page_urls)} URLs on page {page} ({len(new_urls)} new)")
        
        page += 1
        
        if page > 50:
            logger.warning("Reached page limit, stopping")
            break
    
    logger.info(f"Discovered {len(urls)} total URLs")
    return list(urls)


def save_urls(urls: List[str]):
    with open(URLS_FILE, 'w') as f:
        for url in sorted(urls):
            f.write(f"{url}\n")
    logger.info(f"Saved {len(urls)} URLs to {URLS_FILE}")


def load_urls() -> List[str]:
    if not URLS_FILE.exists():
        return []
    with open(URLS_FILE) as f:
        return [line.strip() for line in f if line.strip()]


# =============================================================================
# SCRAPING - Multi-Tab Extraction
# =============================================================================

def scrape_grant_page(url: str) -> Optional[Dict[str, Any]]:
    """Scrape a single NIHR grant page, extracting from ALL tabs."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Error fetching {url}: {e}")
        return None
    
    soup = BeautifulSoup(response.text, 'lxml')
    
    raw = {
        'url': url,
        'scraped_at': datetime.now(timezone.utc),
    }
    
    # =========================================================================
    # HERO SECTION - Title and Programme Type
    # =========================================================================
    
    title_elem = soup.select_one('h1')
    raw['title'] = title_elem.get_text(strip=True) if title_elem else ''
    
    tagline = soup.select_one('.tagline')
    if tagline:
        raw['programme_name'] = tagline.get_text(strip=True)
    
    # =========================================================================
    # SUMMARY LIST - Status, Type, Dates, Reference ID
    # =========================================================================
    
    summary_list = soup.select_one('.summary-list, ul.summary-list')
    if summary_list:
        for item in summary_list.select('li'):
            label_elem = item.select_one('.label')
            value_elem = item.select_one('.value')
            
            if label_elem and value_elem:
                label = label_elem.get_text(strip=True).lower().replace(':', '')
                
                # Status - look for status div with class
                status_div = value_elem.select_one('.status')
                if status_div:
                    raw['status'] = status_div.get_text(strip=True)
                    continue
                
                # Dates - look for time elements with datetime attribute
                time_elem = value_elem.select_one('time[datetime]')
                if time_elem:
                    datetime_str = time_elem.get('datetime')
                    display_str = time_elem.get_text(strip=True)
                    
                    if 'opening' in label:
                        raw['opening_date'] = datetime_str
                        raw['opening_date_display'] = display_str
                    elif 'closing' in label:
                        raw['closing_date'] = datetime_str
                        raw['closing_date_display'] = display_str
                    continue
                
                # Other fields
                value = value_elem.get_text(strip=True)
                
                if 'type' in label:
                    raw['type'] = value
                elif 'reference' in label:
                    raw['reference_id'] = value
    
    # =========================================================================
    # EXTRACT ALL TABS - This is the key improvement in v3.2
    # =========================================================================
    
    # Find all tab panes
    all_tabs = soup.select('.tab-pane')
    
    # Initialize tab content storage
    raw['tabs'] = {}
    all_documents = []
    all_links = []
    
    for tab in all_tabs:
        tab_id = tab.get('id', '')
        
        # Get tab name from the heading or the tab ID
        tab_heading = tab.select_one('h2')
        tab_name = tab_heading.get_text(strip=True) if tab_heading else tab_id.replace('tab-', '').replace('-', ' ').title()
        
        # Get all text content
        tab_text = tab.get_text(separator='\n', strip=True)
        
        # Get rich text HTML
        rich_texts = tab.select('.rich-text, .paragraph--type--rich-text')
        tab_html = '\n'.join(str(rt) for rt in rich_texts)
        
        # Store tab content
        raw['tabs'][tab_name] = {
            'text': tab_text,
            'html': tab_html,
        }
        
        # Extract links from this tab
        for link in tab.select('a[href]'):
            href = link.get('href', '')
            link_text = link.get_text(strip=True)
            if href and link_text:
                full_url = href if href.startswith('http') else f"{NIHR_BASE_URL}{href}"
                
                # Categorize as document or link
                is_doc = any(ext in href.lower() for ext in ['.pdf', '.doc', '.docx', '.xlsx', '.xls'])
                
                link_info = {
                    'title': link_text,
                    'url': full_url,
                    'type': 'PDF' if '.pdf' in href.lower() else 'Document' if is_doc else 'Link',
                    'source_tab': tab_name,
                }
                
                if is_doc:
                    all_documents.append(link_info)
                else:
                    all_links.append(link_info)
    
    raw['documents'] = all_documents
    raw['all_links'] = all_links
    
    # =========================================================================
    # EXTRACT SPECIFIC TAB CONTENT
    # =========================================================================
    
    # Overview tab
    overview = raw['tabs'].get('Overview', {})
    raw['overview_text'] = overview.get('text', '')
    raw['overview_html'] = overview.get('html', '')
    
    # Research Specification tab - often has scope/themes
    research_spec = raw['tabs'].get('Research specification', raw['tabs'].get('Research Specification', {}))
    raw['research_spec_text'] = research_spec.get('text', '')
    
    # Application Guidance tab - often has eligibility info
    app_guidance = raw['tabs'].get('Application guidance', raw['tabs'].get('Application Guidance', {}))
    raw['application_guidance_text'] = app_guidance.get('text', '')
    
    # Application Process tab - how to apply details
    app_process = raw['tabs'].get('Application process', raw['tabs'].get('Application Process', {}))
    raw['application_process_text'] = app_process.get('text', '')
    
    # Contact Details tab
    contact = raw['tabs'].get('Contact Details', raw['tabs'].get('Contact details', {}))
    raw['contact_text'] = contact.get('text', '')
    
    # Supporting Information tab (if exists)
    support_info = raw['tabs'].get('Supporting Information', raw['tabs'].get('Supporting information', {}))
    raw['supporting_info_text'] = support_info.get('text', '')
    
    # =========================================================================
    # EXTRACT FUNDING AMOUNTS FROM ALL TEXT
    # =========================================================================
    
    # Combine all text to search for funding
    all_text = ' '.join([
        raw.get('overview_text', ''),
        raw.get('research_spec_text', ''),
        raw.get('application_guidance_text', ''),
    ])
    
    # Look for various funding patterns
    funding_patterns = [
        r'(?:up to |maximum of |approximately |around )?£([\d,]+(?:\.\d{2})?)\s*(?:million|m)',
        r'£([\d,]+(?:\.\d{2})?)\s*(?:million|m)(?:\s+(?:per project|available|total|funding))?',
        r'(?:funding|budget|award)(?:[^.]*?)£([\d,]+(?:,\d{3})*(?:\.\d{2})?)',
        r'£([\d,]+(?:,\d{3})*)\s+(?:to|and)\s+£([\d,]+(?:,\d{3})*)',
    ]
    
    for pattern in funding_patterns:
        match = re.search(pattern, all_text, re.IGNORECASE)
        if match:
            raw['funding_match'] = match.group(0)
            break
    
    # =========================================================================
    # EXTRACT EMAILS FROM ALL TEXT
    # =========================================================================
    
    all_text_for_email = raw.get('contact_text', '') + ' ' + raw.get('overview_text', '')
    emails = re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', all_text_for_email)
    if emails:
        raw['contact_email'] = emails[0]  # Primary email
        raw['all_emails'] = list(set(emails))
    
    # =========================================================================
    # APPLICATION URL
    # =========================================================================
    
    # Look for "Apply now" or similar buttons
    apply_selectors = [
        'a.btn-primary[href*="apply"]',
        'a.btn-primary[href*="ras"]',
        'a.btn-primary[href*="fundingservice"]',
        'a.btn[href*="apply"]',
        'a[href*="fundingservice.nihr.ac.uk"]',
    ]
    
    for selector in apply_selectors:
        apply_link = soup.select_one(selector)
        if apply_link:
            raw['apply_url'] = apply_link.get('href')
            break
    
    # Also check for "Apply now" text in buttons
    if 'apply_url' not in raw:
        for btn in soup.select('a.btn-primary, a.btn'):
            if 'apply' in btn.get_text(strip=True).lower():
                raw['apply_url'] = btn.get('href')
                break
    
    # =========================================================================
    # META DESCRIPTION
    # =========================================================================
    
    meta_desc = soup.select_one('meta[name="description"]')
    if meta_desc:
        raw['meta_description'] = meta_desc.get('content', '')
    
    # =========================================================================
    # REFERENCE ID FROM URL
    # =========================================================================
    
    if 'reference_id' not in raw:
        id_match = re.search(r'/(\d+)/?$', url)
        if id_match:
            raw['reference_id'] = id_match.group(1)
    
    return raw


# =============================================================================
# NORMALIZATION
# =============================================================================

def normalize_grant(raw: Dict[str, Any]) -> Grant:
    """Convert raw scraped data to normalized Grant with sections."""
    
    # Parse dates
    opens_at = parse_date(raw.get('opening_date'))
    closes_at = parse_date(raw.get('closing_date'))
    
    # Map status
    status = map_status(raw.get('status'), opens_at, closes_at)
    
    # Generate grant_id
    external_id = raw.get('reference_id', '')
    if not external_id:
        external_id = raw['url'].rstrip('/').split('/')[-1]
    grant_id = f"nihr_{external_id}"
    
    # Build description from overview and meta
    description = raw.get('overview_text', '')
    if not description and raw.get('meta_description'):
        description = raw['meta_description']
    
    # Combine scope text from overview and research spec
    scope_text = raw.get('research_spec_text', '') or raw.get('overview_text', '')
    
    # Build sections
    sections = GrantSections(
        summary=SummarySection(
            text=clean_html(description),
            html=raw.get('overview_html'),
            opportunity_type=raw.get('type'),
            programme_name=raw.get('programme_name'),
            extracted_at=datetime.now(timezone.utc),
        ),
        
        eligibility=EligibilitySection(
            text=extract_eligibility_text(raw),
            who_can_apply=extract_who_can_apply(raw),
            geographic_scope="UK",
            uk_registered_required=True,
            extracted_at=datetime.now(timezone.utc),
        ),
        
        scope=ScopeSection(
            text=clean_html(scope_text[:2000]) if scope_text else '',
            themes=extract_themes(raw),
            sectors=["Health", "Social Care"],
            extracted_at=datetime.now(timezone.utc),
        ),
        
        dates=DatesSection(
            opens_at=opens_at,
            closes_at=closes_at,
            deadline_time=extract_deadline_time(raw.get('closing_date_display', '')),
            timezone="UK",
            key_dates_text=build_dates_text(raw),
            extracted_at=datetime.now(timezone.utc),
        ),
        
        funding=FundingSection(
            text=raw.get('funding_match', ''),
            total_pot_gbp=parse_funding_amount(raw.get('funding_match')),
            total_pot_display=raw.get('funding_match'),
            competition_type=CompetitionType.GRANT,
            currency="GBP",
            extracted_at=datetime.now(timezone.utc),
        ),
        
        how_to_apply=HowToApplySection(
            text=clean_html(raw.get('application_process_text', '')[:1000]) if raw.get('application_process_text') else '',
            portal_name=detect_portal_name(raw),
            portal_url=raw.get('apply_url'),
            apply_url=raw.get('apply_url'),
            extracted_at=datetime.now(timezone.utc),
        ),
        
        assessment=AssessmentSection(
            text=extract_assessment_text(raw),
            extracted_at=datetime.now(timezone.utc),
        ),
        
        supporting_info=SupportingInfoSection(
            text=raw.get('supporting_info_text', '') or raw.get('application_guidance_text', ''),
            documents=[
                SupportingDocument(
                    title=doc.get('title', 'Document'),
                    url=doc.get('url', ''),
                    type=doc.get('type'),
                )
                for doc in raw.get('documents', [])
            ],
            extracted_at=datetime.now(timezone.utc),
        ),
        
        contacts=ContactsSection(
            text=raw.get('contact_text', ''),
            helpdesk_email=raw.get('contact_email'),
            extracted_at=datetime.now(timezone.utc),
        ),
    )
    
    # Programme info
    programme = ProgrammeInfo(
        name=raw.get('programme_name'),
        funder="NIHR",
        nihr_programme=map_nihr_programme(raw.get('programme_name')),
    )
    
    return Grant(
        grant_id=grant_id,
        source=GrantSource.NIHR,
        external_id=raw.get('reference_id'),
        title=raw.get('title', ''),
        url=raw.get('url', ''),
        status=status,
        is_active=(status == GrantStatus.OPEN),
        sections=sections,
        programme=programme,
        tags=generate_tags(raw),
        raw=raw,
        processing=ProcessingInfo(
            scraped_at=raw.get('scraped_at'),
            normalized_at=datetime.now(timezone.utc),
            sections_extracted=get_extracted_sections(raw),
            scraper_version="3.2",
            schema_version="3.0",
        ),
    )


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def map_status(status_text: str, opens_at: datetime, closes_at: datetime) -> GrantStatus:
    """Map status text to GrantStatus enum."""
    if not status_text:
        return infer_status_from_dates(opens_at, closes_at)
    
    status_lower = status_text.lower()
    
    if 'closed' in status_lower:
        return GrantStatus.CLOSED
    elif 'open' in status_lower:
        return GrantStatus.OPEN
    elif 'forthcoming' in status_lower or 'upcoming' in status_lower:
        return GrantStatus.FORTHCOMING
    
    return infer_status_from_dates(opens_at, closes_at)


def extract_eligibility_text(raw: Dict) -> str:
    """Extract eligibility info from application guidance or overview."""
    # First try application guidance
    text = raw.get('application_guidance_text', '')
    if not text:
        text = raw.get('overview_text', '')
    
    # Look for eligibility patterns
    patterns = [
        r'(?:eligibility|eligible|who can apply)[:\s]*(.*?)(?:\n\n|\Z)',
        r'(?:applicants? must|you must)[:\s]*(.*?)(?:\n\n|\Z)',
        r'(?:open to|available to)[:\s]*(.*?)(?:\n\n|\Z)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return clean_html(match.group(0)[:800])
    
    return ''


def extract_who_can_apply(raw: Dict) -> List[str]:
    """Extract applicant types."""
    who_can = []
    text = (raw.get('overview_text', '') + ' ' + raw.get('application_guidance_text', '')).lower()
    
    applicant_keywords = {
        'nhs': 'NHS Trust',
        'universit': 'Academic',
        'academic': 'Academic',
        'charit': 'Charity',
        'local authorit': 'Local Authority',
        'sme': 'SME',
        'clinician': 'Clinician',
        'researcher': 'Researcher',
        'dental': 'Dental Professional',
        'nurse': 'Nurse',
        'midwi': 'Midwife',
        'primary care': 'Primary Care',
        'social care': 'Social Care',
    }
    
    for keyword, applicant_type in applicant_keywords.items():
        if keyword in text and applicant_type not in who_can:
            who_can.append(applicant_type)
    
    return who_can


def extract_themes(raw: Dict) -> List[str]:
    """Extract research themes from all content."""
    themes = []
    text = ' '.join([
        raw.get('title', ''),
        raw.get('overview_text', ''),
        raw.get('research_spec_text', ''),
        raw.get('programme_name', ''),
    ]).lower()
    
    theme_keywords = {
        'mental health': 'Mental Health',
        'cancer': 'Cancer',
        'cardiovascular': 'Cardiovascular',
        'dementia': 'Dementia',
        'alzheimer': 'Dementia',
        'diabetes': 'Diabetes',
        'digital health': 'Digital Health',
        'artificial intelligence': 'AI',
        'machine learning': 'AI',
        'health inequalities': 'Health Inequalities',
        'primary care': 'Primary Care',
        'social care': 'Social Care',
        'public health': 'Public Health',
        'dentistry': 'Dentistry',
        'dental': 'Dentistry',
        'clinical fellowship': 'Career Development',
        'career development': 'Career Development',
        'liver': 'Liver Disease',
        'kidney': 'Renal',
        'renal': 'Renal',
        'respiratory': 'Respiratory',
        'stroke': 'Stroke',
        'infection': 'Infectious Disease',
        'antimicrobial': 'Antimicrobial Resistance',
        'musculoskeletal': 'Musculoskeletal',
        'paediatric': 'Paediatrics',
        'pediatric': 'Paediatrics',
        'children': 'Paediatrics',
        'maternal': 'Maternal Health',
        'pregnancy': 'Maternal Health',
        'nice': 'NICE Guidance',
        'eme': 'Efficacy & Mechanism',
        'hta': 'Health Technology Assessment',
        'hsdr': 'Health Services',
        'phr': 'Public Health Research',
    }
    
    for keyword, theme in theme_keywords.items():
        if keyword in text and theme not in themes:
            themes.append(theme)
    
    return themes


def extract_deadline_time(closing_date_display: str) -> Optional[str]:
    """Extract deadline time from display string."""
    if not closing_date_display:
        return None
    
    match = re.search(r'at\s+(\d{1,2}[:.]\d{2}\s*(?:am|pm)?)', closing_date_display, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def build_dates_text(raw: Dict) -> str:
    """Build human-readable dates text."""
    parts = []
    if raw.get('opening_date_display'):
        parts.append(f"Opens: {raw['opening_date_display']}")
    if raw.get('closing_date_display'):
        parts.append(f"Closes: {raw['closing_date_display']}")
    return '. '.join(parts)


def parse_funding_amount(funding_text: str) -> Optional[float]:
    """Parse funding text to extract amount in GBP."""
    if not funding_text:
        return None
    
    # Try to extract number with million
    match = re.search(r'£([\d,.]+)\s*(?:million|m)', funding_text, re.IGNORECASE)
    if match:
        amount_str = match.group(1).replace(',', '')
        try:
            return float(amount_str) * 1_000_000
        except ValueError:
            pass
    
    # Try plain number
    match = re.search(r'£([\d,]+)', funding_text)
    if match:
        amount_str = match.group(1).replace(',', '')
        try:
            return float(amount_str)
        except ValueError:
            pass
    
    return None


def extract_assessment_text(raw: Dict) -> str:
    """Extract assessment criteria from application guidance."""
    text = raw.get('application_guidance_text', '')
    
    patterns = [
        r'(?:assessment|evaluation|criteria|reviewed)[:\s]*(.*?)(?:\n\n|\Z)',
        r'(?:applications will be|proposals are)[^.]*(?:assessed|evaluated|reviewed)[^.]*\.',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return clean_html(match.group(0)[:500])
    
    return ''


def detect_portal_name(raw: Dict) -> str:
    """Detect which portal to use."""
    text = (raw.get('overview_text', '') + ' ' + raw.get('application_process_text', '')).lower()
    apply_url = (raw.get('apply_url') or '').lower()
    
    if 'oriel' in text or 'oriel' in apply_url:
        return 'Oriel'
    elif 'fundingservice' in apply_url:
        return 'NIHR Funding Service'
    elif 'ras' in apply_url or 'research-activity' in apply_url:
        return 'NIHR RAS'
    
    return 'NIHR Funding Service'


def map_nihr_programme(programme_name: str) -> Optional[str]:
    """Map programme name to abbreviation."""
    if not programme_name:
        return None
    
    mappings = {
        'academic clinical fellowship': 'ACF',
        'clinical lectureship': 'CL',
        'health and social care delivery research': 'HSDR',
        'efficacy and mechanism evaluation': 'EME',
        'health technology assessment': 'HTA',
        'public health research': 'PHR',
        'programme grants for applied research': 'PGfAR',
        'research for patient benefit': 'RfPB',
        'invention for innovation': 'i4i',
        'global health': 'GHR',
        'eme programme': 'EME',
        'hta programme': 'HTA',
    }
    
    name_lower = programme_name.lower()
    for full_name, abbrev in mappings.items():
        if full_name in name_lower:
            return abbrev
    return None


def generate_tags(raw: Dict) -> List[str]:
    """Generate searchable tags."""
    tags = ['nihr', 'health', 'research', 'uk']
    
    # Add programme abbreviation
    abbrev = map_nihr_programme(raw.get('programme_name'))
    if abbrev:
        tags.append(abbrev.lower())
    
    # Add type
    if raw.get('type'):
        tags.append(raw['type'].lower().replace(' ', '_'))
    
    # Add themes
    themes = extract_themes(raw)
    for theme in themes:
        tags.append(theme.lower().replace(' ', '_').replace('&', 'and'))
    
    return list(set(tags))


def get_extracted_sections(raw: Dict) -> List[str]:
    """List successfully extracted sections."""
    sections = []
    
    if raw.get('overview_text') or raw.get('meta_description'):
        sections.append('summary')
    if raw.get('opening_date') or raw.get('closing_date'):
        sections.append('dates')
    if raw.get('research_spec_text'):
        sections.append('scope')
    if raw.get('application_guidance_text'):
        sections.append('eligibility')
    if raw.get('application_process_text'):
        sections.append('how_to_apply')
    if raw.get('documents'):
        sections.append('supporting_info')
    if raw.get('contact_text') or raw.get('contact_email'):
        sections.append('contacts')
    if raw.get('funding_match'):
        sections.append('funding')
    
    return sections


# =============================================================================
# INGESTION
# =============================================================================

def ingest_grants(grants: List[Grant], dry_run: bool = False):
    """Save grants to MongoDB and create embeddings in Pinecone."""
    
    if dry_run:
        logger.info(f"DRY RUN: Would ingest {len(grants)} grants")
        for grant in grants[:5]:
            logger.info(f"  - {grant.grant_id}: {grant.title[:60]}...")
            logger.info(f"    Status: {grant.status}, Programme: {grant.programme.name}")
            if grant.sections.dates.opens_at:
                logger.info(f"    Opens: {grant.sections.dates.opens_at}")
            if grant.sections.dates.closes_at:
                logger.info(f"    Closes: {grant.sections.dates.closes_at}")
            if grant.sections.funding.total_pot_display:
                logger.info(f"    Funding: {grant.sections.funding.total_pot_display}")
            logger.info(f"    Tabs extracted: {list(grant.raw.get('tabs', {}).keys())}")
        return
    
    logger.info("Saving to MongoDB...")
    mongo = MongoDBClient()
    success, errors = mongo.upsert_grants(grants)
    logger.info(f"MongoDB: {success} saved, {errors} errors")
    
    logger.info("Creating embeddings in Pinecone...")
    pinecone = PineconeClientV3()
    
    for grant in tqdm(grants, desc="Embedding"):
        try:
            pinecone.embed_and_upsert_grant(grant)
        except Exception as e:
            logger.error(f"Error embedding {grant.grant_id}: {e}")
    
    logger.info("Ingestion complete")


# =============================================================================
# MAIN PIPELINE
# =============================================================================

def run_pipeline(
    skip_discovery: bool = False,
    limit: Optional[int] = None,
    dry_run: bool = False
):
    """Run the full pipeline."""
    
    logger.info("=" * 60)
    logger.info("NIHR Grant Scraper Pipeline v3.2 (Multi-Tab)")
    logger.info("=" * 60)
    
    if skip_discovery:
        urls = load_urls()
        logger.info(f"Loaded {len(urls)} URLs from cache")
    else:
        urls = discover_grant_urls()
        save_urls(urls)
    
    if not urls:
        logger.error("No URLs to process")
        return
    
    if limit:
        urls = urls[:limit]
        logger.info(f"Limited to {limit} URLs")
    
    logger.info(f"Scraping {len(urls)} grant pages...")
    raw_grants = []
    
    for url in tqdm(urls, desc="Scraping"):
        raw = scrape_grant_page(url)
        if raw:
            raw_grants.append(raw)
    
    logger.info(f"Successfully scraped {len(raw_grants)} grants")
    
    logger.info("Normalizing to schema v3...")
    grants = []
    
    for raw in raw_grants:
        try:
            grant = normalize_grant(raw)
            grants.append(grant)
        except Exception as e:
            logger.error(f"Error normalizing {raw.get('url', 'unknown')}: {e}")
    
    logger.info(f"Normalized {len(grants)} grants")
    
    ingest_grants(grants, dry_run=dry_run)
    
    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info(f"  Discovered: {len(urls)} URLs")
    logger.info(f"  Scraped: {len(raw_grants)} grants")
    logger.info(f"  Normalized: {len(grants)} grants")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description='NIHR Grant Scraper Pipeline v3.2')
    parser.add_argument('--skip-discovery', action='store_true', help='Use cached URLs')
    parser.add_argument('--limit', type=int, help='Limit number of grants')
    parser.add_argument('--dry-run', action='store_true', help='Scrape but don\'t save')
    
    args = parser.parse_args()
    
    run_pipeline(
        skip_discovery=args.skip_discovery,
        limit=args.limit,
        dry_run=args.dry_run
    )


if __name__ == '__main__':
    main()
