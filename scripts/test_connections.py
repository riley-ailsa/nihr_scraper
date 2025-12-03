#!/usr/bin/env python3
"""
Test connections to Pinecone, MongoDB, and OpenAI.
Run this to verify everything is set up correctly.
"""

import os
from dotenv import load_dotenv
from pinecone import Pinecone
from pymongo import MongoClient
import openai

# Load environment variables
load_dotenv()

def test_pinecone():
    """Test Pinecone connection"""
    print("\n🧪 Testing Pinecone...")

    try:
        api_key = os.getenv("PINECONE_API_KEY")
        index_name = os.getenv("PINECONE_INDEX_NAME", "ailsa-grants")

        pc = Pinecone(api_key=api_key)
        index = pc.Index(index_name)

        stats = index.describe_index_stats()

        print(f"✅ Pinecone connected!")
        print(f"   Index: {index_name}")
        print(f"   Dimension: {stats['dimension']}")
        print(f"   Total vectors: {stats['total_vector_count']}")

        return True
    except Exception as e:
        print(f"❌ Pinecone connection failed: {e}")
        return False


def test_mongodb():
    """Test MongoDB connection"""
    print("\n🧪 Testing MongoDB...")

    try:
        mongo_uri = os.getenv("MONGO_URI")
        db_name = os.getenv("MONGO_DB_NAME", "ailsa_grants")

        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)

        # Force connection
        client.admin.command('ping')

        db = client[db_name]
        collections = db.list_collection_names()

        # Count grants if collection exists
        grant_count = 0
        if 'grants' in collections:
            grant_count = db.grants.count_documents({})

        print(f"✅ MongoDB connected!")
        print(f"   Database: {db_name}")
        print(f"   Collections: {collections if collections else 'None'}")
        print(f"   Grants count: {grant_count}")

        client.close()
        return True
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        return False


def test_openai():
    """Test OpenAI connection"""
    print("\n🧪 Testing OpenAI...")

    try:
        api_key = os.getenv("OPENAI_API_KEY")
        openai.api_key = api_key

        # Test embedding
        response = openai.embeddings.create(
            input="test",
            model="text-embedding-3-small"
        )

        embedding = response.data[0].embedding

        print(f"✅ OpenAI connected!")
        print(f"   Model: text-embedding-3-small")
        print(f"   Embedding dimensions: {len(embedding)}")

        return True
    except Exception as e:
        print(f"❌ OpenAI connection failed: {e}")
        return False


def main():
    print("="*60)
    print("CONNECTION TESTS")
    print("="*60)

    results = {
        'pinecone': test_pinecone(),
        'mongodb': test_mongodb(),
        'openai': test_openai()
    }

    print("\n" + "="*60)
    print("RESULTS")
    print("="*60)

    all_passed = all(results.values())

    for service, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{service.upper()}: {status}")

    if all_passed:
        print("\n🎉 All connections successful! Ready to ingest data.")
    else:
        print("\n⚠️  Some connections failed. Fix errors above before proceeding.")

    return all_passed


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
