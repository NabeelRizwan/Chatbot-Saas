"""Platform administration using the normal authenticated user and key pool."""
from datetime import datetime
from typing import Generic, Literal, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import func, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from database.connection import get_db
from database.models import Bot, Customer, Organization, PlatformApiKey, User
from services.auth_service import get_current_user
from services import platform_key_service as keys
from services.bot_service import SUPPORTED_MODELS, update_platform_generation_config
from services.tenant_cache_service import invalidate_bot_cache
from utils.encryption import EncryptionError


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Organization roles, cached browser flags and widget tokens grant nothing."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Platform administrator privileges required.")
    return current_user


class SafeAdminRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request: Request):
            try:
                return await handler(request)
            except RequestValidationError as exc:
                # FastAPI normally echoes invalid input; never return secrets.
                return JSONResponse(status_code=422, content={"detail": [
                    {"loc": error["loc"], "msg": "Invalid value; check the field's supported format.", "type": error["type"]}
                    for error in exc.errors()
                ]})
            except (SQLAlchemyError, EncryptionError):
                return JSONResponse(status_code=503, content={
                    "detail": "Credential operation unavailable. Check database and encryption configuration; retry after recovery."
                })
        return safe_handler


router = APIRouter(route_class=SafeAdminRoute, dependencies=[Depends(require_admin)])


class AdminInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class PlatformKeyAddRequest(AdminInput):
    provider: str = Field(min_length=1, max_length=30)
    api_key: SecretStr = Field(min_length=8, max_length=8192)
    label: str = Field(min_length=1, max_length=200)


class PlatformKeyUpdateRequest(AdminInput):
    label: str | None = Field(default=None, max_length=200)


class AssignmentBot(BaseModel):
    id: int
    name: str
    provider: str


class PlatformKeyResponse(BaseModel):
    id: int
    credential_profile_id: int
    provider: str
    label: str | None
    status: Literal["available", "assigned", "disabled"]
    allocated_to_bot_id: int | None
    bot: AssignmentBot | None
    assigned_bot_count: int
    requests_count: int
    tokens_used: int
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    offset: int
    limit: int


class OrganizationResponse(BaseModel):
    id: int
    name: str
    bot_count: int
    created_at: datetime


class AdminBotResponse(BaseModel):
    id: int
    name: str
    organization_id: int
    organization_name: str
    customer_name: str | None
    status: str
    provider: str
    model_name: str
    usage_mode: Literal["byo", "platform"]
    credential_profile_id: int | None
    credential_label: str | None
    credential_status: str | None


class ConfigSnapshot(AdminInput):
    provider: str
    model_name: str
    credential_profile_id: int | None


class ProviderConfigRequest(ConfigSnapshot):
    expected: ConfigSnapshot


def _bot_metadata(bot: Bot) -> dict:
    profile = bot.platform_credential or bot.platform_api_key
    return {
        "id": bot.id, "name": bot.name, "organization_id": bot.organization_id,
        "organization_name": bot.organization.name,
        "customer_name": bot.customer.name if bot.customer else None,
        "status": bot.status, "provider": bot.provider, "model_name": bot.model_name,
        "usage_mode": "byo" if bot.provider_api_key else "platform",
        "credential_profile_id": profile.id if profile else None,
        "credential_label": profile.label if profile else None,
        "credential_status": profile.status if profile else None,
    }


def _locked_bot(db: Session, bot_id: int) -> Bot:
    keys.lock_credential_lifecycle(db)
    bot = db.query(Bot).filter(Bot.id == bot_id).populate_existing().with_for_update().first()
    if not bot or bot.organization_id is None:
        raise HTTPException(status_code=404, detail="Tenant-owned bot not found.")
    return bot


@router.get("/session")
def admin_session(user: User = Depends(require_admin)):
    return {"user_id": user.id, "is_admin": True}


@router.get("/provider-options")
def provider_options():
    return {"providers": [{"id": provider, "models": sorted(models)}
                          for provider, models in SUPPORTED_MODELS.items()],
            "allocation_mode": "one_bot_per_profile"}


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    return {
        "organizations": db.query(func.count(Organization.id)).scalar(),
        "bots": db.query(func.count(Bot.id)).filter(Bot.organization_id.isnot(None)).scalar(),
        "enabled_credentials": db.query(func.count(PlatformApiKey.id)).filter(PlatformApiKey.status != "disabled").scalar(),
    }


@router.get("/organizations", response_model=Page[OrganizationResponse])
def organizations(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                  search: str = Query("", max_length=200), db: Session = Depends(get_db)):
    query = db.query(Organization).filter(Organization.name.ilike(f"%{search}%"))
    total = query.count()
    bot_count = db.query(func.count(Bot.id)).filter(Bot.organization_id == Organization.id).correlate(Organization).scalar_subquery()
    rows = query.add_columns(bot_count).order_by(Organization.id).offset(offset).limit(limit).all()
    return {"items": [{"id": org.id, "name": org.name, "created_at": org.created_at, "bot_count": count}
                      for org, count in rows], "total": total, "offset": offset, "limit": limit}


@router.get("/bots", response_model=Page[AdminBotResponse])
def bots(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
         search: str = Query("", max_length=200), organization_id: int | None = Query(None, ge=1),
         db: Session = Depends(get_db)):
    query = db.query(Bot).join(Organization).outerjoin(Customer, Customer.id == Bot.customer_id)
    if organization_id is not None:
        query = query.filter(Bot.organization_id == organization_id)
    if search:
        query = query.filter(or_(Bot.name.ilike(f"%{search}%"), Organization.name.ilike(f"%{search}%"), Customer.name.ilike(f"%{search}%")))
    total = query.count()
    rows = query.options(joinedload(Bot.organization), joinedload(Bot.customer),
                         joinedload(Bot.platform_credential), joinedload(Bot.platform_api_key)).order_by(Bot.id).offset(offset).limit(limit).all()
    return {"items": [_bot_metadata(bot) for bot in rows], "total": total, "offset": offset, "limit": limit}


@router.patch("/bots/{bot_id}/provider-config", response_model=AdminBotResponse)
def update_provider_config(bot_id: int, data: ProviderConfigRequest,
                           user: User = Depends(require_admin), db: Session = Depends(get_db)):
    bot = _locked_bot(db, bot_id)
    actual = _bot_metadata(bot)
    if any(actual[field] != value for field, value in data.expected.model_dump().items()):
        raise HTTPException(status_code=409, detail="Bot configuration changed. Reload the bot list before saving.")
    try:
        update_platform_generation_config(db, bot, data.provider, data.model_name, data.credential_profile_id)
        keys.record_admin_action(db, user.id, "bot.provider_config_updated", "bot", bot.id, bot.organization_id)
        keys.record_admin_action(db, user.id, "credential.assigned" if data.credential_profile_id else "credential.unassigned",
                                 "bot", bot.id, bot.organization_id, data.credential_profile_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(bot)
    invalidate_bot_cache(bot.id, bot.organization_id)
    return _bot_metadata(bot)


@router.get("/platform-keys", response_model=Page[PlatformKeyResponse])
def list_platform_keys(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                       provider: str | None = Query(None, max_length=30), search: str = Query("", max_length=200),
                       assignable_to_bot_id: int | None = Query(None, ge=1), db: Session = Depends(get_db)):
    return keys.list_keys(db, offset, limit, provider, search, assignable_to_bot_id)


@router.get("/platform-keys/pool-status")
def pool_status(db: Session = Depends(get_db)):
    summary = {}
    for provider, status, count in db.query(PlatformApiKey.provider, PlatformApiKey.status, func.count(PlatformApiKey.id)).group_by(PlatformApiKey.provider, PlatformApiKey.status):
        counts = summary.setdefault(provider, {"available": 0, "assigned": 0, "disabled": 0, "total": 0})
        counts[status] = count
        counts["total"] += count
    return {"providers": summary}


@router.post("/platform-keys", status_code=201, response_model=PlatformKeyResponse)
def add_platform_key(data: PlatformKeyAddRequest, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if data.provider not in SUPPORTED_MODELS:
        raise HTTPException(status_code=422, detail="Choose a supported generation provider.")
    if not data.label.strip():
        raise HTTPException(status_code=422, detail="Enter a credential label.")
    key = keys.admin_add_key(db, data.provider, data.api_key.get_secret_value(), data.label.strip(), user.id)
    return keys.serialize_key(key)


@router.put("/platform-keys/{key_id}", response_model=PlatformKeyResponse)
def update_platform_key(key_id: int, data: PlatformKeyUpdateRequest,
                        user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return keys.serialize_key(keys.admin_update_label(db, key_id, data.label, user.id))


@router.post("/platform-keys/{key_id}/enable", response_model=PlatformKeyResponse)
def enable_platform_key(key_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return keys.serialize_key(keys.admin_enable_key(db, key_id, user.id))


@router.post("/platform-keys/{key_id}/disable", response_model=PlatformKeyResponse)
def disable_platform_key(key_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    # Preserve release + same-provider env fallback; never reallocate a profile.
    return keys.serialize_key(keys.admin_disable_key(db, key_id, user.id))


@router.post("/platform-keys/{key_id}/assign/{bot_id}", response_model=PlatformKeyResponse)
def assign_platform_key(key_id: int, bot_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    bot = _locked_bot(db, bot_id)
    if bot.provider_api_key:
        raise HTTPException(status_code=409, detail="Switch the bot from BYOK to platform mode before assignment.")
    keys.assign_key_to_bot(db, key_id, bot)
    keys.record_admin_action(db, user.id, "credential.assigned", "bot", bot.id, bot.organization_id, key_id)
    db.commit()
    return keys.serialize_key(db.get(PlatformApiKey, key_id), {"id": bot.id, "name": bot.name, "provider": bot.provider})


@router.delete("/platform-keys/{key_id}")
def delete_platform_key(key_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    keys.admin_delete_key(db, key_id, user.id)
    return {"success": True}
