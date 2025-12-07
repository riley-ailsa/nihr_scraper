"""
Enhancement integration for v3 schema.

Uses existing PDFEnhancer and LinkFollower to extract additional content,
then updates v3 Grant objects with enhanced data including funding extraction.
"""

import re
import logging
from typing import Optional, List, Tuple
from dataclasses import replace

from ailsa_shared.models import Grant, SupportingDocument

# Import existing enhancement modules
from src.ingest.resource_fetcher import ResourceFetcher
from src.enhance.pdf_enhancer import PDFEnhancer
from src.enhance.link_follower import LinkFollower
from src.ingest.nihr_funding import NihrFundingOpportunity

logger = logging.getLogger(__name__)


def enhance_grant_v3(
    grant: Grant,
    opp: NihrFundingOpportunity,
    follow_links: bool = True,
    fetch_pdfs: bool = True,
    max_links: int = 5
) -> Tuple[Grant, List[str]]:
    """
    Enhance a v3 Grant with PDF and linked page content.
    
    Args:
        grant: Normalized v3 Grant object
        opp: Original scraped opportunity (has resources list)
        follow_links: Whether to follow webpage links
        fetch_pdfs: Whether to fetch and parse PDFs
        max_links: Maximum number of links to follow
        
    Returns:
        Tuple of (enhanced Grant, list of enhancement log messages)
    """
    logs = []
    fetcher = ResourceFetcher()
    
    enhanced_docs = []
    pdf_texts = []
    
    # Fetch and parse PDFs
    if fetch_pdfs and opp.resources:
        try:
            pdf_enhancer = PDFEnhancer(fetcher)
            pdf_docs = pdf_enhancer.enhance(grant.grant_id, opp.resources)
            
            for doc in pdf_docs:
                enhanced_docs.append(doc)
                pdf_texts.append(doc.text)
                logs.append(f"PDF: {doc.section_name} ({len(doc.text)} chars)")
                
            logger.info(f"Enhanced {grant.grant_id} with {len(pdf_docs)} PDFs")
        except Exception as e:
            logger.error(f"PDF enhancement failed for {grant.grant_id}: {e}")
            logs.append(f"PDF error: {e}")
    
    # Follow relevant links
    if follow_links and opp.resources:
        try:
            link_follower = LinkFollower(fetcher, max_links=max_links)
            link_docs = link_follower.follow_links(
                grant.grant_id, 
                opp.resources,
                opp.url
            )
            
            for doc in link_docs:
                enhanced_docs.append(doc)
                logs.append(f"Link: {doc.section_name} ({len(doc.text)} chars)")
                
            logger.info(f"Enhanced {grant.grant_id} with {len(link_docs)} linked pages")
        except Exception as e:
            logger.error(f"Link following failed for {grant.grant_id}: {e}")
            logs.append(f"Link error: {e}")
    
    # Extract funding from PDFs if not already present
    if not grant.sections.funding.total_pot_gbp and pdf_texts:
        combined_pdf_text = "\n\n".join(pdf_texts)
        funding_result = extract_funding_from_text(combined_pdf_text)
        
        if funding_result:
            amount_gbp, display_text = funding_result
            # Update funding section
            new_funding = replace(
                grant.sections.funding,
                total_pot_gbp=amount_gbp,
                total_pot_display=display_text,
                text=grant.sections.funding.text or f"Funding: {display_text}"
            )
            new_sections = replace(grant.sections, funding=new_funding)
            grant = replace(grant, sections=new_sections)
            logs.append(f"Extracted funding from PDF: {display_text}")
    
    # Extract per-project funding if not present
    if not grant.sections.funding.per_project_max_gbp and pdf_texts:
        combined_pdf_text = "\n\n".join(pdf_texts)
        project_funding = extract_project_funding_from_text(combined_pdf_text)
        
        if project_funding:
            min_gbp, max_gbp = project_funding
            new_funding = replace(
                grant.sections.funding,
                per_project_min_gbp=min_gbp,
                per_project_max_gbp=max_gbp
            )
            new_sections = replace(grant.sections, funding=new_funding)
            grant = replace(grant, sections=new_sections)
            if min_gbp and max_gbp:
                logs.append(f"Extracted project funding: £{min_gbp:,} - £{max_gbp:,}")
            elif max_gbp:
                logs.append(f"Extracted max project funding: £{max_gbp:,}")
    
    # Add enhanced documents to supporting_info
    if enhanced_docs:
        existing_docs = list(grant.sections.supporting_info.documents or [])
        
        for doc in enhanced_docs:
            supporting_doc = SupportingDocument(
                title=doc.section_name or "Enhanced Document",
                url=doc.source_url,
                type=doc.doc_type,  # 'type' not 'doc_type'
                description=f"Enhanced content: {len(doc.text)} characters extracted"
            )
            existing_docs.append(supporting_doc)
        
        new_supporting = replace(
            grant.sections.supporting_info,
            documents=existing_docs
        )
        new_sections = replace(grant.sections, supporting_info=new_supporting)
        grant = replace(grant, sections=new_sections)
    
    return grant, logs


def extract_funding_from_text(text: str) -> Optional[Tuple[int, str]]:
    """
    Extract total funding amount from text (typically PDF content).
    
    Returns:
        Tuple of (amount_in_gbp, display_string) or None
    """
    if not text:
        return None
    
    text_lower = text.lower()
    
    # Patterns for total funding
    patterns = [
        # "total funding of £X million"
        r'total\s+(?:funding|budget|fund)\s+(?:of\s+)?[£$]?\s*([\d,.]+)\s*(million|m|billion|b|thousand|k)?',
        # "£X million available"
        r'[£$]\s*([\d,.]+)\s*(million|m|billion|b|thousand|k)?\s+(?:is\s+)?available',
        # "funding pot of £X"
        r'funding\s+pot\s+(?:of\s+)?[£$]\s*([\d,.]+)\s*(million|m|billion|b|thousand|k)?',
        # "budget of £X million"
        r'budget\s+(?:of\s+)?[£$]\s*([\d,.]+)\s*(million|m|billion|b|thousand|k)?',
        # "up to £X million"
        r'up\s+to\s+[£$]\s*([\d,.]+)\s*(million|m|billion|b|thousand|k)?',
        # "approximately £X million"
        r'approximately\s+[£$]\s*([\d,.]+)\s*(million|m|billion|b|thousand|k)?',
        # "£X million total"
        r'[£$]\s*([\d,.]+)\s*(million|m|billion|b|thousand|k)?\s+total',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            amount_str = match.group(1).replace(',', '')
            magnitude = match.group(2) if len(match.groups()) > 1 else None
            
            try:
                amount = float(amount_str)
                
                # Apply magnitude
                if magnitude:
                    mag_lower = magnitude.lower()
                    if mag_lower in ('million', 'm'):
                        amount *= 1_000_000
                    elif mag_lower in ('billion', 'b'):
                        amount *= 1_000_000_000
                    elif mag_lower in ('thousand', 'k'):
                        amount *= 1_000
                
                amount_int = int(amount)
                
                # Create display string
                if amount_int >= 1_000_000:
                    display = f"£{amount_int / 1_000_000:.1f} million"
                elif amount_int >= 1_000:
                    display = f"£{amount_int / 1_000:.0f}k"
                else:
                    display = f"£{amount_int:,}"
                
                return (amount_int, display)
                
            except ValueError:
                continue
    
    return None


def extract_project_funding_from_text(text: str) -> Optional[Tuple[Optional[int], Optional[int]]]:
    """
    Extract per-project funding range from text.
    
    Returns:
        Tuple of (min_gbp, max_gbp) or None
    """
    if not text:
        return None
    
    text_lower = text.lower()
    
    # Pattern for range: "£X to £Y" or "between £X and £Y"
    range_patterns = [
        r'(?:between\s+)?[£$]\s*([\d,.]+)\s*(million|m|k)?\s+(?:to|and|-)\s+[£$]?\s*([\d,.]+)\s*(million|m|k)?',
        r'projects?\s+(?:of\s+)?(?:up\s+to\s+)?[£$]\s*([\d,.]+)\s*(million|m|k)?',
        r'maximum\s+(?:of\s+)?[£$]\s*([\d,.]+)\s*(million|m|k)?',
        r'up\s+to\s+[£$]\s*([\d,.]+)\s*(million|m|k)?\s+per\s+project',
    ]
    
    # Try range pattern first
    range_match = re.search(range_patterns[0], text_lower)
    if range_match:
        try:
            min_str = range_match.group(1).replace(',', '')
            min_mag = range_match.group(2)
            max_str = range_match.group(3).replace(',', '')
            max_mag = range_match.group(4)
            
            min_val = _parse_amount(min_str, min_mag)
            max_val = _parse_amount(max_str, max_mag)
            
            if min_val and max_val:
                return (int(min_val), int(max_val))
        except (ValueError, IndexError):
            pass
    
    # Try max-only patterns
    for pattern in range_patterns[1:]:
        match = re.search(pattern, text_lower)
        if match:
            try:
                amount_str = match.group(1).replace(',', '')
                magnitude = match.group(2) if len(match.groups()) > 1 else None
                amount = _parse_amount(amount_str, magnitude)
                if amount:
                    return (None, int(amount))
            except (ValueError, IndexError):
                continue
    
    return None


def _parse_amount(amount_str: str, magnitude: Optional[str]) -> Optional[float]:
    """Parse amount string with optional magnitude."""
    try:
        amount = float(amount_str)
        
        if magnitude:
            mag_lower = magnitude.lower()
            if mag_lower in ('million', 'm'):
                amount *= 1_000_000
            elif mag_lower in ('k',):
                amount *= 1_000
        
        return amount
    except ValueError:
        return None


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def enhance_grants_batch(
    grants: List[Tuple[Grant, NihrFundingOpportunity]],
    follow_links: bool = True,
    fetch_pdfs: bool = True,
    max_links: int = 5
) -> List[Tuple[Grant, List[str]]]:
    """
    Enhance a batch of grants.
    
    Args:
        grants: List of (Grant, NihrFundingOpportunity) tuples
        follow_links: Whether to follow webpage links
        fetch_pdfs: Whether to fetch and parse PDFs
        max_links: Maximum links per grant
        
    Returns:
        List of (enhanced Grant, logs) tuples
    """
    results = []
    
    for i, (grant, opp) in enumerate(grants):
        logger.info(f"Enhancing {i+1}/{len(grants)}: {grant.title[:50]}...")
        
        try:
            enhanced, logs = enhance_grant_v3(
                grant, opp,
                follow_links=follow_links,
                fetch_pdfs=fetch_pdfs,
                max_links=max_links
            )
            results.append((enhanced, logs))
        except Exception as e:
            logger.error(f"Failed to enhance {grant.grant_id}: {e}")
            results.append((grant, [f"Enhancement failed: {e}"]))
    
    return results
