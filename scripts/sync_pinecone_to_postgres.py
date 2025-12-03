#!/usr/bin/env python3
"""
Sync NIHR grants from Pinecone to PostgreSQL.

Since the grants are already in Pinecone with metadata,
we can extract the grant-level information and insert into PostgreSQL.
"""

import os
from dotenv import load_dotenv
from pinecone import Pinecone
import psycopg2
from collections import defaultdict
from datetime import datetime
from tqdm import tqdm

load_dotenv()

# Initialize connections
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index = pc.Index(os.getenv("PINECONE_INDEX_NAME", "ailsa-grants"))
pg_conn = psycopg2.connect(os.getenv("DATABASE_URL"))

def parse_date(date_str):
    """Parse date string to date object"""
    if not date_str or date_str == '':
        return None
    try:
        return datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
    except:
        return None

def parse_int(val):
    """Parse integer value"""
    if not val or val == '':
        return None
    try:
        return int(float(val))
    except:
        return None

def fetch_nihr_grants_from_pinecone():
    """
    Fetch all NIHR grant metadata from Pinecone.

    Since vectors are chunked documents, we'll aggregate by grant_id
    to get unique grants.
    """
    print("🔍 Fetching NIHR grants from Pinecone...")

    # We'll do multiple queries to get a large sample
    # (Pinecone doesn't have a list_all API)
    grants = {}

    # Query with different random vectors to get diverse results
    import random
    for batch in range(10):
        print(f"  Batch {batch + 1}/10...")

        # Random query vector for diversity
        query_vec = [random.uniform(-0.1, 0.1) for _ in range(1536)]

        results = index.query(
            vector=query_vec,
            top_k=10000,
            filter={'source': 'nihr'},
            include_metadata=True
        )

        for match in results['matches']:
            meta = match['metadata']
            grant_id = meta.get('grant_id')

            if not grant_id:
                continue

            # Store unique grant info
            if grant_id not in grants:
                grants[grant_id] = {
                    'grant_id': grant_id,
                    'external_id': meta.get('external_id', ''),
                    'title': meta.get('title', ''),
                    'status': meta.get('status', 'Unknown'),
                    'opens_at': meta.get('opens_at', ''),
                    'closes_at': meta.get('closes_at', ''),
                    'total_fund': meta.get('total_fund', ''),
                    'total_fund_gbp': meta.get('total_fund_gbp', 0),
                    'tags': meta.get('tags', ''),
                }

    print(f"✅ Found {len(grants)} unique NIHR grants")
    return list(grants.values())

def construct_grant_url(external_id):
    """Construct NIHR grant URL from external ID"""
    return f"https://www.nihr.ac.uk/funding-and-support/current-funding-opportunities/{external_id}"

def insert_grants_to_postgres(grants):
    """Insert or update grants in PostgreSQL"""
    cursor = pg_conn.cursor()

    print(f"\n💾 Inserting {len(grants)} grants to PostgreSQL...")

    inserted = 0
    updated = 0
    errors = 0

    for grant in tqdm(grants):
        try:
            grant_id = grant['grant_id']
            external_id = grant['external_id']
            title = grant['title'][:500] if grant['title'] else 'Untitled'
            status = grant['status'].title()  # Open/Closed
            open_date = parse_date(grant['opens_at'])
            close_date = parse_date(grant['closes_at'])
            budget = parse_int(grant['total_fund_gbp'])
            tags = [t.strip() for t in grant['tags'].split(',') if t.strip()][:5]

            # Construct URL
            url = construct_grant_url(external_id) if external_id else f"https://www.nihr.ac.uk/unknown/{grant_id}"

            # Check if exists
            cursor.execute("SELECT 1 FROM grants WHERE grant_id = %s", (grant_id,))
            exists = cursor.fetchone() is not None

            # Insert or update
            cursor.execute("""
                INSERT INTO grants (
                    grant_id, source, title, url, call_id,
                    status, open_date, close_date,
                    budget_min, budget_max,
                    tags, description_summary,
                    scraped_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (grant_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    status = EXCLUDED.status,
                    close_date = EXCLUDED.close_date,
                    budget_min = EXCLUDED.budget_min,
                    budget_max = EXCLUDED.budget_max,
                    tags = EXCLUDED.tags,
                    updated_at = NOW()
            """, (
                grant_id,
                'nihr',
                title,
                url,
                external_id,
                status,
                open_date,
                close_date,
                budget,
                budget,
                tags,
                f"{grant['total_fund'][:500]}" if grant['total_fund'] else None,
            ))

            if exists:
                updated += 1
            else:
                inserted += 1

        except Exception as e:
            errors += 1
            print(f"\n  ❌ Error with {grant.get('grant_id', 'unknown')}: {e}")

    pg_conn.commit()
    cursor.close()

    print(f"\n✅ Inserted: {inserted}")
    print(f"🔄 Updated: {updated}")
    if errors:
        print(f"❌ Errors: {errors}")

def main():
    print("=" * 70)
    print("SYNC NIHR GRANTS: PINECONE → POSTGRESQL")
    print("=" * 70)

    # Fetch from Pinecone
    grants = fetch_nihr_grants_from_pinecone()

    if not grants:
        print("❌ No grants found in Pinecone")
        return

    # Insert to PostgreSQL
    insert_grants_to_postgres(grants)

    # Final stats
    cursor = pg_conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM grants WHERE source = 'nihr'")
    total_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM grants WHERE source = 'nihr' AND status = 'Open'")
    open_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM grants WHERE source = 'nihr' AND status = 'Closed'")
    closed_count = cursor.fetchone()[0]

    cursor.close()

    print("\n" + "=" * 70)
    print("SYNC COMPLETE")
    print("=" * 70)
    print(f"📊 PostgreSQL (NIHR):")
    print(f"   Total: {total_count} grants")
    print(f"   Open: {open_count} grants")
    print(f"   Closed: {closed_count} grants")
    print("=" * 70)

    pg_conn.close()

if __name__ == "__main__":
    main()
