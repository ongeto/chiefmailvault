"""AI suggestion approve + IMAP flag tests."""

from unittest.mock import patch

from db.vault import CredentialVault
from db import models
from db.vault import CredentialVault
from core import orchestrator


def _seed_mailbox():
    domain_id = models.create_domain("sug.com", "imap.sug.com")
    vault = CredentialVault(key=CredentialVault.generate_key())
    mb_id = models.create_mailbox(domain_id, "user@sug.com", vault.encrypt("pass"))
    models.insert_message(
        mailbox_id=mb_id,
        uid=10,
        folder="INBOX",
        message_id="<newsletter@sug.com>",
        md5_hash="abc",
        size=1000,
        date="2026-06-01",
        eml_path="/tmp/newsletter.eml",
        subject="Weekly digest",
    )
    sug_id = models.insert_cleanup_suggestion(
        mb_id,
        "newsletter_clutter",
        ["<newsletter@sug.com>"],
        "Newsletter older than 14 days",
        subject="Weekly digest",
    )
    return mb_id, sug_id


def test_execute_suggestions_flags_on_server(tmp_path, monkeypatch):
    domain_id = models.create_domain("sug.com", "imap.sug.com")
    vault = CredentialVault(key=CredentialVault.generate_key())
    mb_id = models.create_mailbox(domain_id, "user@sug.com", vault.encrypt("pass"))
    eml = tmp_path / "newsletter.eml"
    eml.write_bytes(b"newsletter body")
    from storage.checksum import compute_md5

    models.insert_message(
        mailbox_id=mb_id,
        uid=10,
        folder="INBOX",
        message_id="<newsletter@sug.com>",
        md5_hash=compute_md5(eml),
        size=1000,
        date="2026-06-01",
        eml_path=str(eml),
        subject="Weekly digest",
    )
    sug_id = models.insert_cleanup_suggestion(
        mb_id,
        "newsletter_clutter",
        ["<newsletter@sug.com>"],
        "Newsletter older than 14 days",
        subject="Weekly digest",
    )

    def fake_flag(message_ids, password, imap_host, imap_port, email):
        return [
            {"id": mid, "success": True, "status": "flagged_deleted"}
            for mid in message_ids
        ]

    with patch("core.orchestrator.get_vault", return_value=vault):
        with patch("core.orchestrator.purge.flag_messages_for_deletion", side_effect=fake_flag):
            results = orchestrator.execute_suggestions([sug_id])

    assert len(results) == 1
    assert results[0]["success"] is True
    assert results[0]["status"] == "flagged_deleted"

    sug = models.get_cleanup_suggestion(sug_id)
    assert sug["executed"] == 1
    assert sug["approved"] == 1


def test_execute_suggestions_skips_already_executed():
    _, sug_id = _seed_mailbox()
    models.mark_cleanup_executed([sug_id])

    with patch("core.orchestrator.purge.flag_messages_for_deletion") as mock_flag:
        results = orchestrator.execute_suggestions([sug_id])
        mock_flag.assert_not_called()

    assert results[0]["status"] == "already_flagged"
