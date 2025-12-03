#!/usr/bin/env python3
"""
NIHR Sample Preview Script

Quickly test NIHR scraping + normalization on a few URLs without database writes.
Perfect for sanity checking before full ingestion.

Features:
- No database modifications
- Detailed output for manual review
- Fast iteration during development
- Validates scraper + normalizer integration

Usage:
    # Test first 5 URLs
    python3 -m src.scripts.preview_nihr_samples --input nihr_links.txt --limit 5

    # Test specific URLs with verbose output
    python3 -m src.scripts.preview_nihr_samples --input nihr_test_urls.txt --limit 10 --verbose
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.ingest.nihr_funding import NihrFundingScraper
from src.normalize.nihr import normalize_nihr_opportunity

# Configure logging
logging.basicConfig(
    level=logging.WARNING,  # Quiet by default
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Preview NIHR scraping without database modifications"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to file containing NIHR URLs"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of URLs to process (default: 5)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )

    return parser.parse_args()


def format_currency(amount: Optional[int]) -> str:
    """Format currency amount for display."""
    if amount is None:
        return "N/A"
    return f"£{amount:,}"


def truncate_text(text: str, max_length: int = 200) -> str:
    """Truncate text to max length with ellipsis."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."


def main():
    """Main execution function."""
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load URLs
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"❌ Input file not found: {input_path}")
        return 1

    urls = [
        line.strip()
        for line in input_path.read_text().splitlines()
        if line.strip() and not line.startswith('#')
    ]

    # Deduplicate
    urls = list(dict.fromkeys(urls))

    print("=" * 80)
    print("🔍 NIHR Sample Preview")
    print("=" * 80)
    print(f"Input file: {input_path}")
    print(f"Total URLs: {len(urls)}")
    print(f"Previewing: {min(args.limit, len(urls))} URLs")
    print("=" * 80)
    print()

    # Initialize scraper
    scraper = NihrFundingScraper()

    # Statistics
    stats = {
        "success": 0,
        "failed": 0
    }

    # Process sample
    for idx, url in enumerate(urls[:args.limit], start=1):
        print("=" * 80)
        print(f"[{idx}/{min(args.limit, len(urls))}] {url}")
        print("=" * 80)

        try:
            # Scrape
            print("📥 Scraping...")
            opportunity = scraper.scrape(url)

            # Normalize
            print("⚙️  Normalizing...")
            grant, documents = normalize_nihr_opportunity(opportunity)

            # Display results
            print()
            print("📋 GRANT INFORMATION")
            print("-" * 80)
            print(f"Grant ID:          {grant.id}")
            print(f"Title:             {grant.title}")
            print(f"Source:            {grant.source}")
            print(f"External ID:       {grant.external_id or 'N/A'}")
            print(f"Active:            {'✅ Yes' if grant.is_active else '❌ No'}")
            print(f"Opens at:          {grant.opens_at or 'N/A'}")
            print(f"Closes at:         {grant.closes_at or 'N/A'}")
            print(f"Funding:           {grant.total_fund or 'N/A'}")
            print(f"Funding (GBP):     {format_currency(grant.total_fund_gbp)}")
            print(f"Tags:              {', '.join(grant.tags) if grant.tags else 'None'}")
            print(f"Description:       {truncate_text(grant.description)}")
            print()

            # Scraped content summary
            print("📄 SCRAPED CONTENT")
            print("-" * 80)
            print(f"Sections:          {len(opportunity.sections)}")
            for section in opportunity.sections[:10]:  # First 10
                title = section.get("title", "Untitled")
                text_len = len(section.get("text", ""))
                print(f"  • {title} ({text_len:,} chars)")

            if len(opportunity.sections) > 10:
                print(f"  ... and {len(opportunity.sections) - 10} more sections")
            print()

            print(f"Resources:         {len(opportunity.resources)}")
            for resource in opportunity.resources[:10]:  # First 10
                res_type = resource.get("type", "unknown")
                res_title = resource.get("title", "Untitled")
                print(f"  • [{res_type}] {res_title}")

            if len(opportunity.resources) > 10:
                print(f"  ... and {len(opportunity.resources) - 10} more resources")
            print()

            # Key dates if present
            if opportunity.key_dates:
                print(f"Key dates:         {len(opportunity.key_dates)}")
                for kd in opportunity.key_dates[:5]:
                    label = kd.get("label", "Unknown")
                    date = kd.get("date", "TBD")
                    print(f"  • {label}: {date}")
                if len(opportunity.key_dates) > 5:
                    print(f"  ... and {len(opportunity.key_dates) - 5} more dates")
                print()

            # Extra metadata
            if opportunity.extra:
                print(f"Extra metadata:    {len(opportunity.extra)} items")
                for key in list(opportunity.extra.keys())[:5]:
                    value = opportunity.extra[key]
                    if isinstance(value, list):
                        print(f"  • {key}: {len(value)} items")
                    elif isinstance(value, dict):
                        print(f"  • {key}: {len(value)} fields")
                    else:
                        print(f"  • {key}: {truncate_text(str(value), 60)}")
                print()

            # Indexable documents summary
            print("📊 INDEXABLE DOCUMENTS")
            print("-" * 80)
            print(f"Total documents:   {len(documents)}")

            # Group by doc_type
            doc_types = {}
            for doc in documents:
                doc_types[doc.doc_type] = doc_types.get(doc.doc_type, 0) + 1

            for doc_type, count in sorted(doc_types.items()):
                print(f"  • {doc_type}: {count}")
            print()

            # Sample documents
            if documents:
                print("Sample documents:")
                for doc in documents[:3]:
                    print(f"  • {doc.doc_type} | {doc.scope} | {len(doc.text):,} chars")
                    if doc.section_name:
                        print(f"    Section: {doc.section_name}")
                    print(f"    {truncate_text(doc.text, 100)}")
                    print()

            print("✅ Success")
            stats["success"] += 1

        except Exception as e:
            print(f"❌ Failed: {e}")
            stats["failed"] += 1
            if args.verbose:
                import traceback
                traceback.print_exc()

        print()

    # Final summary
    print("=" * 80)
    print("📊 PREVIEW SUMMARY")
    print("=" * 80)
    print(f"Total processed:   {stats['success'] + stats['failed']}")
    print(f"Successful:        {stats['success']} ✅")
    print(f"Failed:            {stats['failed']} ❌")
    print("=" * 80)
    print()

    if stats["success"] > 0:
        print("💡 Next steps:")
        print("  1. Review output above for accuracy")
        print("  2. Check funding amounts are parsed correctly")
        print("  3. Verify sections and resources are captured")
        print("  4. Run full ingestion when satisfied:")
        print(f"     python3 -m src.scripts.backfill_nihr_production --input {input_path}")
        print()

    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
