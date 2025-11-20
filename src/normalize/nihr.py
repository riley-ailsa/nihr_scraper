"""
Normalizer for NIHR funding opportunities.

Converts NihrFundingOpportunity → Grant + IndexableDocuments
following the same pattern as Innovate UK normalizer.
"""

from datetime import datetime
from typing import Tuple, List, Optional

from src.ingest.nihr_funding import NihrFundingOpportunity
from src.core.domain_models import Grant, IndexableDocument
from src.core.money import parse_gbp_amount
from src.core.time_utils import now_london
from src.core.utils import stable_id_from_url, sha1_text


def normalize_nihr_opportunity(
    opportunity: NihrFundingOpportunity
) -> Tuple[Grant, List[IndexableDocument]]:
    """
    Convert raw NIHR opportunity to normalized Grant + Documents.

    Args:
        opportunity: Raw scraped NIHR data

    Returns:
        Tuple[Grant, List[IndexableDocument]]: Normalized grant and documents
    """
    # Parse funding amount
    funding_display = opportunity.funding_text
    total_fund_display, total_fund_gbp = (None, None)
    if funding_display:
        total_fund_display, total_fund_gbp = parse_gbp_amount(funding_display)

    # Get description with fallback
    description = opportunity.description or _build_overview_text(opportunity) or "NIHR Funding Opportunity"

    # Create Grant object
    grant = Grant(
        id=opportunity.opportunity_id,
        source="nihr",
        external_id=opportunity.reference_id,

        # Core fields
        title=opportunity.title or "Untitled NIHR Opportunity",
        description=description,
        url=opportunity.url,

        # Funding
        total_fund=total_fund_display,
        total_fund_gbp=total_fund_gbp,

        # Dates and status
        opens_at=opportunity.opening_date,
        closes_at=opportunity.closing_date,
        is_active=(infer_nihr_status(opportunity) == "open"),

        # Tags
        tags=_extract_tags(opportunity),

        # Timestamps
        scraped_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )

    # Create documents
    documents = _create_documents(opportunity, grant.id)

    # Apply funding fallbacks if needed (prize pot detection, etc.)
    if not grant.total_fund_gbp or grant.total_fund_gbp == 0:
        grant = _apply_prize_funding_fallback(grant, documents)

    return grant, documents


def infer_nihr_status(opportunity: NihrFundingOpportunity) -> str:
    """
    Infer NIHR status with proper timezone handling.

    Returns: "open" | "closed" | "upcoming" | "unknown"
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
            return "closed"
        return "open"

    if status_raw.startswith("closed"):
        return "closed"

    if "opening soon" in status_raw or "launching soon" in status_raw:
        return "upcoming"

    # Fallback: infer from dates
    if opening_date and opening_date > now:
        return "upcoming"
    if closing_date and closing_date < now:
        return "closed"
    if opening_date and (not closing_date or opening_date <= now):
        return "open"

    return "unknown"


def _normalize_status(status: Optional[str], closing_date: Optional[datetime]) -> str:
    """
    DEPRECATED: Use infer_nihr_status instead.
    Normalize NIHR status to canonical format.

    Args:
        status: Raw status from NIHR page
        closing_date: Closing date if available

    Returns:
        str: One of 'active', 'closed', 'upcoming'
    """
    if not status:
        # Infer from date if status missing
        if closing_date:
            now = now_london()
            return "closed" if now > closing_date else "active"
        return "active"  # Default

    status_lower = status.lower()

    if "open" in status_lower or "active" in status_lower:
        return "active"
    if "closed" in status_lower or "expired" in status_lower:
        return "closed"
    if "upcoming" in status_lower or "forthcoming" in status_lower:
        return "upcoming"

    return "active"  # Default


def _is_active(status: Optional[str], closing_date: Optional[datetime]) -> bool:
    """
    DEPRECATED: Use infer_nihr_status instead.
    Determine if opportunity is currently active.

    Args:
        status: Raw status string
        closing_date: Closing date if available

    Returns:
        bool: True if active
    """
    normalized_status = _normalize_status(status, closing_date)
    return normalized_status == "active"


def _create_documents(
    opportunity: NihrFundingOpportunity,
    grant_id: str
) -> List[IndexableDocument]:
    """
    Create IndexableDocument objects from NIHR opportunity sections and resources.

    Args:
        opportunity: Raw NIHR opportunity
        grant_id: Grant ID for linking

    Returns:
        List[IndexableDocument]: Documents ready for embedding
    """
    documents = []

    # Overview document (combine key metadata)
    overview_text = _build_overview_text(opportunity)
    if overview_text:
        # Use stable ID based on content
        doc_id = stable_id_from_url(f"{opportunity.url}#overview", prefix=f"{grant_id}_")
        documents.append(IndexableDocument(
            id=doc_id,
            grant_id=grant_id,
            doc_type="competition_section",
            scope="competition",
            text=overview_text,
            source_url=opportunity.url,
            section_name="overview",
            citation_text=f"{opportunity.title} - Overview"
        ))

    # Section documents
    for section in opportunity.sections:
        text = section.get("text", "")
        if not text:
            continue

        # Generate stable ID from section URL or content
        section_url = section.get("url", opportunity.url)
        section_slug = section.get("slug", section.get("title", "section").lower().replace(" ", "_"))
        section_title = section.get("title", "Section")

        doc_id = stable_id_from_url(section_url, prefix=f"{grant_id}_")

        documents.append(IndexableDocument(
            id=doc_id,
            grant_id=grant_id,
            doc_type=f"nihr_section::{section_slug}",
            scope="competition",
            text=text,
            source_url=section_url,
            section_name=section_slug,
            citation_text=f"{opportunity.title} - {section_title}"
        ))

    # Resource documents (PDFs, etc.)
    for resource in opportunity.resources:
        if not resource.get("text"):
            continue

        # Generate stable ID from resource URL
        resource_url = resource.get("url", opportunity.url)
        doc_id = stable_id_from_url(resource_url, prefix=f"{grant_id}_")

        # Determine document type based on resource type
        doc_type = "briefing_pdf" if resource.get("type") == "pdf" else "document"

        documents.append(IndexableDocument(
            id=doc_id,
            grant_id=grant_id,
            doc_type=doc_type,
            scope="competition",
            text=resource["text"],
            source_url=resource_url,
            citation_text=f"{opportunity.title} - {resource.get('title', 'Resource')}"
        ))

    # Sub-opportunities (if umbrella page)
    if "sub_opportunities" in opportunity.extra:
        sub_opps = opportunity.extra["sub_opportunities"]
        if sub_opps:
            sub_text = _build_sub_opportunities_text(sub_opps)
            doc_id = stable_id_from_url(f"{opportunity.url}#sub_opportunities", prefix=f"{grant_id}_")

            documents.append(IndexableDocument(
                id=doc_id,
                grant_id=grant_id,
                doc_type="competition_section",
                scope="programme",
                text=sub_text,
                source_url=opportunity.url,
                section_name="related_opportunities",
                citation_text=f"{opportunity.title} - Related Opportunities"
            ))

    return documents


def _build_overview_text(opportunity: NihrFundingOpportunity) -> str:
    """
    Build overview text from opportunity metadata.

    Args:
        opportunity: NIHR opportunity

    Returns:
        str: Formatted overview text
    """
    parts = []

    if opportunity.title:
        parts.append(f"Title: {opportunity.title}")

    if opportunity.programme:
        parts.append(f"Programme: {opportunity.programme}")

    if opportunity.reference_id:
        parts.append(f"Reference: {opportunity.reference_id}")

    if opportunity.opportunity_type:
        parts.append(f"Type: {opportunity.opportunity_type}")

    if opportunity.opportunity_status:
        parts.append(f"Status: {opportunity.opportunity_status}")

    if opportunity.funding_text:
        parts.append(f"Funding: {opportunity.funding_text}")

    if opportunity.opening_date:
        parts.append(f"Opens: {opportunity.opening_date.strftime('%Y-%m-%d')}")

    if opportunity.closing_date:
        parts.append(f"Closes: {opportunity.closing_date.strftime('%Y-%m-%d')}")

    # Key dates
    if opportunity.key_dates:
        parts.append("\nKey Dates:")
        for date_item in opportunity.key_dates:
            parts.append(f"- {date_item.get('label', 'Date')}: {date_item.get('date', 'TBD')}")

    return "\n".join(parts)


def _build_sub_opportunities_text(sub_opportunities: List[dict]) -> str:
    """
    Build text summary of sub-opportunities for umbrella pages.

    Args:
        sub_opportunities: List of sub-opportunity dicts

    Returns:
        str: Formatted text
    """
    if not sub_opportunities:
        return ""

    parts = [
        "This is an umbrella programme containing multiple funding opportunities:",
        ""
    ]

    for idx, sub in enumerate(sub_opportunities, 1):
        parts.append(f"{idx}. {sub.get('title', 'Untitled')}")
        parts.append(f"   URL: {sub.get('url', 'N/A')}")
        parts.append("")

    return "\n".join(parts)


def _extract_tags(opportunity: NihrFundingOpportunity) -> List[str]:
    """
    Extract searchable tags from opportunity metadata.

    Args:
        opportunity: NIHR opportunity

    Returns:
        List[str]: Tags for filtering and search
    """
    tags = ["nihr"]

    # Add programme tag
    if opportunity.programme:
        tags.append(opportunity.programme.lower().replace(" ", "_"))

    # Add type tag
    if opportunity.opportunity_type:
        tags.append(opportunity.opportunity_type.lower().replace(" ", "_"))

    # Add funding level tags
    if opportunity.funding_text:
        fund_lower = opportunity.funding_text.lower()
        if "million" in fund_lower:
            tags.append("large_fund")
        elif "thousand" in fund_lower:
            tags.append("small_fund")

    # Add status tags
    if opportunity.opening_date and opportunity.closing_date:
        tags.append("dated")
    else:
        tags.append("rolling")

    # Add umbrella tag if applicable
    if "sub_opportunities" in opportunity.extra:
        tags.append("umbrella_programme")

    return tags


def _apply_prize_funding_fallback(
    grant: Grant,
    documents: List[IndexableDocument]
) -> Grant:
    """
    Apply prize funding fallback if standard parser failed.

    Searches document text for prize-style funding patterns.
    Only applies if grant currently has no funding amount.

    Args:
        grant: Grant object (possibly with null funding)
        documents: Created documents

    Returns:
        Updated grant with prize funding if detected, otherwise unchanged
    """
    import re

    # Skip if we already have funding
    if grant.total_fund_gbp:
        return grant

    # Prize funding patterns
    prize_pat = re.compile(
        r"(share of (?:a |an )?£\s*([\d,.]+)\s*(?:m|million)?\s*(?:prize\s*pot|prize\s*fund))",
        flags=re.IGNORECASE
    )

    per_award_pat = re.compile(
        r"£\s*([\d,.]+)\s*(k|thousand|million|m)?\s*(?:each|per (?:winner|project|award))",
        flags=re.IGNORECASE
    )

    # Search document text
    for doc in documents:
        text = doc.text

        # Priority 1: "share of a £X million prize pot"
        match = prize_pat.search(text)
        if match:
            full_text = match.group(1)
            amount_str = match.group(2).replace(",", "")

            # Check if "million" is explicitly mentioned
            if "million" in full_text.lower() or "m" in full_text.lower():
                amount = float(amount_str) * 1_000_000
            else:
                # Assume millions for prize pots
                amount = float(amount_str) * 1_000_000

            grant.total_fund = full_text
            grant.total_fund_gbp = int(amount)
            return grant

        # Priority 2: "£X per winner/each"
        match = per_award_pat.search(text)
        if match:
            amount_str = match.group(1).replace(",", "")
            magnitude = match.group(2)

            amount = float(amount_str)

            if magnitude:
                mag_lower = magnitude.lower()
                if mag_lower in ("m", "million"):
                    amount *= 1_000_000
                elif mag_lower in ("k", "thousand"):
                    amount *= 1_000

            grant.total_fund = match.group(0)
            grant.total_fund_gbp = int(amount)
            return grant

    return grant
