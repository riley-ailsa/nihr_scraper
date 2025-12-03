#!/usr/bin/env python3
"""
Test connections to Pinecone and PostgreSQL.
Run this to verify everything is set up correctly.
"""

import os
from dotenv import load_dotenv
from pinecone import Pinecone
import psycopg2
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


def test_postgres():
    """Test PostgreSQL connection"""
    print("\n🧪 Testing PostgreSQL...")
    
    try:
        database_url = os.getenv("DATABASE_URL")
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()
        
        # Test query
        cursor.execute("SELECT version();")
        version = cursor.fetchone()[0]
        
        # Check if tables exist
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        tables = [row[0] for row in cursor.fetchall()]
        
        print(f"✅ PostgreSQL connected!")
        print(f"   Version: {version[:50]}...")
        print(f"   Tables found: {len(tables)}")
        print(f"   Sample tables: {tables[:5]}")
        
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ PostgreSQL connection failed: {e}")
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
        'postgres': test_postgres(),
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