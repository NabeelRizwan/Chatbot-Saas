"""Encrypted generation credentials shared by bots, with transactional capacity.

Bot.platform_credential_id is the only live assignment relationship. The legacy
reverse column is retained as historical data, never read or written here.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, or_, text, update
from sqlalchemy.orm import Session, joinedload

from database.connection import SessionLocal
from database.models import AuditLog, Bot, PlatformApiKey
from utils.encryption import decrypt_key, encrypt_key

SUPPORTED_PROVIDERS = {"gemini", "openai", "claude", "grok"}
DEFAULT_BOT_CAPACITY = 2
ASSIGNMENT_PREVIEW_LIMIT = 10


def lock_credential_lifecycle(db: Session) -> None:
    """Serialize all lifecycle writers until commit/rollback across replicas.

    Counts are read AFTER this lock under the application's READ COMMITTED
    isolation. No process-local lock or generation-time allocation is used.
    SQLite is only supported here for isolated unit tests.
    """
    if db.get_bind().dialect.name == "postgresql":
        with db.no_autoflush:
            db.execute(text("SELECT pg_advisory_xact_lock(73421, 1)"))


def record_admin_action(db: Session, actor_user_id: int | None, action: str,
                        target_type: str, target_id: int,
                        organization_id: int | None = None,
                        credential_id: int | None = None) -> None:
    suffix = f":credential:{credential_id}" if credential_id is not None else ""
    db.add(AuditLog(user_id=actor_user_id, organization_id=organization_id,
                    action=f"platform.{action}:{target_type}:{target_id}{suffix}"))


def assignment_count(db: Session, key_id: int) -> int:
    # All tenants, never customers. Even invalid legacy references are counted
    # conservatively for deletion/capacity safety; normal BYOK has no reference.
    return db.query(func.count(Bot.id)).filter(Bot.platform_credential_id == key_id).scalar()


def _count_expression(db: Session):
    return db.query(func.count(Bot.id)).filter(
        Bot.platform_credential_id == PlatformApiKey.id
    ).correlate(PlatformApiKey).scalar_subquery()


def _validate_capacity(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 2147483647:
        raise HTTPException(status_code=422, detail="Maximum bot assignments must be a whole number of at least 1 (up to 2147483647).")


def admin_add_key(db: Session, provider: str, plaintext_api_key: str,
                  label: Optional[str] = None, actor_user_id: int | None = None,
                  max_bot_assignments: int = DEFAULT_BOT_CAPACITY) -> PlatformApiKey:
    provider = provider.lower().strip()
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=422, detail="Choose a supported generation provider.")
    if not plaintext_api_key or not plaintext_api_key.strip():
        raise HTTPException(status_code=422, detail="API key cannot be empty.")
    _validate_capacity(max_bot_assignments)
    lock_credential_lifecycle(db)
    key = PlatformApiKey(provider=provider, encrypted_key=encrypt_key(plaintext_api_key),
                         label=label, status="available", max_bot_assignments=max_bot_assignments,
                         requests_count=0, tokens_used=0)
    db.add(key)
    db.flush()
    record_admin_action(db, actor_user_id, "credential.created", "credential", key.id)
    db.commit()
    db.refresh(key)
    return key


def admin_disable_key(db: Session, key_id: int, actor_user_id: int | None = None) -> PlatformApiKey:
    lock_credential_lifecycle(db)
    key = _get_or_404(db, key_id)
    key.status = "disabled"  # Preserve every reference; never redistribute.
    key.updated_at = datetime.utcnow()
    record_admin_action(db, actor_user_id, "credential.disabled", "credential", key.id)
    db.commit()
    db.refresh(key)
    return key


def admin_enable_key(db: Session, key_id: int, actor_user_id: int | None = None) -> PlatformApiKey:
    lock_credential_lifecycle(db)
    key = _get_or_404(db, key_id)
    key.status = "assigned" if assignment_count(db, key.id) else "available"
    key.updated_at = datetime.utcnow()
    record_admin_action(db, actor_user_id, "credential.enabled", "credential", key.id)
    db.commit()
    db.refresh(key)
    return key


def admin_delete_key(db: Session, key_id: int, actor_user_id: int | None = None) -> None:
    lock_credential_lifecycle(db)
    key = _get_or_404(db, key_id)
    count = assignment_count(db, key.id)
    if count:
        raise HTTPException(status_code=409, detail=f"Cannot delete: {count} bots still reference this credential. Reassign or unassign all of them first; disabling does not release assignments.")
    record_admin_action(db, actor_user_id, "credential.deleted", "credential", key.id)
    db.delete(key)
    db.commit()


def admin_update_key(db: Session, key_id: int, changes: dict,
                     actor_user_id: int | None = None) -> PlatformApiKey:
    lock_credential_lifecycle(db)
    key = _get_or_404(db, key_id)
    if "max_bot_assignments" in changes:
        capacity = changes["max_bot_assignments"]
        _validate_capacity(capacity)
        if changes.get("expected_max_bot_assignments") != key.max_bot_assignments:
            raise HTTPException(status_code=409, detail="Credential capacity changed. Reload before saving.")
        count = assignment_count(db, key.id)
        if capacity < count:
            raise HTTPException(status_code=409, detail=f"Cannot lower capacity below {count} currently assigned bots. Reassign or unassign bots first.")
        key.max_bot_assignments = capacity
        record_admin_action(db, actor_user_id, "credential.capacity_updated", "credential", key.id)
    if "label" in changes:
        key.label = changes["label"]
        record_admin_action(db, actor_user_id, "credential.label_updated", "credential", key.id)
    key.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(key)
    return key


def admin_update_label(db: Session, key_id: int, label: Optional[str], actor_user_id: int | None = None) -> PlatformApiKey:
    return admin_update_key(db, key_id, {"label": label}, actor_user_id)


def list_keys(db: Session, offset: int = 0, limit: int = 50,
              provider: str | None = None, search: str = "",
              assignable_to_bot_id: int | None = None) -> dict:
    query = db.query(PlatformApiKey)
    if provider:
        query = query.filter(PlatformApiKey.provider == provider)
    if search:
        query = query.filter(PlatformApiKey.label.ilike(f"%{search}%"))
    if assignable_to_bot_id is not None:
        current = db.query(Bot.platform_credential_id).filter(Bot.id == assignable_to_bot_id).scalar_subquery()
        query = query.filter(PlatformApiKey.status.in_(("available", "assigned")), or_(
            _count_expression(db) < PlatformApiKey.max_bot_assignments,
            PlatformApiKey.id == current,
        ))
    total = query.count()
    rows = query.order_by(PlatformApiKey.created_at.desc(), PlatformApiKey.id.desc()).offset(offset).limit(limit).all()
    return {"items": [serialize_key(k, db) for k in rows], "total": total, "offset": offset, "limit": limit}


def serialize_key(k: PlatformApiKey, db: Session | None = None) -> dict:
    """Allowlisted admin metadata; previews are bounded, counts are exact."""
    db = db or Session.object_session(k)
    count = assignment_count(db, k.id)
    bots = db.query(Bot).filter(Bot.platform_credential_id == k.id).options(
        joinedload(Bot.organization), joinedload(Bot.customer)
    ).order_by(Bot.id).limit(ASSIGNMENT_PREVIEW_LIMIT).all()
    return {
        "id": k.id, "credential_profile_id": k.id, "provider": k.provider,
        "label": k.label, "status": k.status,
        "assigned_bot_count": count, "max_bot_assignments": k.max_bot_assignments,
        "remaining_capacity": max(0, k.max_bot_assignments - count),
        "assigned_bots": [{"id": b.id, "name": b.name, "provider": b.provider,
                           "model_name": b.model_name, "organization_id": b.organization_id,
                           "organization_name": b.organization.name if b.organization else None,
                           "customer_name": b.customer.name if b.customer else None} for b in bots],
        "assigned_bots_limit": ASSIGNMENT_PREVIEW_LIMIT,
        "requests_count": k.requests_count, "tokens_used": k.tokens_used,
        "last_used_at": k.last_used_at, "created_at": k.created_at, "updated_at": k.updated_at,
    }


def allocate_key_to_bot(db: Session, bot: Bot, actor_user_id: int | None = None) -> bool:
    """Oldest enabled matching profile with a slot; caller owns transaction.

    Exhaustion leaves unassigned. A disabled existing assignment is preserved
    and is NEVER automatically redistributed. Allocation is by bot, not customer.
    """
    lock_credential_lifecycle(db)
    if bot.provider_api_key:
        release_key_from_bot(db, bot.id, actor_user_id)
        return False
    if bot.platform_credential_id:
        existing = _get_or_404(db, bot.platform_credential_id)
        if existing.provider == bot.provider:
            return existing.status in {"available", "assigned"}
        release_key_from_bot(db, bot.id, actor_user_id)
    key = db.query(PlatformApiKey).filter(
        PlatformApiKey.provider == bot.provider,
        PlatformApiKey.status.in_(("available", "assigned")),
        _count_expression(db) < PlatformApiKey.max_bot_assignments,
    ).order_by(PlatformApiKey.created_at, PlatformApiKey.id).populate_existing().with_for_update().first()
    if not key:
        return False
    bot.platform_credential_id = key.id
    key.status = "assigned"
    key.updated_at = datetime.utcnow()
    record_admin_action(db, actor_user_id, "credential.auto_assigned", "bot", bot.id, bot.organization_id, key.id)
    db.flush()
    return True


def assign_key_to_bot(db: Session, key_id: int, bot: Bot, actor_user_id: int | None = None) -> None:
    lock_credential_lifecycle(db)
    key = _get_or_404(db, key_id)
    if bot.provider_api_key:
        raise HTTPException(status_code=409, detail="Switch the bot from BYOK to platform mode before assignment.")
    if key.status not in {"available", "assigned"}:
        raise HTTPException(status_code=409, detail="Disabled credential profiles cannot be assigned.")
    if key.provider != bot.provider:
        raise HTTPException(status_code=400, detail="Credential profile provider does not match the bot provider.")
    if bot.platform_credential_id == key.id:
        return  # Keeping this bot's slot is allowed even at full capacity.
    if assignment_count(db, key.id) >= key.max_bot_assignments:
        raise HTTPException(status_code=409, detail="Credential capacity is full. Choose another profile or increase its maximum bot assignments.")
    release_key_from_bot(db, bot.id, actor_user_id)
    bot.platform_credential_id = key.id
    key.status = "assigned"
    key.updated_at = datetime.utcnow()
    record_admin_action(db, actor_user_id, "credential.assigned", "bot", bot.id, bot.organization_id, key.id)
    db.flush()


def release_key_from_bot(db: Session, bot_id: int, actor_user_id: int | None = None) -> None:
    lock_credential_lifecycle(db)
    bot = db.query(Bot).filter(Bot.id == bot_id).first()
    if not bot or not bot.platform_credential_id:
        return
    key = _get_or_404(db, bot.platform_credential_id)
    bot.platform_credential_id = None
    db.flush()
    if key.status != "disabled":
        key.status = "assigned" if assignment_count(db, key.id) else "available"
    key.updated_at = datetime.utcnow()
    record_admin_action(db, actor_user_id, "credential.unassigned", "bot", bot.id, bot.organization_id, key.id)
    db.flush()


def get_decrypted_key_for_bot(db: Session, bot_id: int, *, expected_provider: str | None = None) -> Optional[str]:
    query = db.query(PlatformApiKey).join(Bot, Bot.platform_credential_id == PlatformApiKey.id).filter(
        Bot.id == bot_id, Bot.provider_api_key.is_(None),
        Bot.provider == PlatformApiKey.provider,
        PlatformApiKey.status.in_(("available", "assigned")),
    )
    # A request may hold an older Bot snapshot while an admin changes provider.
    # Never hand a newly assigned provider's secret to that older adapter.
    if expected_provider is not None:
        query = query.filter(PlatformApiKey.provider == expected_provider)
    key = query.first()
    return decrypt_key(key.encrypted_key) if key else None


def increment_usage(db: Optional[Session], bot_id: int, tokens: int = 0) -> None:
    """Additional best-effort profile aggregate; tenant/request ledgers unchanged."""
    if db is None:
        with SessionLocal() as own_db:
            _do_increment(own_db, bot_id, tokens)
    else:
        _do_increment(db, bot_id, tokens)


def _do_increment(db: Session, bot_id: int, tokens: int) -> None:
    profile = db.query(Bot.platform_credential_id).filter(
        Bot.id == bot_id, Bot.provider_api_key.is_(None)
    ).scalar_subquery()
    db.execute(update(PlatformApiKey).where(PlatformApiKey.id == profile).values(
        requests_count=PlatformApiKey.requests_count + 1,
        tokens_used=PlatformApiKey.tokens_used + max(0, tokens),
        last_used_at=datetime.utcnow(), updated_at=datetime.utcnow(),
    ).execution_options(synchronize_session=False))
    db.commit()


def _get_or_404(db: Session, key_id: int) -> PlatformApiKey:
    key = db.query(PlatformApiKey).filter(PlatformApiKey.id == key_id).populate_existing().with_for_update().first()
    if not key:
        raise HTTPException(status_code=404, detail="Platform API key not found.")
    return key
