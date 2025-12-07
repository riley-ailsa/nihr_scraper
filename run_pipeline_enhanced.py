#!/usr/bin/env python3
"""
NIHR v3 Pipeline with Enhancement

Complete pipeline that:
1. Scrapes NIHR funding pages (existing scraper)
2. Normalizes to v3 schema (normalize_nihr_v3.py)
3. Enhances with PDF/link content (enhance_v3.py)
4. Exports results

Usage:
    # Basic test (no enhancement)
    python run_pipeline_enhanced.py --limit 10 --dry-run
    
    # With PDF enhancement
    python run_pipeline_enhanced.py --limit 10 --dry-run --enhance
    
    # Full enhancement (PDFs + links)
    python run_pipeline_enhanced.py --limit 10 --dry-run --enhance --follow-links
"""

import argparse
import logging
import warnings
from datetime import datetime
from pathlib import Path

import pandas as pd

# Suppress warnings
warnings.filterwarnings('ignore', category=FutureWarning, module='soupsieve')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import scraper and normalizer
from src.ingest.nihr_funding import NihrFundingScraper
from normalize_nihr_v3 import normalize_nihr_v3, grant_to_flat_dict
from enhance_v3 import enhance_grant_v3


def load_urls(limit: int = None) -> list:
    """Load URLs from file."""
    url_file = Path("data/urls/nihr_urls.txt")
    
    if not url_file.exists():
        logger.error(f"URL file not found: {url_file}")
        return []
    
    with open(url_file) as f:
        urls = [line.strip() for line in f if line.strip()]
    
    if limit:
        urls = urls[:limit]
    
    logger.info(f"Loaded {len(urls)} URLs")
    return urls


def run_pipeline(
    limit: int = None,
    enhance: bool = False,
    follow_links: bool = False,
    dry_run: bool = True
):
    """Run the complete pipeline."""
    
    # Load URLs
    urls = load_urls(limit)
    if not urls:
        return
    
    # Initialize scraper
    scraper = NihrFundingScraper()
    
    # Process grants
    results = []
    enhancement_stats = {'pdfs_extracted': 0, 'funding_found': 0, 'links_followed': 0}
    
    for i, url in enumerate(urls):
        logger.info(f"[{i+1}/{len(urls)}] {url}")
        
        try:
            # Scrape
            opp = scraper.scrape(url)
            if not opp:
                logger.warning(f"  ❌ Failed to scrape")
                continue
            
            # Normalize to v3
            grant = normalize_nihr_v3(opp)
            
            # Enhance if requested
            enhancement_logs = []
            if enhance:
                grant, enhancement_logs = enhance_grant_v3(
                    grant, opp,
                    follow_links=follow_links,
                    fetch_pdfs=True,
                    max_links=5
                )
                
                # Track stats
                for log in enhancement_logs:
                    if log.startswith('PDF:'):
                        enhancement_stats['pdfs_extracted'] += 1
                    elif log.startswith('Link:'):
                        enhancement_stats['links_followed'] += 1
                    elif 'funding' in log.lower():
                        enhancement_stats['funding_found'] += 1
            
            results.append({
                'grant': grant,
                'opp': opp,
                'logs': enhancement_logs
            })
            
            logger.info(f"  ✅ {grant.title[:50]}...")
            
            if enhancement_logs:
                for log in enhancement_logs[:3]:  # Show first 3 logs
                    logger.info(f"      {log}")
                    
        except Exception as e:
            logger.error(f"  ❌ Error: {e}")
            continue
    
    logger.info(f"\nProcessed {len(results)}/{len(urls)} grants")
    
    # Export if dry run
    if dry_run and results:
        export_results(results, enhance, enhancement_stats)
    
    return results


def export_results(results: list, enhanced: bool, stats: dict):
    """Export results to Excel."""
    
    # Convert to flat dicts
    rows = []
    for r in results:
        row = grant_to_flat_dict(r['grant'])
        if r['logs']:
            row['enhancement_logs'] = '; '.join(r['logs'])
        rows.append(row)
    
    df = pd.DataFrame(rows)
    
    # Handle datetime columns
    for col in df.columns:
        if 'date' in col.lower() or col.endswith('_at'):
            try:
                df[col] = pd.to_datetime(df[col], errors='coerce')
            except:
                pass
    
    # Generate filename
    suffix = "_enhanced" if enhanced else ""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"nihr_v3{suffix}_{timestamp}.xlsx"
    
    df.to_excel(filename, index=False)
    
    # Print stats
    logger.info(f"\n{'='*60}")
    logger.info(f"EXPORTED: {filename}")
    logger.info(f"{'='*60}")
    
    # Field completeness
    logger.info(f"\nFIELD COMPLETENESS ({len(df)} grants):")
    logger.info("-" * 50)
    
    key_fields = [
        'grant_id', 'title', 'status',
        'summary_text', 'summary_programme_name',
        'eligibility_text', 'scope_text', 'scope_themes',
        'dates_opens_at', 'dates_closes_at',
        'funding_text', 'funding_total_pot_gbp', 'funding_total_pot_display',
        'funding_per_project_min', 'funding_per_project_max',
        'how_to_apply_text', 'assessment_text',
        'contact_email', 'programme_name', 'programme_code'
    ]
    
    for field in key_fields:
        if field in df.columns:
            non_null = df[field].notna() & (df[field] != '') & (df[field] != '[]')
            count = non_null.sum()
            pct = count / len(df) * 100
            
            if pct >= 80:
                icon = "✅"
            elif pct >= 30:
                icon = "⚠️"
            else:
                icon = "❌"
            
            logger.info(f"{icon} {field:35} {count:3}/{len(df)} ({pct:5.1f}%)")
    
    # Enhancement stats if applicable
    if enhanced:
        logger.info(f"\nENHANCEMENT STATS:")
        logger.info("-" * 50)
        logger.info(f"  PDFs extracted:     {stats['pdfs_extracted']}")
        logger.info(f"  Links followed:     {stats['links_followed']}")
        logger.info(f"  Funding found:      {stats['funding_found']}")
    
    # Status breakdown
    logger.info(f"\nSTATUS BREAKDOWN:")
    status_counts = df['status'].value_counts()
    for status, count in status_counts.items():
        logger.info(f"  {status}: {count}")


def main():
    parser = argparse.ArgumentParser(description='NIHR v3 Pipeline with Enhancement')
    parser.add_argument('--limit', type=int, default=10, help='Number of grants to process')
    parser.add_argument('--enhance', action='store_true', help='Enable PDF enhancement')
    parser.add_argument('--follow-links', action='store_true', help='Follow webpage links')
    parser.add_argument('--dry-run', action='store_true', help='Export to Excel only')
    
    args = parser.parse_args()
    
    run_pipeline(
        limit=args.limit,
        enhance=args.enhance,
        follow_links=args.follow_links,
        dry_run=args.dry_run
    )


if __name__ == '__main__':
    main()
