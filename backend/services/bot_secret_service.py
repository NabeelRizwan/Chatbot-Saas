import os

from database.models import Bot
from utils.encryption import EncryptionError, decrypt_key, encrypt_key, mask_key


BYOK_PREFIX = "fernet:v1:"


def is_encrypted_bot_key(value: str | None) -> bool:
    return bool(value and value.startswith(BYOK_PREFIX))


def encrypt_bot_provider_key(plaintext: str) -> str:
    encrypted = encrypt_key(plaintext).decode("ascii")
    return f"{BYOK_PREFIX}{encrypted}"


def _legacy_plaintext_allowed() -> bool:
    configured = os.getenv("ALLOW_LEGACY_PLAINTEXT_BYOK")
    if configured is not None:
        return configured.lower() in {"1", "true", "yes"}
    return os.getenv("APP_ENV", "development").lower() not in {"production", "prod"}


def decrypt_bot_provider_key(
    stored_value: str | None,
    *,
    allow_legacy: bool | None = None,
) -> str | None:
    if not stored_value:
        return None
    if is_encrypted_bot_key(stored_value):
        cipher = stored_value[len(BYOK_PREFIX):].encode("ascii")
        return decrypt_key(cipher)
    legacy_allowed = _legacy_plaintext_allowed() if allow_legacy is None else allow_legacy
    if legacy_allowed:
        return stored_value
    raise EncryptionError(
        "A legacy plaintext bot credential requires the controlled BYOK migration before use."
    )


def mask_bot_provider_key(stored_value: str | None) -> str | None:
    if not stored_value:
        return None
    if is_encrypted_bot_key(stored_value):
        try:
            return mask_key(decrypt_bot_provider_key(stored_value))
        except EncryptionError:
            return "****ENCRYPTED****"
    return mask_key(stored_value)


def migrate_legacy_bot_keys(db) -> dict[str, int]:
    migrated = 0
    already_encrypted = 0
    bots = db.query(Bot).filter(Bot.provider_api_key.is_not(None)).all()
    for bot in bots:
        value = bot.provider_api_key
        if not value:
            continue
        if is_encrypted_bot_key(value):
            already_encrypted += 1
            continue
        bot.provider_api_key = encrypt_bot_provider_key(value)
        migrated += 1
    db.commit()
    return {"migrated": migrated, "already_encrypted": already_encrypted}
