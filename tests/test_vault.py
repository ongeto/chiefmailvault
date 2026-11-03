"""Credential vault tests."""

from db.vault import CredentialVault


def test_encrypt_decrypt_roundtrip():
    key = CredentialVault.generate_key()
    vault = CredentialVault(key=key)
    plaintext = "super-secret-mailbox-password"
    encrypted = vault.encrypt(plaintext)
    assert encrypted != plaintext.encode()
    decrypted = vault.decrypt(encrypted)
    assert decrypted == plaintext


def test_mask_credentials():
    assert CredentialVault.mask("anything") == "********"
    assert CredentialVault.mask(None) == "********"


def test_encrypted_not_plaintext_in_db():
    from db import models
    from db.vault import CredentialVault

    key = CredentialVault.generate_key()
    vault = CredentialVault(key=key)
    domain_id = models.create_domain("test.com", "imap.test.com")
    password = "my-imap-password"
    encrypted = vault.encrypt(password)
    models.create_mailbox(domain_id, "info@test.com", encrypted)

    from db.database import get_db
    with get_db() as conn:
        row = conn.execute("SELECT encrypted_password FROM mailboxes").fetchone()
        stored = row["encrypted_password"]
        assert stored != password.encode()
        assert password not in str(stored)
