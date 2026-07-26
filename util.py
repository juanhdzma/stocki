from __future__ import annotations

from datetime import UTC, datetime, timedelta


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def ensure_aware(dt: datetime) -> datetime:
    """Coerce a naive datetime to UTC-aware; leave already-aware ones untouched."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def parse_iso_aware(value: str | None) -> datetime | None:
    """Parse an ISO timestamp string into a UTC-aware datetime, or None if absent/malformed."""
    if not value:
        return None
    try:
        return ensure_aware(datetime.fromisoformat(value))
    except (ValueError, TypeError):
        return None


def today_and_week_ago() -> tuple[str, str]:
    """(today, 7-days-ago) as ISO dates — the score-history reference window."""
    today = datetime.now(UTC).date()
    return today.isoformat(), (today - timedelta(days=7)).isoformat()
