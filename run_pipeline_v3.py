#!/usr/bin/env python3
"""
NIHR Scraper Pipeline v3

Uses the existing NihrFundingScraper with new ailsa_shared v3 schema.

The original scraper modules (ingest, enhance) are preserved unchanged.
Only the normalization layer is updated to output the sectioned Grant format.

Usage:
    # Scrape and export to Excel for testing
    python run_pipeline.py --limit 20 --dry-run
    
    # Scrape with link following (slower, more data)
    python run_pipeline.py --limit 20 --dry-run --follow-links
    
    # Full production run (no --dry-run)
    python run_pipeline.py
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress FutureWarning from soupsieve
import warnings
warnings.filterwarnings('ignore', category=FutureWarning, module='soupsieve')

# Import existing scraper
from src.ingest.nihr_funding import NihrFundingScraper

# Import v3 normalizer
from normalize_nihr_v3 import normalize_nihr_v3, grant_to_flat_dict

# Import ailsa_shared models
from ailsa_shared.models import Grant, GrantStatus


def load_urls(filepath: str) -> List[str]:
    """Load NIHR opportunity URLs from file."""
    path = Path(filepath)
    
    if not path.exists():
        logger.warning(f"URL file not found: {filepath}")
        return []
    
    with path.open() as f:
        urls = [
            line.strip()
            for line in f
            if line.strip() and not line.startswith("#")
        ]
    
    logger.info(f"Loaded {len(urls)} URLs from {filepath}")
    return urls


def scrape_opportunity(
    url: str,
    scraper: NihrFundingScraper,
    follow_links: bool = False
) -> Optional[Grant]:
    """
    Scrape a single opportunity and normalize to v3 schema.
    
    Args:
        url: NIHR funding page URL
        scraper: Configured scraper instance
        follow_links: Whether to follow linked pages/PDFs
        
    Returns:
        Grant object or None on failure
    """
    try:
        # Step 1: Scrape using existing scraper
        opp = scraper.scrape(url)
        
        # Step 2: Optionally enhance with link following
        if follow_links:
            opp = enhance_with_links(opp, scraper)
        
        # Step 3: Normalize to v3 schema
        grant = normalize_nihr_v3(opp)
        
        logger.info(f"✅ {grant.title[:60]}...")
        return grant
        
    except Exception as e:
        logger.error(f"❌ Error scraping {url}: {type(e).__name__}: {str(e)[:100]}")
        return None


def enhance_with_links(opp, scraper) -> Any:
    """
    Enhance opportunity by following linked pages and PDFs.
    
    Uses the existing enhance modules from the scraper.
    """
    try:
        from src.enhance.pdf_enhancer import PDFEnhancer
        from src.enhance.link_follower import LinkFollower
        from src.ingest.resource_fetcher import ResourceFetcher
        
        fetcher = ResourceFetcher()
        
        # Follow linked pages
        link_follower = LinkFollower(fetcher, max_links=5)
        linked_docs = link_follower.follow_links(
            opp.opportunity_id,
            opp.resources,
            opp.url
        )
        
        # Fetch PDFs
        pdf_enhancer = PDFEnhancer(fetcher)
        pdf_docs = pdf_enhancer.enhance(opp.opportunity_id, opp.resources)
        
        # Add extracted text back to resources
        for doc in linked_docs + pdf_docs:
            if doc.text:
                opp.resources.append({
                    'title': doc.section_name or doc.citation_text,
                    'url': doc.source_url,
                    'type': doc.doc_type,
                    'text': doc.text,
                })
        
        logger.info(f"  Enhanced with {len(linked_docs)} links, {len(pdf_docs)} PDFs")
        
    except ImportError:
        logger.warning("Enhance modules not available, skipping link following")
    except Exception as e:
        logger.warning(f"Enhancement failed: {e}")
    
    return opp


def export_to_excel(grants: List[Grant], output_path: str):
    """Export grants to Excel for testing."""
    import pandas as pd
    
    # Convert to flat dicts
    rows = [grant_to_flat_dict(g) for g in grants]
    
    df = pd.DataFrame(rows)
    
    # Handle timezone-aware datetimes
    for col in df.columns:
        if 'date' in col.lower() or col.endswith('_at'):
            try:
                df[col] = pd.to_datetime(df[col], errors='coerce')
                if df[col].dt.tz is not None:
                    df[col] = df[col].dt.tz_localize(None)
            except Exception:
                pass
    
    df.to_excel(output_path, index=False, sheet_name='NIHR')
    logger.info(f"Exported {len(grants)} grants to {output_path}")


def run_pipeline(
    limit: Optional[int] = None,
    dry_run: bool = False,
    follow_links: bool = False,
    urls_file: str = "data/urls/nihr_urls.txt"
) -> List[Grant]:
    """
    Run the NIHR scraper pipeline.
    
    Args:
        limit: Maximum number of grants to scrape (None = all)
        dry_run: If True, export to Excel instead of database
        follow_links: If True, follow linked pages/PDFs for enhancement
        urls_file: Path to file containing URLs to scrape
        
    Returns:
        List of scraped Grant objects
    """
    logger.info("=" * 70)
    logger.info("NIHR SCRAPER PIPELINE v3")
    logger.info("=" * 70)
    
    # Load URLs
    urls = load_urls(urls_file)
    
    if not urls:
        logger.error("No URLs to process")
        return []
    
    if limit:
        urls = urls[:limit]
        logger.info(f"Limited to {limit} URLs")
    
    logger.info(f"Processing {len(urls)} opportunities...")
    
    # Initialize scraper
    scraper = NihrFundingScraper()
    
    # Process each URL
    grants = []
    for i, url in enumerate(urls, 1):
        logger.info(f"\n[{i}/{len(urls)}] {url}")
        
        grant = scrape_opportunity(url, scraper, follow_links=follow_links)
        
        if grant:
            grants.append(grant)
    
    # Summary
    logger.info(f"\n" + "=" * 70)
    logger.info("PIPELINE COMPLETE")
    logger.info("=" * 70)
    logger.info(f"Processed: {len(urls)}")
    logger.info(f"Success: {len(grants)}")
    logger.info(f"Failed: {len(urls) - len(grants)}")
    
    # Status breakdown
    status_counts = {}
    for g in grants:
        status = g.status.value
        status_counts[status] = status_counts.get(status, 0) + 1
    
    logger.info(f"\nStatus breakdown:")
    for status, count in sorted(status_counts.items()):
        logger.info(f"  {status}: {count}")
    
    # Section extraction stats
    section_counts = {
        'summary': 0,
        'eligibility': 0,
        'scope': 0,
        'dates': 0,
        'funding': 0,
        'how_to_apply': 0,
        'assessment': 0,
        'supporting_info': 0,
        'contacts': 0,
    }
    
    for g in grants:
        if g.sections.summary.text:
            section_counts['summary'] += 1
        if g.sections.eligibility.text:
            section_counts['eligibility'] += 1
        if g.sections.scope.text:
            section_counts['scope'] += 1
        if g.sections.dates.opens_at or g.sections.dates.closes_at:
            section_counts['dates'] += 1
        if g.sections.funding.text or g.sections.funding.total_pot_gbp:
            section_counts['funding'] += 1
        if g.sections.how_to_apply.text:
            section_counts['how_to_apply'] += 1
        if g.sections.assessment.text:
            section_counts['assessment'] += 1
        if g.sections.supporting_info.documents:
            section_counts['supporting_info'] += 1
        if g.sections.contacts.helpdesk_email:
            section_counts['contacts'] += 1
    
    logger.info(f"\nSection extraction rates:")
    for section, count in section_counts.items():
        pct = (count / len(grants) * 100) if grants else 0
        status = "✅" if pct >= 50 else "⚠️" if pct > 0 else "❌"
        logger.info(f"  {status} {section:20} {count}/{len(grants)} ({pct:.0f}%)")
    
    # Dry run: export to Excel
    if dry_run and grants:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = f"grant_test_export_{timestamp}.xlsx"
        export_to_excel(grants, output_path)
    
    return grants


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='NIHR Scraper Pipeline v3')
    parser.add_argument(
        '--limit', '-l',
        type=int,
        default=None,
        help='Maximum number of grants to scrape'
    )
    parser.add_argument(
        '--dry-run', '-d',
        action='store_true',
        help='Export to Excel instead of database'
    )
    parser.add_argument(
        '--follow-links', '-f',
        action='store_true',
        help='Follow linked pages and PDFs for enhancement'
    )
    parser.add_argument(
        '--urls-file', '-u',
        type=str,
        default='data/urls/nihr_urls.txt',
        help='Path to file containing URLs to scrape'
    )
    
    args = parser.parse_args()
    
    grants = run_pipeline(
        limit=args.limit,
        dry_run=args.dry_run,
        follow_links=args.follow_links,
        urls_file=args.urls_file,
    )
    
    return 0 if grants else 1


if __name__ == "__main__":
    sys.exit(main())
