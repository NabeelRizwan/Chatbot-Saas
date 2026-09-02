"""
Admin Routes — Platform API Key Pool Management
================================================
Endpoints:
  GET    /admin/platform-keys          — list all keys (masked)
  POST   /admin/platform-keys          — add a new provider key
  PUT    /admin/platform-keys/{id}     — update label
  POST   /admin/platform-keys/{id}/enable   — re-enable a disabled key
  POST   /admin/platform-keys/{id}/disable  — disable a key (releases bot)
  DELETE /admin/platform-keys/{id}          — delete (only if unassigned)
  GET    /admin/platform-keys/pool-status   — summary counts per provider
  POST   /admin/platform-keys/{id}/assign/{bot_id} — assign a profile to a bot
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import Bot, PlatformApiKey, User
from services.auth_service import get_current_user
from services import platform_key_service

router = APIRouter()


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not getattr(current_user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform administrator privileges required to access this endpoint",
        )
    return current_user


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response schemas
# ─────────────────────────────────────────────────────────────────────────────

class PlatformKeyAddRequest(BaseModel):
    provider: str = Field(..., min_length=1, description="Provider: gemini | openai | claude | grok")
    api_key: str = Field(..., min_length=8, description="Plaintext provider API key (encrypted before storage)")
    label: Optional[str] = Field(default=None, max_length=200, description="Optional human-readable label")


class PlatformKeyUpdateRequest(BaseModel):
    label: Optional[str] = Field(default=None, max_length=200)


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/platform-keys", summary="List all platform API keys")
def list_platform_keys(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Returns all platform API keys with:
    - Masked key value (never full plaintext)
    - Status (available | assigned | disabled)
    - Assigned bot details
    - Usage metrics (requests, tokens, last used)
    """
    return platform_key_service.list_keys(db)


@router.get("/platform-keys/pool-status", summary="Pool availability summary")
def pool_status(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Returns a per-provider summary of key availability.
    Useful for the admin dashboard capacity overview.
    """
    keys = db.query(PlatformApiKey).all()
    summary: dict[str, dict] = {}
    for k in keys:
        if k.provider not in summary:
            summary[k.provider] = {"available": 0, "assigned": 0, "disabled": 0, "total": 0}
        summary[k.provider][k.status] = summary[k.provider].get(k.status, 0) + 1
        summary[k.provider]["total"] += 1
    return {"providers": summary}


@router.post("/platform-keys", status_code=status.HTTP_201_CREATED, summary="Add provider API key")
def add_platform_key(
    data: PlatformKeyAddRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Admin adds a plaintext provider API key.
    The key is encrypted with Fernet before being stored.
    The plaintext key is NEVER persisted.
    """
    key = platform_key_service.admin_add_key(
        db,
        provider=data.provider,
        plaintext_api_key=data.api_key,
        label=data.label,
    )
    return platform_key_service.serialize_key(key)


@router.put("/platform-keys/{key_id}", summary="Update platform key label")
def update_platform_key(
    key_id: int,
    data: PlatformKeyUpdateRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Update the human-readable label of a platform key."""
    key = platform_key_service.admin_update_label(db, key_id, data.label)
    return platform_key_service.serialize_key(key)


@router.post("/platform-keys/{key_id}/enable", summary="Enable a disabled platform key")
def enable_platform_key(
    key_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Re-enable a disabled platform key. Status becomes 'available'."""
    key = platform_key_service.admin_enable_key(db, key_id)
    return platform_key_service.serialize_key(key)


@router.post("/platform-keys/{key_id}/disable", summary="Disable a platform key")
def disable_platform_key(
    key_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Disable a platform key. If assigned, releases the bot back to no-key state.
    The bot will fail requests until the admin assigns a new key or the user
    switches to a custom key.
    """
    key = platform_key_service.admin_disable_key(db, key_id)
    return platform_key_service.serialize_key(key)


@router.post("/platform-keys/{key_id}/assign/{bot_id}", summary="Assign a credential profile to a bot")
def assign_platform_key(
    key_id: int,
    bot_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    bot = db.query(Bot).filter(Bot.id == bot_id).first()
    if not bot or bot.organization_id is None:
        raise HTTPException(status_code=404, detail="Tenant-owned bot not found.")
    if bot.provider_api_key:
        raise HTTPException(status_code=409, detail="Switch the bot from BYOK to platform mode before assignment.")
    platform_key_service.assign_key_to_bot(db, key_id, bot)
    db.commit()
    key = db.query(PlatformApiKey).filter(PlatformApiKey.id == key_id).first()
    return platform_key_service.serialize_key(
        key,
        {"id": bot.id, "name": bot.name, "provider": bot.provider},
    )


@router.delete("/platform-keys/{key_id}", summary="Delete a platform key")
def delete_platform_key(
    key_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Permanently delete a platform key.
    Raises 400 if the key is currently assigned to a bot.
    """
    platform_key_service.admin_delete_key(db, key_id)
    return {"success": True, "message": "Platform API key deleted successfully."}
