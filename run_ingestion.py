#!/usr/bin/env python3
"""
Ingest NIHR grants into production MongoDB + Pinecone.
Rescrapes open opportunities to detect changes.
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

import openai
from pymongo import MongoClient
from pinecone import Pinecone
from tqdm import tqdm
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "ailsa-grants")
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "ailsa_grants")

openai.api_key = OPENAI_API_KEY

# Initialize clients
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(PINECONE_INDEX_NAME)
mongo_client = MongoClient(MONGO_URI)
db = mongo_client[MONGO_DB_NAME]


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
    try:
        cursor = db.grants.find(
            {"source": "nihr", "status": "Open"},
            {"url": 1, "closes_at": 1}
        ).sort("closes_at", 1)

        urls = [doc["url"] for doc in cursor if doc.get("url")]
        print(f"📊 Found {len(urls)} open NIHR grants in database")
        return urls

    except Exception as e:
        print(f"⚠️  Could not fetch open grants: {e}")
        return []


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


def build_grant_document(grant, indexable_docs: List) -> Dict[str, Any]:
    """
    Build MongoDB document from normalized Grant object.

    Args:
        grant: Normalized Grant object
        indexable_docs: List of IndexableDocument objects

    Returns:
        dict: MongoDB document matching the grant schema
    """
    # Build sections array from indexable documents
    sections = []
    for doc in indexable_docs:
        if doc.section_name and doc.text:
            sections.append({
                "name": doc.section_name,
                "text": doc.text,
                "url": doc.source_url or ""
            })

    # Build resources array (filter docs that are resources)
    resources = []
    for doc in indexable_docs:
        if doc.doc_type in ("briefing_pdf", "document"):
            resources.append({
                "id": doc.id,
                "title": doc.citation_text or doc.section_name or "Resource",
                "url": doc.source_url or "",
                "type": "pdf" if doc.doc_type == "briefing_pdf" else "webpage"
            })

    return {
        "grant_id": f"nihr_{grant.external_id}" if grant.external_id else grant.id,
        "source": "nihr",
        "external_id": grant.external_id or "",

        # Core metadata
        "title": grant.title or "",
        "url": grant.url or "",
        "description": grant.description or "",

        # Status & dates (standardized to EU convention)
        "status": "Open" if grant.is_active else "Closed",
        "is_active": grant.is_active,
        "opens_at": grant.opens_at,
        "closes_at": grant.closes_at,

        # Funding
        "total_fund_gbp": grant.total_fund_gbp,
        "total_fund_display": grant.total_fund or "",
        "project_funding_min": None,
        "project_funding_max": None,
        "competition_type": "grant",

        # Classification
        "tags": grant.tags or ["nihr", "health_research"],
        "sectors": ["health", "medical_research"],

        # Sections (tab-aware content)
        "sections": sections,

        # Resources
        "resources": resources,

        # Timestamps
        "scraped_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }


def ingest_nihr_opportunity(url: str, scraper: NihrFundingScraper):
    """
    Ingest one NIHR opportunity into MongoDB + Pinecone.
    Detects and logs changes from previous scrape.

    Returns:
        dict: {'success': bool, 'changed': bool, 'changes': list}
    """
    try:
        # Step 1: Scrape
        print(f"  📥 Scraping...")
        opp = scraper.scrape(url)

        # Step 2: Normalize
        grant, indexable_docs = normalize_nihr_opportunity(opp)

        print(f"  ✅ {grant.title[:60]}...")

        # Step 3: Build MongoDB document
        grant_doc = build_grant_document(grant, indexable_docs)

        # Step 4: Check for existing grant to detect changes
        old_grant = db.grants.find_one({"grant_id": grant_doc["grant_id"]})

        changes = []
        is_new = old_grant is None

        if old_grant:
            # Detect changes
            if old_grant.get("status") != grant_doc["status"]:
                changes.append(f"Status: {old_grant['status']} → {grant_doc['status']}")
            if old_grant.get("closes_at") != grant_doc["closes_at"]:
                old_date = old_grant.get("closes_at")
                new_date = grant_doc["closes_at"]
                old_str = old_date.strftime("%Y-%m-%d") if old_date else "N/A"
                new_str = new_date.strftime("%Y-%m-%d") if new_date else "N/A"
                changes.append(f"Deadline: {old_str} → {new_str}")
            if old_grant.get("total_fund_gbp") != grant_doc["total_fund_gbp"]:
                old_budget = old_grant.get("total_fund_gbp")
                new_budget = grant_doc["total_fund_gbp"]
                old_str = f"£{old_budget:,}" if old_budget else "N/A"
                new_str = f"£{new_budget:,}" if new_budget else "N/A"
                changes.append(f"Budget: {old_str} → {new_str}")
            if old_grant.get("title") != grant_doc["title"]:
                changes.append("Title changed")

        # Step 5: Upsert to MongoDB
        result = db.grants.update_one(
            {"grant_id": grant_doc["grant_id"]},
            {
                "$set": grant_doc,
                "$setOnInsert": {"created_at": datetime.utcnow()}
            },
            upsert=True
        )

        # Verify if new (upserted_id indicates insert, not update)
        is_new = result.upserted_id is not None

        if is_new:
            print(f"  🆕 NEW opportunity")
        elif changes:
            print(f"  🔄 CHANGES: {', '.join(changes)}")
        else:
            print(f"  ✓ No changes")

        print(f"  ✅ Saved to MongoDB")

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
        close_date = grant.closes_at
        index.upsert(vectors=[{
            'id': grant_doc["grant_id"],
            'values': embedding,
            'metadata': {
                'source': 'nihr',
                'title': grant.title[:500] if grant.title else '',
                'status': grant_doc["status"],
                'close_date': close_date.isoformat() if close_date else '',
                'url': grant.url,
                'tags': ','.join(grant.tags[:5]) if grant.tags else '',
                'budget_min': str(grant.total_fund_gbp) if grant.total_fund_gbp else '',
                'budget_max': str(grant.total_fund_gbp) if grant.total_fund_gbp else '',
                'total_fund': grant.total_fund or '',
            }
        }])

        print(f"  ✅ Indexed in Pinecone")

        return {
            'success': True,
            'is_new': is_new,
            'changed': len(changes) > 0,
            'changes': changes
        }

    except Exception as e:
        print(f"  ❌ Error: {type(e).__name__}: {str(e)[:100]}")
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
    file_urls = load_urls("data/urls/nihr_urls.txt")

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
    mongo_count = db.grants.count_documents({"source": "nihr"})
    open_count = db.grants.count_documents({"source": "nihr", "status": "Open"})

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
    print(f"📊 MongoDB (NIHR):")
    print(f"   Total: {mongo_count} grants")
    print(f"   Active: {open_count} grants")
    print(f"📊 Pinecone (Total): {pinecone_stats['total_vector_count']} vectors")

    if all_changes:
        print(f"\n🔄 DETAILED CHANGES:")
        for item in all_changes:
            print(f"\n   Opportunity {item['opportunity_id']}:")
            for change in item['changes']:
                print(f"      • {change}")

    print("=" * 70)

    mongo_client.close()


if __name__ == "__main__":
    main()
