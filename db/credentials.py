"""Shared credential vault singleton."""

from db.vault import CredentialVault

_vault: CredentialVault | None = None


def get_vault() -> CredentialVault:
    global _vault
    if _vault is None:
        _vault = CredentialVault()
    return _vault
