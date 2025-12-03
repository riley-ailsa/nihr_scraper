#!/usr/bin/env python3
"""
Extract funding information from documents in Pinecone and update MongoDB.

Many NIHR grants have funding info in their PDFs and linked pages,
but not in the main grant metadata. This script:
1. Searches all document chunks for funding patterns
2. Extracts the best funding amount for each grant
3. Updates MongoDB with the extracted budgets
"""

import os
import re
from collections import defaultdict
from typing import Dict, List, Tuple, Optional
from dotenv import load_dotenv
from pinecone import Pinecone
from pymongo import MongoClient
from tqdm import tqdm

load_dotenv()

# Initialize connections
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index = pc.Index(os.getenv("PINECONE_INDEX_NAME", "ailsa-grants"))
mongo_client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = mongo_client[os.getenv("MONGO_DATABASE", "nihr_grants")]


def parse_gbp_amount(text: str) -> Optional[int]:
    """
    Parse GBP amount from text.

    Examples:
        "£4 million" → 4_000_000
        "up to £7m" → 7_000_000
        "£600,000" → 600_000
        "£1.5M" → 1_500_000
    """
    if not text:
        return None

    # Pattern: £ followed by number (with optional commas/decimals)
    # followed by optional magnitude word
    pattern = re.compile(
        r'£\s*([\d,\.]+)\s*([kKmMbB](?:illion)?|thousand|million|billion)?',
        re.IGNORECASE
    )

    match = pattern.search(text)
    if not match:
        return None

    # Extract number and magnitude
    number_str = match.group(1).replace(',', '')
    magnitude_str = (match.group(2) or '').lower().strip()

    # Parse base number
    try:
        base_amount = float(number_str)
    except ValueError:
        return None

    # Apply magnitude multiplier
    magnitude_map = {
        'k': 1_000,
        'm': 1_000_000,
        'b': 1_000_000_000,
        'bn': 1_000_000_000,
        'thousand': 1_000,
        'million': 1_000_000,
        'billion': 1_000_000_000,
    }

    multiplier = 1
    for mag_key, mag_value in magnitude_map.items():
        if magnitude_str.startswith(mag_key):
            multiplier = mag_value
            break

    # Calculate final amount
    return int(round(base_amount * multiplier))


def extract_funding_from_pinecone() -> Dict[str, List[Tuple[str, str, int]]]:
    """
    Extract funding information from all NIHR documents in Pinecone.

    Returns:
        Dict mapping grant_id to list of (doc_type, text_snippet, amount_gbp)
    """
    print("🔍 Fetching NIHR documents from Pinecone...")

    grant_funding = defaultdict(list)

    # Query multiple times with different vectors to get diverse results
    import random
    for batch in range(20):
        print(f"  Batch {batch + 1}/20...")

        # Random query vector
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
            text = meta.get('text', '')
            doc_type = meta.get('doc_type', 'unknown')

            if not grant_id or not text:
                continue

            # Search for funding patterns
            funding_patterns = [
                r'up to £[\d,\.]+\s*(?:million|m\b|k\b)?',
                r'funding (?:of |limit of |available )?£[\d,\.]+\s*(?:million|m\b|k\b)?',
                r'budget (?:of |up to )?£[\d,\.]+\s*(?:million|m\b|k\b)?',
                r'award[s]? (?:of |up to )?£[\d,\.]+\s*(?:million|m\b|k\b)?',
                r'grants? of £[\d,\.]+\s*(?:million|m\b|k\b)?',
                r'£[\d,\.]+\s*(?:million|m\b)',
            ]

            for pattern in funding_patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                for match_text in matches:
                    amount = parse_gbp_amount(match_text)
                    if amount and amount > 0:
                        grant_funding[grant_id].append((doc_type, match_text, amount))

    print(f"✅ Found funding info for {len(grant_funding)} grants")
    return dict(grant_funding)


def select_best_funding(funding_list: List[Tuple[str, str, int]]) -> Tuple[str, int]:
    """
    Select the most appropriate funding amount from multiple mentions.

    Strategy:
    1. Prefer "overview" or "research-specification" sections
    2. If multiple amounts, take the most commonly mentioned
    3. If still tied, take the highest

    Returns:
        (funding_text, amount_gbp)
    """
    if not funding_list:
        return None, None

    # Score by doc_type (prefer official sections)
    doc_type_priority = {
        'nihr_section::overview': 10,
        'nihr_section::research-specification': 9,
        'nihr_section::call-specification': 8,
        'pdf': 7,
        'linked_page': 5,
    }

    # Count occurrences of each amount
    amount_counts = defaultdict(int)
    amount_to_text = {}

    for doc_type, text, amount in funding_list:
        priority = doc_type_priority.get(doc_type, 1)
        amount_counts[amount] += priority
        amount_to_text[amount] = text

    # Get best amount (highest weighted count, then highest amount)
    best_amount = max(amount_counts.keys(), key=lambda a: (amount_counts[a], a))
    best_text = amount_to_text[best_amount]

    return best_text, best_amount


def update_mongodb(grant_funding: Dict[str, List[Tuple[str, str, int]]]):
    """Update MongoDB with extracted funding amounts."""
    from datetime import datetime

    print(f"\n💾 Updating MongoDB with funding info...")

    updated = 0
    skipped_has_funding = 0
    skipped_no_funding = 0

    for grant_id, funding_list in tqdm(grant_funding.items()):
        # Check if grant already has funding
        existing = db.grants.find_one(
            {"grant_id": grant_id},
            {"total_fund_gbp": 1}
        )

        if not existing:
            skipped_no_funding += 1
            continue

        existing_budget = existing.get("total_fund_gbp")

        # Skip if already has budget
        if existing_budget and existing_budget > 0:
            skipped_has_funding += 1
            continue

        # Select best funding amount
        funding_text, amount = select_best_funding(funding_list)

        if not amount or amount <= 0:
            skipped_no_funding += 1
            continue

        # Update database
        db.grants.update_one(
            {"grant_id": grant_id},
            {
                "$set": {
                    "total_fund_gbp": amount,
                    "total_fund_display": funding_text,
                    "updated_at": datetime.utcnow()
                }
            }
        )

        updated += 1

    print(f"\n✅ Updated: {updated}")
    print(f"⏭️  Skipped (already has funding): {skipped_has_funding}")
    print(f"⏭️  Skipped (no funding found): {skipped_no_funding}")


def main():
    print("=" * 70)
    print("EXTRACT FUNDING FROM DOCUMENTS → MONGODB")
    print("=" * 70)

    # Extract funding from Pinecone documents
    grant_funding = extract_funding_from_pinecone()

    if not grant_funding:
        print("❌ No funding information found")
        return

    # Show some examples
    print("\n📊 Sample extracted funding:\n")
    for grant_id, funding_list in list(grant_funding.items())[:5]:
        text, amount = select_best_funding(funding_list)
        print(f"{grant_id}: £{amount:,}")
        print(f"  Text: {text}")
        print(f"  Sources: {len(funding_list)} mentions")
        print()

    # Update MongoDB
    update_mongodb(grant_funding)

    # Final stats
    total = db.grants.count_documents({"source": "nihr"})
    with_positive = db.grants.count_documents({
        "source": "nihr",
        "total_fund_gbp": {"$gt": 0}
    })

    print("\n" + "=" * 70)
    print("EXTRACTION COMPLETE")
    print("=" * 70)
    print(f"📊 MongoDB (NIHR):")
    print(f"   Total grants: {total}")
    if total > 0:
        print(f"   With budget: {with_positive} ({with_positive*100//total}%)")
        print(f"   Without budget: {total - with_positive} ({(total-with_positive)*100//total}%)")
    else:
        print(f"   With budget: {with_positive}")
        print(f"   Without budget: {total - with_positive}")
    print("=" * 70)

    mongo_client.close()


if __name__ == "__main__":
    main()
