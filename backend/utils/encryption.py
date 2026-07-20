"""
Fernet-based symmetric encryption for platform API keys stored at rest.

Environment variable required:
    PLATFORM_KEY_ENCRYPTION_KEY  — a 32-byte URL-safe base64-encoded key.

Generate once and store securely:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from __future__ import annotations

import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken


class EncryptionError(Exception):
    """Raised when encryption/decryption fails."""


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    """Load the Fernet instance once, cached for the process lifetime."""
    raw_key = os.getenv("PLATFORM_KEY_ENCRYPTION_KEY", "")
    if not raw_key:
        raise EncryptionError(
            "PLATFORM_KEY_ENCRYPTION_KEY environment variable is not set. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        return Fernet(raw_key.encode())
    except Exception as exc:
        raise EncryptionError(f"Invalid PLATFORM_KEY_ENCRYPTION_KEY: {exc}") from exc


def encrypt_key(plaintext: str) -> bytes:
    """Encrypt a plaintext API key and return cipher bytes for DB storage."""
    if not plaintext or not plaintext.strip():
        raise EncryptionError("Cannot encrypt an empty key.")
    return _get_fernet().encrypt(plaintext.strip().encode("utf-8"))


def decrypt_key(cipher_bytes: bytes) -> str:
    """Decrypt cipher bytes from DB and return plaintext API key."""
    if not cipher_bytes:
        raise EncryptionError("Cannot decrypt empty cipher bytes.")
    try:
        return _get_fernet().decrypt(cipher_bytes).decode("utf-8")
    except InvalidToken as exc:
        raise EncryptionError(
            "Failed to decrypt platform API key — key may be corrupted or the encryption key has changed."
        ) from exc


def mask_key(plaintext: str | None) -> str | None:
    """Return a masked representation for display: AIza****abcd (never expose full value)."""
    if not plaintext:
        return None
    if len(plaintext) <= 8:
        return "****"
    prefix = plaintext[:4]
    suffix = plaintext[-4:]
    return f"{prefix}{'*' * 8}{suffix}"
