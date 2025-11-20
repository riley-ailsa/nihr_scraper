"""
Storage layer for Grant objects.

Handles:
- Persisting Grant objects to database
- Retrieving grants by ID or URL
- Listing grants with pagination
"""

import json
import logging
from typing import List, Optional
from datetime import datetime

from src.core.domain_models import Grant
from .db import Database


logger = logging.getLogger(__name__)


class GrantStore:
    """
    Persistent storage for Grant objects.

    Usage:
        store = GrantStore("grants.db")
        store.upsert_grant(grant)
        grant = store.get_grant(grant_id)
    """

    def __init__(self, db_path: str = "grants.db"):
        """
        Initialize grant store.

        Args:
            db_path: Path to SQLite database
        """
        self.db = Database(db_path)

    def upsert_grant(self, grant: Grant) -> None:
        """
        Insert or update a grant.

        Uses UPSERT (INSERT ... ON CONFLICT) to handle updates.

        Args:
            grant: Grant object to persist
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO grants (
                    id, source, external_id, title, url, description,
                    opens_at, closes_at, total_fund, total_fund_gbp, project_size,
                    funding_rules_json, is_active, tags_json,
                    created_at, updated_at
                )
                VALUES (
                    :id, :source, :external_id, :title, :url, :description,
                    :opens_at, :closes_at, :total_fund, :total_fund_gbp, :project_size,
                    :funding_rules_json, :is_active, :tags_json,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                ON CONFLICT(id) DO UPDATE SET
                    source=excluded.source,
                    external_id=excluded.external_id,
                    title=excluded.title,
                    url=excluded.url,
                    description=excluded.description,
                    opens_at=excluded.opens_at,
                    closes_at=excluded.closes_at,
                    total_fund=excluded.total_fund,
                    total_fund_gbp=excluded.total_fund_gbp,
                    project_size=excluded.project_size,
                    funding_rules_json=excluded.funding_rules_json,
                    is_active=excluded.is_active,
                    tags_json=excluded.tags_json,
                    updated_at=CURRENT_TIMESTAMP;
                """,
                {
                    "id": grant.id,
                    "source": grant.source,
                    "external_id": grant.external_id,
                    "title": grant.title,
                    "url": grant.url,
                    "description": grant.description or "",
                    "opens_at": grant.opens_at.isoformat() if grant.opens_at else None,
                    "closes_at": grant.closes_at.isoformat() if grant.closes_at else None,
                    "total_fund": grant.total_fund,
                    "total_fund_gbp": grant.total_fund_gbp,
                    "project_size": grant.project_size,
                    "funding_rules_json": json.dumps(grant.funding_rules or {}),
                    "is_active": 1 if grant.is_active else 0,
                    "tags_json": json.dumps(grant.tags or []),
                },
            )

            logger.debug(f"Upserted grant: {grant.id}")

    def exists(self, grant_id: str) -> bool:
        """
        Check if grant exists by ID.

        Args:
            grant_id: Grant ID to check

        Returns:
            True if grant exists
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM grants WHERE id = ? LIMIT 1",
                (grant_id,)
            )
            return cursor.fetchone() is not None

    def exists_by_url(self, url: str) -> bool:
        """
        Check if grant exists by URL.

        Useful for deduplication during ingestion.

        Args:
            url: Grant URL to check

        Returns:
            True if grant with this URL exists
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM grants WHERE url = ? LIMIT 1",
                (url,)
            )
            return cursor.fetchone() is not None

    def get_grant(self, grant_id: str) -> Optional[Grant]:
        """
        Retrieve grant by ID.

        Args:
            grant_id: Grant ID

        Returns:
            Grant object or None if not found
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM grants WHERE id = ? LIMIT 1",
                (grant_id,)
            )
            row = cursor.fetchone()

            if not row:
                return None

            return self._row_to_grant(row)

    def list_grants(
        self,
        limit: int = 100,
        offset: int = 0,
        active_only: bool = False
    ) -> List[Grant]:
        """
        List grants with pagination.

        Args:
            limit: Maximum number of grants to return
            offset: Number of grants to skip
            active_only: If True, only return active grants

        Returns:
            List of Grant objects
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            query = "SELECT * FROM grants"
            params = []

            if active_only:
                query += " WHERE is_active = 1"

            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [self._row_to_grant(row) for row in rows]

    def _row_to_grant(self, row) -> Grant:
        """
        Convert database row to Grant object.

        Args:
            row: SQLite row

        Returns:
            Grant object
        """
        def parse_datetime(s: Optional[str]) -> Optional[datetime]:
            return datetime.fromisoformat(s) if s else None

        # Check if total_fund_gbp column exists in row
        try:
            total_fund_gbp = row["total_fund_gbp"]
        except (KeyError, IndexError):
            total_fund_gbp = None

        return Grant(
            id=row["id"],
            source=row["source"],
            external_id=row["external_id"],
            title=row["title"],
            url=row["url"],
            description=row["description"] or "",
            opens_at=parse_datetime(row["opens_at"]),
            closes_at=parse_datetime(row["closes_at"]),
            total_fund=row["total_fund"],
            total_fund_gbp=total_fund_gbp,
            project_size=row["project_size"],
            funding_rules=json.loads(row["funding_rules_json"] or "{}"),
            is_active=bool(row["is_active"]),
            tags=json.loads(row["tags_json"] or "[]"),
            scraped_at=parse_datetime(row["created_at"]),
            updated_at=parse_datetime(row["updated_at"]),
        )
