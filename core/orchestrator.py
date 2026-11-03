"""Job orchestration with thread pool."""

import logging
from concurrent.futures import ThreadPoolExecutor

from app.websocket import log as ws_log
from db import models
from db.credentials import get_vault
from imap import purge, restore, sync
from intelligence import classifier
from storage import mirror

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=3)
_backup_running = False
_scan_running = False
_import_running = False
_import_progress: dict = {
    "imported": 0,
    "skipped_existing": 0,
    "failed": 0,
    "total": 0,
    "skipped_details": [],
}


def _sync_and_mirror(mailbox_id: int, force: bool = False) -> dict:
    result = sync.sync_mailbox(mailbox_id, force_resync=force, log_fn=ws_log)
    if result.get("success") or result.get("partial"):
        mailbox = models.get_mailbox(mailbox_id)
        if mailbox:
            ws_log(f"Post-sync archive step for {mailbox['email']}...")
            mirror_result = mirror.mirror_mailbox(
                mailbox_id,
                mailbox["email"],
                log_fn=ws_log,
                messages_added=result.get("messages_added", 0),
            )
            ws_log(f"Archive step done for {mailbox['email']}: {mirror_result}")
    return result


def _run_backup(
    mailbox_id: int | None = None, force: bool = False, domain_id: int | None = None
) -> list[dict]:
    global _backup_running
    _backup_running = True
    try:
        if mailbox_id:
            mailbox = models.get_mailbox(mailbox_id)
            mailboxes = [mailbox] if mailbox else []
        elif domain_id:
            mailboxes = models.list_mailboxes(domain_id)
        else:
            mailboxes = models.list_mailboxes()

        results = []
        for mb in mailboxes:
            if not mb.get("credentials_validated"):
                ws_log(f"Skipping {mb['email']}: credentials not validated")
                results.append({
                    "success": False,
                    "mailbox_id": mb["id"],
                    "error": "Mailbox credentials have not been validated",
                })
                continue
            ws_log(f"Starting backup for {mb['email']}")
            try:
                results.append(_sync_and_mirror(mb["id"], force))
            except Exception as exc:
                results.append({"success": False, "mailbox_id": mb["id"], "error": str(exc)})

        total_added = sum(r.get("messages_added", 0) for r in results)
        failed = sum(1 for r in results if not r.get("success"))
        partial = sum(1 for r in results if r.get("partial"))
        if partial:
            ws_log(
                f"Backup finished: {total_added} messages added, {failed} interrupted "
                f"({partial} partial — re-run backup to continue)"
            )
        else:
            ws_log(f"Backup finished: {total_added} messages added, {failed} failed")
        return results
    finally:
        _backup_running = False


def trigger_backup(
    mailbox_id: int | None = None, force: bool = False, domain_id: int | None = None
) -> list[dict]:
    """Run backup synchronously (used by tests and scheduler)."""
    return _run_backup(mailbox_id, force, domain_id)


def trigger_backup_background(
    mailbox_id: int | None = None, force: bool = False, domain_id: int | None = None
) -> dict:
    """Queue backup in background — returns immediately without blocking the web server."""
    if _backup_running:
        ws_log("Backup already in progress — please wait")
        return {"success": False, "status": "busy", "message": "A backup is already running"}

    ws_log("Backup started...")
    _executor.submit(_run_backup, mailbox_id, force, domain_id)
    return {"success": True, "status": "started", "message": "Backup running in background"}


def is_backup_running() -> bool:
    return _backup_running


def _scan_one_mailbox(mailbox_id: int) -> int:
    import asyncio

    mailbox = models.get_mailbox(mailbox_id)
    if not mailbox:
        return 0
    ws_log(f"AI scan starting for {mailbox['email']}...")
    result = asyncio.run(classifier.scan_mailbox(mailbox_id, log_fn=ws_log))
    count = result.get("suggestions_added", 0)
    ws_log(f"AI scan complete for {mailbox['email']}: {count} suggestion(s) — {result.get('message', '')}")
    return count


def _run_intelligence_scan(
    mailbox_id: int | None = None, domain_id: int | None = None
) -> dict:
    global _scan_running
    _scan_running = True
    try:
        if mailbox_id:
            mailbox = models.get_mailbox(mailbox_id)
            mailboxes = [mailbox] if mailbox else []
        elif domain_id:
            mailboxes = models.list_mailboxes(domain_id)
        else:
            mailboxes = models.list_mailboxes()

        total = 0
        scanned = 0
        for mb in mailboxes:
            if not mb:
                continue
            try:
                total += _scan_one_mailbox(mb["id"])
                scanned += 1
            except Exception as exc:
                ws_log(f"AI scan failed for {mb['email']}: {exc}")
                logger.exception("Intelligence scan error")

        ws_log(f"AI scan finished: {total} suggestion(s) across {scanned} mailbox(es)")
        return {"success": True, "suggestions_added": total, "mailboxes_scanned": scanned}
    finally:
        _scan_running = False


def trigger_intelligence_scan(mailbox_id: int) -> dict:
    """Run intelligence scan synchronously (used by tests)."""
    return _run_intelligence_scan(mailbox_id=mailbox_id)


def trigger_intelligence_scan_background(
    mailbox_id: int | None = None, domain_id: int | None = None
) -> dict:
    """Queue AI scan in background — can run while backup is in progress."""
    if _scan_running:
        return {"success": False, "status": "busy", "message": "An AI scan is already running"}

    scope = "selected mailbox" if mailbox_id else ("selected domain" if domain_id else "all mailboxes")
    ws_log(f"AI scan started ({scope})...")
    _executor.submit(_run_intelligence_scan, mailbox_id, domain_id)
    return {"success": True, "status": "started", "message": "AI scan running in background"}


def is_scan_running() -> bool:
    return _scan_running


def execute_flag_large(message_ids: list[int]) -> list[dict]:
    results = []
    by_mailbox: dict[int, list[int]] = {}
    for mid in message_ids:
        msg = models.get_message(mid)
        if msg:
            by_mailbox.setdefault(msg["mailbox_id"], []).append(mid)

    for mailbox_id, mids in by_mailbox.items():
        mailbox = models.get_mailbox(mailbox_id)
        if not mailbox:
            continue
        password = get_vault().decrypt(mailbox["encrypted_password"])
        batch = purge.flag_messages_for_deletion(
            mids, password, mailbox["imap_host"], mailbox["imap_port"], mailbox["email"]
        )
        results.extend(batch)
        ws_log(f"Flagged {len(batch)} large email(s) for {mailbox['email']}")
    return results


def execute_cleanup(duplicate_ids: list[int]) -> list[dict]:
    results = []
    by_mailbox: dict[int, list[int]] = {}
    for dup_id in duplicate_ids:
        dup = models.get_duplicate(dup_id)
        if dup:
            by_mailbox.setdefault(dup["mailbox_id"], []).append(dup_id)

    for mailbox_id, dup_ids in by_mailbox.items():
        mailbox = models.get_mailbox(mailbox_id)
        if not mailbox:
            continue
        password = get_vault().decrypt(mailbox["encrypted_password"])
        batch = purge.flag_duplicates_for_deletion(
            dup_ids, password, mailbox["imap_host"], mailbox["imap_port"], mailbox["email"]
        )
        results.extend(batch)
        ws_log(f"Flagged {len(batch)} duplicates for {mailbox['email']}")
    return results


def _resolve_suggestion_db_message_ids(suggestion: dict) -> tuple[list[int], list[str]]:
    """Map RFC Message-ID headers to backed-up message row IDs."""
    db_ids: list[int] = []
    errors: list[str] = []
    seen: set[int] = set()

    for header_id in suggestion.get("message_ids") or []:
        matches = models.get_messages_by_message_id(suggestion["mailbox_id"], header_id)
        if not matches:
            errors.append(f"No backed-up message for {str(header_id)[:48]}")
            continue
        for msg in matches:
            mid = msg["id"]
            if mid in seen:
                continue
            seen.add(mid)
            if msg.get("purge_status") == "flagged_deleted":
                continue
            db_ids.append(mid)

    return db_ids, errors


def execute_suggestions(suggestion_ids: list[int]) -> list[dict]:
    """Approve AI suggestions and flag matching messages on the IMAP server."""
    if not suggestion_ids:
        return []

    pending: list[tuple[int, dict, list[int], list[str]]] = []
    results: list[dict] = []

    for sid in suggestion_ids:
        suggestion = models.get_cleanup_suggestion(sid)
        if not suggestion:
            results.append({"id": sid, "success": False, "error": "Suggestion not found"})
            continue
        if suggestion.get("executed"):
            results.append({"id": sid, "success": True, "status": "already_flagged"})
            continue

        db_ids, resolve_errors = _resolve_suggestion_db_message_ids(suggestion)
        if not db_ids:
            models.mark_cleanup_approved([sid])
            err = "; ".join(resolve_errors) if resolve_errors else "No messages to flag"
            results.append({"id": sid, "success": False, "error": err})
            ws_log(f"AI suggestion {sid} not flagged: {err}")
            continue

        pending.append((sid, suggestion, db_ids, resolve_errors))

    by_mailbox: dict[int, list[int]] = {}
    for _, suggestion, db_ids, _ in pending:
        by_mailbox.setdefault(suggestion["mailbox_id"], []).extend(db_ids)

    flag_by_db_id: dict[int, dict] = {}
    for mailbox_id, db_ids in by_mailbox.items():
        mailbox = models.get_mailbox(mailbox_id)
        if not mailbox:
            for db_id in db_ids:
                flag_by_db_id[db_id] = {"id": db_id, "success": False, "error": "Mailbox not found"}
            continue
        password = get_vault().decrypt(mailbox["encrypted_password"])
        unique_ids = list(dict.fromkeys(db_ids))
        batch = purge.flag_messages_for_deletion(
            unique_ids,
            password,
            mailbox["imap_host"],
            mailbox["imap_port"],
            mailbox["email"],
        )
        for item in batch:
            flag_by_db_id[item["id"]] = item
        flagged = sum(
            1 for item in batch
            if item.get("success") and item.get("status") in ("flagged_deleted", "already_flagged")
        )
        ws_log(f"Flagged {flagged} AI suggestion message(s) for {mailbox['email']}")

    for sid, suggestion, db_ids, resolve_errors in pending:
        flags = [flag_by_db_id.get(db_id) for db_id in db_ids]
        ok_flags = [
            f for f in flags
            if f and f.get("success") and f.get("status") in ("flagged_deleted", "already_flagged")
        ]
        if len(ok_flags) == len(db_ids):
            models.mark_cleanup_executed([sid])
            results.append({"id": sid, "success": True, "status": "flagged_deleted"})
            continue

        models.mark_cleanup_approved([sid])
        flag_errors = [
            f.get("error", "Flag failed")
            for f in flags
            if not f or not f.get("success") or f.get("status") not in ("flagged_deleted", "already_flagged")
        ]
        errors = resolve_errors + flag_errors
        err = "; ".join(errors) if errors else "Failed to flag on server"
        results.append({"id": sid, "success": False, "error": err})
        ws_log(f"AI suggestion {sid} partially failed: {err}")

    return results


def execute_expunge(mailbox_id: int) -> dict:
    mailbox = models.get_mailbox(mailbox_id)
    if not mailbox:
        return {"success": False, "error": "Mailbox not found"}
    password = get_vault().decrypt(mailbox["encrypted_password"])
    result = purge.expunge_mailbox(
        mailbox_id, password, mailbox["imap_host"], mailbox["imap_port"], mailbox["email"]
    )
    ws_log(f"Expunged mailbox {mailbox['email']}")
    return result


def verify_mailbox_integrity(mailbox_id: int, repair: bool = False) -> dict:
    from storage.integrity import audit_mailbox

    mailbox = models.get_mailbox(mailbox_id)
    if not mailbox:
        return {"success": False, "error": "Mailbox not found"}
    ws_log(f"Manual integrity audit for {mailbox['email']}...")
    summary = audit_mailbox(mailbox_id, log_fn=ws_log)
    repair_info = None
    if repair or summary.get("failed", 0) > 0:
        from imap.repair import repair_mailbox

        ws_log(
            f"Repairing integrity failures for {mailbox['email']} "
            f"({summary.get('failed', 0)} failed)..."
        )
        repair_info = repair_mailbox(mailbox_id, log_fn=ws_log)
        summary = repair_info.get("integrity") or audit_mailbox(mailbox_id, log_fn=ws_log)
    result = {"success": True, **summary}
    if repair_info:
        result["repair"] = {
            "repaired": repair_info.get("repaired", 0),
            "migrated": repair_info.get("migrated", 0),
            "failed": repair_info.get("failed", 0),
        }
    return result


def preview_flag_verified(mailbox_id: int) -> dict:
    mailbox = models.get_mailbox(mailbox_id)
    if not mailbox:
        return {"success": False, "error": "Mailbox not found"}
    candidates = models.list_verified_purge_candidates(mailbox_id)
    total_bytes = sum(int(m.get("size") or 0) for m in candidates)
    stats = models.get_mailbox_integrity_stats(mailbox_id)
    warnings: list[str] = []
    if not stats.get("restore_ready"):
        warnings.append(
            "Mailbox is not fully restore-ready. Run Verify Backups first; only integrity-OK messages will be flagged."
        )
    if not candidates:
        warnings.append("No verified messages available to flag (already flagged or none verified).")
    return {
        "success": True,
        "mailbox_id": mailbox_id,
        "email": mailbox["email"],
        "count": len(candidates),
        "total_bytes": total_bytes,
        "integrity": stats,
        "warnings": warnings,
        "message_ids": [m["id"] for m in candidates],
    }


def flag_verified_for_deletion(mailbox_id: int) -> dict:
    """Flag all integrity-verified messages on the server for deletion (does not expunge)."""
    preview = preview_flag_verified(mailbox_id)
    if not preview.get("success"):
        return preview
    message_ids = preview.get("message_ids") or []
    if not message_ids:
        return {**preview, "flagged": 0, "failed": 0, "results": []}

    mailbox = models.get_mailbox(mailbox_id)
    password = get_vault().decrypt(mailbox["encrypted_password"])
    ws_log(
        f"Flagging {len(message_ids)} verified message(s) for deletion on {mailbox['email']} "
        f"(~{preview['total_bytes']} bytes)..."
    )
    results = purge.flag_messages_for_deletion(
        message_ids,
        password,
        mailbox["imap_host"],
        mailbox["imap_port"],
        mailbox["email"],
    )
    flagged = sum(
        1 for r in results
        if r.get("success") and r.get("status") in ("flagged_deleted", "already_flagged")
    )
    failed = len(results) - flagged
    ws_log(f"Flagged verified messages for {mailbox['email']}: {flagged} ok, {failed} failed")
    return {
        "success": failed == 0,
        "mailbox_id": mailbox_id,
        "email": mailbox["email"],
        "flagged": flagged,
        "failed": failed,
        "total_bytes": preview["total_bytes"],
        "results": results,
    }


def preview_import(message_ids: list[int]) -> dict:
    return restore.preview_restore(message_ids)


def _run_import(message_ids: list[int]) -> dict:
    global _import_running, _import_progress
    _import_running = True
    _import_progress = {
        "imported": 0,
        "skipped_existing": 0,
        "failed": 0,
        "total": len(message_ids),
        "skipped_details": [],
    }
    try:
        ws_log(f"Restore started for {len(message_ids)} selected message(s)...")
        result = restore.restore_messages(message_ids, log_fn=ws_log)
        _import_progress = {
            "imported": result.get("imported", 0),
            "skipped_existing": result.get("skipped_existing", 0),
            "failed": result.get("failed", 0),
            "total": len(message_ids),
            "skipped_details": result.get("skipped_details") or [],
        }
        return result
    finally:
        _import_running = False

def trigger_import_background(message_ids: list[int]) -> dict:
    """Queue selective restore in background."""
    if _import_running:
        return {"success": False, "status": "busy", "message": "A restore is already running"}
    if not message_ids:
        return {"success": False, "status": "error", "message": "No messages selected"}

    preview = restore.preview_restore(message_ids)
    if preview["restorable"] == 0:
        return {
            "success": False,
            "status": "error",
            "message": "No restorable messages in selection",
            "preview": preview,
        }

    _executor.submit(_run_import, message_ids)
    return {
        "success": True,
        "status": "started",
        "message": f"Restore running for {preview['restorable']} message(s)",
        "preview": preview,
    }


def is_import_running() -> bool:
    return _import_running


def get_import_progress() -> dict:
    return {"running": _import_running, **_import_progress}