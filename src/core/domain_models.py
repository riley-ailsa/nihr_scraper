"""
Canonical domain models for the grant discovery system.

These models represent the final, normalized data structures that the entire
system uses for storage, indexing, and search.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any


@dataclass
class Grant:
    """
    Canonical grant/competition object.

    This is the normalized, system-wide representation of a funding opportunity.
    All scrapers (Innovate UK, SBIR, etc.) normalize their output into this format.
    """
    # Required fields
    id: str
    source: str  # e.g., "innovate_uk", "sbir_gov"
    title: str
    description: str
    url: str

    # Optional fields
    external_id: Optional[str] = None  # Source's native ID
    opens_at: Optional[datetime] = None
    closes_at: Optional[datetime] = None
    is_active: bool = False

    # Funding information
    total_fund: Optional[str] = None  # Display string: "£4 million"
    total_fund_gbp: Optional[int] = None  # Numeric value: 4_000_000
    project_size: Optional[str] = None

    # Structured funding rules (if available)
    funding_rules: Dict[str, Any] = field(default_factory=dict)

    # Tags for filtering/search
    tags: List[str] = field(default_factory=list)

    # Timestamps
    scraped_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class IndexableDocument:
    """
    Document ready for vector indexing.

    This represents a chunk of text that will be:
    1. Embedded into a vector
    2. Stored in a vector index
    3. Retrieved during semantic search
    """
    # Required fields (no defaults)
    id: str
    grant_id: str
    doc_type: str  # "competition_section", "briefing_pdf", "guidance"
    text: str
    source_url: str

    # Optional fields (with defaults)
    resource_id: Optional[str] = None  # Link to original resource
    section_name: Optional[str] = None  # For sections: "eligibility", "scope", etc.
    citation_text: Optional[str] = None  # Human-readable citation
    scope: str = "competition"  # "competition" or "global"
    chunk_index: int = 0
    total_chunks: int = 1
    indexed_at: datetime = field(default_factory=datetime.utcnow)
