"""Selective restore / IMAP import tests."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from db import models
from db.database import get_db
from db.vault import CredentialVault
from imap import restore
from storage.checksum import compute_md5


def _seed(tmp_path: Path, folder: str = "INBOX", message_id: str = "<restore@test.com>"):
    domain_id = models.create_domain("restore.com", "imap.restore.com")
    vault = CredentialVault(key=CredentialVault.generate_key())
    mb_id = models.create_mailbox(
        domain_id, "user@restore.com", vault.encrypt("pass"), credentials_validated=True
    )
    eml = tmp_path / "email.eml"
    eml.write_bytes(
        b"From: a@b.com\r\nSubject: Hi\r\nMessage-ID: " + message_id.encode() + b"\r\n\r\nBody"
    )
    mid = models.insert_message(
        mailbox_id=mb_id,
        uid=42,
        folder=folder,
        message_id=message_id,
        md5_hash=compute_md5(eml),
        size=eml.stat().st_size,
        date="2026-06-01T10:00:00+03:00",
        eml_path=str(eml),
        subject="Hi",
        sender="a@b.com",
    )
    return mb_id, mid, vault, eml


def test_preview_restore_counts_and_warns(tmp_path):
    _, mid, _, _ = _seed(tmp_path)
    with get_db() as conn:
        conn.execute("UPDATE messages SET size = ? WHERE id = ?", (60 * 1024 * 1024, mid))

    preview = restore.preview_restore([mid])
    assert preview["restorable"] == 1
    assert preview["total_bytes"] == 60 * 1024 * 1024
    assert any("quota" in w.lower() or "MB" in w for w in preview["warnings"])


def test_preview_skips_missing_eml(tmp_path):
    _, mid, _, eml = _seed(tmp_path)
    eml.unlink()
    preview = restore.preview_restore([mid])
    assert preview["restorable"] == 0
    assert preview["skipped"] == 1


def test_restore_skips_existing_message_id(tmp_path):
    _, mid, vault, _ = _seed(tmp_path)
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = None
    client.message_id_exists.return_value = True

    with patch("imap.restore.ImapClient", return_value=client):
        with patch("imap.restore.get_vault", return_value=vault):
            with patch("imap.restore.resolve_imap_folder_name", return_value="INBOX"):
                result = restore.restore_messages([mid])

    assert result["imported"] == 0
    assert result["skipped_existing"] == 1
    client.append.assert_not_called()


def test_restore_appends_to_original_folder(tmp_path):
    _, mid, vault, _ = _seed(tmp_path, folder="Sent")
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = None
    client.message_id_exists.return_value = False
    client.conn = MagicMock()

    with patch("imap.restore.ImapClient", return_value=client):
        with patch("imap.restore.get_vault", return_value=vault):
            with patch("imap.restore.resolve_imap_folder_name", return_value="INBOX.Sent") as resolve:
                result = restore.restore_messages([mid])

    resolve.assert_called()
    assert result["imported"] == 1
    assert result["failed"] == 0
    client.append.assert_called_once()
    assert client.append.call_args.args[0] == "INBOX.Sent"
