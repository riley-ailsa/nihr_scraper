"""
Storage layer for IndexableDocument objects.

Handles:
- Persisting document text and metadata
- Retrieving documents by grant
- Batch operations
"""

import logging
from typing import List, Optional
from datetime import datetime

from src.core.domain_models import IndexableDocument
from .db import Database


logger = logging.getLogger(__name__)


class DocumentStore:
    """
    Persistent storage for IndexableDocument objects.

    Usage:
        store = DocumentStore("grants.db")
        store.upsert_documents(docs)
        docs = store.get_documents_for_grant(grant_id)
    """

    def __init__(self, db_path: str = "grants.db"):
        """
        Initialize document store.

        Args:
            db_path: Path to SQLite database
        """
        self.db = Database(db_path)

    def upsert_documents(self, docs: List[IndexableDocument]) -> None:
        """
        Insert or update multiple documents.

        Uses batch operations for efficiency.

        Args:
            docs: List of IndexableDocument objects to persist
        """
        if not docs:
            return

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            for doc in docs:
                # Extract resource_id from the doc if it exists
                resource_id = getattr(doc, 'resource_id', None)
                scope = getattr(doc, 'scope', 'competition')

                cursor.execute(
                    """
                    INSERT INTO documents (
                        id, grant_id, resource_id, doc_type,
                        scope, source_url, text,
                        created_at, updated_at
                    )
                    VALUES (
                        :id, :grant_id, :resource_id, :doc_type,
                        :scope, :source_url, :text,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    ON CONFLICT(id) DO UPDATE SET
                        grant_id=excluded.grant_id,
                        resource_id=excluded.resource_id,
                        doc_type=excluded.doc_type,
                        scope=excluded.scope,
                        source_url=excluded.source_url,
                        text=excluded.text,
                        updated_at=CURRENT_TIMESTAMP;
                    """,
                    {
                        "id": doc.id,
                        "grant_id": doc.grant_id,
                        "resource_id": resource_id,
                        "doc_type": doc.doc_type,
                        "scope": scope,
                        "source_url": doc.source_url,
                        "text": doc.text,
                    },
                )

            logger.debug(f"Upserted {len(docs)} documents")

    def get_documents_for_grant(self, grant_id: str) -> List[IndexableDocument]:
        """
        Retrieve all documents for a specific grant.

        Args:
            grant_id: Grant ID

        Returns:
            List of IndexableDocument objects
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, grant_id, resource_id, doc_type,
                       scope, source_url, text, created_at
                FROM documents
                WHERE grant_id = ?
                ORDER BY created_at
                """,
                (grant_id,),
            )
            rows = cursor.fetchall()

            return [self._row_to_document(row) for row in rows]

    def get_document(self, doc_id: str) -> Optional[IndexableDocument]:
        """
        Retrieve a single document by ID.

        Args:
            doc_id: Document ID

        Returns:
            IndexableDocument or None if not found
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, grant_id, resource_id, doc_type,
                       scope, source_url, text, created_at
                FROM documents
                WHERE id = ? LIMIT 1
                """,
                (doc_id,),
            )
            row = cursor.fetchone()

            if not row:
                return None

            return self._row_to_document(row)

    def _row_to_document(self, row) -> IndexableDocument:
        """
        Convert database row to IndexableDocument.

        Args:
            row: SQLite row

        Returns:
            IndexableDocument object
        """
        def parse_datetime(s: Optional[str]) -> Optional[datetime]:
            return datetime.fromisoformat(s) if s else None

        return IndexableDocument(
            id=row["id"],
            grant_id=row["grant_id"],
            doc_type=row["doc_type"],
            text=row["text"],
            source_url=row["source_url"],
            section_name=None,  # Not stored in DB
            citation_text=None,  # Not stored in DB
            chunk_index=0,
            total_chunks=1,
            indexed_at=parse_datetime(row["created_at"]),
        )
