#!/usr/bin/env python3
"""
Generate embeddings for NIHR documents that don't have them yet.

This script:
1. Finds all NIHR documents without embeddings
2. Generates embeddings using the VectorIndex
3. Shows progress and estimates

Usage:
    python3 scripts/generate_nihr_embeddings.py
    python3 scripts/generate_nihr_embeddings.py --batch-size 50
"""

import argparse
import logging
import sys
import time
import sqlite3
import os
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables from .env file if it exists
env_file = project_root / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip()

from src.storage.document_store import DocumentStore
from src.index.vector_index import VectorIndex
from src.core.domain_models import IndexableDocument

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Generate embeddings for NIHR documents"
    )
    parser.add_argument(
        "--db",
        default="grants.db",
        help="Path to database file (default: grants.db)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of documents to process per batch (default: 50)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without actually doing it"
    )

    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info("🔢 NIHR Embedding Generation")
    logger.info("=" * 80)
    logger.info(f"Database: {args.db}")
    logger.info(f"Batch size: {args.batch_size}")
    if args.dry_run:
        logger.info("DRY RUN MODE - No changes will be made")
    logger.info("=" * 80)
    logger.info("")

    # Connect to database directly
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    # Get NIHR documents without embeddings
    logger.info("📊 Finding NIHR documents without embeddings...")

    query = """
        SELECT d.id, d.grant_id, d.scope, d.source_url, d.text, g.source, d.doc_type
        FROM documents d
        JOIN grants g ON d.grant_id = g.id
        WHERE g.source = 'nihr'
        AND d.id NOT IN (SELECT DISTINCT doc_id FROM embeddings)
        ORDER BY d.id
    """

    cursor = conn.execute(query)
    rows = cursor.fetchall()

    logger.info(f"   Found {len(rows)} NIHR documents without embeddings")
    logger.info("")

    if not rows:
        logger.info("✅ All NIHR documents already have embeddings!")
        conn.close()
        return 0

    # Show some stats
    cursor = conn.execute("""
        SELECT
            COUNT(DISTINCT d.id) as doc_count,
            COUNT(DISTINCT e.id) as embedding_count
        FROM documents d
        JOIN grants g ON d.grant_id = g.id
        LEFT JOIN embeddings e ON d.id = e.doc_id
        WHERE g.source = 'nihr'
    """)
    stats = cursor.fetchone()
    logger.info(f"   Total NIHR documents: {stats['doc_count']}")
    logger.info(f"   With embeddings: {stats['doc_count'] - len(rows)}")
    logger.info(f"   Without embeddings: {len(rows)}")
    logger.info("")

    if args.dry_run:
        logger.info("=" * 80)
        logger.info("DRY RUN SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Would generate embeddings for {len(rows)} documents")
        logger.info(f"Estimated time: ~{len(rows) * 0.5 / 60:.1f} minutes")
        logger.info(f"Estimated cost: ~${len(rows) * 0.0001:.2f}")
        logger.info("")
        logger.info("Run without --dry-run to actually generate embeddings")
        conn.close()
        return 0

    # Initialize vector index
    try:
        vector_index = VectorIndex(db_path=args.db)
    except Exception as e:
        logger.error(f"❌ Failed to initialize VectorIndex: {e}")
        logger.error("   Make sure OPENAI_API_KEY is set")
        conn.close()
        return 1

    # Convert rows to IndexableDocument objects
    documents = []
    for row in rows:
        doc = IndexableDocument(
            id=row['id'],
            grant_id=row['grant_id'],
            doc_type=row['doc_type'],
            text=row['text'],
            source_url=row['source_url'],
            scope=row['scope']
        )
        documents.append(doc)

    logger.info("=" * 80)
    logger.info("🚀 GENERATING EMBEDDINGS")
    logger.info("=" * 80)
    logger.info(f"Total documents to process: {len(documents)}")
    logger.info(f"Batch size: {args.batch_size}")
    logger.info("")

    start_time = datetime.now()
    processed = 0
    failed = 0

    # Process in batches
    for i in range(0, len(documents), args.batch_size):
        batch = documents[i:i + args.batch_size]
        batch_num = (i // args.batch_size) + 1
        total_batches = (len(documents) + args.batch_size - 1) // args.batch_size

        logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} documents)...")

        try:
            # Generate embeddings for this batch
            vector_index.index_documents(batch)
            processed += len(batch)

            # Calculate progress
            elapsed = (datetime.now() - start_time).total_seconds()
            rate = processed / elapsed if elapsed > 0 else 0
            remaining = len(documents) - processed
            eta = remaining / rate if rate > 0 else 0

            logger.info(f"  ✅ Batch complete: {processed}/{len(documents)} total")
            logger.info(f"     Rate: {rate:.1f} docs/sec, ETA: {eta/60:.1f} min")

        except Exception as e:
            logger.error(f"  ❌ Batch failed: {e}")
            failed += len(batch)
            continue

        # Small pause between batches to be nice to API
        if i + args.batch_size < len(documents):
            time.sleep(1)

    # Final summary
    elapsed = (datetime.now() - start_time).total_seconds()

    logger.info("")
    logger.info("=" * 80)
    logger.info("✅ EMBEDDING GENERATION COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Total documents: {len(documents)}")
    logger.info(f"Successfully processed: {processed}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Elapsed time: {elapsed:.1f}s ({elapsed/60:.1f} min)")

    if processed > 0:
        logger.info(f"Average rate: {processed/elapsed:.1f} docs/sec")

    logger.info("=" * 80)
    logger.info("")

    # Verification
    logger.info("🔍 Verifying embeddings...")
    cursor = conn.execute("""
        SELECT COUNT(*) as count
        FROM embeddings e
        JOIN documents d ON e.doc_id = d.id
        JOIN grants g ON d.grant_id = g.id
        WHERE g.source = 'nihr'
    """)
    nihr_embeddings = cursor.fetchone()['count']
    logger.info(f"   NIHR embeddings in database: {nihr_embeddings:,}")
    logger.info("")
    logger.info("Run this to check full balance:")
    logger.info("  python3 scripts/check_data_balance.py")
    logger.info("")

    conn.close()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
