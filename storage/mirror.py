"""Package mailbox storage into zip archives for cloud upload."""

import logging
import zipfile
from pathlib import Path

from config import DROPBOX_ENABLED, DRIVE_ENABLED, NAS_ENABLED, UPLOADS_DIR
from core.timezone_utils import now_local_naive
from db import models
from storage import drive, dropbox, nas
from storage.local import get_mailbox_storage_root, sanitize_account, get_domain_from_email

logger = logging.getLogger(__name__)


def create_backup_zip(email: str, log_fn=None) -> Path | None:
    """Package mailbox storage into a zip archive for cloud upload."""
    _log = log_fn or (lambda msg: None)
    source = get_mailbox_storage_root(email)
    if not source.exists():
        logger.warning("No storage found for %s", email)
        return None

    files = [f for f in source.rglob("*") if f.is_file()]
    if not files:
        _log(f"No archived files to zip for {email}")
        return None

    domain = get_domain_from_email(email)
    account = sanitize_account(email)
    timestamp = now_local_naive().strftime("%Y%m%d_%H%M%S")
    zip_name = f"{domain}_{account}_backup_{timestamp}.zip"
    zip_path = UPLOADS_DIR / zip_name
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    _log(f"Creating backup zip for {email} ({len(files)} file(s))...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, file in enumerate(files, 1):
            zf.write(file, file.relative_to(source.parent.parent))
            if i % 500 == 0 or i == len(files):
                _log(f"Zipping {email}: {i}/{len(files)} files")

    logger.info("Created backup zip: %s", zip_path)
    _log(f"Backup zip ready: {zip_path.name}")
    return zip_path


def mirror_mailbox(
    mailbox_id: int,
    email: str,
    log_fn=None,
    messages_added: int = 0,
) -> dict:
    """Zip and upload to configured destinations."""
    _log = log_fn or (lambda msg: None)
    result = {"drive": False, "dropbox": False, "nas": False}
    cloud_enabled = DRIVE_ENABLED or DROPBOX_ENABLED or NAS_ENABLED

    if not cloud_enabled:
        models.mark_messages_cloud_synced(mailbox_id)
        models.mark_messages_nas_synced(mailbox_id)
        result["local_only"] = True
        _log(f"Archive check complete for {email} (cloud mirror disabled)")
        return result

    if messages_added == 0:
        _log(f"Skipping cloud zip for {email} (no new messages this run)")
        return {**result, "skipped": True}

    zip_path = create_backup_zip(email, log_fn=_log)
    source = get_mailbox_storage_root(email)

    if DRIVE_ENABLED and zip_path:
        _log(f"Uploading {email} backup to Google Drive...")
        result["drive"] = drive.upload_to_drive(zip_path)
    if DROPBOX_ENABLED and zip_path:
        _log(f"Uploading {email} backup to Dropbox...")
        result["dropbox"] = dropbox.upload_to_dropbox(zip_path)
    if NAS_ENABLED:
        _log(f"Mirroring {email} archive to NAS...")
        result["nas"] = nas.mirror_to_nas(source, email)

    if result["drive"] or result["dropbox"]:
        models.mark_messages_cloud_synced(mailbox_id)
    if result["nas"]:
        models.mark_messages_nas_synced(mailbox_id)

    return result
