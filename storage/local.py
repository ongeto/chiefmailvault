"""Local storage path helpers."""

import re
from datetime import datetime
from pathlib import Path

from config import STORAGE_DIR
from core.timezone_utils import now_local_naive

MONTH_NAMES = [
    "", "01_January", "02_February", "03_March", "04_April",
    "05_May", "06_June", "07_July", "08_August", "09_September",
    "10_October", "11_November", "12_December",
]


def sanitize_account(email: str) -> str:
    """Convert info@domain.com -> info_at_domain."""
    local, _, domain = email.partition("@")
    domain_part = domain.replace(".", "_") if domain else ""
    return f"{local}_at_{domain_part}" if domain_part else local.replace("@", "_at_")


def get_domain_from_email(email: str) -> str:
    return email.split("@")[-1] if "@" in email else email


def sanitize_folder(folder: str) -> str:
    """Make an IMAP folder name safe for a filesystem path segment."""
    name = (folder or "UNKNOWN").strip() or "UNKNOWN"
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"\s+", "_", name)
    return name[:120]


def build_eml_path(
    email: str,
    uid: int,
    msg_date: datetime | None = None,
    folder: str = "INBOX",
) -> Path:
    """Build storage path including folder — IMAP UIDs are unique per folder only."""
    dt = msg_date or now_local_naive()
    domain = get_domain_from_email(email)
    account = sanitize_account(email)
    month_folder = MONTH_NAMES[dt.month]
    folder_part = sanitize_folder(folder)
    base = STORAGE_DIR / domain / account / str(dt.year) / month_folder / folder_part
    base.mkdir(parents=True, exist_ok=True)
    return base / f"email_{uid}.eml"


def get_attachments_dir(eml_path: Path) -> Path:
    att_dir = eml_path.parent / "attachments"
    att_dir.mkdir(parents=True, exist_ok=True)
    return att_dir


def get_mailbox_storage_root(email: str) -> Path:
    domain = get_domain_from_email(email)
    account = sanitize_account(email)
    return STORAGE_DIR / domain / account


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    return name[:200] if name else "attachment"
