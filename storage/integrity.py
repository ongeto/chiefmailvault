"""Post-backup integrity audit — confirm .eml files are restore-ready."""

import logging
from pathlib import Path

from core.timezone_utils import now_iso
from db import models
from db.database import get_db
from storage.checksum import verify_md5

logger = logging.getLogger(__name__)


def check_message_integrity(msg: dict) -> tuple[bool, str]:
    """Return (ok, reason) for a single backed-up message."""
    eml_path = msg.get("eml_path") or ""
    if not eml_path.strip():
        return False, "Missing eml_path"
    path = Path(eml_path)
    if not path.exists():
        return False, f".eml missing: {eml_path}"
    if path.stat().st_size <= 0:
        return False, f".eml empty: {eml_path}"
    md5 = msg.get("md5_hash") or ""
    if not md5:
        return False, "Missing MD5 hash"
    if not verify_md5(path, md5):
        return False, f"MD5 mismatch: {eml_path}"
    return True, "OK"


def audit_mailbox(mailbox_id: int, log_fn=None) -> dict:
    """
    Re-verify every backed-up message for a mailbox.
    Updates integrity_ok / verified_at on each row and mailbox summary fields.
    """
    _log = log_fn or (lambda msg: None)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE mailbox_id = ?", (mailbox_id,)
        ).fetchall()
    messages = [dict(r) for r in rows]
    total = len(messages)
    ok_count = 0
    failed: list[dict] = []

    _log(f"Integrity audit starting for mailbox_id={mailbox_id} ({total} message(s))...")
    for msg in messages:
        ok, reason = check_message_integrity(msg)
        models.update_message_integrity(msg["id"], ok)
        if ok:
            ok_count += 1
        else:
            failed.append({"id": msg["id"], "uid": msg.get("uid"), "folder": msg.get("folder"), "error": reason})
            if len(failed) <= 5:
                _log(f"Integrity fail id={msg['id']} uid={msg.get('uid')}: {reason}")

    models.update_mailbox_integrity(mailbox_id, ok_count, total)
    summary = {
        "mailbox_id": mailbox_id,
        "total": total,
        "ok": ok_count,
        "failed": total - ok_count,
        "restore_ready": ok_count == total and total > 0,
        "verified_at": now_iso(),
        "failures": failed[:20],
    }
    if total == 0:
        _log("Integrity audit: no messages to verify")
    elif summary["restore_ready"]:
        _log(f"Integrity audit: {ok_count}/{total} OK — restore-ready")
    else:
        _log(f"Integrity audit: {ok_count}/{total} OK — {summary['failed']} failed (not restore-ready)")
    return summary
