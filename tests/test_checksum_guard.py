"""Pre-delete checksum guard tests."""

from pathlib import Path

from db import models
from imap.purge import can_purge
from storage.checksum import compute_md5


def _setup_mailbox_with_message(eml_path: Path, md5: str, cloud_synced=0, nas_synced=0):
    from db.vault import CredentialVault
    vault = CredentialVault(key=CredentialVault.generate_key())
    domain_id = models.create_domain("guard.com", "imap.guard.com")
    mb_id = models.create_mailbox(domain_id, "user@guard.com", vault.encrypt("pass"))
    models.insert_message(
        mailbox_id=mb_id,
        uid=1,
        folder="INBOX",
        message_id="<guard-test@guard.com>",
        md5_hash=md5,
        size=100,
        date="2026-06-01",
        eml_path=str(eml_path),
        cloud_synced=cloud_synced,
        nas_synced=nas_synced,
    )
    return mb_id


def test_can_purge_fails_md5_mismatch(tmp_path):
    eml = tmp_path / "email.eml"
    eml.write_bytes(b"original content")
    real_md5 = compute_md5(eml)
    mb_id = _setup_mailbox_with_message(eml, "wrong_hash_value")

    ok, reason = can_purge(mb_id, "<guard-test@guard.com>")
    assert ok is False
    assert "MD5" in reason


def test_can_purge_fails_no_cloud_sync(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DRIVE_ENABLED", True)
    monkeypatch.setattr(config, "DROPBOX_ENABLED", False)
    monkeypatch.setattr(config, "NAS_ENABLED", False)
    monkeypatch.setattr(config, "CLOUD_REQUIRED", False)

    eml = tmp_path / "email.eml"
    eml.write_bytes(b"content")
    md5 = compute_md5(eml)
    mb_id = _setup_mailbox_with_message(eml, md5, cloud_synced=0, nas_synced=0)

    ok, reason = can_purge(mb_id, "<guard-test@guard.com>")
    assert ok is False


def test_can_purge_succeeds_local_only(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DRIVE_ENABLED", False)
    monkeypatch.setattr(config, "DROPBOX_ENABLED", False)
    monkeypatch.setattr(config, "NAS_ENABLED", False)

    eml = tmp_path / "email.eml"
    eml.write_bytes(b"verified content")
    md5 = compute_md5(eml)
    mb_id = _setup_mailbox_with_message(eml, md5)

    ok, reason = can_purge(mb_id, "<guard-test@guard.com>")
    assert ok is True
