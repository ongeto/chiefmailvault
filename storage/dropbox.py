"""Dropbox HTTP v2 upload."""

import logging
from pathlib import Path

import httpx

from config import DROPBOX_ENABLED, DROPBOX_PATH, DROPBOX_TOKEN

logger = logging.getLogger(__name__)


def upload_to_dropbox(zip_path: Path) -> bool:
    if not DROPBOX_ENABLED:
        logger.info("Dropbox upload skipped (disabled)")
        return False
    if not DROPBOX_TOKEN:
        logger.warning("Dropbox enabled but token not configured")
        return False
    try:
        dropbox_path = f"{DROPBOX_PATH.rstrip('/')}/{zip_path.name}"
        headers = {
            "Authorization": f"Bearer {DROPBOX_TOKEN}",
            "Dropbox-API-Arg": f'{{"path": "{dropbox_path}", "mode": "add"}}',
            "Content-Type": "application/octet-stream",
        }
        with open(zip_path, "rb") as f:
            data = f.read()
        resp = httpx.post(
            "https://content.dropboxapi.com/2/files/upload",
            headers=headers,
            content=data,
            timeout=120,
        )
        resp.raise_for_status()
        logger.info("Uploaded %s to Dropbox", zip_path.name)
        return True
    except Exception as exc:
        logger.error("Dropbox upload failed: %s", exc)
        return False
