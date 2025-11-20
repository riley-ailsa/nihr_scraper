"""
Shared utility functions for ID generation, hashing, and date parsing.
"""

import hashlib
import re
from datetime import datetime
from typing import Optional
from dateutil import parser as dateparser


def stable_id_from_url(url: str, prefix: str = "") -> str:
    """
    Generate a stable, short identifier from a URL.

    Uses SHA1 hash truncated to 16 characters.

    Args:
        url: Full URL to hash
        prefix: Optional prefix (e.g., "iuk_", "res_")

    Returns:
        Stable ID like "iuk_a1b2c3d4e5f6g7h8"

    Examples:
        >>> stable_id_from_url("https://example.com/page", "iuk_")
        'iuk_a1b2c3d4e5f6g7h8'
    """
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}{h}" if prefix else h


def sha1_text(text: str) -> str:
    """
    Generate SHA1 hash of text content.

    Used for de-duplication of document content.

    Args:
        text: Text to hash

    Returns:
        Full 40-character SHA1 hex digest

    Examples:
        >>> sha1_text("Hello world")
        '7b502c3a1f48c8609ae212cdfb639dee39673f5e'
    """
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def parse_date_maybe(text: str) -> Optional[datetime]:
    """
    Attempt to parse a date string, returning None on failure.

    Uses dateutil.parser with day-first=True for UK date formats.

    Args:
        text: Date string (e.g., "10 April 2024 11:00am")

    Returns:
        Parsed datetime or None if parsing fails

    Examples:
        >>> parse_date_maybe("10 April 2024 11:00am")
        datetime.datetime(2024, 4, 10, 11, 0)
        >>> parse_date_maybe("not a date")
        None
    """
    text = text.strip()
    if not text:
        return None

    try:
        # dayfirst=True handles UK date formats (DD/MM/YYYY)
        return dateparser.parse(text, dayfirst=True)
    except (ValueError, TypeError, AttributeError):
        return None


def clean_text(text: str) -> str:
    """
    Clean text by normalizing whitespace and removing extra newlines.

    Args:
        text: Raw text

    Returns:
        Cleaned text
    """
    # Replace multiple spaces with single space
    text = re.sub(r' +', ' ', text)
    # Replace multiple newlines with double newline
    text = re.sub(r'\n\n+', '\n\n', text)
    return text.strip()


def extract_money_amount(text: str) -> Optional[str]:
    """
    Extract money amounts from text (e.g., "£5 million", "£150,000").

    Args:
        text: Text containing money amount

    Returns:
        Extracted amount string or None

    Examples:
        >>> extract_money_amount("Up to £5 million is available")
        'Up to £5 million'
    """
    # Pattern: "up to £X million/thousand" or "£X to £Y"
    patterns = [
        r'up to £[0-9,]+(?:\s*(?:million|thousand|billion))?',
        r'£[0-9,]+(?:\s*(?:million|thousand|billion))?\s+to\s+£[0-9,]+(?:\s*(?:million|thousand|billion))?',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)

    return None
