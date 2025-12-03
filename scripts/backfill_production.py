#!/usr/bin/env python3
"""
Batch ingestion script for NIHR funding opportunities.

Features:
- Reads URLs from file (one per line)
- Deduplicates at file level
- Checks database for existing grants (skips duplicates)
- Robust error handling (continues on failures)
- Checkpoint support for crash recovery
- Rate limiting to respect NIHR servers
- Full logging and progress tracking

Usage:
    python3 -m src.scripts.backfill_nihr_production \
        --input nihr_urls.txt \
        --batch-size 20 \
        --checkpoint checkpoints/nihr_ingest.txt
"""

import argparse
import logging
import sys
import time
import random
from pathlib import Path
from datetime import datetime
from typing import List, Set

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.ingest.nihr_funding import NihrFundingScraper
from src.normalize.nihr import normalize_nihr_opportunity
from src.storage.grant_store import GrantStore
from src.storage.document_store import DocumentStore
from src.index.vector_index import VectorIndex

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_checkpoint(checkpoint_path: Path) -> Set[str]:
    """
    Load previously processed URLs from checkpoint file.

    Args:
        checkpoint_path: Path to checkpoint file

    Returns:
        set: URLs that have been processed
    """
    if not checkpoint_path.exists():
        return set()

    with open(checkpoint_path, 'r') as f:
        return {line.strip() for line in f if line.strip()}


def save_checkpoint(checkpoint_path: Path, url: str):
    """
    Append URL to checkpoint file.

    Args:
        checkpoint_path: Path to checkpoint file
        url: URL to mark as processed
    """
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_path, 'a') as f:
        f.write(f"{url}\n")


def deduplicate_urls(urls: List[str]) -> List[str]:
    """
    Remove duplicate URLs while preserving order.

    Args:
        urls: List of URLs (may contain duplicates)

    Returns:
        List[str]: Deduplicated URLs
    """
    seen = set()
    deduped = []

    for url in urls:
        if url in seen:
            logger.warning(f"Duplicate URL found in input file: {url}")
            continue
        seen.add(url)
        deduped.append(url)

    if len(deduped) < len(urls):
        logger.info(f"Removed {len(urls) - len(deduped)} duplicate URLs from input")

    return deduped


def main():
    parser = argparse.ArgumentParser(
        description="Batch ingest NIHR funding opportunities"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to file containing NIHR URLs (one per line)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Number of URLs to process before pausing (default: 20)"
    )
    parser.add_argument(
        "--sleep-min",
        type=float,
        default=0.5,
        help="Minimum seconds to wait between requests (default: 0.5)"
    )
    parser.add_argument(
        "--sleep-max",
        type=float,
        default=1.5,
        help="Maximum seconds to wait between requests (default: 1.5)"
    )
    parser.add_argument(
        "--checkpoint",
        help="Path to checkpoint file for crash recovery"
    )
    parser.add_argument(
        "--db",
        default="grants.db",
        help="Path to database file (default: grants.db)"
    )

    args = parser.parse_args()

    # Initialize components
    logger.info("=" * 80)
    logger.info("🔄 NIHR Batch Ingestion Started")
    logger.info("=" * 80)
    logger.info(f"Input file:    {args.input}")
    logger.info(f"Database:      {args.db}")
    logger.info(f"Batch size:    {args.batch_size}")
    logger.info(f"Rate limit:    {args.sleep_min}-{args.sleep_max}s between requests")
    if args.checkpoint:
        logger.info(f"Checkpoint:    {args.checkpoint}")
    logger.info("=" * 80)
    logger.info("")

    # Load URLs from file
    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {args.input}")
        return 1

    with open(input_path, 'r') as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    logger.info(f"📊 Loaded {len(urls)} URLs from input file")

    # Deduplicate URLs
    urls = deduplicate_urls(urls)
    logger.info(f"📊 Processing {len(urls)} unique URLs")
    logger.info("")

    # Load checkpoint
    processed_urls: Set[str] = set()
    checkpoint_path = None
    if args.checkpoint:
        checkpoint_path = Path(args.checkpoint)
        processed_urls = load_checkpoint(checkpoint_path)
        if processed_urls:
            logger.info(f"⏸️  Loaded checkpoint: {len(processed_urls)} URLs already processed")
            logger.info("")

    # Initialize scraper and storage
    scraper = NihrFundingScraper()
    grant_store = GrantStore(args.db)
    document_store = DocumentStore(args.db)

    # Initialize vector index (optional - only if API key is set)
    import os
    vector_index = None
    if os.getenv("OPENAI_API_KEY"):
        try:
            vector_index = VectorIndex(db_path=args.db)
            logger.info("✅ Vector index initialized (embeddings will be generated)")
        except Exception as e:
            logger.warning(f"⚠️  Vector index unavailable: {e}")
            logger.warning("   Proceeding without embeddings")
    else:
        logger.warning("⚠️  OPENAI_API_KEY not set - skipping embeddings")

    # Statistics
    stats = {
        "total": len(urls),
        "processed": 0,
        "skipped_checkpoint": 0,
        "skipped_exists": 0,
        "created": 0,
        "updated": 0,
        "failed": 0,
        "start_time": datetime.now()
    }

    # Process URLs
    for idx, url in enumerate(urls, start=1):
        # Skip if in checkpoint
        if url in processed_urls:
            logger.info(f"[{idx}/{stats['total']}] ⏭️  Skipping (in checkpoint): {url}")
            stats["skipped_checkpoint"] += 1
            continue

        # Check if already in database
        if grant_store.exists_by_url(url):
            logger.info(f"[{idx}/{stats['total']}] ⏭️  Skipping (already in DB): {url}")
            stats["skipped_exists"] += 1

            # Mark in checkpoint if using one
            if checkpoint_path:
                save_checkpoint(checkpoint_path, url)

            continue

        logger.info(f"[{idx}/{stats['total']}] Processing: {url}")

        try:
            # Scrape
            logger.debug("  ├─ Scraping...")
            opportunity = scraper.scrape(url)
            logger.debug(f"  ├─ Scraped: {opportunity.title}")

            # Normalize
            logger.debug("  ├─ Normalizing...")
            grant, documents = normalize_nihr_opportunity(opportunity)
            logger.debug(f"  ├─ Normalized: {len(documents)} documents")

            # Store grant (upsert handles both insert and update)
            existing_grant = grant_store.get_grant(grant.id)
            grant_store.upsert_grant(grant)
            if existing_grant:
                stats["updated"] += 1
                logger.debug(f"  ├─ Updated grant: {grant.id}")
            else:
                stats["created"] += 1
                logger.debug(f"  ├─ Created grant: {grant.id}")

            # Store documents
            if documents:
                document_store.upsert_documents(documents)
                logger.debug(f"  ├─ Stored {len(documents)} documents")

                # Generate embeddings (if vector index available)
                if vector_index:
                    try:
                        vector_index.index_documents(documents)
                        logger.debug(f"  ├─ Generated embeddings for {len(documents)} documents")
                    except Exception as e:
                        logger.warning(f"  ⚠️  Failed to generate embeddings: {e}")

            logger.info(f"  ✅ Success: {grant.id}")
            stats["processed"] += 1

            # Save checkpoint
            if checkpoint_path:
                save_checkpoint(checkpoint_path, url)

        except Exception as e:
            logger.error(f"  ❌ Failed: {e}", exc_info=True)
            stats["failed"] += 1
            continue

        # Rate limiting with random jitter (be polite to NIHR servers)
        if idx < stats["total"]:  # Don't sleep after last one
            delay = random.uniform(args.sleep_min, args.sleep_max)
            time.sleep(delay)

        # Batch pause
        if idx % args.batch_size == 0 and idx < stats["total"]:
            logger.info("")
            logger.info(f"⏸️  Batch checkpoint: {idx}/{stats['total']} processed")
            logger.info(f"   Success: {stats['processed']}, Failed: {stats['failed']}, Skipped: {stats['skipped_checkpoint'] + stats['skipped_exists']}")
            logger.info("")

    # Final statistics
    elapsed = (datetime.now() - stats["start_time"]).total_seconds()

    logger.info("")
    logger.info("=" * 80)
    logger.info("✅ NIHR Batch Ingestion Complete")
    logger.info("=" * 80)
    logger.info(f"Total URLs:             {stats['total']}")
    logger.info(f"Successfully processed: {stats['processed']}")
    logger.info(f"  - Created new:        {stats['created']}")
    logger.info(f"  - Updated existing:   {stats['updated']}")
    logger.info(f"Skipped:                {stats['skipped_checkpoint'] + stats['skipped_exists']}")
    logger.info(f"  - Checkpoint:         {stats['skipped_checkpoint']}")
    logger.info(f"  - Already in DB:      {stats['skipped_exists']}")
    logger.info(f"Failed:                 {stats['failed']}")
    logger.info(f"Elapsed time:           {elapsed:.1f}s ({elapsed/60:.1f}min)")

    # Calculate success rate
    if stats['total'] > 0:
        success_rate = (stats['processed'] / stats['total']) * 100
        logger.info(f"Success rate:           {success_rate:.1f}%")

    logger.info("=" * 80)
    logger.info("")

    # Next steps message
    if stats["processed"] > 0:
        logger.info("💡 Next steps:")
        logger.info("  1. Validate database:")
        logger.info(f"     python3 scripts/inspect_db.py --db {args.db}")
        logger.info("  2. Test search:")
        logger.info("     python3 -m src.scripts.test_search")
        logger.info("")

    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
