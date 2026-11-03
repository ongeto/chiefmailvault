"""Incremental IMAP backup sync."""

import logging
from pathlib import Path

from config import LARGE_EMAIL_THRESHOLD
from db import models
from db.credentials import get_vault
from imap.client import ImapClient
from imap.dedup import check_and_flag_duplicate, rescan_mailbox_duplicates
from imap.folders import canonical_folder_name, list_mailbox_folders
from parser.eml_writer import extract_attachments, extract_metadata, parse_message, write_eml
from storage.checksum import compute_md5
from storage.integrity import audit_mailbox, check_message_integrity
from storage.local import build_eml_path

logger = logging.getLogger(__name__)


def _save_message(
    mailbox_id: int,
    uid: int,
    folder_key: str,
    raw: bytes,
    email: str,
    log_fn,
) -> bool:
    """Persist one message; returns True if newly added (False if updated in place)."""
    msg = parse_message(raw)
    meta = extract_metadata(msg)
    eml_path = build_eml_path(email, uid, meta.get("msg_date"), folder=folder_key)
    size = write_eml(raw, eml_path)
    extract_attachments(msg, eml_path, uid)
    md5 = compute_md5(eml_path)
    is_large = size > LARGE_EMAIL_THRESHOLD

    existing = models.get_message_by_uid(mailbox_id, folder_key, uid)
    if existing:
        models.update_message_storage(
            existing["id"],
            eml_path=str(eml_path),
            md5_hash=md5,
            size=size,
            message_id_header=meta["message_id"],
            date=meta["date"],
            sender=meta["sender"],
            subject=meta["subject"],
            content_type=meta["content_type"],
            snippet=meta["snippet"],
            is_large=is_large,
        )
        row_id = existing["id"]
        newly_added = False
    else:
        row_id = models.insert_message(
            mailbox_id=mailbox_id,
            uid=uid,
            folder=folder_key,
            message_id=meta["message_id"],
            md5_hash=md5,
            size=size,
            date=meta["date"],
            eml_path=str(eml_path),
            sender=meta["sender"],
            subject=meta["subject"],
            content_type=meta["content_type"],
            snippet=meta["snippet"],
            is_large=is_large,
        )
        newly_added = True

    ok, reason = check_message_integrity({
        "eml_path": str(eml_path),
        "md5_hash": md5,
    })
    models.update_message_integrity(row_id, ok)
    if not ok:
        raise RuntimeError(f"Integrity check failed after save uid={uid}: {reason}")

    if meta["message_id"]:
        check_and_flag_duplicate(mailbox_id, meta["message_id"])

    if is_large:
        log_fn(f"Large email flagged: uid={uid} size={size}")
    return newly_added


def sync_mailbox(mailbox_id: int, force_resync: bool = False, log_fn=None) -> dict:
    """Sync a single mailbox incrementally."""
    _log = log_fn or (lambda msg: logger.info(msg))
    mailbox = models.get_mailbox(mailbox_id)
    if not mailbox:
        return {"success": False, "error": "Mailbox not found"}

    if not mailbox.get("credentials_validated"):
        msg = f"Skipping {mailbox['email']}: credentials not validated"
        _log(msg)
        return {"success": False, "error": "Mailbox credentials have not been validated"}

    password = get_vault().decrypt(mailbox["encrypted_password"])
    email = mailbox["email"]
    host = mailbox["imap_host"]
    port = mailbox["imap_port"]

    job_id = models.create_backup_job(mailbox_id)
    messages_added = 0
    error = None
    partial = False
    integrity = None

    try:
        _log(f"Connecting to IMAP for {email}...")
        with ImapClient(host, port, email, password) as client:
            imap_folders = client.list_folders(log_fn=_log)
            if not imap_folders:
                _log("No folders discovered; falling back to INBOX")
                imap_folders = ["INBOX"]
            else:
                _log(f"Discovered {len(imap_folders)} folder(s): {', '.join(imap_folders)}")

            for imap_folder in imap_folders:
                folder_key = canonical_folder_name(imap_folder)
                _log(f"Syncing {email} / {imap_folder}")
                try:
                    client.select_folder(imap_folder)
                except RuntimeError as exc:
                    _log(f"Skipping folder {imap_folder}: {exc}")
                    continue

                known_uids = set() if force_resync else models.get_known_uids(mailbox_id, folder_key)
                all_uids = client.search_all_uids(log_fn=_log)
                new_uids = [u for u in all_uids if u not in known_uids]
                total_new = len(new_uids)
                _log(f"Found {total_new} new messages in {folder_key}")

                for i, uid in enumerate(new_uids, 1):
                    # Skip if saved during a prior partial run or earlier in this loop
                    if not force_resync and uid in models.get_known_uids(mailbox_id, folder_key):
                        continue

                    raw = client.fetch_rfc822(uid, log_fn=_log)
                    if not raw:
                        continue

                    if i % 10 == 0 or i == total_new:
                        _log(f"Downloading {email}/{folder_key}: {i}/{total_new}")

                    try:
                        _save_message(mailbox_id, uid, folder_key, raw, email, _log)
                        messages_added += 1
                    except Exception as exc:
                        logger.exception("Failed to save uid=%s", uid)
                        _log(f"Failed to save uid={uid}: {exc}")

        models.update_mailbox_sync(mailbox_id)
        dup_added = rescan_mailbox_duplicates(mailbox_id, log_fn=_log)
        if dup_added:
            _log(f"Duplicate scan: {dup_added} inbox/sent pair(s) flagged")
        integrity = audit_mailbox(mailbox_id, log_fn=_log)
        if integrity and integrity.get("failed", 0) > 0:
            from imap.repair import repair_mailbox

            _log(
                f"Integrity failures detected ({integrity['failed']}) — "
                "repairing via folder-aware re-fetch..."
            )
            repair_result = repair_mailbox(mailbox_id, log_fn=_log)
            integrity = repair_result.get("integrity") or audit_mailbox(mailbox_id, log_fn=_log)
        _log(f"Sync complete: {messages_added} messages added for {email}")

    except Exception as exc:
        error = str(exc)
        partial = messages_added > 0
        if partial:
            models.update_mailbox_sync(mailbox_id)
            dup_added = rescan_mailbox_duplicates(mailbox_id, log_fn=_log)
            if dup_added:
                _log(f"Duplicate scan: {dup_added} inbox/sent pair(s) flagged")
            integrity = audit_mailbox(mailbox_id, log_fn=_log)
            _log(
                f"Sync interrupted for {email} after {messages_added} message(s): {error}"
            )
            _log("Progress saved — run backup again to continue from where it stopped.")
        else:
            _log(f"Sync failed for {email}: {error}")
        logger.exception("Sync error")

    models.finish_backup_job(job_id, messages_added, error)
    return {
        "success": error is None,
        "partial": partial,
        "mailbox_id": mailbox_id,
        "messages_added": messages_added,
        "error": error,
        "job_id": job_id,
        "integrity": integrity,
    }
