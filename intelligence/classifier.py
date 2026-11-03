"""Metadata-based cleanup classification."""

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta

from config import OLLAMA_ENABLED, OLLAMA_MODEL
from core.timezone_utils import now_local_naive, parse_iso_to_local_naive
from db import models
from db.database import get_db
from intelligence import ollama_client

logger = logging.getLogger(__name__)

CATEGORIES = {
    "system_notifications": "System Notifications",
    "newsletter_clutter": "Newsletter Clutter",
    "bloated_threads": "Bloated Thread",
    "large_attachments": "Large Attachment",
}

BLOATED_THREAD_MIN_MESSAGES = 2


def category_label(key: str) -> str:
    return CATEGORIES.get(key, key.replace("_", " ").title())


def _suggestion_fields(msg: dict) -> dict:
    return {
        "subject": msg.get("subject") or "",
        "sender": msg.get("sender") or "",
        "date": msg.get("date"),
        "folder": msg.get("folder") or "",
        "size": msg.get("size") or 0,
    }


def _normalize_subject(subject: str) -> str:
    s = (subject or "").strip()
    pattern = re.compile(r"^(re|fwd|fw)\s*:\s*", re.IGNORECASE)
    while True:
        match = pattern.match(s)
        if not match:
            break
        s = s[match.end() :].strip()
    return s.lower() or (subject or "").lower()


def _parse_msg_date(msg: dict) -> datetime | None:
    """Parse message date to naive local time (Nairobi) for safe comparisons."""
    return parse_iso_to_local_naive(msg.get("date") or "")


def detect_bloated_threads(messages: list[dict]) -> list[tuple[dict, str]]:
    """
    Bloated email = an older message in a conversation thread where 2+ messages
    share the same normalized subject. The newest message is kept; older ones are flagged.
    """
    threads: dict[str, list[dict]] = defaultdict(list)
    for msg in messages:
        subject = msg.get("subject") or ""
        key = _normalize_subject(subject)
        if key:
            threads[key].append(msg)

    candidates: list[tuple[dict, str]] = []
    for key, group in threads.items():
        if len(group) < BLOATED_THREAD_MIN_MESSAGES:
            continue
        sorted_group = sorted(
            group,
            key=lambda m: (_parse_msg_date(m) or datetime.min, m.get("id", 0)),
            reverse=True,
        )
        newest = sorted_group[0]
        newest_date = _parse_msg_date(newest)
        date_hint = newest_date.strftime("%d %b %Y") if newest_date else "newest"
        thread_title = (newest.get("subject") or key)[:50]

        for older in sorted_group[1:]:
            if not older.get("message_id"):
                continue
            reason = (
                f"Older message in thread ({len(group)} total) — "
                f"keep newest ({date_hint}): {thread_title}"
            )
            candidates.append((older, reason))
    return candidates


def _rule_based_classify(msg: dict) -> tuple[str | None, str]:
    """Fallback classifier when Ollama unavailable (excludes bloated threads)."""
    now = now_local_naive()
    subject_lower = (msg.get("subject") or "").lower()
    sender_lower = (msg.get("sender") or "").lower()

    msg_date = _parse_msg_date(msg)

    if msg.get("is_large"):
        return "large_attachments", "Email exceeds 25 MB threshold"

    alert_keywords = ["alert", "notification", "cron", "build", "noreply", "no-reply", "mailer-daemon"]
    if msg_date and (now - msg_date) > timedelta(days=30):
        if any(k in subject_lower or k in sender_lower for k in alert_keywords):
            return "system_notifications", "Automated notification older than 30 days"

    newsletter_keywords = ["newsletter", "unsubscribe", "digest", "weekly", "promo"]
    if any(k in subject_lower or k in sender_lower for k in newsletter_keywords):
        if msg_date and (now - msg_date) > timedelta(days=14):
            return "newsletter_clutter", "Newsletter/subscription older than 14 days"

    return None, ""


async def scan_mailbox(mailbox_id: int, log_fn=None) -> dict:
    """Generate cleanup suggestions for a mailbox. Returns scan summary."""
    _log = log_fn or (lambda msg: None)
    models.clear_cleanup_suggestions(mailbox_id)

    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE mailbox_id = ? ORDER BY date DESC LIMIT 500",
            (mailbox_id,),
        ).fetchall()
    messages = [dict(r) for r in rows]
    if not messages:
        return {"suggestions_added": 0, "engine": "none", "message": "No backed-up messages to scan"}

    suggestions_added = 0
    engine = "rules"
    scan_message = "Rule-based scan complete"

    if OLLAMA_ENABLED:
        status = await ollama_client.check_ready()
        _log(status["message"])
        if status["available"] and status["model_ready"]:
            try:
                suggestions_added = await _ollama_scan(mailbox_id, messages)
                engine = "ollama"
                scan_message = f"Ollama scan complete ({OLLAMA_MODEL})"
            except Exception as exc:
                logger.warning("Ollama scan failed, using rule-based: %s", exc)
                _log(f"Ollama scan failed: {exc} — falling back to rules")
                try:
                    suggestions_added = _rule_based_scan(mailbox_id, messages)
                    scan_message = f"Ollama failed — used rules ({exc})"
                except Exception as rule_exc:
                    logger.exception("Rule-based scan failed")
                    _log(f"Rule-based scan failed: {rule_exc}")
                    raise rule_exc
        else:
            suggestions_added = _rule_based_scan(mailbox_id, messages)
            scan_message = status["message"] + " — used rules"
    else:
        suggestions_added = _rule_based_scan(mailbox_id, messages)

    return {
        "suggestions_added": suggestions_added,
        "engine": engine,
        "message": scan_message,
    }


async def _ollama_scan(mailbox_id: int, messages: list[dict]) -> int:
    metadata_batch = [
        {
            "index": i,
            "sender": m.get("sender", ""),
            "subject": m.get("subject", ""),
            "folder": m.get("folder", ""),
            "size_bytes": m.get("size", 0),
            "date": m.get("date", ""),
            "content_type": m.get("content_type", ""),
            "snippet": (m.get("snippet") or "")[:100],
        }
        for i, m in enumerate(messages)
    ]

    for m in metadata_batch:
        assert len(m.get("snippet", "")) <= 100

    parsed = await ollama_client.classify_metadata(metadata_batch)
    count = 0
    for item in parsed:
        category = item.get("category", "keep")
        if category == "keep":
            continue
        idx = item.get("index", -1)
        if not (0 <= idx < len(messages)):
            continue
        mid = messages[idx].get("message_id")
        if not mid:
            continue
        msg = messages[idx]
        models.insert_cleanup_suggestion(
            mailbox_id,
            category,
            [mid],
            item.get("reason") or category_label(category),
            **_suggestion_fields(msg),
        )
        count += 1
    return count


def _rule_based_scan(mailbox_id: int, messages: list[dict]) -> int:
    count = 0
    seen: set[str] = set()

    for msg, reason in detect_bloated_threads(messages):
        mid = msg.get("message_id")
        if mid and mid not in seen:
            models.insert_cleanup_suggestion(
                mailbox_id, "bloated_threads", [mid], reason, **_suggestion_fields(msg)
            )
            seen.add(mid)
            count += 1

    for msg in messages:
        category, reason = _rule_based_classify(msg)
        mid = msg.get("message_id")
        if category and mid and mid not in seen:
            models.insert_cleanup_suggestion(
                mailbox_id, category, [mid], reason, **_suggestion_fields(msg)
            )
            seen.add(mid)
            count += 1
    return count
