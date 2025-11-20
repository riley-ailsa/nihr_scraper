"""
SQLite-based cache for fetched resources.
Prevents re-fetching PDFs and webpages.
"""

import sqlite3
import hashlib
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class FetchCache:
    """Cache for fetched resources with TTL support."""

    def __init__(self, db_path: str = "fetch_cache.db", ttl_days: int = 30):
        self.db_path = db_path
        self.ttl_days = ttl_days
        self._init_db()

    def _init_db(self):
        """Initialize cache database."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fetch_cache (
                url_hash TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                content BLOB,
                content_type TEXT,
                fetched_at TIMESTAMP,
                metadata TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_fetched_at
            ON fetch_cache(fetched_at)
        """)
        conn.commit()
        conn.close()

    def get(self, url: str) -> Optional[Dict[str, Any]]:
        """Get cached resource if not expired."""
        url_hash = hashlib.sha256(url.encode()).hexdigest()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT content, content_type, fetched_at, metadata
            FROM fetch_cache
            WHERE url_hash = ?
        """, (url_hash,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        content, content_type, fetched_at, metadata = row

        # Check TTL
        fetched_dt = datetime.fromisoformat(fetched_at)
        if datetime.now() - fetched_dt > timedelta(days=self.ttl_days):
            logger.debug(f"Cache expired for {url}")
            return None

        return {
            'content': content,
            'content_type': content_type,
            'metadata': json.loads(metadata) if metadata else {}
        }

    def set(self, url: str, content: bytes, content_type: str,
            metadata: Optional[Dict] = None):
        """Store resource in cache."""
        url_hash = hashlib.sha256(url.encode()).hexdigest()

        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT OR REPLACE INTO fetch_cache
            (url_hash, url, content, content_type, fetched_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            url_hash,
            url,
            content,
            content_type,
            datetime.now().isoformat(),
            json.dumps(metadata) if metadata else None
        ))
        conn.commit()
        conn.close()

        logger.debug(f"Cached {content_type}: {url}")

    def cleanup_expired(self):
        """Remove expired entries."""
        cutoff = datetime.now() - timedelta(days=self.ttl_days)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM fetch_cache
            WHERE fetched_at < ?
        """, (cutoff.isoformat(),))

        deleted = cursor.rowcount
        conn.commit()
        conn.close()

        if deleted > 0:
            logger.info(f"Cleaned up {deleted} expired cache entries")