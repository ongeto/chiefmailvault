"""Timezone utility tests."""

from datetime import datetime
from zoneinfo import ZoneInfo

from core.timezone_utils import get_tz, now_iso, parse_iso_to_local_naive, to_local_naive


def test_default_timezone_is_nairobi():
    assert str(get_tz()) == "Africa/Nairobi"


def test_now_iso_has_nairobi_offset():
    iso = now_iso()
    assert "+03:00" in iso or iso.endswith("+0300")


def test_parse_utc_to_local_naive():
    parsed = parse_iso_to_local_naive("2026-01-01T09:00:00+00:00")
    assert parsed == datetime(2026, 1, 1, 12, 0, 0)


def test_to_local_naive_from_aware():
    utc = datetime(2026, 6, 1, 9, 0, tzinfo=ZoneInfo("UTC"))
    assert to_local_naive(utc) == datetime(2026, 6, 1, 12, 0, 0)
