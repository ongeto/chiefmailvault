"""RFC822 .eml writer and attachment extraction."""

import email
import email.policy
from core.timezone_utils import now_local, now_local_naive, to_local, to_local_naive
from email.message import Message
from pathlib import Path

from storage.local import get_attachments_dir, safe_filename


def parse_message(raw_bytes: bytes) -> Message:
    return email.message_from_bytes(raw_bytes, policy=email.policy.default)


def extract_metadata(msg: Message) -> dict:
    message_id = msg.get("Message-ID", "").strip()
    sender = msg.get("From", "")
    subject = msg.get("Subject", "")
    content_type = msg.get_content_type()
    date_hdr = msg.get("Date")
    msg_date = None
    if date_hdr:
        try:
            from email.utils import parsedate_to_datetime
            msg_date = parsedate_to_datetime(date_hdr)
        except Exception:
            msg_date = now_local()
    local_date = to_local(msg_date) if msg_date else None
    snippet = _extract_snippet(msg)[:100]
    return {
        "message_id": message_id,
        "sender": sender,
        "subject": subject,
        "content_type": content_type,
        "date": local_date.isoformat() if local_date else None,
        "msg_date": to_local_naive(msg_date) if msg_date else None,
        "snippet": snippet,
    }


def _extract_snippet(msg: Message) -> str:
    try:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode("utf-8", errors="replace").strip()
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                return payload.decode("utf-8", errors="replace").strip()
    except Exception:
        pass
    return ""


def write_eml(raw_bytes: bytes, eml_path: Path) -> int:
    """Write raw RFC822 bytes to .eml file. Returns file size."""
    eml_path.parent.mkdir(parents=True, exist_ok=True)
    eml_path.write_bytes(raw_bytes)
    return len(raw_bytes)


def extract_attachments(msg: Message, eml_path: Path, uid: int) -> list[str]:
    """Extract attachments to sibling attachments/ directory."""
    att_dir = get_attachments_dir(eml_path)
    saved = []
    if not msg.is_multipart():
        return saved
    for part in msg.walk():
        disposition = part.get_content_disposition()
        if disposition != "attachment":
            continue
        filename = part.get_filename()
        if not filename:
            ext = part.get_content_subtype() or "bin"
            filename = f"attachment_{uid}.{ext}"
        filename = safe_filename(filename)
        filepath = att_dir / filename
        payload = part.get_payload(decode=True)
        if payload:
            filepath.write_bytes(payload)
            saved.append(str(filepath))
    return saved
