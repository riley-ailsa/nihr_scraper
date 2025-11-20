#!/usr/bin/env python3
"""
Ingest NIHR grants into production PostgreSQL + Pinecone.
Rescrapes open opportunities to detect changes.
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

import psycopg2
import openai
from pinecone import Pinecone
from tqdm import tqdm
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "ailsa-grants")
DATABASE_URL = os.getenv("DATABASE_URL")

openai.api_key = OPENAI_API_KEY

# Initialize clients
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(PINECONE_INDEX_NAME)
pg_conn = psycopg2.connect(DATABASE_URL)


# Import scraper components
from src.ingest.nihr_funding import NihrFundingScraper
from src.normalize.nihr import normalize_nihr_opportunity, infer_nihr_status


def load_urls(filepath: str) -> List[str]:
    """Load NIHR opportunity URLs from file"""
    path = Path(filepath)

    if not path.exists():
        print(f"❌ File not found: {filepath}")
        return []

    with path.open() as f:
        urls = [
            line.strip()
            for line in f
            if line.strip() and not line.startswith("#")
        ]

    print(f"📁 Loaded {len(urls)} URLs from {filepath}")
    return urls


def get_open_grants_from_db() -> List[str]:
    """Get URLs of all open NIHR grants from database"""
    cursor = pg_conn.cursor()

    try:
        cursor.execute("""
            SELECT url
            FROM grants
            WHERE source = 'nihr'
            AND status = 'Open'
            ORDER BY close_date ASC
        """)

        urls = [row[0] for row in cursor.fetchall()]
        print(f"📊 Found {len(urls)} open NIHR grants in database")
        return urls

    except Exception as e:
        print(f"⚠️  Could not fetch open grants: {e}")
        return []
    finally:
        cursor.close()


def extract_embedding_text(grant: Dict[str, Any], documents: List[Dict[str, Any]]) -> str:
    """
    Extract rich text for embedding from grant + documents.

    Combines title, description, and key document content.
    """
    parts = []

    # Title
    if grant.get('title'):
        parts.append(f"Title: {grant['title']}")

    # Programme
    parts.append(f"Programme: NIHR")

    # Status and dates
    if grant.get('is_active'):
        parts.append(f"Status: Open")
    else:
        parts.append(f"Status: Closed")

    if grant.get('closes_at'):
        parts.append(f"Deadline: {grant['closes_at']}")

    # Funding
    if grant.get('total_fund'):
        parts.append(f"Funding: {grant['total_fund']}")

    # Description
    if grant.get('description'):
        desc = grant['description']
        if len(desc) > 3000:
            desc = desc[:2500] + "\n...\n" + desc[-500:]
        parts.append(f"\nDescription:\n{desc}")

    # Add key documents (overview, eligibility, guidance)
    for doc in documents[:3]:  # Limit to first 3 documents
        if doc.get('text'):
            text = doc['text']
            section_name = doc.get('section_name', 'content')

            # Limit document length
            doc_text = text[:1500] if len(text) > 1500 else text
            parts.append(f"\n{section_name.replace('-', ' ').title()}:\n{doc_text}")

    return "\n".join(parts)


def ingest_nihr_opportunity(url: str, scraper: NihrFundingScraper):
    """
    Ingest one NIHR opportunity into PostgreSQL + Pinecone.
    Detects and logs changes from previous scrape.

    Returns:
        dict: {'success': bool, 'changed': bool, 'changes': list}
    """
    cursor = pg_conn.cursor()

    try:
        # Step 1: Scrape
        print(f"  📥 Scraping...")
        opp = scraper.scrape(url)

        # Step 2: Normalize
        grant, indexable_docs = normalize_nihr_opportunity(opp)

        print(f"  ✅ {grant.title[:60]}...")

        # Step 3: Check for existing grant to detect changes
        cursor.execute("""
            SELECT status, close_date, title, budget_max, updated_at
            FROM grants
            WHERE grant_id = %s
        """, (grant.id,))

        existing = cursor.fetchone()
        changes = []
        is_new = existing is None

        if existing:
            old_status, old_close_date, old_title, old_budget, old_updated = existing
            new_status = "Open" if grant.is_active else "Closed"
            new_close_date = grant.closes_at.date() if grant.closes_at else None

            # Detect changes
            if old_status != new_status:
                changes.append(f"Status: {old_status} → {new_status}")
            if old_close_date != new_close_date:
                changes.append(f"Deadline: {old_close_date} → {new_close_date}")
            if old_budget != grant.total_fund_gbp:
                old_budget_str = f"£{old_budget:,}" if old_budget else "N/A"
                new_budget_str = f"£{grant.total_fund_gbp:,}" if grant.total_fund_gbp else "N/A"
                changes.append(f"Budget: {old_budget_str} → {new_budget_str}")
            if old_title != grant.title:
                changes.append(f"Title changed")

        # Step 4: Insert/Update PostgreSQL
        status = "Open" if grant.is_active else "Closed"
        open_date = grant.opens_at.date() if grant.opens_at else None
        close_date = grant.closes_at.date() if grant.closes_at else None

        cursor.execute("""
            INSERT INTO grants (
                grant_id, source, title, url, call_id,
                status, open_date, close_date,
                tags, description_summary, budget_min, budget_max,
                scraped_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (grant_id) DO UPDATE SET
                status = EXCLUDED.status,
                title = EXCLUDED.title,
                close_date = EXCLUDED.close_date,
                tags = EXCLUDED.tags,
                description_summary = EXCLUDED.description_summary,
                budget_min = EXCLUDED.budget_min,
                budget_max = EXCLUDED.budget_max,
                updated_at = NOW()
        """, (
            grant.id,
            grant.source,
            grant.title,
            grant.url,
            grant.external_id,
            status,
            open_date,
            close_date,
            grant.tags,
            grant.description[:500] if grant.description else None,
            grant.total_fund_gbp,
            grant.total_fund_gbp,
        ))

        pg_conn.commit()

        if is_new:
            print(f"  🆕 NEW opportunity")
        elif changes:
            print(f"  🔄 CHANGES: {', '.join(changes)}")
        else:
            print(f"  ✓ No changes")

        print(f"  ✅ Saved to PostgreSQL")

        # Step 5: Generate embedding
        print(f"  🔮 Generating embedding...")
        embedding_text = extract_embedding_text(
            {
                'title': grant.title,
                'description': grant.description,
                'total_fund': grant.total_fund,
                'is_active': grant.is_active,
                'closes_at': grant.closes_at,
            },
            [
                {
                    'section_name': doc.section_name,
                    'text': doc.text
                }
                for doc in indexable_docs
            ]
        )

        response = openai.embeddings.create(
            input=embedding_text,
            model="text-embedding-3-small"
        )
        embedding = response.data[0].embedding

        # Step 6: Upsert to Pinecone
        print(f"  📌 Upserting to Pinecone...")
        index.upsert(vectors=[{
            'id': grant.id,
            'values': embedding,
            'metadata': {
                'source': 'nihr',
                'title': grant.title[:500] if grant.title else '',
                'status': status,
                'close_date': close_date.isoformat() if close_date else '',
                'url': grant.url,
                'tags': ','.join(grant.tags[:5]) if grant.tags else '',
                'budget_min': str(grant.total_fund_gbp) if grant.total_fund_gbp else '',
                'budget_max': str(grant.total_fund_gbp) if grant.total_fund_gbp else '',
                'total_fund': grant.total_fund or '',
            }
        }])

        print(f"  ✅ Indexed in Pinecone")

        cursor.close()
        return {
            'success': True,
            'is_new': is_new,
            'changed': len(changes) > 0,
            'changes': changes
        }

    except Exception as e:
        print(f"  ❌ Error: {type(e).__name__}: {str(e)[:100]}")
        pg_conn.rollback()
        cursor.close()
        return {
            'success': False,
            'is_new': False,
            'changed': False,
            'changes': []
        }


def main():
    """Main ingestion pipeline"""
    print("=" * 70)
    print("INGESTING NIHR GRANTS TO PRODUCTION")
    print("=" * 70)

    # Get URLs - prioritize rescaping open grants from DB
    open_urls = get_open_grants_from_db()

    # Also load any new URLs from file
    file_urls = load_urls("nihr_urls.txt")

    # Combine and deduplicate
    all_urls = list(dict.fromkeys(open_urls + file_urls))  # Preserves order, removes dupes

    if not all_urls:
        print("❌ No URLs to process")
        return

    print(f"\n📋 Processing {len(all_urls)} opportunities:")
    print(f"   🔄 {len(open_urls)} open grants (rescraping for changes)")
    print(f"   📁 {len(file_urls)} from file")

    # Initialize scraper
    scraper = NihrFundingScraper()

    # Process each URL
    success_count = 0
    fail_count = 0
    new_count = 0
    changed_count = 0
    unchanged_count = 0
    all_changes = []

    print(f"\n🚀 Processing {len(all_urls)} opportunities...\n")

    for i, url in enumerate(tqdm(all_urls, desc="Ingesting"), 1):
        # Extract opportunity ID from URL
        opp_id = url.split('/')[-1]
        print(f"\n[{i}/{len(all_urls)}] Opportunity {opp_id}")

        result = ingest_nihr_opportunity(url, scraper)

        if result['success']:
            success_count += 1
            if result['is_new']:
                new_count += 1
            elif result['changed']:
                changed_count += 1
                all_changes.append({
                    'opportunity_id': opp_id,
                    'changes': result['changes']
                })
            else:
                unchanged_count += 1
        else:
            fail_count += 1

    # Final stats
    cursor = pg_conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM grants WHERE source = 'nihr'")
    postgres_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM grants WHERE source = 'nihr' AND status = 'Open'")
    open_count = cursor.fetchone()[0]

    cursor.close()

    pinecone_stats = index.describe_index_stats()

    print(f"\n" + "=" * 70)
    print("INGESTION COMPLETE")
    print("=" * 70)
    print(f"✅ Success: {success_count}")
    print(f"❌ Failed: {fail_count}")
    print(f"")
    print(f"📊 Changes Detected:")
    print(f"   🆕 New: {new_count}")
    print(f"   🔄 Updated: {changed_count}")
    print(f"   ✓ Unchanged: {unchanged_count}")
    print(f"")
    print(f"📊 PostgreSQL (NIHR):")
    print(f"   Total: {postgres_count} grants")
    print(f"   Open: {open_count} grants")
    print(f"📊 Pinecone (Total): {pinecone_stats['total_vector_count']} vectors")

    if all_changes:
        print(f"\n🔄 DETAILED CHANGES:")
        for item in all_changes:
            print(f"\n   Opportunity {item['opportunity_id']}:")
            for change in item['changes']:
                print(f"      • {change}")

    print("=" * 70)

    pg_conn.close()


if __name__ == "__main__":
    main()
