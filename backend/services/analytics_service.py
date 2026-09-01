from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from database.models import Bot, ConversationMessage, ConversationSession, Document, OrganizationMembership
from services.usage_service import consume_message_quota, record_usage, release_message_quota


def track_widget_chat_message(
    *,
    bot_id: int,
    session_id: str,
    user_message: str,
    assistant_response: str | None,
    response_time_ms: int | None,
    status: str = "success",
    token_usage: dict | None = None,
    error_message: str | None = None,
    is_fallback: bool = False,
    had_knowledge_hit: bool = False,
    retrieval_attempted: bool = False,
    client_turn_id: str | None = None,
    allow_aborted_retry: bool = False,
    usage_reservation_key: str | None = None,
    channel: str = "widget",
) -> None:
    db = SessionLocal()
    try:
        record_widget_chat_message(
            db=db,
            bot_id=bot_id,
            session_id=session_id,
            user_message=user_message,
            assistant_response=assistant_response,
            response_time_ms=response_time_ms,
            status=status,
            token_usage=token_usage,
            error_message=error_message,
            is_fallback=is_fallback,
            had_knowledge_hit=had_knowledge_hit,
            retrieval_attempted=retrieval_attempted,
            client_turn_id=client_turn_id,
            allow_aborted_retry=allow_aborted_retry,
            usage_reservation_key=usage_reservation_key,
            channel=channel,
        )
    finally:
        db.close()


def record_widget_chat_message(
    *,
    db: Session,
    bot_id: int,
    session_id: str,
    user_message: str,
    assistant_response: str | None,
    response_time_ms: int | None,
    status: str = "success",
    token_usage: dict | None = None,
    error_message: str | None = None,
    is_fallback: bool = False,
    had_knowledge_hit: bool = False,
    retrieval_attempted: bool = False,
    client_turn_id: str | None = None,
    allow_aborted_retry: bool = False,
    usage_reservation_key: str | None = None,
    channel: str = "widget",
) -> bool:
    bot = db.query(Bot).filter(Bot.id == bot_id).first()
    organization_id = bot.organization_id if bot else None
    if status == "success" and usage_reservation_key:
        consume_message_quota(db, organization_id, usage_reservation_key, commit=False)
    elif status in {"error", "aborted"} and usage_reservation_key:
        release_message_quota(db, organization_id, usage_reservation_key)

    if client_turn_id:
        existing = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.bot_id == bot_id)
            .filter(ConversationMessage.session_id == session_id)
            .filter(ConversationMessage.client_turn_id == client_turn_id)
            .first()
        )
        if existing:
            if (
                existing.status == "error"
                or (existing.status == "aborted" and allow_aborted_retry)
            ) and status == "success":
                existing.assistant_response = assistant_response
                existing.response_time_ms = response_time_ms
                existing.token_usage = token_usage
                existing.status = "success"
                existing.error_message = None
                existing.is_fallback = is_fallback
                existing.had_knowledge_hit = had_knowledge_hit
                existing.retrieval_attempted = retrieval_attempted
                db.commit()
                if not usage_reservation_key:
                    record_usage(db, organization_id, messages_sent=1)
                return True
            return False
    session = (
        db.query(ConversationSession)
        .filter(ConversationSession.bot_id == bot_id)
        .filter(ConversationSession.session_id == session_id)
        .first()
    )
    now = datetime.utcnow()
    if not session:
        session = ConversationSession(
            bot_id=bot_id,
            organization_id=organization_id,
            session_id=session_id,
            channel=channel,
            created_at=now,
            updated_at=now,
        )
        db.add(session)
        db.flush()
    else:
        session.updated_at = now

    db.add(
        ConversationMessage(
            conversation_session_id=session.id,
            bot_id=bot_id,
            organization_id=organization_id,
            session_id=session_id,
            client_turn_id=client_turn_id,
            user_message=user_message,
            assistant_response=assistant_response,
            response_time_ms=response_time_ms,
            token_usage=token_usage,
            status=status,
            error_message=error_message,
            is_fallback=is_fallback,
            had_knowledge_hit=had_knowledge_hit,
            retrieval_attempted=retrieval_attempted,
            created_at=now,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return False
    if status == "success" and not usage_reservation_key:
        record_usage(db, organization_id, messages_sent=1)
    return True


def get_bot_analytics_summary(db: Session, bot_id: int) -> dict:
    since = datetime.utcnow() - timedelta(hours=24)

    total_conversations = (
        db.query(func.count(ConversationSession.id))
        .filter(ConversationSession.bot_id == bot_id)
        .scalar()
        or 0
    )
    total_messages = (
        db.query(func.count(ConversationMessage.id))
        .filter(ConversationMessage.bot_id == bot_id)
        .scalar()
        or 0
    )
    average_response_time_ms = (
        db.query(func.avg(ConversationMessage.response_time_ms))
        .filter(ConversationMessage.bot_id == bot_id)
        .filter(ConversationMessage.status == "success")
        .scalar()
    )
    recent_conversations_24h = (
        db.query(func.count(ConversationSession.id))
        .filter(ConversationSession.bot_id == bot_id)
        .filter(ConversationSession.created_at >= since)
        .scalar()
        or 0
    )
    recent_messages_24h = (
        db.query(func.count(ConversationMessage.id))
        .filter(ConversationMessage.bot_id == bot_id)
        .filter(ConversationMessage.created_at >= since)
        .scalar()
        or 0
    )
    successful_messages = (
        db.query(func.count(ConversationMessage.id))
        .filter(ConversationMessage.bot_id == bot_id)
        .filter(ConversationMessage.status == "success")
        .scalar()
        or 0
    )
    errored_messages = (
        db.query(func.count(ConversationMessage.id))
        .filter(ConversationMessage.bot_id == bot_id)
        .filter(ConversationMessage.status == "error")
        .scalar()
        or 0
    )
    last_message_at = (
        db.query(func.max(ConversationMessage.created_at))
        .filter(ConversationMessage.bot_id == bot_id)
        .scalar()
    )

    return {
        "bot_id": bot_id,
        "total_conversations": total_conversations,
        "total_messages": total_messages,
        "average_response_time_ms": float(average_response_time_ms) if average_response_time_ms is not None else None,
        "recent_conversations_24h": recent_conversations_24h,
        "recent_messages_24h": recent_messages_24h,
        "successful_messages": successful_messages,
        "errored_messages": errored_messages,
        "last_message_at": last_message_at,
    }


def _frequency_rank(messages: list[ConversationMessage], limit: int = 5) -> list[dict]:
    counts: dict[str, dict] = {}
    for message in messages:
        text = (message.user_message or "").strip()
        if not text:
            continue
        key = " ".join(text.casefold().split())
        entry = counts.setdefault(key, {"question": text, "count": 0})
        entry["count"] += 1
    return sorted(counts.values(), key=lambda item: (-item["count"], item["question"].casefold()))[:limit]


def get_organization_analytics_details(db: Session, organization_id: int) -> dict:
    """Measured organization analytics over an explicit rolling 30-day UTC window."""
    end = datetime.utcnow()
    start = end - timedelta(days=30)
    today_start = end.replace(hour=0, minute=0, second=0, microsecond=0)
    messages = db.query(ConversationMessage).filter(
        ConversationMessage.organization_id == organization_id,
        ConversationMessage.created_at >= start,
        ConversationMessage.created_at < end,
    ).all()
    sessions = db.query(ConversationSession).filter(
        ConversationSession.organization_id == organization_id,
        ConversationSession.created_at >= start,
        ConversationSession.created_at < end,
    ).all()
    successful = [message for message in messages if message.status == "success"]
    attempted = [message for message in successful if message.retrieval_attempted]
    evidence_hits = [message for message in attempted if message.had_knowledge_hit]
    fallback = [message for message in successful if message.is_fallback]
    response_times = [message.response_time_ms for message in successful if message.response_time_ms is not None]

    active_bots = db.query(func.count(Bot.id)).filter(
        Bot.organization_id == organization_id, Bot.status == "active"
    ).scalar() or 0
    team_members = db.query(func.count(OrganizationMembership.id)).filter(
        OrganizationMembership.organization_id == organization_id
    ).scalar() or 0

    trends = []
    for offset in range(6, -1, -1):
        day = (end - timedelta(days=offset)).date()
        trends.append({
            "date": day.isoformat(),
            "chat_sessions": sum(1 for session in sessions if session.created_at.date() == day),
            "messages": sum(1 for message in messages if message.created_at.date() == day),
        })

    bot_session_counts: dict[int, int] = {}
    for session in sessions:
        bot_session_counts[session.bot_id] = bot_session_counts.get(session.bot_id, 0) + 1
    bot_names = {
        bot.id: bot.name
        for bot in db.query(Bot).filter(Bot.organization_id == organization_id).all()
    }
    top_bots = [
        {"id": bot_id, "name": bot_names.get(bot_id, "Deleted bot"), "chat_sessions": count}
        for bot_id, count in sorted(bot_session_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    ]

    largest_sources = [
        {
            "id": document.id,
            "filename": document.filename,
            "chunk_count": document.chunk_count,
            "token_count": document.token_count,
            "logical_size_bytes": document.logical_size_bytes,
            "source_type": document.source_type,
        }
        for document in db.query(Document).filter(
            Document.organization_id == organization_id,
            Document.status == "ready",
        ).order_by(Document.chunk_count.desc(), Document.id.asc()).limit(5).all()
    ]
    gap_events = [
        message for message in successful
        if message.is_fallback or (message.retrieval_attempted and not message.had_knowledge_hit)
    ]

    return {
        "window": {
            "label": "Last 30 days",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timezone": "UTC",
        },
        "summary": {
            "chat_sessions": len(sessions),
            "total_messages": len(messages),
            "successful_messages": len(successful),
            "avg_response_time_ms": (sum(response_times) / len(response_times)) if response_times else None,
            "fallback_rate": (len(fallback) / len(successful) * 100) if successful else 0.0,
            "retrieval_attempt_rate": (len(attempted) / len(successful) * 100) if successful else 0.0,
            "evidence_found_rate": (len(evidence_hits) / len(attempted) * 100) if attempted else 0.0,
            "active_bots": int(active_bots),
            "team_members": int(team_members),
            "chat_sessions_today": sum(1 for session in sessions if session.created_at >= today_start),
            "messages_today": sum(1 for message in messages if message.created_at >= today_start),
        },
        "trends": {"window": "Last 7 days", "series": trends},
        "top_bots": top_bots,
        "largest_knowledge_sources": largest_sources,
        "insights": {
            "top_questions": _frequency_rank(messages),
            "frequent_unanswered_questions": _frequency_rank(gap_events),
        },
        "metric_notes": {
            "chat_sessions": "Distinct stored chat sessions, not deduplicated visitors.",
            "evidence_found_rate": "Successful retrieval attempts with at least one returned evidence source.",
            "largest_knowledge_sources": "Ranked by stored chunk count, not views or citation engagement.",
        },
    }
