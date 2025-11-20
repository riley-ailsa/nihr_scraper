"""
Timezone utilities for grant status determination.
All grant deadlines are in UK local time (Europe/London).
"""

from datetime import datetime
import zoneinfo

# Canonical timezone for all grant operations
TZ_LONDON = zoneinfo.ZoneInfo("Europe/London")


def now_london():
    """
    Get current datetime in London local time.

    Returns:
        datetime: Current time with Europe/London timezone
    """
    return datetime.now(TZ_LONDON)


def infer_status(opens_at, closes_at):
    """
    Determine grant status using London local time.

    Compares current London time against grant open/close dates to determine
    if a grant is upcoming, active, or closed. Handles timezone-naive datetimes
    by assuming they are in London time.

    Args:
        opens_at: datetime or None - When grant opens
        closes_at: datetime or None - When grant closes

    Returns:
        str: One of 'upcoming', 'active', or 'closed'
    """
    now = now_london()

    # Ensure datetimes are timezone-aware (assume London time if naive)
    if opens_at and opens_at.tzinfo is None:
        opens_at = opens_at.replace(tzinfo=TZ_LONDON)
    if closes_at and closes_at.tzinfo is None:
        closes_at = closes_at.replace(tzinfo=TZ_LONDON)

    # Status logic
    if opens_at and now < opens_at:
        return "upcoming"
    if closes_at and now > closes_at:
        return "closed"
    return "active"
