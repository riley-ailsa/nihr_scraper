#!/usr/bin/env python3
"""
Simple test script for NIHR Scraper v3

Run from the NIHR scraper directory:
    cd ~/Ailsa/"NIHR scraper"
    python test_nihr_v3.py --limit 10

This test:
1. Loads URLs from data/urls/nihr_urls.txt
2. Scrapes using your existing NihrFundingScraper
3. Normalizes to ailsa_shared v3 schema
4. Exports to Excel with field completeness stats
"""

import sys
import argparse
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Suppress FutureWarnings
import warnings
warnings.filterwarnings('ignore', category=FutureWarning)


def main():
    parser = argparse.ArgumentParser(description='Test NIHR Scraper v3')
    parser.add_argument('--limit', '-l', type=int, default=10, help='Number of grants to scrape')
    parser.add_argument('--follow-links', '-f', action='store_true', help='Follow linked pages/PDFs')
    args = parser.parse_args()
    
    # Verify we're in the right directory
    if not Path('src/ingest/nihr_funding.py').exists():
        logger.error("Run this from the NIHR scraper directory!")
        logger.error("cd ~/Ailsa/'NIHR scraper'")
        sys.exit(1)
    
    # Import scraper and normalizer
    from src.ingest.nihr_funding import NihrFundingScraper
    from normalize_nihr_v3 import normalize_nihr_v3, grant_to_flat_dict
    
    # Load URLs
    urls_file = Path('data/urls/nihr_urls.txt')
    if not urls_file.exists():
        logger.error(f"URL file not found: {urls_file}")
        sys.exit(1)
    
    with open(urls_file) as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    
    urls = urls[:args.limit]
    logger.info(f"Testing with {len(urls)} URLs")
    
    # Scrape and normalize
    scraper = NihrFundingScraper()
    grants = []
    
    for i, url in enumerate(urls, 1):
        logger.info(f"[{i}/{len(urls)}] {url}")
        
        try:
            # Scrape
            opp = scraper.scrape(url)
            
            # Normalize to v3
            grant = normalize_nihr_v3(opp)
            grants.append(grant)
            
            logger.info(f"  ✅ {grant.title[:50]}...")
            
        except Exception as e:
            logger.error(f"  ❌ {type(e).__name__}: {str(e)[:80]}")
    
    if not grants:
        logger.error("No grants scraped!")
        sys.exit(1)
    
    # Convert to flat dicts for Excel
    rows = [grant_to_flat_dict(g) for g in grants]
    df = pd.DataFrame(rows)
    
    # Handle timezone-aware datetimes
    for col in df.columns:
        if 'date' in col.lower() or col.endswith('_at'):
            try:
                df[col] = pd.to_datetime(df[col], errors='coerce')
                if df[col].dt.tz is not None:
                    df[col] = df[col].dt.tz_localize(None)
            except:
                pass
    
    # Export
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = f"nihr_v3_test_{timestamp}.xlsx"
    df.to_excel(output_file, index=False, sheet_name='NIHR_v3')
    
    logger.info(f"\n{'='*60}")
    logger.info(f"EXPORTED: {output_file}")
    logger.info(f"{'='*60}")
    
    # Field completeness stats
    logger.info(f"\nFIELD COMPLETENESS ({len(grants)} grants):")
    logger.info("-" * 50)
    
    for col in df.columns:
        non_empty = df[col].notna().sum()
        if df[col].dtype == 'object':
            non_empty = (df[col].notna() & (df[col] != '') & (df[col] != '[]')).sum()
        pct = (non_empty / len(df)) * 100
        status = "✅" if pct >= 50 else "⚠️" if pct > 0 else "❌"
        logger.info(f"{status} {col:35} {non_empty:2}/{len(df)} ({pct:3.0f}%)")
    
    # Section summary
    logger.info(f"\nSECTION SUMMARY:")
    logger.info("-" * 50)
    
    section_groups = {
        'Summary': ['summary_text', 'summary_programme_name'],
        'Eligibility': ['eligibility_text', 'eligibility_who_can_apply'],
        'Scope': ['scope_text', 'scope_themes'],
        'Dates': ['dates_opens_at', 'dates_closes_at'],
        'Funding': ['funding_text', 'funding_total_pot_gbp'],
        'How to Apply': ['how_to_apply_text', 'how_to_apply_url'],
        'Assessment': ['assessment_text'],
        'Supporting Info': ['supporting_docs_count'],
        'Contacts': ['contact_email'],
    }
    
    for section, fields in section_groups.items():
        has_data = 0
        for g in grants:
            flat = grant_to_flat_dict(g)
            if any(flat.get(f) for f in fields):
                has_data += 1
        pct = (has_data / len(grants)) * 100
        status = "✅" if pct >= 50 else "⚠️" if pct > 0 else "❌"
        logger.info(f"{status} {section:20} {has_data}/{len(grants)} ({pct:.0f}%)")
    
    # Status breakdown
    logger.info(f"\nSTATUS BREAKDOWN:")
    for g in grants:
        status_counts = {}
        status = g.status.value
        status_counts[status] = status_counts.get(status, 0) + 1
    
    status_counts = {}
    for g in grants:
        s = g.status.value
        status_counts[s] = status_counts.get(s, 0) + 1
    
    for status, count in sorted(status_counts.items()):
        logger.info(f"  {status}: {count}")


if __name__ == '__main__':
    main()
