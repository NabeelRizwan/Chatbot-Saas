"""
Platform API Key Service
========================
Manages the lifecycle of admin-uploaded, encrypted provider API keys
allocated 1:1 to individual bots.

Rules enforced here:
- Admin uploads plaintext key → encrypted before DB write.
- Key is NEVER stored in plaintext.
- One key → one bot (enforced by UNIQUE constraint + service checks).
- Key is released when bot is deleted or switches to BYOK.
- Usage metrics updated by LLM router after every successful call.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from database.models import Bot, PlatformApiKey
from utils.encryption import decrypt_key, encrypt_key, mask_key

SUPPORTED_PROVIDERS = {"gemini", "openai", "claude", "grok"}


# ─────────────────────────────────────────────────────────────────────────────
# Admin operations
# ─────────────────────────────────────────────────────────────────────────────

def admin_add_key(
    db: Session,
    provider: str,
    plaintext_api_key: str,
    label: Optional[str] = None,
) -> PlatformApiKey:
    """Admin adds a provider key. Encrypts it before storing."""
    provider = provider.lower().strip()
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported provider '{provider}'. Supported: {', '.join(sorted(SUPPORTED_PROVIDERS))}.",
        )
    if not plaintext_api_key or not plaintext_api_key.strip():
        raise HTTPException(status_code=422, detail="API key cannot be empty.")

    encrypted = encrypt_key(plaintext_api_key)
    key_record = PlatformApiKey(
        provider=provider,
        encrypted_key=encrypted,
        label=label,
        status="available",
        allocated_to_bot_id=None,
        requests_count=0,
        tokens_used=0,
    )
    db.add(key_record)
    db.commit()
    db.refresh(key_record)
    return key_record


def admin_disable_key(db: Session, key_id: int) -> PlatformApiKey:
    """Disable a key. If assigned, releases the bot first."""
    key = _get_or_404(db, key_id)
    if key.status == "assigned" or db.query(Bot.id).filter(Bot.platform_credential_id == key.id).first():
        _do_release(key, db)
    key.status = "disabled"
    key.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(key)
    return key


def admin_enable_key(db: Session, key_id: int) -> PlatformApiKey:
    """Re-enable a previously disabled key (sets it to available)."""
    key = _get_or_404(db, key_id)
    if key.status == "assigned":
        raise HTTPException(status_code=400, detail="Key is already assigned.")
    key.status = "available"
    key.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(key)
    return key


def admin_delete_key(db: Session, key_id: int) -> None:
    """Delete a key. Raises if currently assigned to a bot."""
    key = _get_or_404(db, key_id)
    referenced = db.query(Bot.id).filter(Bot.platform_credential_id == key.id).first()
    if key.status == "assigned" or referenced:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete a key that is currently assigned to a bot. "
                   "Delete the bot or switch it to a custom key first.",
        )
    db.delete(key)
    db.commit()


def admin_update_label(db: Session, key_id: int, label: Optional[str]) -> PlatformApiKey:
    """Update the human-readable label of a key."""
    key = _get_or_404(db, key_id)
    key.label = label
    key.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(key)
    return key


def list_keys(db: Session) -> list[dict]:
    """Return all platform keys with masked values and assignment metadata."""
    keys = db.query(PlatformApiKey).order_by(PlatformApiKey.created_at.desc()).all()
    result = []
    for k in keys:
        bot_info = None
        if k.allocated_to_bot_id:
            bot = db.query(Bot).filter(Bot.id == k.allocated_to_bot_id).first()
            if bot:
                bot_info = {"id": bot.id, "name": bot.name, "provider": bot.provider}
        result.append(serialize_key(k, bot_info))
    return result


def serialize_key(k: PlatformApiKey, bot_info: Optional[dict] = None) -> dict:
    """Serialize a key for API response. Masked key, never plaintext."""
    masked = None
    try:
        plaintext = decrypt_key(k.encrypted_key)
        masked = mask_key(plaintext)
    except Exception:
        masked = "****ENCRYPTED****"

    return {
        "id": k.id,
        "credential_profile_id": k.id,
        "provider": k.provider,
        "masked_key": masked,
        "label": k.label,
        "status": k.status,
        "allocated_to_bot_id": k.allocated_to_bot_id,
        "bot": bot_info,
        "requests_count": k.requests_count,
        "tokens_used": k.tokens_used,
        "last_used_at": k.last_used_at,
        "created_at": k.created_at,
        "updated_at": k.updated_at,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Allocation lifecycle (called by bot_service)
# ─────────────────────────────────────────────────────────────────────────────

def allocate_key_to_bot(db: Session, bot: Bot) -> None:
    """
    Transactionally allocate an available platform key to a bot.

    - Uses SELECT FOR UPDATE to prevent race conditions.
    - Raises HTTP 400 with user-friendly message if no key is available.
    - Safe to call multiple times; skips re-allocation if provider unchanged.
    """
    # Check if bot already has a correctly-provisioned platform key
    existing = (
        db.query(PlatformApiKey)
        .filter(
            or_(
                PlatformApiKey.allocated_to_bot_id == bot.id,
                PlatformApiKey.id == bot.platform_credential_id,
            )
        )
        .first()
    )
    if existing:
        if existing.provider == bot.provider and existing.status == "assigned":
            bot.platform_credential_id = existing.id
            existing.allocated_to_bot_id = bot.id
            return  # Already correctly allocated — nothing to do
        # Provider changed: release old key first
        _do_release(existing, db)
        db.flush()

    # Lock a row transactionally to prevent double-allocation under concurrent requests
    key = (
        db.query(PlatformApiKey)
        .filter(
            PlatformApiKey.provider == bot.provider,
            PlatformApiKey.status == "available",
            PlatformApiKey.allocated_to_bot_id.is_(None),
        )
        .with_for_update(skip_locked=True)
        .first()
    )

    if not key:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No platform-managed API keys are currently available for {bot.provider.upper()}. "
                "Please use a custom API key or contact the administrator to add more platform keys."
            ),
        )

    key.allocated_to_bot_id = bot.id
    key.status = "assigned"
    key.updated_at = datetime.utcnow()
    bot.platform_credential_id = key.id
    db.add(bot)
    db.add(key)
    db.flush()


def assign_key_to_bot(db: Session, key_id: int, bot: Bot) -> None:
    """Assign a specific non-secret credential profile to a bot."""
    key = _get_or_404(db, key_id)
    if key.status == "disabled":
        raise HTTPException(status_code=400, detail="Disabled credential profiles cannot be assigned.")
    if key.provider != (bot.provider or "").lower().strip():
        raise HTTPException(status_code=400, detail="Credential profile provider does not match the bot provider.")
    if key.allocated_to_bot_id not in {None, bot.id}:
        raise HTTPException(status_code=409, detail="Credential profile is already assigned to another bot.")
    release_key_from_bot(db, bot.id)
    key.allocated_to_bot_id = bot.id
    key.status = "assigned"
    key.updated_at = datetime.utcnow()
    bot.platform_credential_id = key.id
    db.add_all([key, bot])
    db.flush()


def release_key_from_bot(db: Session, bot_id: int) -> None:
    """
    Release the platform key assigned to a bot.
    Called on bot deletion, provider change, or switch to BYOK.
    """
    key = (
        db.query(PlatformApiKey)
        .filter(
            or_(
                PlatformApiKey.allocated_to_bot_id == bot_id,
                PlatformApiKey.id == db.query(Bot.platform_credential_id).filter(Bot.id == bot_id).scalar_subquery(),
            )
        )
        .first()
    )
    if key:
        _do_release(key, db)
        db.flush()
    else:
        bot = db.query(Bot).filter(Bot.id == bot_id).first()
        if bot:
            bot.platform_credential_id = None
            db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# LLM Router helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_decrypted_key_for_bot(db: Session, bot_id: int) -> Optional[str]:
    """
    Return the decrypted plaintext API key assigned to a bot.
    Returns None if no platform key is assigned.
    """
    bot = db.query(Bot).filter(Bot.id == bot_id).first()
    if not bot:
        return None
    key = None
    if bot.platform_credential_id:
        key = db.query(PlatformApiKey).filter(
            PlatformApiKey.id == bot.platform_credential_id,
            PlatformApiKey.provider == bot.provider,
            PlatformApiKey.status == "assigned",
            PlatformApiKey.allocated_to_bot_id == bot.id,
        ).first()
    if not key:
        key = db.query(PlatformApiKey).filter(
            PlatformApiKey.allocated_to_bot_id == bot_id,
            PlatformApiKey.provider == bot.provider,
            PlatformApiKey.status == "assigned",
        ).first()
    if not key:
        return None
    return decrypt_key(key.encrypted_key)


def increment_usage(
    db: Optional[Session],
    bot_id: int,
    tokens: int = 0,
) -> None:
    """
    Increment requests_count, tokens_used, and last_used_at for the platform
    key assigned to a bot. Called by the LLM router after each successful call.
    No-op if the bot uses a custom key (no platform key assigned).
    
    If db is None, opens its own session (useful for background/async callers).
    """
    if db is None:
        with SessionLocal() as own_db:
            _do_increment(own_db, bot_id, tokens)
    else:
        _do_increment(db, bot_id, tokens)


def _do_increment(db: Session, bot_id: int, tokens: int) -> None:
    key = (
        db.query(PlatformApiKey)
        .filter(PlatformApiKey.allocated_to_bot_id == bot_id)
        .first()
    )
    if not key:
        return
    key.requests_count = (key.requests_count or 0) + 1
    key.tokens_used = (key.tokens_used or 0) + tokens
    key.last_used_at = datetime.utcnow()
    key.updated_at = datetime.utcnow()
    db.add(key)
    db.commit()



# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_or_404(db: Session, key_id: int) -> PlatformApiKey:
    key = db.query(PlatformApiKey).filter(PlatformApiKey.id == key_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="Platform API key not found.")
    return key


def _do_release(key: PlatformApiKey, db: Session | None = None) -> None:
    """Reset key allocation fields. Caller must flush/commit."""
    bot_id = key.allocated_to_bot_id
    if db is not None:
        bot = None
        if bot_id:
            bot = db.query(Bot).filter(Bot.id == bot_id).first()
        if not bot:
            bot = db.query(Bot).filter(Bot.platform_credential_id == key.id).first()
        if bot and bot.platform_credential_id == key.id:
            bot.platform_credential_id = None
    key.allocated_to_bot_id = None
    key.status = "available"
    key.updated_at = datetime.utcnow()
