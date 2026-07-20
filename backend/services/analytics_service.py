from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from database.models import Bot, ConversationMessage, ConversationSession
from services.usage_service import record_usage


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
) -> None:
    bot = db.query(Bot).filter(Bot.id == bot_id).first()
    organization_id = bot.organization_id if bot else None
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
            channel="widget",
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
            user_message=user_message,
            assistant_response=assistant_response,
            response_time_ms=response_time_ms,
            token_usage=token_usage,
            status=status,
            error_message=error_message,
            is_fallback=is_fallback,
            had_knowledge_hit=had_knowledge_hit,
            created_at=now,
        )
    )
    db.commit()
    if status == "success":
        record_usage(db, organization_id, messages_sent=1)


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
