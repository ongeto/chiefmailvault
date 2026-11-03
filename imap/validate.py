"""IMAP credential validation."""

import imaplib
import logging

from imap.client import ImapClient

logger = logging.getLogger(__name__)


def validate_credentials(host: str, port: int, email: str, password: str) -> tuple[bool, str]:
    """Test IMAP login and INBOX access. Returns (success, message)."""
    if not email or not password:
        return False, "Email and password are required"
    if "@" not in email:
        return False, "Invalid email address"

    try:
        with ImapClient(host, port, email, password) as client:
            client.select_folder("INBOX")
        logger.info("Credentials validated for %s@%s", email, host)
        return True, "Connection successful — inbox accessible"
    except imaplib.IMAP4.error as exc:
        logger.warning("IMAP auth failed for %s: %s", email, exc)
        return False, f"Login failed: check email and password ({exc})"
    except OSError as exc:
        logger.warning("IMAP connection failed for %s@%s: %s", email, host, exc)
        return False, f"Cannot reach mail server {host}:{port} — check host and network"
    except Exception as exc:
        logger.warning("Credential validation error for %s: %s", email, exc)
        return False, f"Validation failed: {exc}"
