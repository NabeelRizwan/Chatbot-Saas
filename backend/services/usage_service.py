from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import Bot, Document, OrganizationMembership, UsageDaily, UsageMonthly
from services.billing_service import get_plan_limits


def current_month() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def _get_daily(db: Session, organization_id: int) -> UsageDaily:
    today = date.today()
    usage = db.query(UsageDaily).filter(UsageDaily.organization_id == organization_id, UsageDaily.date == today).first()
    if not usage:
        usage = UsageDaily(organization_id=organization_id, date=today)
        db.add(usage)
        db.flush()
    return usage


def _get_monthly(db: Session, organization_id: int) -> UsageMonthly:
    month = current_month()
    usage = db.query(UsageMonthly).filter(UsageMonthly.organization_id == organization_id, UsageMonthly.month == month).first()
    if not usage:
        usage = UsageMonthly(organization_id=organization_id, month=month)
        db.add(usage)
        db.flush()
    return usage


def record_usage(
    db: Session,
    organization_id: int | None,
    *,
    messages_sent: int = 0,
    tokens_used: int = 0,
    embeddings_used: int = 0,
    document_uploads: int = 0,
    storage_bytes_delta: int = 0,
) -> None:
    if not organization_id:
        return
    daily = _get_daily(db, organization_id)
    monthly = _get_monthly(db, organization_id)
    for usage in (daily, monthly):
        usage.messages_sent += messages_sent
        usage.tokens_used += tokens_used
        usage.embeddings_used += embeddings_used
        usage.document_uploads += document_uploads
        usage.storage_bytes = max(0, usage.storage_bytes + storage_bytes_delta)
        usage.updated_at = datetime.utcnow()
    db.commit()


def refresh_resource_usage(db: Session, organization_id: int) -> None:
    active_bots = db.query(func.count(Bot.id)).filter(Bot.organization_id == organization_id).scalar() or 0
    storage_bytes = (
        db.query(func.coalesce(func.sum(Document.file_size), 0))
        .filter(Document.organization_id == organization_id)
        .scalar()
        or 0
    )
    daily = _get_daily(db, organization_id)
    monthly = _get_monthly(db, organization_id)
    for usage in (daily, monthly):
        usage.active_bots = active_bots
        usage.storage_bytes = int(storage_bytes)
        usage.updated_at = datetime.utcnow()
    db.commit()


def get_usage_summary(db: Session, organization_id: int) -> dict:
    refresh_resource_usage(db, organization_id)
    usage = _get_monthly(db, organization_id)
    limits = get_plan_limits(db, organization_id)
    return {
        "organization_id": organization_id,
        "month": usage.month,
        "usage": {
            "messages_sent": usage.messages_sent,
            "tokens_used": usage.tokens_used,
            "embeddings_used": usage.embeddings_used,
            "document_uploads": usage.document_uploads,
            "storage_bytes": usage.storage_bytes,
            "active_bots": usage.active_bots,
        },
        "limits": limits,
    }


def _limit_error(resource: str, limit: int) -> HTTPException:
    return HTTPException(status_code=402, detail=f"{resource} limit reached for the current plan. Upgrade to continue.")


def ensure_can_create_bot(db: Session, organization_id: int) -> None:
    limits = get_plan_limits(db, organization_id)
    limit = int(limits.get("max_bots", 0))
    if limit <= 0:
        return
    count = db.query(func.count(Bot.id)).filter(Bot.organization_id == organization_id).scalar() or 0
    if count >= limit:
        raise _limit_error("Bot", limit)


def ensure_can_add_document(db: Session, organization_id: int, incoming_bytes: int = 0) -> None:
    limits = get_plan_limits(db, organization_id)
    max_documents = int(limits.get("max_documents", 0))
    if max_documents > 0:
        count = db.query(func.count(Document.id)).filter(Document.organization_id == organization_id).scalar() or 0
        if count >= max_documents:
            raise _limit_error("Document", max_documents)
    storage_limit = int(limits.get("storage_bytes", 0))
    if storage_limit > 0:
        current_storage = (
            db.query(func.coalesce(func.sum(Document.file_size), 0))
            .filter(Document.organization_id == organization_id)
            .scalar()
            or 0
        )
        if int(current_storage) + incoming_bytes > storage_limit:
            raise _limit_error("Storage", storage_limit)


def ensure_can_send_message(db: Session, organization_id: int | None) -> None:
    if not organization_id:
        return
    limits = get_plan_limits(db, organization_id)
    limit = int(limits.get("monthly_messages", 0))
    if limit <= 0:
        return
    usage = _get_monthly(db, organization_id)
    if usage.messages_sent >= limit:
        raise _limit_error("Monthly message", limit)


def ensure_can_add_member(db: Session, organization_id: int) -> None:
    limits = get_plan_limits(db, organization_id)
    limit = int(limits.get("team_members", 0))
    if limit <= 0:
        return
    count = (
        db.query(func.count(OrganizationMembership.id))
        .filter(OrganizationMembership.organization_id == organization_id)
        .scalar()
        or 0
    )
    if count >= limit:
        raise _limit_error("Team member", limit)
