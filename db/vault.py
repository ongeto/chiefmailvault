"""AES-256 credential vault using Fernet encryption."""

import base64

from cryptography.fernet import Fernet, InvalidToken

from config import VAULT_KEY


class CredentialVault:
    """Encrypt and decrypt credentials at rest."""

    def __init__(self, key: str | None = None) -> None:
        raw = key or VAULT_KEY
        if raw:
            self._fernet = Fernet(raw.encode() if isinstance(raw, str) else raw)
        else:
            generated = Fernet.generate_key()
            self._fernet = Fernet(generated)
            print(
                "[ChiefMailVault] Generated CMV_VAULT_KEY — add to .env:\n"
                f"CMV_VAULT_KEY={generated.decode()}"
            )

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        try:
            return self._fernet.decrypt(ciphertext).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Failed to decrypt credential") from exc

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode()

    @staticmethod
    def mask(value: str | None) -> str:
        if not value:
            return "********"
        return "********"
