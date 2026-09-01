import os
from datetime import date, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import (
    Bot,
    Document,
    MessageUsageReservation,
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
    Plan,
    Subscription,
    UsageDaily,
    UsageMonthly,
)
from services.billing_service import ensure_default_plans, get_or_create_subscription


CURRENT_DOCUMENT_STATUSES = ("ready", "staging")


def message_reservation_ttl_seconds() -> int:
    """Conservative ceiling for a live chat request plus provider retries.

    The normal provider request is measured in seconds. One hour is deliberately
    much longer than the configured provider timeouts/retries, so maintenance
    cannot reclaim a merely slow request. Deployments with longer request
    envelopes can raise MESSAGE_RESERVATION_STALE_SECONDS.
    """
    configured = int(os.getenv("MESSAGE_RESERVATION_STALE_SECONDS", "3600"))
    return max(3600, configured)


def _reservation_expiry(now: datetime | None = None) -> datetime:
    return (now or datetime.utcnow()) + timedelta(seconds=message_reservation_ttl_seconds())


def current_month() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def _lock_quota_owner(db: Session, organization_id: int):
    """Serialize quota decisions on the tenant row, which always exists."""
    db.rollback()
    db.query(Organization).filter(Organization.id == organization_id).with_for_update().one()
    subscription = db.query(Subscription).filter(
        Subscription.organization_id == organization_id
    ).first()
    if subscription:
        return subscription
    plan = db.query(Plan).filter(Plan.code == "free", Plan.active.is_(True)).first()
    if not plan:
        db.rollback()
        ensure_default_plans(db)
        return _lock_quota_owner(db, organization_id)

    class DefaultSubscription:
        pass

    fallback = DefaultSubscription()
    fallback.plan = plan
    return fallback


def _limits(subscription: Subscription) -> dict[str, int]:
    return subscription.plan.limits_json or {}


def _get_daily(db: Session, organization_id: int) -> UsageDaily:
    today = date.today()
    usage = db.query(UsageDaily).filter(
        UsageDaily.organization_id == organization_id, UsageDaily.date == today
    ).first()
    if not usage:
        usage = UsageDaily(organization_id=organization_id, date=today)
        db.add(usage)
        db.flush()
    return usage


def _get_monthly(db: Session, organization_id: int) -> UsageMonthly:
    month = current_month()
    usage = db.query(UsageMonthly).filter(
        UsageMonthly.organization_id == organization_id, UsageMonthly.month == month
    ).first()
    if not usage:
        usage = UsageMonthly(organization_id=organization_id, month=month)
        db.add(usage)
        db.flush()
    return usage


def _apply_usage(
    db: Session,
    organization_id: int,
    *,
    messages_sent: int = 0,
    tokens_used: int = 0,
    embeddings_used: int = 0,
    document_uploads: int = 0,
    storage_bytes_delta: int = 0,
) -> None:
    now = datetime.utcnow()
    for usage in (_get_daily(db, organization_id), _get_monthly(db, organization_id)):
        usage.messages_sent += messages_sent
        usage.tokens_used += tokens_used
        usage.embeddings_used += embeddings_used
        usage.document_uploads += document_uploads
        usage.storage_bytes = max(0, usage.storage_bytes + storage_bytes_delta)
        usage.updated_at = now


def record_usage(
    db: Session,
    organization_id: int | None,
    *,
    messages_sent: int = 0,
    tokens_used: int = 0,
    embeddings_used: int = 0,
    document_uploads: int = 0,
    storage_bytes_delta: int = 0,
    commit: bool = True,
) -> None:
    if not organization_id:
        return
    _lock_quota_owner(db, organization_id)
    _apply_usage(
        db, organization_id,
        messages_sent=messages_sent,
        tokens_used=tokens_used,
        embeddings_used=embeddings_used,
        document_uploads=document_uploads,
        storage_bytes_delta=storage_bytes_delta,
    )
    if commit:
        db.commit()


def reserve_message_quota(
    db: Session,
    organization_id: int | None,
    *,
    idempotency_key: str | None = None,
    channel: str = "unknown",
) -> str | None:
    """Reserve one monthly slot before generation, durably and idempotently."""
    if not organization_id:
        return None
    key = idempotency_key or f"server:{uuid4().hex}"
    subscription = _lock_quota_owner(db, organization_id)
    period = current_month()
    existing = db.query(MessageUsageReservation).filter(
        MessageUsageReservation.organization_id == organization_id,
        MessageUsageReservation.period == period,
        MessageUsageReservation.idempotency_key == key,
    ).first()
    if existing:
        if existing.status == "released":
            usage = _get_monthly(db, organization_id)
            reserved = db.query(func.count(MessageUsageReservation.id)).filter(
                MessageUsageReservation.organization_id == organization_id,
                MessageUsageReservation.period == period,
                MessageUsageReservation.status == "reserved",
            ).scalar() or 0
            limit = int(_limits(subscription).get("monthly_messages", 0))
            if limit > 0 and usage.messages_sent + reserved >= limit:
                db.rollback()
                raise _limit_error("Monthly message", limit)
            existing.status = "reserved"
            existing.channel = channel
            now = datetime.utcnow()
            existing.updated_at = now
            existing.last_heartbeat_at = now
            existing.expires_at = _reservation_expiry(now)
        db.commit()
        return key

    usage = _get_monthly(db, organization_id)
    reserved = db.query(func.count(MessageUsageReservation.id)).filter(
        MessageUsageReservation.organization_id == organization_id,
        MessageUsageReservation.period == period,
        MessageUsageReservation.status == "reserved",
    ).scalar() or 0
    limit = int(_limits(subscription).get("monthly_messages", 0))
    if limit > 0 and usage.messages_sent + reserved >= limit:
        db.rollback()
        raise _limit_error("Monthly message", limit)
    now = datetime.utcnow()
    db.add(MessageUsageReservation(
        organization_id=organization_id,
        period=period,
        idempotency_key=key,
        channel=channel,
        status="reserved",
        last_heartbeat_at=now,
        expires_at=_reservation_expiry(now),
    ))
    db.commit()
    return key


def heartbeat_message_quota(
    db: Session,
    organization_id: int | None,
    idempotency_key: str | None,
) -> bool:
    """Extend a still-active reservation without reviving a settled one."""
    if not organization_id or not isinstance(idempotency_key, str) or not idempotency_key:
        return False
    now = datetime.utcnow()
    changed = db.query(MessageUsageReservation).filter(
        MessageUsageReservation.organization_id == organization_id,
        MessageUsageReservation.period == current_month(),
        MessageUsageReservation.idempotency_key == idempotency_key,
        MessageUsageReservation.status == "reserved",
    ).update(
        {
            "last_heartbeat_at": now,
            "expires_at": _reservation_expiry(now),
            "updated_at": now,
        },
        synchronize_session=False,
    )
    db.commit()
    return bool(changed)


def reconcile_stale_message_reservations(
    db: Session,
    *,
    now: datetime | None = None,
    organization_id: int | None = None,
) -> list[int]:
    """Release only expired, unsettled reservations.

    Settlement never decrements usage: a reservation has not been counted until
    it is consumed. Row locks and the reserved-status predicate make repeated
    maintenance runs idempotent and safe against concurrent consume/release.
    """
    current = now or datetime.utcnow()
    query = db.query(MessageUsageReservation).filter(
        MessageUsageReservation.status == "reserved",
        MessageUsageReservation.expires_at <= current,
        MessageUsageReservation.last_heartbeat_at <= current - timedelta(
            seconds=message_reservation_ttl_seconds()
        ),
    )
    if organization_id is not None:
        query = query.filter(MessageUsageReservation.organization_id == organization_id)
    reservations = query.with_for_update().all()
    released_ids: list[int] = []
    for reservation in reservations:
        reservation.status = "released"
        reservation.updated_at = current
        released_ids.append(reservation.id)
    db.commit()
    return released_ids


def consume_message_quota(
    db: Session,
    organization_id: int | None,
    idempotency_key: str | None,
    *,
    commit: bool = True,
) -> bool:
    """Consume a reserved turn once; completed replays are no-ops."""
    if not organization_id or not isinstance(idempotency_key, str) or not idempotency_key:
        return False
    _lock_quota_owner(db, organization_id)
    reservation = db.query(MessageUsageReservation).filter(
        MessageUsageReservation.organization_id == organization_id,
        MessageUsageReservation.period == current_month(),
        MessageUsageReservation.idempotency_key == idempotency_key,
    ).with_for_update().first()
    if not reservation or reservation.status != "reserved":
        if commit:
            db.commit()
        return False
    reservation.status = "consumed"
    reservation.updated_at = datetime.utcnow()
    _apply_usage(db, organization_id, messages_sent=1)
    if commit:
        db.commit()
    return True


def release_message_quota(
    db: Session,
    organization_id: int | None,
    idempotency_key: str | None,
) -> bool:
    if not organization_id or not isinstance(idempotency_key, str) or not idempotency_key:
        return False
    _lock_quota_owner(db, organization_id)
    reservation = db.query(MessageUsageReservation).filter(
        MessageUsageReservation.organization_id == organization_id,
        MessageUsageReservation.period == current_month(),
        MessageUsageReservation.idempotency_key == idempotency_key,
    ).with_for_update().first()
    changed = bool(reservation and reservation.status == "reserved")
    if changed:
        reservation.status = "released"
        reservation.updated_at = datetime.utcnow()
    db.commit()
    return changed


def ensure_can_send_message(
    db: Session,
    organization_id: int | None,
    idempotency_key: str | None = None,
    channel: str = "unknown",
) -> str | None:
    """Compatibility entry point; now performs the atomic reservation."""
    if idempotency_key is None and hasattr(db, "info"):
        context = db.info.pop("message_quota_context", {})
        idempotency_key = context.get("idempotency_key")
        channel = context.get("channel", channel)
    return reserve_message_quota(
        db, organization_id, idempotency_key=idempotency_key, channel=channel
    )


def set_message_quota_context(
    db: Session, *, idempotency_key: str | None, channel: str
) -> None:
    """Attach request-local reservation identity while preserving legacy call sites."""
    if hasattr(db, "info"):
        db.info["message_quota_context"] = {
            "idempotency_key": idempotency_key,
            "channel": channel,
        }


def _resource_totals(
    db: Session, organization_id: int, statuses: tuple[str, ...]
) -> tuple[int, int]:
    row = db.query(
        func.count(Document.id), func.coalesce(func.sum(Document.logical_size_bytes), 0)
    ).filter(
        Document.organization_id == organization_id,
        Document.status.in_(statuses),
    ).one()
    return int(row[0] or 0), int(row[1] or 0)


def refresh_resource_usage(db: Session, organization_id: int) -> None:
    _lock_quota_owner(db, organization_id)
    active_bots = db.query(func.count(Bot.id)).filter(Bot.organization_id == organization_id).scalar() or 0
    _, storage_bytes = _resource_totals(db, organization_id, ("ready",))
    now = datetime.utcnow()
    for usage in (_get_daily(db, organization_id), _get_monthly(db, organization_id)):
        usage.active_bots = active_bots
        usage.storage_bytes = storage_bytes
        usage.updated_at = now
    db.commit()


def get_usage_summary(db: Session, organization_id: int) -> dict:
    refresh_resource_usage(db, organization_id)
    subscription = get_or_create_subscription(db, organization_id)
    usage = _get_monthly(db, organization_id)
    bots_used = db.query(func.count(Bot.id)).filter(Bot.organization_id == organization_id).scalar() or 0
    documents_used, storage_used = _resource_totals(db, organization_id, ("ready",))
    documents_reserved, storage_reserved = _resource_totals(db, organization_id, ("staging",))
    return {
        "organization_id": organization_id,
        "month": usage.month,
        "current_plan": subscription.plan.code,
        "current_period": {
            "start": subscription.current_period_start.isoformat() if subscription.current_period_start else f"{usage.month}-01T00:00:00",
            "end": subscription.current_period_end.isoformat() if subscription.current_period_end else None,
        },
        "usage": {
            "messages_used": usage.messages_sent,
            "bots_used": int(bots_used),
            "documents_used": documents_used,
            "logical_storage_bytes": storage_used,
            "knowledge_resources_reserved": documents_reserved,
            "logical_storage_reserved_bytes": storage_reserved,
            "provider_tokens": None,
            "embedding_usage": None,
            "messages_sent": usage.messages_sent,
            "active_bots": int(bots_used),
            "document_uploads": usage.document_uploads,
            "storage_bytes": storage_used,
            "tokens_used": None,
            "embeddings_used": None,
        },
        "limits": _limits(subscription),
        "metering": {
            "provider_tokens": "unavailable",
            "embedding_usage": "unavailable",
            "storage_definition": "Uploaded source bytes; otherwise UTF-8 extracted text bytes for current knowledge resources.",
        },
    }


def _limit_error(resource: str, limit: int) -> HTTPException:
    return HTTPException(status_code=402, detail=f"{resource} limit reached for the current plan. Upgrade to continue.")


def ensure_can_create_bot(db: Session, organization_id: int) -> None:
    subscription = _lock_quota_owner(db, organization_id)
    limit = int(_limits(subscription).get("max_bots", 0))
    count = db.query(func.count(Bot.id)).filter(Bot.organization_id == organization_id).scalar() or 0
    if limit > 0 and count >= limit:
        db.rollback()
        raise _limit_error("Bot", limit)


def ensure_can_add_document(db: Session, organization_id: int, incoming_bytes: int = 0) -> None:
    subscription = _lock_quota_owner(db, organization_id)
    count, storage = _resource_totals(db, organization_id, CURRENT_DOCUMENT_STATUSES)
    max_documents = int(_limits(subscription).get("max_documents", 0))
    if max_documents > 0 and count >= max_documents:
        db.rollback()
        raise _limit_error("Document", max_documents)
    storage_limit = int(_limits(subscription).get("storage_bytes", 0))
    if storage_limit > 0 and storage + max(0, incoming_bytes) > storage_limit:
        db.rollback()
        raise _limit_error("Logical storage", storage_limit)


def ensure_can_promote_knowledge(
    db: Session,
    organization_id: int,
    *,
    resulting_documents: int,
    resulting_storage_bytes: int,
    replaced_website_id: int | None = None,
    replaced_document_ids: list[int] | None = None,
) -> None:
    """Validate an entire staged version immediately before atomic promotion."""
    subscription = _lock_quota_owner(db, organization_id)
    base = db.query(
        func.count(Document.id), func.coalesce(func.sum(Document.logical_size_bytes), 0)
    ).filter(Document.organization_id == organization_id, Document.status == "ready")
    if replaced_website_id is not None:
        base = base.filter((Document.website_id.is_(None)) | (Document.website_id != replaced_website_id))
    if replaced_document_ids:
        base = base.filter(Document.id.notin_(replaced_document_ids))
    row = base.one()
    projected_documents = int(row[0] or 0) + resulting_documents
    projected_storage = int(row[1] or 0) + resulting_storage_bytes
    max_documents = int(_limits(subscription).get("max_documents", 0))
    storage_limit = int(_limits(subscription).get("storage_bytes", 0))
    if max_documents > 0 and projected_documents > max_documents:
        db.rollback()
        raise _limit_error("Document", max_documents)
    if storage_limit > 0 and projected_storage > storage_limit:
        db.rollback()
        raise _limit_error("Logical storage", storage_limit)


def ensure_can_add_member(db: Session, organization_id: int) -> None:
    subscription = _lock_quota_owner(db, organization_id)
    limit = int(_limits(subscription).get("team_members", 0))
    members = db.query(func.count(OrganizationMembership.id)).filter(
        OrganizationMembership.organization_id == organization_id
    ).scalar() or 0
    pending_invites = db.query(func.count(OrganizationInvitation.id)).filter(
        OrganizationInvitation.organization_id == organization_id,
        OrganizationInvitation.status == "pending",
        OrganizationInvitation.expires_at > datetime.utcnow(),
    ).scalar() or 0
    if limit > 0 and members + pending_invites >= limit:
        db.rollback()
        raise _limit_error("Team member", limit)
