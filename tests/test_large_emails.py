"""Large email triage tests."""

from db import models
from db.vault import CredentialVault


def test_list_large_emails_filters_by_size(tmp_path):
    vault = CredentialVault(key=CredentialVault.generate_key())
    domain_id = models.create_domain("large.com", "imap.large.com")
    mb_id = models.create_mailbox(domain_id, "user@large.com", vault.encrypt("pass"))

    eml = tmp_path / "small.eml"
    eml.write_bytes(b"x" * 100)
    eml_large = tmp_path / "big.eml"
    eml_large.write_bytes(b"x" * 100)

    models.insert_message(
        mailbox_id=mb_id, uid=1, folder="INBOX", message_id="<small@large.com>",
        md5_hash="a", size=1024, date="2026-06-01", eml_path=str(eml), is_large=False,
    )
    models.insert_message(
        mailbox_id=mb_id, uid=2, folder="INBOX", message_id="<big@large.com>",
        md5_hash="b", size=26 * 1024 * 1024, date="2026-06-01", eml_path=str(eml_large), is_large=True,
    )

    large = models.list_large_emails(mb_id)
    assert len(large) == 1
    assert large[0]["uid"] == 2
    assert large[0]["is_large"] == 1
