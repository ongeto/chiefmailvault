"""Pre-delete verification and IMAP purge lifecycle."""

import logging

import config
from db import models
from imap.client import ImapClient
from storage.checksum import verify_md5

logger = logging.getLogger(__name__)


def _cloud_ok(messages: list[dict]) -> bool:
    if not config.CLOUD_REQUIRED:
        if not config.DRIVE_ENABLED and not config.DROPBOX_ENABLED and not config.NAS_ENABLED:
            return True
        return any(m.get("cloud_synced") or m.get("nas_synced") for m in messages)
    return all(m.get("cloud_synced") or m.get("nas_synced") for m in messages)


def can_purge(mailbox_id: int, message_id: str) -> tuple[bool, str]:
    """Verify backup integrity before server-side deletion."""
    messages = models.get_messages_by_message_id(mailbox_id, message_id)
    if not messages:
        return False, "No messages found for Message-ID"

    for msg in messages:
        if msg.get("integrity_ok") == 0:
            return False, "Integrity audit failed — re-run Verify Backups"
        eml_path = msg.get("eml_path")
        if not eml_path:
            return False, f"Missing eml_path for uid {msg['uid']}"
        from pathlib import Path
        path = Path(eml_path)
        if not path.exists():
            return False, f".eml file missing on disk: {eml_path}"
        if not verify_md5(path, msg["md5_hash"]):
            return False, f"MD5 mismatch for {eml_path}"

    if not _cloud_ok(messages):
        return False, "Cloud/NAS sync not verified"

    return True, "OK"


def can_purge_message(msg: dict) -> tuple[bool, str]:
    """Verify a single backed-up message is safe to flag for server deletion."""
    if msg.get("integrity_ok") == 0:
        return False, "Integrity audit failed — re-run Verify Backups"
    eml_path = msg.get("eml_path")
    if not eml_path:
        return False, f"Missing eml_path for uid {msg.get('uid')}"
    from pathlib import Path

    path = Path(eml_path)
    if not path.exists():
        return False, f".eml file missing on disk: {eml_path}"
    if not verify_md5(path, msg["md5_hash"]):
        return False, f"MD5 mismatch for {eml_path}"
    if not _cloud_ok([msg]):
        return False, "Cloud/NAS sync not verified"
    return True, "OK"


def flag_messages_for_deletion(
    message_ids: list[int], password: str, imap_host: str, imap_port: int, email: str
) -> list[dict]:
    """Mark large (or other) messages for deletion on the server — does NOT expunge."""
    from imap.folders import resolve_imap_folder_name

    results = []
    mailbox_id = None

    for mid in message_ids:
        msg = models.get_message(mid)
        if not msg:
            results.append({"id": mid, "success": False, "error": "Not found"})
            continue
        if msg.get("purge_status") == "flagged_deleted":
            results.append({"id": mid, "success": True, "status": "already_flagged"})
            continue
        mailbox_id = msg["mailbox_id"]
        ok, reason = can_purge_message(msg)
        if not ok:
            results.append({"id": mid, "success": False, "error": reason})
            continue
        results.append({"id": mid, "success": True, "status": "pending_flag", "msg": msg})

    if not mailbox_id:
        return results

    to_flag = [r for r in results if r.get("status") == "pending_flag"]
    if not to_flag:
        return results

    with ImapClient(imap_host, imap_port, email, password) as client:
        for r in to_flag:
            msg = r["msg"]
            try:
                imap_folder = resolve_imap_folder_name(client.conn, msg["folder"])
                client.flag_deleted(msg["uid"], imap_folder)
                models.update_message_purge_status(r["id"], "flagged_deleted")
                r["status"] = "flagged_deleted"
                logger.info(
                    "Flagged message %s uid=%s folder=%s for deletion",
                    r["id"], msg["uid"], imap_folder,
                )
            except Exception as exc:
                r["success"] = False
                r["error"] = str(exc)
            finally:
                r.pop("msg", None)

    return results


def flag_duplicates_for_deletion(
    duplicate_ids: list[int], password: str, imap_host: str, imap_port: int, email: str
) -> list[dict]:
    """Mark INBOX copies for deletion — does NOT expunge."""
    results = []
    mailbox_id = None

    for dup_id in duplicate_ids:
        dup = models.get_duplicate(dup_id)
        if not dup:
            results.append({"id": dup_id, "success": False, "error": "Not found"})
            continue
        mailbox_id = dup["mailbox_id"]
        ok, reason = can_purge(dup["mailbox_id"], dup["message_id"])
        if not ok:
            results.append({"id": dup_id, "success": False, "error": reason})
            continue
        results.append({"id": dup_id, "success": True, "status": "pending_flag"})

    if not mailbox_id:
        return results

    to_flag = [r for r in results if r.get("status") == "pending_flag"]
    if not to_flag:
        return results

    with ImapClient(imap_host, imap_port, email, password) as client:
        from imap.folders import resolve_imap_folder_name

        inbox_folder = resolve_imap_folder_name(client.conn, "INBOX")
        for r in to_flag:
            dup = models.get_duplicate(r["id"])
            try:
                client.flag_deleted(dup["inbox_uid"], inbox_folder)
                models.update_duplicate_status(r["id"], "flagged_deleted")
                r["status"] = "flagged_deleted"
                logger.info("Flagged duplicate %s inbox_uid=%s for deletion", r["id"], dup["inbox_uid"])
            except Exception as exc:
                r["success"] = False
                r["error"] = str(exc)

    return results


def expunge_mailbox(
    mailbox_id: int, password: str, imap_host: str, imap_port: int, email: str
) -> dict:
    """Execute IMAP EXPUNGE in each folder that has flagged messages."""
    from imap.folders import resolve_imap_folder_name

    folders = set(models.get_flagged_folders(mailbox_id))
    flagged_dups = models.list_duplicates(mailbox_id)
    if any(d["status"] == "flagged_deleted" for d in flagged_dups):
        folders.add("INBOX")

    if not folders:
        return {"success": True, "mailbox_id": mailbox_id, "folders_expunged": []}

    expunged = []
    with ImapClient(imap_host, imap_port, email, password) as client:
        for folder_key in sorted(folders):
            imap_folder = resolve_imap_folder_name(client.conn, folder_key)
            client.select_folder(imap_folder)
            client.expunge()
            expunged.append(imap_folder)

    for dup in flagged_dups:
        if dup["status"] == "flagged_deleted":
            models.update_duplicate_status(dup["id"], "purged")

    models.mark_flagged_messages_purged(mailbox_id)

    logger.info("Expunged mailbox %s (%s) folders: %s", mailbox_id, email, expunged)
    return {"success": True, "mailbox_id": mailbox_id, "folders_expunged": expunged}
