"""
Persistent storage for embeddings.

Stores OpenAI embeddings in SQLite to avoid regeneration on restart.
"""

import pickle
import logging
from typing import List, Dict, Any, Optional, Tuple

import numpy as np

from .db import Database


logger = logging.getLogger(__name__)


class EmbeddingStore:
    """
    Persistent storage for vector embeddings.

    Features:
    - Store embeddings in SQLite (BLOB)
    - Fast bulk load on startup
    - Incremental updates
    - Automatic de-duplication
    """

    def __init__(self, db_path: str = "grants.db"):
        """Initialize embedding store."""
        self.db = Database(db_path)
        logger.info("EmbeddingStore initialized")

    def save_embedding(
        self,
        emb_id: str,
        doc_id: str,
        grant_id: Optional[str],
        chunk_index: int,
        vector: np.ndarray,
        text: str,
        source_url: str,
        doc_type: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> None:
        """Save a single embedding to database."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            vector_blob = pickle.dumps(vector.astype(np.float32))

            cursor.execute(
                """
                INSERT OR REPLACE INTO embeddings (
                    id, doc_id, grant_id, chunk_index, vector, text,
                    source_url, doc_type, scope, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    emb_id, doc_id, grant_id, chunk_index, vector_blob,
                    text, source_url, doc_type, scope,
                ),
            )

    def save_batch(self, embeddings: List[Dict[str, Any]]) -> None:
        """Save multiple embeddings in a single transaction."""
        if not embeddings:
            return

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            for emb in embeddings:
                vector_blob = pickle.dumps(emb["vector"].astype(np.float32))

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO embeddings (
                        id, doc_id, grant_id, chunk_index, vector, text,
                        source_url, doc_type, scope, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        emb["emb_id"], emb["doc_id"], emb["grant_id"],
                        emb["chunk_index"], vector_blob, emb["text"],
                        emb["source_url"], emb["doc_type"], emb["scope"],
                    ),
                )

        logger.info(f"Saved {len(embeddings)} embeddings to database")

    def load_all(self) -> List[Tuple[str, np.ndarray, str, Dict[str, Any]]]:
        """Load all embeddings from database."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT id, vector, text, doc_id, grant_id, chunk_index,
                       source_url, doc_type, scope
                FROM embeddings
                ORDER BY created_at
                """
            )

            rows = cursor.fetchall()

        embeddings = []

        for row in rows:
            emb_id = row["id"]
            vector = pickle.loads(row["vector"])
            text = row["text"]

            metadata = {
                "doc_id": row["doc_id"],
                "grant_id": row["grant_id"],
                "chunk_index": row["chunk_index"],
                "source_url": row["source_url"],
                "doc_type": row["doc_type"],
                "scope": row["scope"],
            }

            embeddings.append((emb_id, vector, text, metadata))

        logger.info(f"Loaded {len(embeddings)} embeddings from database")
        return embeddings

    def exists(self, emb_id: str) -> bool:
        """Check if embedding already exists."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM embeddings WHERE id = ? LIMIT 1",
                (emb_id,)
            )
            return cursor.fetchone() is not None

    def count(self) -> int:
        """Get total number of embeddings."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM embeddings")
            return cursor.fetchone()[0]

    def delete_for_grant(self, grant_id: str) -> int:
        """Delete all embeddings for a specific grant."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM embeddings WHERE grant_id = ?",
                (grant_id,)
            )
            deleted = cursor.rowcount

        logger.info(f"Deleted {deleted} embeddings for grant {grant_id}")
        return deleted
