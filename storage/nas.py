"""Local NAS folder mirroring."""

import logging
import shutil
from pathlib import Path

from config import NAS_ENABLED, NAS_PATH

logger = logging.getLogger(__name__)


def mirror_to_nas(source_dir: Path, email: str) -> bool:
    if not NAS_ENABLED:
        logger.info("NAS mirror skipped (disabled)")
        return False
    if not NAS_PATH:
        logger.warning("NAS enabled but path not configured")
        return False
    try:
        from storage.local import sanitize_account, get_domain_from_email

        domain = get_domain_from_email(email)
        account = sanitize_account(email)
        dest = Path(NAS_PATH) / domain / account
        dest.mkdir(parents=True, exist_ok=True)
        if source_dir.exists():
            for item in source_dir.rglob("*"):
                if item.is_file():
                    rel = item.relative_to(source_dir)
                    target = dest / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, target)
        logger.info("Mirrored %s to NAS at %s", email, dest)
        return True
    except Exception as exc:
        logger.error("NAS mirror failed: %s", exc)
        return False
