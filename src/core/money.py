"""
Money parsing utilities for UK funding amounts.

Handles various formats:
- "£4 million" → (£4 million, 4000000)
- "up to £7m" → (up to £7m, 7000000)
- "£600,000" → (£600,000, 600000)
- "£1.5M" → (£1.5M, 1500000)
"""

import re
from typing import Optional, Tuple


# Magnitude multipliers
_MAGNITUDE_MAP = {
    # Short forms
    "k": 1_000,
    "m": 1_000_000,
    "b": 1_000_000_000,
    "bn": 1_000_000_000,
    # Long forms
    "thousand": 1_000,
    "million": 1_000_000,
    "billion": 1_000_000_000,
}


def parse_gbp_amount(text: str) -> Tuple[str, Optional[int]]:
    """
    Parse GBP amount from text, extracting both display string and numeric value.

    Examples:
        "£4 million" → ("£4 million", 4_000_000)
        "up to £7m" → ("up to £7m", 7_000_000)
        "£600,000" → ("£600,000", 600_000)
        "£1.5M" → ("£1.5M", 1_500_000)
        "not specified" → ("not specified", None)

    Args:
        text: Raw funding amount text

    Returns:
        Tuple of (display_string, amount_in_gbp)
        amount_in_gbp is None if parsing fails
    """
    if not text or not text.strip():
        return text, None

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()

    # Pattern: £ followed by number (with optional commas/decimals)
    # followed by optional magnitude word
    pattern = re.compile(
        r"£\s*([\d,\.]+)\s*([kKmMbB](?:illion)?|thousand|million|billion)?",
        re.IGNORECASE
    )

    match = pattern.search(text)

    if not match:
        return text, None

    # Extract number and magnitude
    number_str = match.group(1).replace(",", "")
    magnitude_str = (match.group(2) or "").lower().strip()

    # Parse base number
    try:
        base_amount = float(number_str)
    except ValueError:
        return text, None

    # Apply magnitude multiplier
    multiplier = 1

    # Check for magnitude word
    for mag_key, mag_value in _MAGNITUDE_MAP.items():
        if magnitude_str.startswith(mag_key):
            multiplier = mag_value
            break

    # Calculate final amount
    amount_gbp = int(round(base_amount * multiplier))

    return text, amount_gbp


def format_gbp_amount(amount: Optional[int]) -> str:
    """
    Format numeric GBP amount for display.

    Examples:
        4_000_000 → "£4.0m"
        750_000 → "£750k"
        1_500_000 → "£1.5m"

    Args:
        amount: Amount in GBP (pence not supported)

    Returns:
        Formatted string
    """
    if amount is None:
        return "Not specified"

    if amount >= 1_000_000:
        return f"£{amount / 1_000_000:.1f}m"
    elif amount >= 1_000:
        return f"£{amount / 1_000:.0f}k"
    else:
        return f"£{amount:,}"
