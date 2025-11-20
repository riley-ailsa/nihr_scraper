#!/usr/bin/env python3
"""
Enhance existing NIHR grants with PDFs, links, and partnerships.

Usage:
    python scripts/enhance_nihr_grants.py --test 5  # Test on 5 grants
    python scripts/enhance_nihr_grants.py --all     # Enhance all grants
    python scripts/enhance_nihr_grants.py --grant-id <id>  # Enhance specific grant
"""

import argparse
import logging
import time
import sys
import os
from typing import List, Tuple, Dict
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.storage.grant_store import GrantStore
from src.storage.document_store import DocumentStore
from src.storage.fetch_cache import FetchCache
from src.ingest.resource_fetcher import ResourceFetcher
from src.ingest.nihr_funding import NihrFundingScraper
from src.enhance.pdf_enhancer import PDFEnhancer
from src.enhance.link_follower import LinkFollower
from src.enhance.partnership_handler import PartnershipHandler
from src.api.embeddings import create_embeddings_batch
from src.storage.embedding_store import EmbeddingStore

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def enhance_single_grant(grant_id: str,
                        grant_store: GrantStore,
                        doc_store: DocumentStore,
                        embedding_store: EmbeddingStore,
                        scraper: NihrFundingScraper,
                        enhancers: dict) -> dict:
    """
    Enhance a single grant with all three phases.

    Returns dict with enhancement statistics.
    """
    start_time = time.time()

    # Get grant and existing documents
    grant = grant_store.get_grant(grant_id)
    if not grant:
        logger.error(f"Grant not found: {grant_id}")
        return {'error': 'Grant not found'}

    existing_docs = doc_store.get_documents_for_grant(grant_id)
    base_char_count = sum(len(doc.text) for doc in existing_docs)

    logger.info(f"Enhancing grant: {grant.title}")
    logger.info(f"  Existing: {len(existing_docs)} docs, {base_char_count:,} chars")

    # Scrape fresh data to get resources
    try:
        opportunity = scraper.scrape(grant.url)
        resources = opportunity.resources
        raw_html = scraper._fetch(grant.url)  # Get raw HTML for partnership detection
    except Exception as e:
        logger.error(f"Failed to scrape grant URL {grant.url}: {e}")
        # Try to use cached data if available
        resources = []
        raw_html = ""

    logger.info(f"  Found {len(resources)} resources from scraper")

    new_documents = []

    # Phase 1: PDF Enhancement
    try:
        pdf_docs = enhancers['pdf'].enhance(grant_id, resources)
        new_documents.extend(pdf_docs)
        logger.info(f"  PDFs: Added {len(pdf_docs)} documents")
    except Exception as e:
        logger.error(f"  PDF enhancement failed: {e}")

    # Phase 2: Link Following
    try:
        link_docs = enhancers['link'].follow_links(
            grant_id, resources, grant.url
        )
        new_documents.extend(link_docs)
        logger.info(f"  Links: Added {len(link_docs)} documents")
    except Exception as e:
        logger.error(f"  Link following failed: {e}")

    # Phase 3: Partnership Detection
    try:
        if raw_html:
            partner_docs = enhancers['partnership'].enhance_partnership_grant(
                grant_id, grant.title, raw_html, resources
            )
            new_documents.extend(partner_docs)
            logger.info(f"  Partnerships: Added {len(partner_docs)} documents")
    except Exception as e:
        logger.error(f"  Partnership detection failed: {e}")

    # Store new documents
    if new_documents:
        doc_store.upsert_documents(new_documents)

        # Create embeddings for new documents
        logger.info(f"  Creating embeddings for {len(new_documents)} new documents")
        try:
            embeddings = create_embeddings_batch([doc.text for doc in new_documents])

            # Store embeddings
            embeddings_to_save = []
            for doc, embedding in zip(new_documents, embeddings):
                if embedding is not None:
                    embeddings_to_save.append({
                        'emb_id': f"{doc.id}_emb",
                        'doc_id': doc.id,
                        'grant_id': grant_id,
                        'chunk_index': 0,
                        'vector': embedding,
                        'text': doc.text[:1000],  # Store first 1000 chars for reference
                        'source_url': doc.source_url,
                        'doc_type': doc.doc_type,
                        'scope': doc.scope
                    })

            if embeddings_to_save:
                embedding_store.save_batch(embeddings_to_save)
                logger.info(f"  Saved {len(embeddings_to_save)} embeddings")
        except Exception as e:
            logger.error(f"  Failed to create/save embeddings: {e}")

    # Calculate statistics
    new_char_count = sum(len(doc.text) for doc in new_documents)
    total_char_count = base_char_count + new_char_count
    improvement = (total_char_count / base_char_count - 1) if base_char_count > 0 else 0

    elapsed_time = time.time() - start_time

    stats = {
        'grant_id': grant_id,
        'title': grant.title[:50],
        'base_docs': len(existing_docs),
        'new_docs': len(new_documents),
        'base_chars': base_char_count,
        'new_chars': new_char_count,
        'total_chars': total_char_count,
        'improvement': improvement,
        'pdf_docs': len([d for d in new_documents if d.doc_type == 'pdf']),
        'link_docs': len([d for d in new_documents if d.doc_type == 'linked_page']),
        'partner_docs': len([d for d in new_documents if 'partner' in d.doc_type]),
        'elapsed_seconds': elapsed_time
    }

    logger.info(f"  COMPLETE: {improvement:.1%} improvement in {elapsed_time:.1f}s")

    return stats


def main():
    parser = argparse.ArgumentParser(description='Enhance NIHR grants')
    parser.add_argument('--test', type=int, help='Test on N grants')
    parser.add_argument('--all', action='store_true', help='Enhance all grants')
    parser.add_argument('--grant-id', help='Enhance specific grant')
    args = parser.parse_args()

    # Initialize storage
    grant_store = GrantStore()
    doc_store = DocumentStore()
    embedding_store = EmbeddingStore()
    cache = FetchCache()

    # Initialize scraper
    scraper = NihrFundingScraper()

    # Initialize enhancers
    fetcher = ResourceFetcher(cache)
    enhancers = {
        'pdf': PDFEnhancer(fetcher),
        'link': LinkFollower(fetcher, max_links=10),
        'partnership': PartnershipHandler(fetcher)
    }

    # Get grants to enhance
    if args.grant_id:
        grant_ids = [args.grant_id]
    elif args.test:
        all_grants = grant_store.list_grants(limit=1000)  # Get all grants
        nihr_grants = [g for g in all_grants if g.source == 'nihr']
        grant_ids = [g.id for g in nihr_grants[:args.test]]
    elif args.all:
        all_grants = grant_store.list_grants(limit=1000)  # Get all grants
        nihr_grants = [g for g in all_grants if g.source == 'nihr']
        grant_ids = [g.id for g in nihr_grants]
    else:
        parser.error("Specify --test N, --all, or --grant-id")

    logger.info(f"Enhancing {len(grant_ids)} NIHR grants")

    # Process grants
    all_stats = []
    for i, grant_id in enumerate(grant_ids, 1):
        logger.info(f"\n[{i}/{len(grant_ids)}] Processing {grant_id}")

        stats = enhance_single_grant(
            grant_id,
            grant_store,
            doc_store,
            embedding_store,
            scraper,
            enhancers
        )

        all_stats.append(stats)

        # Rate limit
        if i < len(grant_ids):
            time.sleep(2)  # 2 seconds between grants to be polite

    # Summary statistics
    successful = [s for s in all_stats if 'error' not in s]

    if successful:
        avg_improvement = sum(s['improvement'] for s in successful) / len(successful)
        total_new_docs = sum(s['new_docs'] for s in successful)
        total_new_chars = sum(s['new_chars'] for s in successful)
        avg_time = sum(s['elapsed_seconds'] for s in successful) / len(successful)

        print(f"\n{'='*60}")
        print("ENHANCEMENT COMPLETE")
        print(f"{'='*60}")
        print(f"Grants enhanced: {len(successful)}/{len(grant_ids)}")
        print(f"Average improvement: {avg_improvement:.1%}")
        print(f"Total new documents: {total_new_docs:,}")
        print(f"Total new characters: {total_new_chars:,}")
        print(f"Average time per grant: {avg_time:.1f}s")
        print(f"PDF documents: {sum(s['pdf_docs'] for s in successful)}")
        print(f"Link documents: {sum(s['link_docs'] for s in successful)}")
        print(f"Partner documents: {sum(s['partner_docs'] for s in successful)}")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()