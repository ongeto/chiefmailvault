"""Re-fetch integrity-failed messages onto folder-aware storage paths."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from config import LARGE_EMAIL_THRESHOLD
from db import models
from db.credentials import get_vault
from imap.client import ImapClient
from imap.folders import resolve_imap_folder_name
from parser.eml_writer import extract_attachments, extract_metadata, parse_message, write_eml
from storage.checksum import compute_md5
from storage.integrity import audit_mailbox, check_message_integrity
from storage.local import build_eml_path, sanitize_folder

logger = logging.getLogger(__name__)


def path_includes_folder(eml_path: str, folder: str) -> bool:
    """True when the .eml already lives under the folder-aware segment."""
    try:
        return Path(eml_path).parent.name == sanitize_folder(folder)
    except Exception:
        return False


def _parse_msg_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            return datetime.strptime(date_str[:31].strip(), fmt)
        except ValueError:
            continue
    return None


def _rewrite_message_from_raw(msg_row: dict, raw: bytes, email: str) -> tuple[bool, str]:
    uid = int(msg_row["uid"])
    folder_key = msg_row.get("folder") or "INBOX"
    parsed = parse_message(raw)
    meta = extract_metadata(parsed)
    eml_path = build_eml_path(email, uid, meta.get("msg_date"), folder=folder_key)
    size = write_eml(raw, eml_path)
    extract_attachments(parsed, eml_path, uid)
    md5 = compute_md5(eml_path)
    is_large = size > LARGE_EMAIL_THRESHOLD

    models.update_message_storage(
        msg_row["id"],
        eml_path=str(eml_path),
        md5_hash=md5,
        size=size,
        message_id_header=meta.get("message_id"),
        date=meta.get("date"),
        sender=meta.get("sender") or "",
        subject=meta.get("subject") or "",
        content_type=meta.get("content_type") or "",
        snippet=meta.get("snippet") or "",
        is_large=is_large,
    )
    ok, reason = check_message_integrity({"eml_path": str(eml_path), "md5_hash": md5})
    models.update_message_integrity(msg_row["id"], ok)
    return ok, reason


def _migrate_ok_legacy_path(msg_row: dict, email: str) -> bool:
    """
    Copy an integrity-OK message from a legacy shared path into the folder segment.
    Source is left in place so a sibling UID in another folder remains readable until repaired.
    """
    src = Path(msg_row["eml_path"] or "")
    if not src.exists():
        return False
    folder_key = msg_row.get("folder") or "INBOX"
    dest = build_eml_path(
        email, int(msg_row["uid"]), _parse_msg_date(msg_row.get("date")), folder=folder_key
    )
    if dest.resolve() == src.resolve():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes())
    md5 = compute_md5(dest)
    models.update_message_storage(
        msg_row["id"],
        eml_path=str(dest),
        md5_hash=md5,
        size=dest.stat().st_size,
    )
    models.update_message_integrity(msg_row["id"], True)
    return True


def repair_mailbox(mailbox_id: int, log_fn=None) -> dict:
    """
    Re-download integrity-failed messages and migrate legacy shared paths.

    Older builds stored ``email_{uid}.eml`` without the IMAP folder, so Sent
    overwrote Inbox for the same per-folder UID.
    """
    _log = log_fn or (lambda msg: None)
    mailbox = models.get_mailbox(mailbox_id)
    if not mailbox:
        return {"success": False, "error": "Mailbox not found", "repaired": 0, "failed": 0}

    email = mailbox["email"]
    password = get_vault().decrypt(mailbox["encrypted_password"])

    audit_mailbox(mailbox_id, log_fn=_log)
    failed_rows = models.list_integrity_failed_messages(mailbox_id)
    all_msgs = models.list_mailbox_messages(mailbox_id)
    legacy_ok = [
        m
        for m in all_msgs
        if m.get("integrity_ok") == 1
        and m.get("eml_path")
        and not path_includes_folder(m["eml_path"], m.get("folder") or "INBOX")
    ]

    repaired = 0
    migrate_count = 0
    still_failed: list[dict] = []

    if failed_rows:
        _log(
            f"Repair: re-fetching {len(failed_rows)} integrity-failed message(s) "
            f"for {email} onto folder-aware paths..."
        )
        try:
            with ImapClient(
                mailbox["imap_host"], mailbox["imap_port"], email, password
            ) as client:
                folder_map: dict[str, str] = {}
                for i, msg_row in enumerate(failed_rows, 1):
                    folder_key = msg_row.get("folder") or "INBOX"
                    uid = int(msg_row["uid"])
                    try:
                        if folder_key not in folder_map:
                            folder_map[folder_key] = resolve_imap_folder_name(
                                client.conn, folder_key
                            )
                        client.select_folder(folder_map[folder_key])
                        raw = client.fetch_rfc822(uid, log_fn=_log)
                        if not raw:
                            still_failed.append(
                                {"id": msg_row["id"], "uid": uid, "error": "Empty FETCH"}
                            )
                            _log(f"Repair fail id={msg_row['id']} uid={uid}: empty FETCH")
                            continue
                        ok, reason = _rewrite_message_from_raw(msg_row, raw, email)
                        if ok:
                            repaired += 1
                            if i % 10 == 0 or i == len(failed_rows):
                                _log(f"Repair progress: {i}/{len(failed_rows)}")
                        else:
                            still_failed.append(
                                {"id": msg_row["id"], "uid": uid, "error": reason}
                            )
                            _log(f"Repair fail id={msg_row['id']} uid={uid}: {reason}")
                    except Exception as exc:
                        logger.exception("Repair failed id=%s uid=%s", msg_row["id"], uid)
                        still_failed.append(
                            {"id": msg_row["id"], "uid": uid, "error": str(exc)}
                        )
                        _log(f"Repair fail id={msg_row['id']} uid={uid}: {exc}")
        except Exception as exc:
            _log(f"Repair IMAP connection failed for {email}: {exc}")
            return {
                "success": False,
                "error": str(exc),
                "mailbox_id": mailbox_id,
                "email": email,
                "repaired": repaired,
                "migrated": 0,
                "failed": len(failed_rows) - repaired,
            }

    if legacy_ok:
        _log(f"Repair: migrating {len(legacy_ok)} OK message(s) off legacy shared paths...")
        for msg_row in legacy_ok:
            try:
                if _migrate_ok_legacy_path(msg_row, email):
                    migrate_count += 1
            except Exception as exc:
                logger.exception("Legacy migrate failed id=%s", msg_row["id"])
                _log(f"Legacy migrate fail id={msg_row['id']}: {exc}")

    summary = audit_mailbox(mailbox_id, log_fn=_log)
    _log(
        f"Repair done for {email}: re-fetched={repaired}, migrated={migrate_count}, "
        f"still_failed={len(still_failed)}; audit {summary['ok']}/{summary['total']} OK"
    )
    return {
        "success": bool(summary.get("restore_ready")),
        "mailbox_id": mailbox_id,
        "email": email,
        "repaired": repaired,
        "migrated": migrate_count,
        "failed": len(still_failed),
        "failures": still_failed[:20],
        "integrity": summary,
    }
