from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import Bot, ConversationMessage, ConversationSession, Document, User, OrganizationMembership
from schemas.schemas import AnalyticsSummaryResponse
from services.auth_service import get_optional_user
from services.analytics_service import get_bot_analytics_summary
from services.bot_service import get_bot_or_404
from services.organization_service import require_org_role

router = APIRouter()


@router.get("/bot/{bot_id}/summary", response_model=AnalyticsSummaryResponse)
def get_bot_summary(
    bot_id: int = Path(..., gt=0),
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    get_bot_or_404(db, bot_id, user=current_user)
    return get_bot_analytics_summary(db, bot_id)


@router.get("/organization/{organization_id}/details")
def get_organization_details(
    organization_id: int = Path(..., gt=0),
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    require_org_role(db, current_user, organization_id, "member")

    # 1. Total stats
    total_conversations = (
        db.query(func.count(ConversationSession.id))
        .filter(ConversationSession.organization_id == organization_id)
        .scalar()
        or 0
    )
    unique_visitors = (
        db.query(func.count(func.distinct(ConversationSession.session_id)))
        .filter(ConversationSession.organization_id == organization_id)
        .scalar()
        or 0
    )
    total_messages = (
        db.query(func.count(ConversationMessage.id))
        .filter(ConversationMessage.organization_id == organization_id)
        .scalar()
        or 0
    )
    avg_response_time = (
        db.query(func.avg(ConversationMessage.response_time_ms))
        .filter(ConversationMessage.organization_id == organization_id)
        .filter(ConversationMessage.status == "success")
        .scalar()
    )

    active_bots = (
        db.query(func.count(Bot.id))
        .filter(Bot.organization_id == organization_id)
        .filter(Bot.status == "active")
        .scalar()
        or 0
    )
    total_users = (
        db.query(func.count(OrganizationMembership.id))
        .filter(OrganizationMembership.organization_id == organization_id)
        .scalar()
        or 0
    )

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    conversations_today = (
        db.query(func.count(ConversationSession.id))
        .filter(ConversationSession.organization_id == organization_id)
        .filter(ConversationSession.created_at >= today_start)
        .scalar()
        or 0
    )
    messages_today = (
        db.query(func.count(ConversationMessage.id))
        .filter(ConversationMessage.organization_id == organization_id)
        .filter(ConversationMessage.created_at >= today_start)
        .scalar()
        or 0
    )

    user_activity_score = 0
    if total_users > 0:
        ratio = (messages_today / total_users)
        user_activity_score = min(100, int(ratio * 10) + 10 if messages_today > 0 else 0)

    resolved_count = (
        db.query(func.count(ConversationSession.id))
        .filter(ConversationSession.organization_id == organization_id)
        .filter(ConversationSession.status == "resolved")
        .scalar()
        or 0
    )
    resolution_rate = (resolved_count / total_conversations) * 100 if total_conversations > 0 else 100.0

    fallback_count = (
        db.query(func.count(ConversationMessage.id))
        .filter(ConversationMessage.organization_id == organization_id)
        .filter(ConversationMessage.is_fallback == True)
        .scalar()
        or 0
    )
    fallback_rate = (fallback_count / total_messages) * 100 if total_messages > 0 else 0.0

    hit_count = (
        db.query(func.count(ConversationMessage.id))
        .filter(ConversationMessage.organization_id == organization_id)
        .filter(ConversationMessage.had_knowledge_hit == True)
        .scalar()
        or 0
    )
    hit_rate = (hit_count / total_messages) * 100 if total_messages > 0 else 0.0

    # 2. Daily trends (7 days)
    trends = []
    for i in range(6, -1, -1):
        date_val = (datetime.utcnow() - timedelta(days=i)).date()
        convs = (
            db.query(func.count(ConversationSession.id))
            .filter(ConversationSession.organization_id == organization_id)
            .filter(func.date(ConversationSession.created_at) == date_val)
            .scalar()
            or 0
        )
        msgs = (
            db.query(func.count(ConversationMessage.id))
            .filter(ConversationMessage.organization_id == organization_id)
            .filter(func.date(ConversationMessage.created_at) == date_val)
            .scalar()
            or 0
        )
        trends.append({"date": date_val.strftime("%Y-%m-%d"), "conversations": convs, "messages": msgs})

    # 3. Top Bots
    top_bots_rows = (
        db.query(Bot.id, Bot.name, func.count(ConversationSession.id).label("conv_count"))
        .join(ConversationSession, Bot.id == ConversationSession.bot_id)
        .filter(Bot.organization_id == organization_id)
        .group_by(Bot.id, Bot.name)
        .order_by(text("conv_count DESC"))
        .limit(5)
        .all()
    )
    top_bots = [{"id": r[0], "name": r[1], "conversations": r[2]} for r in top_bots_rows]

    # 4. Top Documents
    docs = (
        db.query(Document)
        .filter(Document.organization_id == organization_id)
        .order_by(Document.chunk_count.desc())
        .limit(5)
        .all()
    )
    top_documents = [
        {
            "id": d.id,
            "filename": d.filename,
            "chunk_count": d.chunk_count,
            "token_count": d.token_count,
            "source_type": d.source_type,
        }
        for d in docs
    ]

    # 5. AI Insights
    recent_msgs = (
        db.query(ConversationMessage.user_message)
        .filter(ConversationMessage.organization_id == organization_id)
        .filter(ConversationMessage.user_message != None)
        .order_by(ConversationMessage.created_at.desc())
        .limit(10)
        .all()
    )
    top_questions = list(set([r[0] for r in recent_msgs if r[0]]))[:5]

    recent_fallbacks = (
        db.query(ConversationMessage.user_message)
        .filter(ConversationMessage.organization_id == organization_id)
        .filter(ConversationMessage.is_fallback == True)
        .order_by(ConversationMessage.created_at.desc())
        .limit(10)
        .all()
    )
    unanswered_questions = list(set([r[0] for r in recent_fallbacks if r[0]]))[:5]

    knowledge_gaps = []
    for q in unanswered_questions[:3]:
        words = [w for w in q.lower().split() if len(w) > 4]
        topic = " ".join(words[:2]) if words else "specific queries"
        knowledge_gaps.append(f"Insufficient knowledge regarding '{topic or q}'")
    if not knowledge_gaps:
        knowledge_gaps = ["No significant knowledge gaps identified yet."]

    suggested_improvements = []
    if unanswered_questions:
        suggested_improvements.append("Upload documentation answering current fallback questions.")
    suggested_improvements.append("Refine system prompts for small talk greeting interactions.")
    suggested_improvements.append("Add custom Q&As to resolve high-frequency user inquiries.")

    return {
        "summary": {
            "total_conversations": total_conversations,
            "unique_visitors": unique_visitors,
            "total_messages": total_messages,
            "avg_response_time_ms": float(avg_response_time) if avg_response_time is not None else None,
            "resolution_rate": resolution_rate,
            "fallback_rate": fallback_rate,
            "hit_rate": hit_rate,
            "active_bots": active_bots,
            "total_users": total_users,
            "conversations_today": conversations_today,
            "messages_today": messages_today,
            "user_activity_score": user_activity_score,
        },
        "trends": trends,
        "top_bots": top_bots,
        "top_documents": top_documents,
        "insights": {
            "top_questions": top_questions,
            "unanswered_questions": unanswered_questions,
            "knowledge_gaps": knowledge_gaps,
            "suggested_improvements": suggested_improvements,
        },
    }

