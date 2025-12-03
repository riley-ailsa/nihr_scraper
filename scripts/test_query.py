#!/usr/bin/env python3
"""
Test a clearly NIHR-relevant query to see what gets returned.
"""

import sys
import sqlite3
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.index.vector_index import VectorIndex
from src.storage.embedding_store import EmbeddingStore

def get_grant_source(grant_id: str) -> str:
    """Get the source for a grant ID from the database."""
    conn = sqlite3.connect("grants.db")
    cursor = conn.cursor()
    cursor.execute("SELECT source FROM grants WHERE id = ?", (grant_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else "unknown"

def main():
    print("=" * 80)
    print("Testing NIHR-relevant query")
    print("=" * 80)
    print()

    # Initialize the vector index
    vector_index = VectorIndex(db_path="grants.db", use_persistent_storage=True)

    # Test query
    query = "mental health clinical trial funding"
    print(f"Query: '{query}'")
    print()

    # Search
    results = vector_index.query(query, top_k=10)

    print(f"Found {len(results)} results:")
    print()

    for i, result in enumerate(results, 1):
        source = get_grant_source(result.grant_id) if result.grant_id else "unknown"
        print(f"{i}. Score: {result.score:.4f}")
        print(f"   Grant ID: {result.grant_id}")
        print(f"   Source: {source}")
        print(f"   Text preview: {result.text[:200]}...")
        print()

    # Count by source
    sources = {}
    for result in results:
        source = get_grant_source(result.grant_id) if result.grant_id else "unknown"
        sources[source] = sources.get(source, 0) + 1

    print("Results by source:")
    for source, count in sources.items():
        print(f"  {source:30} {count:>10}")
    print()

if __name__ == "__main__":
    main()
