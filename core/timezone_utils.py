"""Application timezone helpers (default: Africa/Nairobi, UTC+3)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from config import APP_TIMEZONE


def get_tz() -> ZoneInfo:
    return ZoneInfo(APP_TIMEZONE)


def now_local() -> datetime:
    """Current time in the configured app timezone (aware)."""
    return datetime.now(get_tz())


def now_local_naive() -> datetime:
    """Current local time without tzinfo — safe for comparisons."""
    return now_local().replace(tzinfo=None)


def now_iso() -> str:
    """ISO timestamp with offset, e.g. 2026-07-03T12:00:00+03:00."""
    return now_local().isoformat()


def to_local(dt: datetime) -> datetime:
    """Convert any datetime to aware local time."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=get_tz())
    return dt.astimezone(get_tz())


def to_local_naive(dt: datetime) -> datetime:
    """Convert datetime to naive local time (Nairobi wall clock)."""
    return to_local(dt).replace(tzinfo=None)


def parse_iso_to_local_naive(value: str) -> datetime | None:
    """Parse ISO date string to naive local time for sorting/comparisons."""
    if not value:
        return None
    raw = str(value).strip()
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is not None:
            return dt.astimezone(get_tz()).replace(tzinfo=None)
        return dt
    except Exception:
        return None
