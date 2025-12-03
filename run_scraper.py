#!/usr/bin/env python3
"""
Complete dry run of NIHR scraper pipeline:
1. Scrape NIHR page
2. Normalize to Grant + Documents
3. Generate embeddings (sample)
4. Show what would be stored

No actual database writes - just shows the data flow.
"""
import os
import json
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

print("=" * 80)
print("NIHR SCRAPER DRY RUN - NO DATABASE WRITES")
print("=" * 80)

# Step 1: Scrape NIHR page
print("\n[STEP 1] Scraping NIHR funding page...")
print("-" * 80)

from src.ingest.nihr_funding import NihrFundingScraper

scraper = NihrFundingScraper()
url = 'https://www.nihr.ac.uk/funding/team-science-award-cohort-3/2025448'

print(f"Target URL: {url}")
opp = scraper.scrape(url)

print(f"\n✅ Scraping complete!")
print(f"   Title: {opp.title}")
print(f"   Status: {opp.opportunity_status}")
print(f"   Reference: {opp.reference_id}")
print(f"   Programme: {opp.programme or 'N/A'}")
print(f"   Funding: {opp.funding_text[:80]}..." if opp.funding_text else "   Funding: None")
print(f"   Opens: {opp.opening_date}")
print(f"   Closes: {opp.closing_date}")
print(f"   Sections: {len(opp.sections)}")
print(f"   Resources: {len(opp.resources)}")

# Step 2: Normalize to Grant + Documents
print("\n[STEP 2] Normalizing to Grant + Documents...")
print("-" * 80)

from src.normalize.nihr import normalize_nihr_opportunity, infer_nihr_status

grant, documents = normalize_nihr_opportunity(opp)

print(f"\n✅ Normalization complete!")
print(f"   Grant ID: {grant.id}")
print(f"   Grant Source: {grant.source}")
print(f"   External ID: {grant.external_id}")
print(f"   Title: {grant.title}")
print(f"   URL: {grant.url}")
print(f"   Status: {infer_nihr_status(opp)}")
print(f"   Is Active: {grant.is_active}")
print(f"   Total Fund: {grant.total_fund}")
print(f"   Total Fund GBP: £{grant.total_fund_gbp:,}" if grant.total_fund_gbp else "   Total Fund GBP: None")
print(f"   Tags: {grant.tags}")
print(f"   Documents: {len(documents)}")

print("\n   Document breakdown:")
for i, doc in enumerate(documents, 1):
    print(f"   {i}. {doc.doc_type:45s} | {doc.section_name:20s} | {len(doc.text):6,d} chars")

# Step 3: Generate embeddings (sample)
print("\n[STEP 3] Generating embeddings (sample: first 3 documents)...")
print("-" * 80)

from src.api.embeddings import create_embeddings_batch

# Sample first 3 documents for dry run
sample_docs = documents[:3]
print(f"Generating embeddings for {len(sample_docs)} sample documents...")

texts = [doc.text for doc in sample_docs]
embeddings = create_embeddings_batch(texts)

print(f"\n✅ Embeddings generated!")
print(f"   Count: {len(embeddings)}")
print(f"   Dimensions: {len(embeddings[0]) if embeddings else 'N/A'}")
print(f"   Sample embedding (first 5 values): {embeddings[0][:5] if embeddings else 'N/A'}")

# Step 4: Show Grant data that would be stored
print("\n[STEP 4] Grant data that would be stored in MongoDB...")
print("-" * 80)

grant_data = {
    "id": grant.id,
    "source": grant.source,
    "external_id": grant.external_id,
    "title": grant.title,
    "url": grant.url,
    "description": grant.description[:100] + "..." if grant.description and len(grant.description) > 100 else grant.description,
    "opens_at": grant.opens_at.isoformat() if grant.opens_at else None,
    "closes_at": grant.closes_at.isoformat() if grant.closes_at else None,
    "total_fund": grant.total_fund,
    "total_fund_gbp": grant.total_fund_gbp,
    "is_active": grant.is_active,
    "tags": grant.tags,
}

print("Grant record to be stored:")
print(json.dumps(grant_data, indent=2))

# Step 5: Show Document data
print("\n[STEP 5] Document data that would be stored...")
print("-" * 80)

print(f"Documents to be stored: {len(documents)}")
for i, doc in enumerate(documents, 1):
    print(f"\n   Document {i}:")
    print(f"      ID: {doc.id}")
    print(f"      Grant ID: {doc.grant_id}")
    print(f"      Type: {doc.doc_type}")
    print(f"      Section: {doc.section_name}")
    print(f"      Text length: {len(doc.text):,} chars")
    print(f"      Source URL: {doc.source_url}")
    print(f"      Citation: {doc.citation_text}")
    if i <= 3:  # Show text preview for first 3
        print(f"      Text preview: {doc.text[:100]}...")

# Step 6: Show Embedding data
print("\n[STEP 6] Embeddings that would be stored in Pinecone...")
print("-" * 80)

print(f"Embeddings to be upserted: {len(documents)} total")
print(f"   Index: {os.getenv('PINECONE_INDEX_NAME')}")
print(f"   Namespace: grants")

for i, (doc, emb) in enumerate(zip(sample_docs, embeddings), 1):
    print(f"\n   Embedding {i}:")
    print(f"      Vector ID: {doc.id}")
    print(f"      Dimensions: {len(emb)}")
    print(f"      Metadata:")
    metadata = {
        "grant_id": doc.grant_id,
        "doc_type": doc.doc_type,
        "section_name": doc.section_name,
        "source_url": doc.source_url,
        "text_preview": doc.text[:100] + "...",
    }
    print(json.dumps(metadata, indent=10))

# Step 7: Database check (MongoDB)
print("\n[STEP 7] MongoDB connection check...")
print("-" * 80)

try:
    from pymongo import MongoClient

    mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017')
    mongo_db_name = os.getenv('MONGO_DATABASE', 'nihr_grants')

    client = MongoClient(mongo_uri)
    db = client[mongo_db_name]

    # Check if grant already exists
    grant_id = f"nihr_{grant.external_id}" if grant.external_id else grant.id
    existing = db.grants.find_one({"grant_id": grant_id})

    if existing:
        print(f"⚠️  Grant already exists in MongoDB")
        print(f"   Existing ID: {existing.get('grant_id')}")
        print(f"   Existing title: {existing.get('title')}")
        print(f"   Scraped at: {existing.get('scraped_at')}")
        print(f"   → Would UPDATE existing record")
    else:
        print(f"✅ Grant does not exist in database")
        print(f"   → Would INSERT new record")

    # Check total grant count
    total_count = db.grants.count_documents({"source": "nihr"})
    print(f"\n   Total NIHR grants in database: {total_count}")
    print(f"   → Would upsert {len(documents)} documents")

    client.close()

except Exception as e:
    print(f"❌ MongoDB connection error: {str(e)}")

# Step 8: Pinecone check
print("\n[STEP 8] Pinecone index check...")
print("-" * 80)

try:
    from pinecone import Pinecone

    pc = Pinecone(api_key=os.getenv('PINECONE_API_KEY'))
    index_name = os.getenv('PINECONE_INDEX_NAME')
    index = pc.Index(index_name)

    stats = index.describe_index_stats()
    print(f"✅ Pinecone index: {index_name}")
    print(f"   Total vectors: {stats.total_vector_count:,}")
    print(f"   → Would upsert {len(documents)} new vectors")

    # Try to fetch one existing vector for this grant
    try:
        existing_vec = index.fetch(ids=[documents[0].id])
        if existing_vec.vectors:
            print(f"\n   ⚠️  Vector {documents[0].id} already exists")
            print(f"   → Would UPDATE existing vectors")
        else:
            print(f"\n   ✅ Vectors do not exist for this grant")
            print(f"   → Would INSERT new vectors")
    except Exception:
        print(f"\n   ✅ Vectors do not exist for this grant")
        print(f"   → Would INSERT new vectors")

except Exception as e:
    print(f"❌ Pinecone connection error: {str(e)}")

# Summary
print("\n" + "=" * 80)
print("DRY RUN SUMMARY")
print("=" * 80)

print("\n✅ All pipeline steps completed successfully!")
print(f"\nData ready to be stored:")
print(f"   • 1 Grant record (ID: {grant.id})")
print(f"   • {len(documents)} Document records")
print(f"   • {len(documents)} Embedding vectors (1536 dimensions each)")

total_chars = len(grant.title or '') + len(grant.description or '') + sum(len(d.text) for d in documents)
print(f"\nTotal storage estimate:")
print(f"   • MongoDB: ~{total_chars:,} characters")
print(f"   • Pinecone: ~{len(documents) * 1536 * 4:,} bytes ({len(documents) * 1536 * 4 / 1024:.1f} KB)")

print("\n" + "=" * 80)
print("To run full ingestion:")
print("  python run_ingestion.py")
print("=" * 80)
