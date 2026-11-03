"""Classifier and bloated-thread detection tests."""

from datetime import timedelta

from core.timezone_utils import now_local_naive
from intelligence.classifier import detect_bloated_threads, _rule_based_classify


def _msg(subject, message_id, days_ago=0, **kwargs):
    date = (now_local_naive() - timedelta(days=days_ago)).isoformat()
    return {
        "subject": subject,
        "message_id": message_id,
        "date": date,
        "sender": kwargs.get("sender", "a@example.com"),
        "is_large": kwargs.get("is_large", False),
    }


def test_bloated_thread_keeps_newest_only():
    messages = [
        _msg("Contract review", "<m1>", days_ago=10),
        _msg("Re: Contract review", "<m2>", days_ago=5),
        _msg("Re: Contract review", "<m3>", days_ago=1),
    ]
    candidates = detect_bloated_threads(messages)
    ids = {c[0]["message_id"] for c in candidates}
    assert "<m3>" not in ids
    assert "<m1>" in ids
    assert "<m2>" in ids
    assert len(candidates) == 2


def test_single_message_not_bloated():
    messages = [_msg("Re: Solo subject", "<solo>", days_ago=1)]
    assert detect_bloated_threads(messages) == []


def test_bloated_thread_mixed_timezone_dates():
    messages = [
        {
            "subject": "Contract review",
            "message_id": "<m1>",
            "date": "2026-01-01T10:00:00+03:00",
        },
        {
            "subject": "Re: Contract review",
            "message_id": "<m2>",
            "date": "2026-06-01T12:00:00",
        },
    ]
    candidates = detect_bloated_threads(messages)
    assert len(candidates) == 1
    assert candidates[0][0]["message_id"] == "<m1>"


def test_re_prefix_alone_not_bloated_without_thread():
    """A lone Re: email should not be flagged by rule-based classify anymore."""
    msg = _msg("Re: One off reply", "<one>", days_ago=1)
    category, _ = _rule_based_classify(msg)
    assert category is None
