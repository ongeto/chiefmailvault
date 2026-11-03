"""Restore selected local .eml backups to the original IMAP folder."""

import logging
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from db import models
from db.credentials import get_vault
from imap.client import ImapClient
from imap.folders import resolve_imap_folder_name
from storage.checksum import verify_md5

logger = logging.getLogger(__name__)

QUOTA_WARN_BYTES = 50 * 1024 * 1024  # 50 MB


def preview_restore(message_ids: list[int]) -> dict:
    """Dry-run: validate selected messages and estimate quota impact."""
    items: list[dict] = []
    total_bytes = 0
    missing = 0
    by_mailbox: dict[int, int] = {}

    for mid in message_ids:
        msg = models.get_message(mid)
        if not msg:
            missing += 1
            items.append({"id": mid, "ok": False, "error": "Message not found in vault"})
            continue

        eml_path = msg.get("eml_path") or ""
        path = Path(eml_path) if eml_path else None
        size = int(msg.get("size") or 0)
        ok = True
        error = None

        if not path or not path.exists():
            ok = False
            error = "Local .eml file missing"
            missing += 1
        elif msg.get("md5_hash") and not verify_md5(path, msg["md5_hash"]):
            ok = False
            error = "MD5 mismatch — local file may be corrupt"
            missing += 1
        elif not (msg.get("folder") or "").strip():
            ok = False
            error = "No original folder recorded"
            missing += 1

        if ok:
            total_bytes += size
            by_mailbox[msg["mailbox_id"]] = by_mailbox.get(msg["mailbox_id"], 0) + 1

        items.append({
            "id": mid,
            "ok": ok,
            "error": error,
            "mailbox_id": msg["mailbox_id"],
            "folder": msg.get("folder"),
            "subject": msg.get("subject") or "",
            "size": size,
            "message_id": msg.get("message_id") or "",
        })

    warnings: list[str] = []
    if total_bytes >= QUOTA_WARN_BYTES:
        mb = total_bytes / (1024 * 1024)
        warnings.append(
            f"This restore will upload about {mb:.1f} MB to the mail server and use Hostinger quota."
        )
    if len(by_mailbox) > 1:
        warnings.append(
            "Selection spans multiple mailboxes — each will be restored to its own original folder."
        )
    if missing:
        warnings.append(f"{missing} selected item(s) cannot be restored and will be skipped.")

    return {
        "count": len(message_ids),
        "restorable": sum(1 for i in items if i["ok"]),
        "skipped": missing,
        "total_bytes": total_bytes,
        "warnings": warnings,
        "items": items,
    }


def _append_date(msg: dict) -> datetime | None:
    raw = msg.get("date")
    if not raw:
        return None
    try:
        text = str(raw).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except Exception:
        try:
            return parsedate_to_datetime(str(raw))
        except Exception:
            return None


def _subject_hint(msg: dict) -> str:
    subject = (msg.get("subject") or "(no subject)").replace("\n", " ").strip()
    if len(subject) > 50:
        subject = subject[:47] + "..."
    return subject


def restore_messages(message_ids: list[int], log_fn=None) -> dict:
    """
    Restore selected vault messages to their original IMAP folders.
    Skips messages whose Message-ID already exists on the server.
    """
    _log = log_fn or (lambda msg: None)
    if not message_ids:
        return {
            "success": False,
            "imported": 0,
            "skipped_existing": 0,
            "failed": 0,
            "results": [],
            "skipped_details": [],
            "error": "No message IDs provided",
        }

    preview = preview_restore(message_ids)
    restorable = [i for i in preview["items"] if i["ok"]]
    results: list[dict] = []
    skipped_details: list[dict] = []

    for item in preview["items"]:
        if item["ok"]:
            continue
        detail = {
            "id": item["id"],
            "reason": item.get("error") or "Not restorable",
            "subject": item.get("subject") or "",
            "folder": item.get("folder") or "",
            "message_id": item.get("message_id") or "",
        }
        skipped_details.append(detail)
        results.append({
            "id": item["id"],
            "success": False,
            "status": "skipped_invalid",
            "error": detail["reason"],
        })
        _log(
            f"Restore skip (invalid): [{detail['folder']}] {detail['subject'] or '(no subject)'} "
            f"— {detail['reason']}"
        )

    if not restorable:
        _log("Restore cancelled — no restorable messages in selection")
        return {
            "success": False,
            "imported": 0,
            "skipped_existing": 0,
            "failed": len(results),
            "results": results,
            "skipped_details": skipped_details,
            "error": "No restorable messages",
        }

    for warning in preview["warnings"]:
        _log(f"Restore warning: {warning}")

    by_mailbox: dict[int, list[dict]] = {}
    for item in restorable:
        by_mailbox.setdefault(item["mailbox_id"], []).append(item)

    imported = 0
    skipped_existing = 0
    failed = len([r for r in results if r.get("status") == "skipped_invalid"])

    for mailbox_id, items in by_mailbox.items():
        mailbox = models.get_mailbox(mailbox_id)
        if not mailbox:
            for item in items:
                results.append({"id": item["id"], "success": False, "status": "failed", "error": "Mailbox not found"})
                failed += 1
                _log(f"Restore failed id={item['id']}: mailbox not found")
            continue
        if not mailbox.get("credentials_validated"):
            for item in items:
                results.append({
                    "id": item["id"],
                    "success": False,
                    "status": "failed",
                    "error": "Mailbox credentials not validated",
                })
                failed += 1
                _log(f"Restore failed id={item['id']}: credentials not validated")
            continue

        password = get_vault().decrypt(mailbox["encrypted_password"])
        email = mailbox["email"]
        _log(f"Restore starting for {email}: {len(items)} message(s) → original folders")

        try:
            with ImapClient(mailbox["imap_host"], mailbox["imap_port"], email, password) as client:
                folder_cache: dict[str, str] = {}
                for idx, item in enumerate(items, 1):
                    msg = models.get_message(item["id"])
                    if not msg:
                        results.append({"id": item["id"], "success": False, "status": "failed", "error": "Not found"})
                        failed += 1
                        _log(f"Restore failed id={item['id']}: message row not found")
                        continue

                    folder_key = msg["folder"]
                    if folder_key not in folder_cache:
                        folder_cache[folder_key] = resolve_imap_folder_name(client.conn, folder_key)
                        _log(f"Restore target folder: {folder_key} → {folder_cache[folder_key]}")
                    imap_folder = folder_cache[folder_key]
                    subject = _subject_hint(msg)
                    message_id = (msg.get("message_id") or "").strip()

                    try:
                        if message_id and client.message_id_exists(message_id, imap_folder, log_fn=None):
                            detail = {
                                "id": item["id"],
                                "reason": "Message-ID already exists on server",
                                "subject": msg.get("subject") or "",
                                "folder": folder_key,
                                "message_id": message_id,
                            }
                            skipped_details.append(detail)
                            results.append({
                                "id": item["id"],
                                "success": True,
                                "status": "skipped_existing",
                                "folder": folder_key,
                                "reason": detail["reason"],
                                "message_id": message_id,
                                "subject": detail["subject"],
                            })
                            skipped_existing += 1
                            _log(
                                f"Restore skip (already on server): [{folder_key}] {subject} "
                                f"— Message-ID {message_id}"
                            )
                        else:
                            if not message_id:
                                _log(
                                    f"Restore note: [{folder_key}] {subject} has no Message-ID "
                                    f"— uploading without dedup check"
                                )
                            raw = Path(msg["eml_path"]).read_bytes()
                            client.append(
                                imap_folder,
                                raw,
                                flags="\\Seen",
                                date_time=_append_date(msg),
                                log_fn=_log,
                            )
                            results.append({
                                "id": item["id"],
                                "success": True,
                                "status": "imported",
                                "folder": folder_key,
                                "subject": msg.get("subject") or "",
                            })
                            imported += 1
                            _log(f"Restore imported: [{folder_key}] {subject}")
                    except Exception as exc:
                        logger.exception("Restore failed for message id=%s", item["id"])
                        results.append({
                            "id": item["id"],
                            "success": False,
                            "status": "failed",
                            "error": str(exc),
                            "subject": msg.get("subject") or "",
                            "folder": folder_key,
                        })
                        failed += 1
                        _log(f"Restore failed: [{folder_key}] {subject} — {exc}")

                    if idx % 10 == 0 or idx == len(items):
                        _log(
                            f"Restore progress {email}: {idx}/{len(items)} "
                            f"(imported={imported}, skipped={skipped_existing}, failed={failed})"
                        )
        except Exception as exc:
            logger.exception("Restore connection failed for mailbox %s", email)
            _log(f"Restore connection failed for {email}: {exc}")
            for item in items:
                if not any(r["id"] == item["id"] for r in results):
                    results.append({
                        "id": item["id"],
                        "success": False,
                        "status": "failed",
                        "error": str(exc),
                    })
                    failed += 1

    if skipped_details:
        _log(f"Restore skip summary ({len(skipped_details)}):")
        for detail in skipped_details[:20]:
            mid = detail.get("message_id") or "(no Message-ID)"
            _log(
                f"  • [{detail.get('folder') or '?'}] "
                f"{(detail.get('subject') or '(no subject)')[:50]} — {detail.get('reason')} ({mid})"
            )
        if len(skipped_details) > 20:
            _log(f"  … and {len(skipped_details) - 20} more")

    _log(
        f"Restore finished: imported={imported}, skipped_existing={skipped_existing}, failed={failed}"
    )
    return {
        "success": failed == 0,
        "imported": imported,
        "skipped_existing": skipped_existing,
        "failed": failed,
        "results": results,
        "skipped_details": skipped_details,
    }
