"""API route handlers."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user
from core import orchestrator
from db import models
from db.credentials import get_vault

router = APIRouter(prefix="/api")


class DomainCreate(BaseModel):
    name: str
    imap_host: str = "imap.hostinger.com"
    imap_port: int = 993


class MailboxCreate(BaseModel):
    domain_id: int
    email: str
    password: str


class MailboxUpdate(BaseModel):
    domain_id: int | None = None
    email: str | None = None
    password: str | None = None


class CleanupExecute(BaseModel):
    duplicate_ids: list[int]


class FlagLargeRequest(BaseModel):
    message_ids: list[int]


class ExpungeRequest(BaseModel):
    mailbox_id: int


class BackupTrigger(BaseModel):
    mailbox_id: int | None = None
    domain_id: int | None = None
    force: bool = False


class IntelligenceScan(BaseModel):
    mailbox_id: int | None = None
    domain_id: int | None = None


class ApproveSuggestions(BaseModel):
    suggestion_ids: list[int]


class ImportPreview(BaseModel):
    message_ids: list[int]


class ImportTrigger(BaseModel):
    message_ids: list[int]


@router.get("/stats")
async def get_stats(domain_id: int | None = None, user: str = Depends(get_current_user)):
    return models.get_stats(domain_id)


@router.get("/domains")
async def list_domains(user: str = Depends(get_current_user)):
    return models.list_domains()


@router.post("/domains")
async def create_domain(body: DomainCreate, user: str = Depends(get_current_user)):
    domain_id = models.create_domain(body.name, body.imap_host, body.imap_port)
    return {"id": domain_id, "name": body.name}


@router.get("/mailboxes")
async def list_mailboxes(domain_id: int | None = None, user: str = Depends(get_current_user)):
    mailboxes = models.list_mailboxes(domain_id)
    for mb in mailboxes:
        mb.pop("encrypted_password", None)
        mb["password"] = get_vault().mask("")
        mb["integrity"] = models.get_mailbox_integrity_stats(mb["id"])
    return mailboxes


@router.post("/mailboxes/validate")
async def validate_mailbox(body: MailboxCreate, user: str = Depends(get_current_user)):
    """Test IMAP credentials without saving."""
    domain = models.get_domain(body.domain_id)
    if not domain:
        raise HTTPException(400, "Domain not found")

    from imap.validate import validate_credentials

    valid, message = validate_credentials(
        domain["imap_host"], domain["imap_port"], body.email, body.password
    )
    return {"valid": valid, "message": message}


@router.post("/mailboxes")
async def create_mailbox(body: MailboxCreate, user: str = Depends(get_current_user)):
    domain = models.get_domain(body.domain_id)
    if not domain:
        raise HTTPException(400, "Domain not found")

    from imap.validate import validate_credentials

    valid, message = validate_credentials(
        domain["imap_host"], domain["imap_port"], body.email, body.password
    )
    if not valid:
        raise HTTPException(400, detail=message)

    encrypted = get_vault().encrypt(body.password)
    mailbox_id = models.create_mailbox(
        body.domain_id, body.email, encrypted, credentials_validated=True
    )
    return {
        "id": mailbox_id,
        "email": body.email,
        "password": get_vault().mask(body.password),
        "credentials_validated": True,
        "message": message,
    }


@router.get("/mailboxes/{mailbox_id}")
async def get_mailbox(mailbox_id: int, user: str = Depends(get_current_user)):
    mailbox = models.get_mailbox(mailbox_id)
    if not mailbox:
        raise HTTPException(404, "Mailbox not found")
    mailbox.pop("encrypted_password", None)
    mailbox["password"] = get_vault().mask("")
    return mailbox


@router.post("/mailboxes/{mailbox_id}/revalidate")
async def revalidate_mailbox(mailbox_id: int, user: str = Depends(get_current_user)):
    """Re-test stored IMAP credentials and update the validated flag."""
    mailbox = models.get_mailbox(mailbox_id)
    if not mailbox:
        raise HTTPException(404, "Mailbox not found")

    domain = models.get_domain(mailbox["domain_id"])
    if not domain:
        raise HTTPException(400, "Domain not found")

    from imap.validate import validate_credentials

    try:
        password = get_vault().decrypt(mailbox["encrypted_password"])
    except Exception:
        models.mark_mailbox_validated(mailbox_id, False)
        return {
            "valid": False,
            "message": "Stored password could not be decrypted — update the password",
            "open_edit": True,
        }

    valid, message = validate_credentials(
        domain["imap_host"], domain["imap_port"], mailbox["email"], password
    )
    models.mark_mailbox_validated(mailbox_id, valid)
    return {
        "valid": valid,
        "message": message if valid else f"{message} — update the password to fix this",
        "open_edit": not valid,
    }


@router.post("/mailboxes/{mailbox_id}/verify")
async def verify_mailbox(
    mailbox_id: int,
    repair: bool = True,
    user: str = Depends(get_current_user),
):
    """Re-verify all local .eml backups; re-fetch failed ones onto folder-aware paths."""
    result = orchestrator.verify_mailbox_integrity(mailbox_id, repair=repair)
    if not result.get("success") and result.get("error"):
        raise HTTPException(404 if "not found" in result["error"].lower() else 400, result["error"])
    return result


@router.get("/mailboxes/{mailbox_id}/integrity")
async def mailbox_integrity(mailbox_id: int, user: str = Depends(get_current_user)):
    mailbox = models.get_mailbox(mailbox_id)
    if not mailbox:
        raise HTTPException(404, "Mailbox not found")
    return models.get_mailbox_integrity_stats(mailbox_id)


@router.post("/mailboxes/{mailbox_id}/flag-verified")
async def flag_verified_mailbox(mailbox_id: int, user: str = Depends(get_current_user)):
    """
    Flag all integrity-verified messages for server deletion.
    Preview-style response if you pass ?preview=1 — otherwise executes.
    """
    preview = orchestrator.preview_flag_verified(mailbox_id)
    if not preview.get("success"):
        raise HTTPException(404 if "not found" in (preview.get("error") or "").lower() else 400, preview.get("error"))
    return preview


@router.post("/mailboxes/{mailbox_id}/flag-verified/execute")
async def flag_verified_mailbox_execute(mailbox_id: int, user: str = Depends(get_current_user)):
    result = orchestrator.flag_verified_for_deletion(mailbox_id)
    if result.get("error") and not result.get("success") and result.get("flagged") is None:
        raise HTTPException(404 if "not found" in result["error"].lower() else 400, result["error"])
    return result


@router.put("/mailboxes/{mailbox_id}")
async def update_mailbox(
    mailbox_id: int, body: MailboxUpdate, user: str = Depends(get_current_user)
):
    mailbox = models.get_mailbox(mailbox_id)
    if not mailbox:
        raise HTTPException(404, "Mailbox not found")

    domain_id = body.domain_id if body.domain_id is not None else mailbox["domain_id"]
    email = body.email if body.email is not None else mailbox["email"]
    domain = models.get_domain(domain_id)
    if not domain:
        raise HTTPException(400, "Domain not found")

    encrypted = None
    validated = mailbox.get("credentials_validated", 0)

    if body.password:
        from imap.validate import validate_credentials

        valid, message = validate_credentials(
            domain["imap_host"], domain["imap_port"], email, body.password
        )
        if not valid:
            raise HTTPException(400, detail=message)
        encrypted = get_vault().encrypt(body.password)
        validated = True
    elif body.email or body.domain_id:
        # Re-validate existing password when email or domain changes
        from imap.validate import validate_credentials

        password = get_vault().decrypt(mailbox["encrypted_password"])
        valid, message = validate_credentials(
            domain["imap_host"], domain["imap_port"], email, password
        )
        if not valid:
            raise HTTPException(400, detail=f"Existing password invalid for new settings: {message}")
        validated = True

    ok = models.update_mailbox(
        mailbox_id,
        email=body.email,
        domain_id=body.domain_id,
        encrypted_password=encrypted,
        credentials_validated=validated if (body.password or body.email or body.domain_id) else None,
    )
    if not ok:
        raise HTTPException(500, "Failed to update mailbox")
    return {"success": True, "id": mailbox_id}


@router.delete("/mailboxes/{mailbox_id}")
async def delete_mailbox(mailbox_id: int, user: str = Depends(get_current_user)):
    mailbox = models.get_mailbox(mailbox_id)
    if not mailbox:
        raise HTTPException(404, "Mailbox not found")
    models.delete_mailbox(mailbox_id)
    return {"success": True, "id": mailbox_id}


@router.get("/duplicates")
async def list_duplicates(
    mailbox_id: int | None = None,
    domain_id: int | None = None,
    user: str = Depends(get_current_user),
):
    return models.list_duplicates(mailbox_id, domain_id)


@router.get("/large-emails")
async def list_large_emails(
    mailbox_id: int | None = None,
    domain_id: int | None = None,
    user: str = Depends(get_current_user),
):
    return models.list_large_emails(mailbox_id, domain_id)


@router.get("/cleanup/suggestions")
async def list_suggestions(
    mailbox_id: int | None = None,
    domain_id: int | None = None,
    user: str = Depends(get_current_user),
):
    return models.list_cleanup_suggestions(mailbox_id, domain_id)


@router.post("/cleanup/flag-large")
async def flag_large_emails(body: FlagLargeRequest, user: str = Depends(get_current_user)):
    if not body.message_ids:
        raise HTTPException(400, "No message IDs provided")
    results = orchestrator.execute_flag_large(body.message_ids)
    return {"results": results}


@router.post("/cleanup/execute")
async def cleanup_execute(body: CleanupExecute, user: str = Depends(get_current_user)):
    if not body.duplicate_ids:
        raise HTTPException(400, "No duplicate IDs provided")
    results = orchestrator.execute_cleanup(body.duplicate_ids)
    return {"results": results}


@router.post("/cleanup/expunge")
async def cleanup_expunge(body: ExpungeRequest, user: str = Depends(get_current_user)):
    result = orchestrator.execute_expunge(body.mailbox_id)
    return result


@router.post("/cleanup/approve")
async def approve_suggestions(body: ApproveSuggestions, user: str = Depends(get_current_user)):
    if not body.suggestion_ids:
        raise HTTPException(400, "No suggestion IDs provided")
    results = orchestrator.execute_suggestions(body.suggestion_ids)
    flagged = sum(1 for r in results if r.get("success"))
    failed = len(results) - flagged
    return {"flagged": flagged, "failed": failed, "results": results}


@router.post("/backup/trigger")
async def backup_trigger(body: BackupTrigger, user: str = Depends(get_current_user)):
    return orchestrator.trigger_backup_background(body.mailbox_id, body.force, body.domain_id)


@router.get("/backup/status")
async def backup_status(user: str = Depends(get_current_user)):
    return {"running": orchestrator.is_backup_running()}


@router.post("/intelligence/scan")
async def intelligence_scan(body: IntelligenceScan, user: str = Depends(get_current_user)):
    return orchestrator.trigger_intelligence_scan_background(body.mailbox_id, body.domain_id)


@router.get("/intelligence/status")
async def intelligence_status(user: str = Depends(get_current_user)):
    from intelligence import ollama_client

    ollama = await ollama_client.check_ready()
    return {"running": orchestrator.is_scan_running(), "ollama": ollama}


@router.get("/messages/restorable")
async def list_restorable_messages(
    mailbox_id: int | None = None,
    domain_id: int | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
    user: str = Depends(get_current_user),
):
    return models.list_restorable_messages(mailbox_id, domain_id, q, limit, offset)


@router.post("/import/preview")
async def import_preview(body: ImportPreview, user: str = Depends(get_current_user)):
    if not body.message_ids:
        raise HTTPException(400, "No message IDs provided")
    return orchestrator.preview_import(body.message_ids)


@router.post("/import/trigger")
async def import_trigger(body: ImportTrigger, user: str = Depends(get_current_user)):
    if not body.message_ids:
        raise HTTPException(400, "No message IDs provided")
    return orchestrator.trigger_import_background(body.message_ids)


@router.get("/import/status")
async def import_status(user: str = Depends(get_current_user)):
    return orchestrator.get_import_progress()
