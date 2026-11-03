"""Google Drive API v3 upload."""

import logging
from pathlib import Path

from config import DRIVE_CREDENTIALS_FILE, DRIVE_ENABLED, DRIVE_FOLDER_ID

logger = logging.getLogger(__name__)


def upload_to_drive(zip_path: Path) -> bool:
    if not DRIVE_ENABLED:
        logger.info("Google Drive upload skipped (disabled)")
        return False
    if not DRIVE_CREDENTIALS_FILE or not DRIVE_FOLDER_ID:
        logger.warning("Drive enabled but credentials/folder not configured")
        return False
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        SCOPES = ["https://www.googleapis.com/auth/drive.file"]
        creds_path = Path(DRIVE_CREDENTIALS_FILE)
        if not creds_path.exists():
            logger.error("Drive credentials file not found: %s", creds_path)
            return False

        flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
        creds = flow.run_local_server(port=0)
        service = build("drive", "v3", credentials=creds)
        metadata = {"name": zip_path.name, "parents": [DRIVE_FOLDER_ID]}
        media = MediaFileUpload(str(zip_path), mimetype="application/zip")
        service.files().create(body=metadata, media_body=media, fields="id").execute()
        logger.info("Uploaded %s to Google Drive", zip_path.name)
        return True
    except Exception as exc:
        logger.error("Drive upload failed: %s", exc)
        return False
