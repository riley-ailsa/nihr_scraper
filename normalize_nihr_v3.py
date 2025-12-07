"""
NIHR Normalizer v3 - Converts NihrFundingOpportunity to ailsa_shared Grant schema.

Preserves all existing scraper logic. Only changes output format to match
the sectioned Grant schema for better RAG retrieval.

Usage:
    from normalize_nihr_v3 import normalize_nihr_v3
    
    # opp is from existing NihrFundingScraper
    grant = normalize_nihr_v3(opp)
"""

import re
import logging
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict, Any

# Import existing NIHR scraper types
from src.ingest.nihr_funding import NihrFundingOpportunity

# Import ailsa_shared v3 models
from ailsa_shared.models import (
    Grant,
    GrantSource,
    GrantStatus,
    GrantSections,
    SummarySection,
    EligibilitySection,
    ScopeSection,
    DatesSection,
    FundingSection,
    HowToApplySection,
    AssessmentSection,
    SupportingInfoSection,
    SupportingDocument,
    ContactsSection,
    Contact,
    ProgrammeInfo,
    ProcessingInfo,
    CompetitionType,
)

# Import existing utilities
from src.core.money import parse_gbp_amount
from src.core.time_utils import now_london

logger = logging.getLogger(__name__)


# =============================================================================
# MAIN NORMALIZER
# =============================================================================

def normalize_nihr_v3(opportunity: NihrFundingOpportunity) -> Grant:
    """
    Convert NihrFundingOpportunity to ailsa_shared Grant v3 schema.
    
    Args:
        opportunity: Raw scraped NIHR data from existing scraper
        
    Returns:
        Grant: Normalized grant in v3 sectioned format
    """
    now = datetime.now(timezone.utc)
    
    # Infer status
    status = infer_nihr_status(opportunity)
    is_active = status == GrantStatus.OPEN
    
    # Generate grant_id
    grant_id = _generate_grant_id(opportunity)
    
    # Extract sections from scraped data
    sections = _extract_sections(opportunity)
    
    # Extract programme info
    programme = _extract_programme_info(opportunity)
    
    # Extract tags
    tags = _extract_tags(opportunity)
    
    # Build the Grant object
    grant = Grant(
        grant_id=grant_id,
        source=GrantSource.NIHR,
        external_id=opportunity.reference_id,
        title=opportunity.title or "Untitled NIHR Opportunity",
        url=opportunity.url,
        status=status,
        is_active=is_active,
        sections=sections,
        programme=programme,
        tags=tags,
        raw=_build_raw_data(opportunity),
        processing=ProcessingInfo(
            scraped_at=now,
            normalized_at=now,
            sections_extracted=_list_extracted_sections(sections),
            scraper_version="nihr_v3",
            schema_version="3.0",
        ),
        created_at=now,
        updated_at=now,
    )
    
    return grant


# =============================================================================
# STATUS INFERENCE
# =============================================================================

def infer_nihr_status(opportunity: NihrFundingOpportunity) -> GrantStatus:
    """
    Infer NIHR status with proper timezone handling.
    
    Returns: GrantStatus enum
    """
    import pytz
    
    status_raw = (opportunity.opportunity_status or "").strip().lower()
    now = now_london()
    
    # Make dates timezone-aware if they're naive
    opening_date = opportunity.opening_date
    if opening_date and opening_date.tzinfo is None:
        opening_date = pytz.timezone('Europe/London').localize(opening_date)
    
    closing_date = opportunity.closing_date
    if closing_date and closing_date.tzinfo is None:
        closing_date = pytz.timezone('Europe/London').localize(closing_date)
    
    if status_raw.startswith("open"):
        if closing_date and closing_date < now:
            return GrantStatus.CLOSED
        return GrantStatus.OPEN
    
    if status_raw.startswith("closed"):
        return GrantStatus.CLOSED
    
    if "opening soon" in status_raw or "launching soon" in status_raw:
        return GrantStatus.FORTHCOMING
    
    if "forthcoming" in status_raw:
        return GrantStatus.FORTHCOMING
    
    # Fallback: infer from dates
    if opening_date and opening_date > now:
        return GrantStatus.FORTHCOMING
    if closing_date and closing_date < now:
        return GrantStatus.CLOSED
    if opening_date and (not closing_date or opening_date <= now):
        return GrantStatus.OPEN
    
    return GrantStatus.UNKNOWN


# =============================================================================
# SECTION EXTRACTION
# =============================================================================

def _extract_sections(opp: NihrFundingOpportunity) -> GrantSections:
    """Extract all sections from NIHR opportunity."""
    
    # Find sections by slug/name
    # The scraper returns sections as list of dicts with 'slug', 'title', 'text', 'html' keys
    sections_by_slug = {}
    for section in opp.sections:
        slug = section.get('slug', '').lower().strip()
        title = section.get('title', '').lower().strip()
        # Use slug if available, otherwise convert title to slug format
        key = slug if slug else title.replace(' ', '-')
        if key:
            sections_by_slug[key] = section
            logger.debug(f"Section key: {key} -> {len(section.get('text', ''))} chars")
    
    logger.debug(f"Available section keys: {list(sections_by_slug.keys())}")
    
    now = datetime.now(timezone.utc)
    
    return GrantSections(
        summary=_extract_summary_section(opp, sections_by_slug, now),
        eligibility=_extract_eligibility_section(opp, sections_by_slug, now),
        scope=_extract_scope_section(opp, sections_by_slug, now),
        dates=_extract_dates_section(opp, now),
        funding=_extract_funding_section(opp, sections_by_slug, now),
        how_to_apply=_extract_how_to_apply_section(opp, sections_by_slug, now),
        assessment=_extract_assessment_section(opp, sections_by_slug, now),
        supporting_info=_extract_supporting_info_section(opp, now),
        contacts=_extract_contacts_section(opp, sections_by_slug, now),
    )


def _extract_summary_section(
    opp: NihrFundingOpportunity,
    sections: Dict[str, Any],
    now: datetime
) -> SummarySection:
    """Extract summary from Overview section."""
    
    # Try to find overview section
    overview_text = ""
    overview_html = None
    
    # Look for overview section by various possible keys
    for key in ['overview', 'about', 'summary', 'about-this-opportunity']:
        if key in sections:
            section = sections[key]
            overview_text = section.get('text', '') or ''
            overview_html = section.get('html')
            logger.debug(f"Found summary in section '{key}': {len(overview_text)} chars")
            break
    
    # Fallback to description if no overview section found
    if not overview_text and opp.description:
        overview_text = opp.description
        logger.debug(f"Using description as summary: {len(overview_text)} chars")
    
    # Clean up boilerplate
    overview_text = _clean_overview_text(overview_text)
    
    # Extract programme name from title if not provided
    programme_name = opp.programme
    if not programme_name:
        programme_name = _infer_programme_name_from_title(opp.title or "")
    
    return SummarySection(
        text=overview_text[:5000] if overview_text else "",
        html=overview_html,
        opportunity_type=opp.opportunity_type,
        programme_name=programme_name,
        extracted_at=now,
    )


def _extract_eligibility_section(
    opp: NihrFundingOpportunity,
    sections: Dict[str, Any],
    now: datetime
) -> EligibilitySection:
    """Extract eligibility information."""
    
    eligibility_text = ""
    who_can_apply = []
    
    # Try to find eligibility content in dedicated sections
    for key in ['eligibility', 'who-can-apply', 'application-guidance']:
        if key in sections:
            text = sections[key].get('text', '') or ''
            if 'eligib' in text.lower() or 'who can' in text.lower():
                eligibility_text = text
                break
    
    # For HTA/commissioned calls with minimal tabs, use overview as fallback
    if not eligibility_text and 'overview' in sections:
        overview_text = sections['overview'].get('text', '') or ''
        # Check if overview has eligibility-related content
        if any(term in overview_text.lower() for term in ['applicant', 'eligible', 'who can apply', 'lead applicant', 'nhs', 'university']):
            eligibility_text = overview_text
    
    # Also check description as last resort
    if not eligibility_text and opp.description:
        eligibility_text = opp.description
    
    # Extract who can apply patterns from all available text
    all_text = f"{eligibility_text} {opp.description or ''}"
    who_can_apply = _extract_who_can_apply(all_text)
    
    # Detect partnership requirements
    partnership_required = _detect_partnership_required(all_text)
    
    return EligibilitySection(
        text=eligibility_text[:3000] if eligibility_text else "",
        who_can_apply=who_can_apply,
        geographic_scope="UK",  # NIHR is typically UK-focused
        uk_registered_required=True,
        partnership_required=partnership_required,
        extracted_at=now,
    )


def _extract_scope_section(
    opp: NihrFundingOpportunity,
    sections: Dict[str, Any],
    now: datetime
) -> ScopeSection:
    """Extract scope from Research specification section."""
    
    scope_text = ""
    
    # Try research specification first (NIHR-specific), then other possible keys
    for key in ['research-specification', 'research-spec', 'scope', 'strategic-themes', 
                'about-this-call', 'call-specification']:
        if key in sections:
            scope_text = sections[key].get('text', '') or ''
            logger.debug(f"Found scope in section '{key}': {len(scope_text)} chars")
            break
    
    # For HTA/commissioned calls with minimal tabs, use overview as fallback
    if not scope_text and 'overview' in sections:
        overview_text = sections['overview'].get('text', '') or ''
        # Overview often contains the research scope for commissioned calls
        scope_text = overview_text
    
    # Use description as last resort
    if not scope_text and opp.description:
        scope_text = opp.description
    
    # Clean up the scope text
    scope_text = _clean_scope_text(scope_text)
    
    # Extract themes from title, description, and scope text
    all_text = f"{opp.title or ''} {opp.description or ''} {scope_text}"
    themes = _extract_themes_from_text(all_text)
    
    return ScopeSection(
        text=scope_text[:5000] if scope_text else "",
        themes=themes,
        sectors=["Health", "Social Care"],
        extracted_at=now,
    )


def _extract_dates_section(opp: NihrFundingOpportunity, now: datetime) -> DatesSection:
    """Extract dates information."""
    
    # Build key dates text from key_dates list
    key_dates_text = ""
    if opp.key_dates:
        parts = []
        for kd in opp.key_dates:
            label = kd.get('label', '')
            date = kd.get('date', '')
            if label and date:
                parts.append(f"{label}: {date}")
        key_dates_text = "\n".join(parts)
    
    # Extract deadline time from closing_date
    deadline_time = None
    if opp.closing_date:
        hour = opp.closing_date.hour
        minute = opp.closing_date.minute
        if hour > 0 or minute > 0:
            # Format as 12-hour time
            am_pm = "am" if hour < 12 else "pm"
            hour_12 = hour if hour <= 12 else hour - 12
            if hour_12 == 0:
                hour_12 = 12
            deadline_time = f"{hour_12}:{minute:02d}{am_pm}"
    
    return DatesSection(
        opens_at=opp.opening_date,
        closes_at=opp.closing_date,
        deadline_time=deadline_time,
        timezone="Europe/London",
        key_dates_text=key_dates_text if key_dates_text else None,
        extracted_at=now,
    )


def _extract_funding_section(
    opp: NihrFundingOpportunity,
    sections: Dict[str, Any],
    now: datetime
) -> FundingSection:
    """Extract funding information."""
    
    funding_text = opp.funding_text or ""
    
    # Parse funding amount
    total_pot_display, total_pot_gbp = None, None
    if funding_text:
        total_pot_display, total_pot_gbp = parse_gbp_amount(funding_text)
    
    # If no funding in main field, search sections
    if not total_pot_gbp:
        for section in opp.sections:
            text = section.get('text', '')
            funding_match = _extract_funding_from_text(text)
            if funding_match:
                total_pot_display, total_pot_gbp = funding_match
                if not funding_text:
                    funding_text = total_pot_display
                break
    
    return FundingSection(
        text=funding_text if funding_text else None,
        total_pot_gbp=total_pot_gbp,
        total_pot_display=total_pot_display,
        currency="GBP",
        competition_type=CompetitionType.GRANT,
        extracted_at=now,
    )


def _extract_how_to_apply_section(
    opp: NihrFundingOpportunity,
    sections: Dict[str, Any],
    now: datetime
) -> HowToApplySection:
    """Extract application process information."""
    
    how_to_apply_text = ""
    apply_url = None
    
    # Find application process section
    for key in ['application-process', 'how-to-apply', 'apply']:
        if key in sections:
            how_to_apply_text = sections[key].get('text', '') or ''
            break
    
    # For commissioned calls, application info may be in overview
    if not how_to_apply_text and 'overview' in sections:
        overview_text = sections['overview'].get('text', '') or ''
        if any(term in overview_text.lower() for term in ['submit', 'application', 'apply', 'deadline']):
            how_to_apply_text = overview_text
    
    # Extract apply URL from resources
    for resource in opp.resources:
        url = resource.get('url', '')
        title = resource.get('title', '').lower()
        if 'apply' in title or 'fundingservice' in url or 'oriel' in url:
            apply_url = url
            break
    
    return HowToApplySection(
        text=how_to_apply_text[:3000] if how_to_apply_text else None,
        portal_name="NIHR Funding Service",
        apply_url=apply_url,
        extracted_at=now,
    )


def _extract_assessment_section(
    opp: NihrFundingOpportunity,
    sections: Dict[str, Any],
    now: datetime
) -> AssessmentSection:
    """Extract assessment/application guidance information."""
    
    guidance_text = ""
    
    # Application guidance is key for NIHR
    for key in ['application-guidance', 'guidance', 'assessment']:
        if key in sections:
            guidance_text = sections[key].get('text', '') or ''
            break
    
    # For commissioned calls, guidance may be in overview or supporting-information
    if not guidance_text:
        for key in ['overview', 'supporting-information']:
            if key in sections:
                section_text = sections[key].get('text', '') or ''
                if any(term in section_text.lower() for term in ['guidance', 'criteria', 'assess', 'review']):
                    guidance_text = section_text
                    break
    
    return AssessmentSection(
        text=guidance_text[:3000] if guidance_text else None,
        guidance_text=guidance_text[:5000] if guidance_text else None,
        extracted_at=now,
    )


def _extract_supporting_info_section(
    opp: NihrFundingOpportunity,
    now: datetime
) -> SupportingInfoSection:
    """Extract supporting documents and resources."""
    
    documents = []
    
    for resource in opp.resources:
        url = resource.get('url', '')
        title = resource.get('title', 'Resource')
        res_type = resource.get('type', 'webpage')
        
        # Skip empty or invalid
        if not url:
            continue
        
        documents.append(SupportingDocument(
            title=title,
            url=url,
            type=res_type.upper() if res_type else None,
        ))
    
    return SupportingInfoSection(
        documents=documents,
        extracted_at=now,
    )


def _extract_contacts_section(
    opp: NihrFundingOpportunity,
    sections: Dict[str, Any],
    now: datetime
) -> ContactsSection:
    """Extract contact information."""
    
    contact_text = ""
    helpdesk_email = None
    
    # Find contact section
    for key in ['contact-details', 'contact', 'contacts']:
        if key in sections:
            contact_text = sections[key].get('text', '')
            break
    
    # Extract email from text
    email_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', contact_text)
    if email_match:
        helpdesk_email = email_match.group(0)
    
    # Also check extra metadata
    if not helpdesk_email and opp.extra:
        helpdesk_email = opp.extra.get('contact_email')
    
    contacts = []
    if helpdesk_email:
        contacts.append(Contact(
            email=helpdesk_email,
            organisation="NIHR",
        ))
    
    return ContactsSection(
        text=contact_text[:1000] if contact_text else None,
        contacts=contacts,
        helpdesk_email=helpdesk_email,
        extracted_at=now,
    )


# =============================================================================
# PROGRAMME INFO
# =============================================================================

def _extract_programme_info(opp: NihrFundingOpportunity) -> ProgrammeInfo:
    """Extract programme metadata."""
    
    # Try to get programme name from scraper, or infer from title
    programme_name = opp.programme
    if not programme_name:
        programme_name = _infer_programme_name_from_title(opp.title or "")
    
    programme_code = _infer_programme_code(programme_name or opp.title or "")
    
    return ProgrammeInfo(
        name=programme_name if programme_name else None,
        code=programme_code,
        funder="NIHR",
        nihr_programme=programme_code,
    )


def _infer_programme_name_from_title(title: str) -> Optional[str]:
    """Infer programme name from opportunity title."""
    if not title:
        return None
    
    title_lower = title.lower()
    
    # Check for HTA commissioned call number pattern (e.g., "23/101", "24/56")
    # These are Health Technology Assessment commissioned calls
    import re
    if re.match(r'^\d{2}/\d+\s', title):
        return 'Health Technology Assessment'
    
    # Map title patterns to programme names
    programme_patterns = [
        # Core programmes
        ('programme grants for applied research', 'Programme Grants for Applied Research'),
        ('programme development grant', 'Programme Development Grants'),
        ('health technology assessment', 'Health Technology Assessment'),
        ('efficacy and mechanism evaluation', 'Efficacy and Mechanism Evaluation'),
        ('health and social care delivery research', 'Health and Social Care Delivery Research'),
        ('health services and delivery research', 'Health and Social Care Delivery Research'),
        ('public health research', 'Public Health Research'),
        ('research for patient benefit', 'Research for Patient Benefit'),
        ('invention for innovation', 'Invention for Innovation'),
        ('global health research', 'Global Health Research'),
        
        # Career development
        ('academic clinical fellowship', 'Academic Clinical Fellowship'),
        ('clinical lectureship', 'Clinical Lectureship'),
        ('advanced clinical and practitioner academic fellowship', 'Advanced Clinical and Practitioner Academic Fellowship'),
        ('acaf', 'Advanced Clinical and Practitioner Academic Fellowship'),
        ('advanced local authority fellowship', 'Advanced Local Authority Fellowship'),
        ('alaf', 'Advanced Local Authority Fellowship'),
        ('advanced fellowship', 'Advanced Fellowship'),
        ('development and skills enhancement award', 'Development and Skills Enhancement Award'),
        ('dsea', 'Development and Skills Enhancement Award'),
        
        # Other programmes
        ('team science award', 'Team Science Award'),
        ('better methods, better research', 'Better Methods Better Research'),
        ('bmbr', 'Better Methods Better Research'),
        ('application development award', 'Application Development Award'),
        ('ada', 'Application Development Award'),
        ('policy research unit', 'Policy Research Unit'),
        ('pru', 'Policy Research Unit'),
        ('research design service', 'Research Design Service'),
        ('rds', 'Research Design Service'),
        ('systematic review', 'Systematic Review'),
        ('evidence synthesis', 'Evidence Synthesis'),
        ('platform study', 'Platform Study'),
        ('e-trial', 'E-Trials'),
        
        # Infrastructure
        ('biomedical research centre', 'Biomedical Research Centre'),
        ('brc', 'Biomedical Research Centre'),
        ('clinical research facility', 'Clinical Research Facility'),
        ('crf', 'Clinical Research Facility'),
        ('applied research collaboration', 'Applied Research Collaboration'),
        ('arc', 'Applied Research Collaboration'),
        
        # Abbreviated forms
        ('phirst', 'Public Health Research'),
        ('pgfar', 'Programme Grants for Applied Research'),
        ('pdg', 'Programme Development Grants'),
        ('hta', 'Health Technology Assessment'),
        ('eme', 'Efficacy and Mechanism Evaluation'),
        ('hsdr', 'Health and Social Care Delivery Research'),
        ('phr', 'Public Health Research'),
        ('rfpb', 'Research for Patient Benefit'),
        ('i4i', 'Invention for Innovation'),
        ('ghr', 'Global Health Research'),
        ('acf', 'Academic Clinical Fellowship'),
    ]
    
    for pattern, name in programme_patterns:
        if pattern in title_lower:
            return name
    
    # If no match found but title looks like a commissioned call topic
    # (research-focused titles without programme indicators)
    # Return None and let it be categorized as "Commissioned Call"
    return None


def _infer_programme_code(text: str) -> Optional[str]:
    """Infer NIHR programme code from programme name or title."""
    
    if not text:
        return None
    
    # Check for HTA commissioned call number pattern (e.g., "23/101", "24/56")
    if re.match(r'^\d{2}/\d+\s', text):
        return 'HTA'
    
    text_lower = text.lower()
    
    # Map common programme names/patterns to codes
    mappings = [
        # Core programmes
        ('programme grants for applied research', 'PGfAR'),
        ('pgfar', 'PGfAR'),
        ('programme development grant', 'PDG'),
        ('health technology assessment', 'HTA'),
        ('efficacy and mechanism evaluation', 'EME'),
        ('health and social care delivery research', 'HSDR'),
        ('health services and delivery research', 'HSDR'),
        ('public health research', 'PHR'),
        ('research for patient benefit', 'RfPB'),
        ('invention for innovation', 'i4i'),
        ('global health research', 'GHR'),
        
        # Career development
        ('academic clinical fellowship', 'ACF'),
        ('clinical lectureship', 'CL'),
        ('advanced clinical and practitioner academic fellowship', 'ACAF'),
        ('acaf', 'ACAF'),
        ('advanced local authority fellowship', 'ALAF'),
        ('alaf', 'ALAF'),
        ('advanced fellowship', 'AF'),
        ('development and skills enhancement award', 'DSEA'),
        ('dsea', 'DSEA'),
        
        # Other programmes
        ('team science award', 'TSA'),
        ('better methods, better research', 'BMBR'),
        ('bmbr', 'BMBR'),
        ('application development award', 'ADA'),
        ('ada', 'ADA'),
        ('policy research unit', 'PRU'),
        ('pru', 'PRU'),
        ('phirst', 'PHR'),
        ('systematic review', 'SR'),
        ('evidence synthesis', 'ES'),
        
        # Infrastructure
        ('biomedical research centre', 'BRC'),
        ('brc', 'BRC'),
        ('clinical research facility', 'CRF'),
        ('crf', 'CRF'),
        ('applied research collaboration', 'ARC'),
        ('arc', 'ARC'),
        
        # Abbreviated forms in titles
        (' hta ', 'HTA'),
        (' eme ', 'EME'),
        (' hsdr ', 'HSDR'),
        (' phr ', 'PHR'),
        (' rfpb ', 'RfPB'),
        (' i4i ', 'i4i'),
        (' ghr ', 'GHR'),
        (' acf ', 'ACF'),
        (' pdg ', 'PDG'),
    ]
    
    for pattern, code in mappings:
        if pattern in text_lower:
            return code
    
    return None


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _generate_grant_id(opp: NihrFundingOpportunity) -> str:
    """Generate stable grant ID."""
    if opp.reference_id:
        # Clean reference ID
        ref = re.sub(r'[^\w]', '_', opp.reference_id)
        return f"nihr_{ref}"
    
    # Fallback to opportunity_id
    return opp.opportunity_id


def _clean_overview_text(text: str) -> str:
    """Remove boilerplate from overview text."""
    if not text:
        return ""
    
    # Remove just the "This opportunity is now closed" line (not everything after it)
    text = re.sub(
        r'This opportunity is now closed\.?\s*',
        '',
        text,
        flags=re.IGNORECASE
    )
    
    # Remove "Applications are now being assessed" line
    text = re.sub(
        r'Applications are now being assessed\.?\s*',
        '',
        text,
        flags=re.IGNORECASE
    )
    
    # Remove redundant "Overview" heading at start
    text = re.sub(
        r'^Overview\s+',
        '',
        text,
        flags=re.IGNORECASE
    )
    
    return text.strip()


def _clean_scope_text(text: str) -> str:
    """Clean scope text."""
    if not text:
        return ""
    
    # Remove just the closed/status message line
    text = re.sub(
        r'This opportunity is now closed\.?\s*',
        '',
        text,
        flags=re.IGNORECASE
    )
    
    return text.strip()


def _extract_who_can_apply(text: str) -> List[str]:
    """Extract who can apply from text."""
    who_can_apply = []
    
    patterns = [
        (r'NHS', 'NHS Trust'),
        (r'universit', 'University'),
        (r'academic', 'Academic Institution'),
        (r'clinical', 'Clinical Researcher'),
        (r'SME|small.*?medium', 'SME'),
        (r'charit', 'Charity'),
        (r'research organisation', 'Research Organisation'),
    ]
    
    text_lower = text.lower()
    
    for pattern, label in patterns:
        if re.search(pattern, text_lower, re.IGNORECASE):
            if label not in who_can_apply:
                who_can_apply.append(label)
    
    return who_can_apply


def _detect_partnership_required(text: str) -> Optional[bool]:
    """Detect if partnership is required."""
    if not text:
        return None
    
    text_lower = text.lower()
    
    if 'must partner' in text_lower or 'partnership required' in text_lower:
        return True
    if 'collaboration' in text_lower and 'required' in text_lower:
        return True
    
    return None


def _extract_themes_from_text(text: str) -> List[str]:
    """Extract themes from text."""
    themes = []
    
    if not text:
        return themes
    
    text_lower = text.lower()
    
    theme_patterns = [
        (r'mental health', 'Mental Health'),
        (r'cancer', 'Cancer'),
        (r'cardiovascular|heart', 'Cardiovascular'),
        (r'diabetes', 'Diabetes'),
        (r'dementia|alzheimer', 'Dementia'),
        (r'digital health', 'Digital Health'),
        (r'social care', 'Social Care'),
        (r'public health', 'Public Health'),
        (r'dentistry|dental', 'Dentistry'),
        (r'primary care', 'Primary Care'),
        (r'rehabilitation', 'Rehabilitation'),
        (r'rare disease', 'Rare Diseases'),
        (r'paediatric|child', 'Paediatrics'),
        (r'infectious disease|antimicrobial', 'Infectious Disease'),
        (r'respiratory', 'Respiratory'),
        (r'musculoskeletal', 'Musculoskeletal'),
        (r'clinical fellowship|lectureship', 'Career Development'),
        (r'health inequalit', 'Health Inequalities'),
        (r'ageing|older people', 'Ageing'),
        (r'obesity|weight', 'Obesity'),
        (r'stroke', 'Stroke'),
        (r'kidney|renal', 'Renal'),
        (r'liver', 'Liver'),
        (r'AI|artificial intelligence|machine learning', 'AI/ML'),
        (r'under-represented disciplines', 'Under-represented Disciplines'),
        (r'applied research', 'Applied Research'),
    ]
    
    for pattern, theme in theme_patterns:
        if re.search(pattern, text_lower, re.IGNORECASE):
            if theme not in themes:
                themes.append(theme)
    
    return themes


def _extract_funding_from_text(text: str) -> Optional[Tuple[str, int]]:
    """Extract funding amount from text."""
    if not text:
        return None
    
    # Pattern: "up to £X million"
    match = re.search(
        r'up to £\s*([\d,.]+)\s*(million|m)',
        text,
        re.IGNORECASE
    )
    if match:
        amount_str = match.group(1).replace(',', '')
        try:
            amount = float(amount_str) * 1_000_000
            display = match.group(0)
            return display, int(amount)
        except ValueError:
            pass
    
    # Pattern: "£X million"
    match = re.search(
        r'£\s*([\d,.]+)\s*(million|m)',
        text,
        re.IGNORECASE
    )
    if match:
        amount_str = match.group(1).replace(',', '')
        try:
            amount = float(amount_str) * 1_000_000
            display = match.group(0)
            return display, int(amount)
        except ValueError:
            pass
    
    return None


def _extract_tags(opp: NihrFundingOpportunity) -> List[str]:
    """Extract searchable tags."""
    tags = ["nihr", "health_research"]
    
    # Add programme tag from programme name or inferred from title
    programme_name = opp.programme or _infer_programme_name_from_title(opp.title or "")
    if programme_name:
        prog_tag = programme_name.lower().replace(' ', '_')
        tags.append(prog_tag)
    
    # Add programme code tag
    programme_code = _infer_programme_code(programme_name or opp.title or "")
    if programme_code:
        tags.append(programme_code.lower())
    
    # Add type tag
    if opp.opportunity_type:
        type_tag = opp.opportunity_type.lower().replace(' ', '_')
        tags.append(type_tag)
    
    # Add funding level tags
    if opp.funding_text:
        fund_lower = opp.funding_text.lower()
        if 'million' in fund_lower:
            tags.append('large_fund')
        elif 'thousand' in fund_lower or '000' in fund_lower:
            tags.append('small_fund')
    
    # Add status tags
    if opp.opening_date and opp.closing_date:
        tags.append('dated')
    else:
        tags.append('rolling')
    
    # Add umbrella tag if applicable
    if 'sub_opportunities' in opp.extra:
        tags.append('umbrella_programme')
    
    return tags


def _build_raw_data(opp: NihrFundingOpportunity) -> Dict[str, Any]:
    """Build raw data dict for storage."""
    return {
        'opportunity_id': opp.opportunity_id,
        'reference_id': opp.reference_id,
        'programme': opp.programme,
        'opportunity_status': opp.opportunity_status,
        'opportunity_type': opp.opportunity_type,
        'funding_text': opp.funding_text,
        'sections_count': len(opp.sections),
        'resources_count': len(opp.resources),
        'key_dates_count': len(opp.key_dates),
    }


def _list_extracted_sections(sections: GrantSections) -> List[str]:
    """List which sections have content."""
    extracted = []
    
    if sections.summary.text:
        extracted.append('summary')
    if sections.eligibility.text:
        extracted.append('eligibility')
    if sections.scope.text:
        extracted.append('scope')
    if sections.dates.opens_at or sections.dates.closes_at:
        extracted.append('dates')
    if sections.funding.text or sections.funding.total_pot_gbp:
        extracted.append('funding')
    if sections.how_to_apply.text:
        extracted.append('how_to_apply')
    if sections.assessment.text or sections.assessment.guidance_text:
        extracted.append('assessment')
    if sections.supporting_info.documents:
        extracted.append('supporting_info')
    if sections.contacts.text or sections.contacts.helpdesk_email:
        extracted.append('contacts')
    
    return extracted


# =============================================================================
# EXPORT HELPERS
# =============================================================================

def grant_to_flat_dict(grant: Grant) -> Dict[str, Any]:
    """
    Flatten Grant to dict for Excel export.
    
    Converts nested sections to prefixed columns.
    """
    flat = {
        'grant_id': grant.grant_id,
        'source': grant.source.value,
        'external_id': grant.external_id,
        'title': grant.title,
        'url': grant.url,
        'status': grant.status.value,
        'is_active': grant.is_active,
        'tags': ','.join(grant.tags) if grant.tags else '',
        
        # Summary
        'summary_text': grant.sections.summary.text,
        'summary_opportunity_type': grant.sections.summary.opportunity_type,
        'summary_programme_name': grant.sections.summary.programme_name,
        
        # Eligibility
        'eligibility_text': grant.sections.eligibility.text,
        'eligibility_who_can_apply': ','.join(grant.sections.eligibility.who_can_apply),
        'eligibility_countries': ','.join(grant.sections.eligibility.eligible_countries),
        'eligibility_geographic_scope': grant.sections.eligibility.geographic_scope,
        'eligibility_partnership_required': grant.sections.eligibility.partnership_required,
        
        # Scope
        'scope_text': grant.sections.scope.text,
        'scope_themes': ','.join(grant.sections.scope.themes),
        'scope_sectors': ','.join(grant.sections.scope.sectors),
        'scope_trl_range': grant.sections.scope.trl_range,
        'scope_topic_code': grant.sections.scope.topic_code,
        
        # Dates
        'dates_opens_at': grant.sections.dates.opens_at,
        'dates_closes_at': grant.sections.dates.closes_at,
        'dates_deadline_time': grant.sections.dates.deadline_time,
        'dates_timezone': grant.sections.dates.timezone,
        'dates_project_duration': grant.sections.dates.project_duration,
        
        # Funding
        'funding_text': grant.sections.funding.text,
        'funding_total_pot_gbp': grant.sections.funding.total_pot_gbp,
        'funding_total_pot_eur': grant.sections.funding.total_pot_eur,
        'funding_total_pot_display': grant.sections.funding.total_pot_display,
        'funding_per_project_min': grant.sections.funding.per_project_min_gbp,
        'funding_per_project_max': grant.sections.funding.per_project_max_gbp,
        'funding_rate': grant.sections.funding.funding_rate,
        'funding_competition_type': grant.sections.funding.competition_type.value if grant.sections.funding.competition_type else None,
        
        # How to Apply
        'how_to_apply_text': grant.sections.how_to_apply.text,
        'how_to_apply_portal': grant.sections.how_to_apply.portal_name,
        'how_to_apply_url': grant.sections.how_to_apply.apply_url,
        
        # Assessment
        'assessment_text': grant.sections.assessment.text,
        'assessment_criteria': ','.join(grant.sections.assessment.criteria),
        
        # Supporting Docs
        'supporting_docs_count': len(grant.sections.supporting_info.documents),
        'supporting_docs': '|'.join([d.url for d in grant.sections.supporting_info.documents[:5]]),
        
        # Contacts
        'contact_email': grant.sections.contacts.helpdesk_email,
        'contact_url': grant.sections.contacts.helpdesk_url,
        
        # Programme
        'programme_name': grant.programme.name,
        'programme_funder': grant.programme.funder,
        'programme_code': grant.programme.code,
    }
    
    return flat
