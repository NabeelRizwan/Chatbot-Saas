from datetime import datetime
from typing import Any, Literal, Optional
import csv
import io
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import Text
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import Bot, ConversationMessage, ConversationSession, User
from services.auth_service import get_optional_user
from services.organization_service import require_org_role

router = APIRouter()


@router.get("/organizations/{organization_id}/conversations")
def list_conversations(
    organization_id: int = Path(..., gt=0),
    bot_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    include_archived: bool = Query(False),
    is_pinned: Optional[bool] = Query(None),
    sort_by: str = Query("activity"),
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    require_org_role(db, current_user, organization_id, "member")

    query = db.query(ConversationSession).filter(ConversationSession.organization_id == organization_id)

    if not include_archived:
        query = query.filter((ConversationSession.is_archived == False) | (ConversationSession.is_archived == None))
    else:
        query = query.filter(ConversationSession.is_archived == True)

    if is_pinned is not None:
        query = query.filter(ConversationSession.is_pinned == is_pinned)
    if bot_id:
        query = query.filter(ConversationSession.bot_id == bot_id)
    if status:
        query = query.filter(ConversationSession.status == status)
    if tag:
        query = query.filter(ConversationSession.tags.cast(Text).like(f'%"{tag}"%'))
    if search:
        subquery = (
            db.query(ConversationMessage.conversation_session_id)
            .filter(
                ConversationMessage.user_message.ilike(f"%{search}%")
                | ConversationMessage.assistant_response.ilike(f"%{search}%")
            )
            .subquery()
        )
        query = query.filter(ConversationSession.id.in_(subquery))

    query = query.join(Bot, Bot.id == ConversationSession.bot_id)
    
    order_by_fields = [ConversationSession.is_pinned.desc()]
    if sort_by == "date":
        order_by_fields.append(ConversationSession.created_at.desc())
    else:
        order_by_fields.append(ConversationSession.updated_at.desc())

    sessions = query.order_by(*order_by_fields).all()

    res = []
    for s in sessions:
        res.append(
            {
                "id": s.id,
                "bot_id": s.bot_id,
                "bot_name": s.bot.name if s.bot else "Unknown Bot",
                "organization_id": s.organization_id,
                "session_id": s.session_id,
                "title": s.title or (f"Chat {s.session_id[:8]}" if s.session_id else "Untitled Chat"),
                "is_pinned": s.is_pinned or False,
                "is_archived": s.is_archived or False,
                "shared_token": s.shared_token,
                "channel": s.channel,
                "status": s.status or "open",
                "tags": s.tags or [],
                "created_at": s.created_at,
                "updated_at": s.updated_at,
            }
        )
    return res


@router.get("/organizations/{organization_id}/conversations/export")
def export_conversations(
    organization_id: int = Path(..., gt=0),
    format: str = Query("json"),
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    require_org_role(db, current_user, organization_id, "member")

    sessions = (
        db.query(ConversationSession)
        .filter(ConversationSession.organization_id == organization_id)
        .order_by(ConversationSession.created_at.desc())
        .all()
    )

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Session ID", "Bot ID", "Bot Name", "Channel", "Status", "Tags", "Created At", "Updated At"])
        for s in sessions:
            writer.writerow(
                [
                    s.session_id,
                    s.bot_id,
                    s.bot.name if s.bot else "",
                    s.channel,
                    s.status or "open",
                    ",".join(s.tags or []),
                    s.created_at.isoformat(),
                    s.updated_at.isoformat(),
                ]
            )
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=conversations_org_{organization_id}.csv"},
        )
    else:
        # Default to JSON
        res = []
        for s in sessions:
            res.append(
                {
                    "id": s.id,
                    "session_id": s.session_id,
                    "bot_id": s.bot_id,
                    "bot_name": s.bot.name if s.bot else "",
                    "channel": s.channel,
                    "status": s.status or "open",
                    "tags": s.tags or [],
                    "created_at": s.created_at,
                    "updated_at": s.updated_at,
                }
            )
        return res


@router.get("/organizations/{organization_id}/conversations/{session_id}")
def get_conversation(
    organization_id: int = Path(..., gt=0),
    session_id: str = Path(...),
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    require_org_role(db, current_user, organization_id, "member")

    try:
        sess_id_int = int(session_id)
        session = (
            db.query(ConversationSession)
            .filter(
                ConversationSession.organization_id == organization_id,
                (ConversationSession.id == sess_id_int) | (ConversationSession.session_id == session_id),
            )
            .first()
        )
    except ValueError:
        session = (
            db.query(ConversationSession)
            .filter(
                ConversationSession.organization_id == organization_id,
                ConversationSession.session_id == session_id,
            )
            .first()
        )

    if not session:
        raise HTTPException(status_code=404, detail="Conversation session not found")

    messages = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_session_id == session.id)
        .order_by(ConversationMessage.created_at.asc())
        .all()
    )

    return {
        "session": {
            "id": session.id,
            "bot_id": session.bot_id,
            "bot_name": session.bot.name if session.bot else "Unknown Bot",
            "organization_id": session.organization_id,
            "session_id": session.session_id,
            "title": session.title or (f"Chat {session.session_id[:8]}" if session.session_id else "Untitled Chat"),
            "is_pinned": session.is_pinned or False,
            "is_archived": session.is_archived or False,
            "shared_token": session.shared_token,
            "channel": session.channel,
            "status": session.status or "open",
            "tags": session.tags or [],
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        },
        "messages": [
            {
                "id": m.id,
                "user_message": m.user_message,
                "assistant_response": m.assistant_response,
                "response_time_ms": m.response_time_ms,
                "status": m.status,
                "is_fallback": m.is_fallback or False,
                "had_knowledge_hit": m.had_knowledge_hit or False,
                "created_at": m.created_at,
            }
            for m in messages
        ],
    }


@router.patch("/organizations/{organization_id}/conversations/{session_id}")
async def update_conversation(
    request: Request,
    organization_id: int = Path(..., gt=0),
    session_id: str = Path(...),
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    require_org_role(db, current_user, organization_id, "member")

    try:
        sess_id_int = int(session_id)
        session = (
            db.query(ConversationSession)
            .filter(
                ConversationSession.organization_id == organization_id,
                (ConversationSession.id == sess_id_int) | (ConversationSession.session_id == session_id),
            )
            .first()
        )
    except ValueError:
        session = (
            db.query(ConversationSession)
            .filter(
                ConversationSession.organization_id == organization_id,
                ConversationSession.session_id == session_id,
            )
            .first()
        )

    if not session:
        raise HTTPException(status_code=404, detail="Conversation session not found")

    body = await request.json()
    if "status" in body:
        session.status = body["status"]
    if "tags" in body:
        session.tags = body["tags"]
    if "title" in body:
        session.title = body["title"]
    if "is_archived" in body:
        session.is_archived = body["is_archived"]
    if "is_pinned" in body:
        session.is_pinned = body["is_pinned"]
    if "shared_token" in body:
        session.shared_token = body["shared_token"]

    db.commit()
    db.refresh(session)

    return {
        "id": session.id,
        "status": session.status,
        "tags": session.tags,
        "title": session.title,
        "is_archived": session.is_archived,
        "is_pinned": session.is_pinned,
        "shared_token": session.shared_token,
    }


@router.post("/organizations/{organization_id}/conversations/{session_id}/duplicate")
def duplicate_conversation(
    organization_id: int = Path(..., gt=0),
    session_id: str = Path(...),
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    require_org_role(db, current_user, organization_id, "member")

    try:
        sess_id_int = int(session_id)
        session = db.query(ConversationSession).filter(
            ConversationSession.organization_id == organization_id,
            (ConversationSession.id == sess_id_int) | (ConversationSession.session_id == session_id),
        ).first()
    except ValueError:
        session = db.query(ConversationSession).filter(
            ConversationSession.organization_id == organization_id,
            ConversationSession.session_id == session_id,
        ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Conversation session not found")

    new_sess_uuid = str(uuid.uuid4())
    new_title = f"Copy of {session.title}" if session.title else f"Copy of Chat {session.session_id[:8]}"

    new_session = ConversationSession(
        bot_id=session.bot_id,
        organization_id=session.organization_id,
        session_id=new_sess_uuid,
        title=new_title,
        channel=session.channel,
        status=session.status,
        tags=session.tags,
    )
    db.add(new_session)
    db.flush()

    messages = db.query(ConversationMessage).filter(
        ConversationMessage.conversation_session_id == session.id
    ).order_by(ConversationMessage.created_at.asc()).all()

    for m in messages:
        new_msg = ConversationMessage(
            conversation_session_id=new_session.id,
            bot_id=m.bot_id,
            organization_id=m.organization_id,
            session_id=new_sess_uuid,
            user_message=m.user_message,
            assistant_response=m.assistant_response,
            response_time_ms=m.response_time_ms,
            token_usage=m.token_usage,
            status=m.status,
            error_message=m.error_message,
            is_fallback=m.is_fallback,
            had_knowledge_hit=m.had_knowledge_hit,
        )
        db.add(new_msg)

    db.commit()
    db.refresh(new_session)

    return {
        "id": new_session.id,
        "session_id": new_session.session_id,
        "title": new_session.title,
        "status": new_session.status,
    }


@router.delete("/organizations/{organization_id}/conversations/{session_id}")
def delete_conversation(
    organization_id: int = Path(..., gt=0),
    session_id: str = Path(...),
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    require_org_role(db, current_user, organization_id, "member")

    try:
        sess_id_int = int(session_id)
        session = db.query(ConversationSession).filter(
            ConversationSession.organization_id == organization_id,
            (ConversationSession.id == sess_id_int) | (ConversationSession.session_id == session_id),
        ).first()
    except ValueError:
        session = db.query(ConversationSession).filter(
            ConversationSession.organization_id == organization_id,
            ConversationSession.session_id == session_id,
        ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Conversation session not found")

    db.delete(session)
    db.commit()
    return {"status": "deleted"}


@router.post("/organizations/{organization_id}/conversations/{session_id}/share")
def share_conversation(
    organization_id: int = Path(..., gt=0),
    session_id: str = Path(...),
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    require_org_role(db, current_user, organization_id, "member")

    try:
        sess_id_int = int(session_id)
        session = db.query(ConversationSession).filter(
            ConversationSession.organization_id == organization_id,
            (ConversationSession.id == sess_id_int) | (ConversationSession.session_id == session_id),
        ).first()
    except ValueError:
        session = db.query(ConversationSession).filter(
            ConversationSession.organization_id == organization_id,
            ConversationSession.session_id == session_id,
        ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Conversation session not found")

    if not session.shared_token:
        session.shared_token = str(uuid.uuid4())
        db.commit()
        db.refresh(session)

    return {"shared_token": session.shared_token}


@router.post("/organizations/{organization_id}/conversations/{session_id}/unshare")
def unshare_conversation(
    organization_id: int = Path(..., gt=0),
    session_id: str = Path(...),
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    require_org_role(db, current_user, organization_id, "member")

    try:
        sess_id_int = int(session_id)
        session = db.query(ConversationSession).filter(
            ConversationSession.organization_id == organization_id,
            (ConversationSession.id == sess_id_int) | (ConversationSession.session_id == session_id),
        ).first()
    except ValueError:
        session = db.query(ConversationSession).filter(
            ConversationSession.organization_id == organization_id,
            ConversationSession.session_id == session_id,
        ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Conversation session not found")

    session.shared_token = None
    db.commit()
    return {"status": "unshared"}
