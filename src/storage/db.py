"""
Lightweight SQLite database wrapper.

Handles:
- Database initialization
- Schema creation
- Connection management

Designed to be easily swappable with Postgres/MySQL later.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
import logging


logger = logging.getLogger(__name__)


class Database:
    """
    SQLite database wrapper for grants and documents.

    Usage:
        db = Database("grants.db")
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM grants")
    """

    def __init__(self, path: str = "grants.db"):
        """
        Initialize database.

        Args:
            path: Path to SQLite database file
        """
        self.path = path

        # Ensure parent directory exists
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)

        # Initialize schema
        self._init_db()

        logger.info(f"Database initialized: {self.path}")

    def _init_db(self):
        """Create database schema if it doesn't exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Grants table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS grants (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    external_id TEXT,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    description TEXT,
                    opens_at TEXT,
                    closes_at TEXT,
                    total_fund TEXT,
                    total_fund_gbp INTEGER,
                    project_size TEXT,
                    funding_rules_json TEXT,
                    is_active INTEGER NOT NULL,
                    tags_json TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # Create index on URL for fast lookups
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_grants_url
                ON grants(url);
                """
            )

            # Create index on source for filtering
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_grants_source
                ON grants(source);
                """
            )

            # Documents table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    grant_id TEXT NOT NULL,
                    resource_id TEXT,
                    doc_type TEXT NOT NULL,
                    scope TEXT DEFAULT 'competition',
                    source_url TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (grant_id) REFERENCES grants(id) ON DELETE CASCADE
                );
                """
            )

            # Create index on grant_id for fast joins
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_documents_grant_id
                ON documents(grant_id);
                """
            )

            # Create index on doc_type for filtering
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_documents_doc_type
                ON documents(doc_type);
                """
            )

            # Embeddings table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS embeddings (
                    id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    grant_id TEXT,
                    chunk_index INTEGER NOT NULL,
                    vector BLOB NOT NULL,
                    text TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    doc_type TEXT,
                    scope TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (grant_id) REFERENCES grants(id) ON DELETE CASCADE
                );
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_embeddings_grant_id
                ON embeddings(grant_id);
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_embeddings_doc_id
                ON embeddings(doc_id);
                """
            )

            # Explanations cache table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS explanations (
                    query_hash TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    model TEXT NOT NULL,
                    referenced_grants TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    accessed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    access_count INTEGER DEFAULT 1
                );
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_explanations_query
                ON explanations(query);
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_explanations_accessed
                ON explanations(accessed_at);
                """
            )

            conn.commit()
            logger.debug("Database schema created/verified (including embeddings and explanations)")

    @contextmanager
    def get_connection(self) -> Iterator[sqlite3.Connection]:
        """
        Get a database connection context manager.

        Automatically commits on success, closes on exit.

        Yields:
            sqlite3.Connection
        """
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row  # Enable column access by name

        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            conn.close()
