"""Post-backup integrity audit tests."""

from pathlib import Path

from db import models
from db.vault import CredentialVault
from storage.checksum import compute_md5
from storage.integrity import audit_mailbox, check_message_integrity


def _seed(tmp_path: Path, good: bool = True):
    domain_id = models.create_domain("integ.com", "imap.integ.com")
    vault = CredentialVault(key=CredentialVault.generate_key())
    mb_id = models.create_mailbox(
        domain_id, "user@integ.com", vault.encrypt("pass"), credentials_validated=True
    )
    eml = tmp_path / "email.eml"
    eml.write_bytes(b"From: a@b.com\r\nSubject: Hi\r\n\r\nBody")
    md5 = compute_md5(eml) if good else "wronghash"
    mid = models.insert_message(
        mailbox_id=mb_id,
        uid=1,
        folder="INBOX",
        message_id="<integ@test.com>",
        md5_hash=md5,
        size=eml.stat().st_size,
        date="2026-06-01",
        eml_path=str(eml),
        subject="Hi",
    )
    return mb_id, mid, eml


def test_check_message_integrity_ok(tmp_path):
    _, mid, _ = _seed(tmp_path, good=True)
    msg = models.get_message(mid)
    ok, reason = check_message_integrity(msg)
    assert ok is True
    assert reason == "OK"


def test_check_message_integrity_md5_fail(tmp_path):
    _, mid, _ = _seed(tmp_path, good=False)
    msg = models.get_message(mid)
    ok, reason = check_message_integrity(msg)
    assert ok is False
    assert "MD5" in reason


def test_audit_mailbox_marks_restore_ready(tmp_path):
    mb_id, mid, _ = _seed(tmp_path, good=True)
    summary = audit_mailbox(mb_id)
    assert summary["ok"] == 1
    assert summary["total"] == 1
    assert summary["restore_ready"] is True
    msg = models.get_message(mid)
    assert msg["integrity_ok"] == 1
    stats = models.get_mailbox_integrity_stats(mb_id)
    assert stats["restore_ready"] is True


def test_audit_mailbox_fails_closed(tmp_path):
    mb_id, mid, eml = _seed(tmp_path, good=True)
    eml.unlink()
    summary = audit_mailbox(mb_id)
    assert summary["restore_ready"] is False
    assert summary["failed"] == 1
    msg = models.get_message(mid)
    assert msg["integrity_ok"] == 0


def test_verified_purge_candidates_only_ok(tmp_path):
    mb_id, mid, _ = _seed(tmp_path, good=True)
    audit_mailbox(mb_id)
    candidates = models.list_verified_purge_candidates(mb_id)
    assert len(candidates) == 1
    assert candidates[0]["id"] == mid
