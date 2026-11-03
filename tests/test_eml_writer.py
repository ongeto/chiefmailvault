"""EML writer tests."""

import email
from datetime import datetime
from pathlib import Path

from parser.eml_writer import extract_attachments, extract_metadata, parse_message, write_eml
from storage.local import build_eml_path


def _make_test_email(with_attachment=False):
    msg = email.message.EmailMessage()
    msg["From"] = "sender@example.com"
    msg["To"] = "info@example.com"
    msg["Subject"] = "Test Invoice"
    msg["Message-ID"] = "<test-123@example.com>"
    msg["Date"] = "Mon, 15 Jun 2026 10:00:00 +0000"
    msg.set_content("Hello, this is a test email body.")
    if with_attachment:
        msg.add_attachment(b"PDF content here", maintype="application", subtype="pdf", filename="invoice.pdf")
    return msg.as_bytes()


def test_write_eml_and_metadata():
    raw = _make_test_email()
    eml_path = build_eml_path("info@example.com", 10214, datetime(2026, 6, 15), folder="INBOX")
    size = write_eml(raw, eml_path)
    assert eml_path.exists()
    assert size > 0
    assert "example.com" in str(eml_path)
    assert "06_June" in str(eml_path)
    assert "INBOX" in eml_path.parts
    assert eml_path.name == "email_10214.eml"

    sent_path = build_eml_path("info@example.com", 10214, datetime(2026, 6, 15), folder="Sent")
    assert "Sent" in sent_path.parts
    assert sent_path != eml_path

    msg = parse_message(raw)
    meta = extract_metadata(msg)
    assert meta["message_id"] == "<test-123@example.com>"
    assert "sender@example.com" in meta["sender"]
    assert meta["subject"] == "Test Invoice"


def test_extract_attachments():
    raw = _make_test_email(with_attachment=True)
    eml_path = build_eml_path("info@example.com", 99, datetime(2026, 6, 15))
    write_eml(raw, eml_path)
    msg = parse_message(raw)
    saved = extract_attachments(msg, eml_path, 99)
    assert len(saved) == 1
    assert Path(saved[0]).exists()
    assert "attachments" in saved[0]
