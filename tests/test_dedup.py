"""Deduplication engine tests."""

from db import models
from imap.dedup import check_and_flag_duplicate, rescan_mailbox_duplicates


def _seed_message(mailbox_id, uid, folder, message_id):
    models.insert_message(
        mailbox_id=mailbox_id,
        uid=uid,
        folder=folder,
        message_id=message_id,
        md5_hash="abc123",
        size=1000,
        date="2026-06-01",
        eml_path=f"/tmp/email_{uid}.eml",
    )


def test_duplicate_detected_inbox_and_sent():
    domain_id = models.create_domain("dup.com", "imap.dup.com")
    from db.vault import CredentialVault
    vault = CredentialVault(key=CredentialVault.generate_key())
    mb_id = models.create_mailbox(domain_id, "user@dup.com", vault.encrypt("pass"))

    msg_id = "<duplicate-test@dup.com>"
    _seed_message(mb_id, 100, "INBOX", msg_id)
    _seed_message(mb_id, 200, "Sent", msg_id)

    dup_id = check_and_flag_duplicate(mb_id, msg_id)
    assert dup_id is not None

    dups = models.list_duplicates(mb_id)
    assert len(dups) == 1
    assert dups[0]["inbox_uid"] == 100
    assert dups[0]["sent_uid"] == 200
    assert dups[0]["status"] == "flagged"


def test_no_duplicate_single_folder():
    domain_id = models.create_domain("nodup.com", "imap.nodup.com")
    from db.vault import CredentialVault
    vault = CredentialVault(key=CredentialVault.generate_key())
    mb_id = models.create_mailbox(domain_id, "user@nodup.com", vault.encrypt("pass"))

    msg_id = "<single@nodup.com>"
    _seed_message(mb_id, 1, "INBOX", msg_id)

    dup_id = check_and_flag_duplicate(mb_id, msg_id)
    assert dup_id is None


def test_rescan_backfills_missed_duplicate():
    domain_id = models.create_domain("rescan.com", "imap.rescan.com")
    from db.vault import CredentialVault
    vault = CredentialVault(key=CredentialVault.generate_key())
    mb_id = models.create_mailbox(domain_id, "user@rescan.com", vault.encrypt("pass"))

    msg_id = "<rescan-test@rescan.com>"
    _seed_message(mb_id, 10, "INBOX", msg_id)
    _seed_message(mb_id, 20, "Sent", msg_id)

    assert models.list_duplicates(mb_id) == []
    added = rescan_mailbox_duplicates(mb_id)
    assert added == 1
    dups = models.list_duplicates(mb_id)
    assert len(dups) == 1
    assert dups[0]["inbox_uid"] == 10
    assert dups[0]["sent_uid"] == 20


def test_inbox_trash_not_duplicate():
    domain_id = models.create_domain("trash.com", "imap.trash.com")
    from db.vault import CredentialVault
    vault = CredentialVault(key=CredentialVault.generate_key())
    mb_id = models.create_mailbox(domain_id, "user@trash.com", vault.encrypt("pass"))

    msg_id = "<trash-test@trash.com>"
    _seed_message(mb_id, 1, "INBOX", msg_id)
    _seed_message(mb_id, 2, "INBOX.Trash", msg_id)

    assert rescan_mailbox_duplicates(mb_id) == 0
    assert models.list_duplicates(mb_id) == []
