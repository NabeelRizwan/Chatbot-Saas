import json
from time import perf_counter

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import Bot, ConversationSession, ConversationMessage
from schemas.schemas import PublicChatRequest, PublicChatResponse, PublicWidgetConfigResponse
from services.analytics_service import track_widget_chat_message
from services.llm_router import LLMRouterError
from services.observability_service import ChatTrace, track_chat_completion
from services.rag_service import answer_question, stream_answer_question
from services.usage_service import ensure_can_send_message

router = APIRouter()


def get_public_bot_or_404(db: Session, bot_id: int) -> Bot:
    bot = db.query(Bot).filter(Bot.id == bot_id).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    return bot


@router.get("/widget/{bot_id}", response_model=PublicWidgetConfigResponse)
def get_widget_config(bot_id: int = Path(..., gt=0), db: Session = Depends(get_db)):
    bot = get_public_bot_or_404(db, bot_id)
    default_config = {
        "bot_id": bot.id,
        "bot_name": bot.name,
        "welcome_message": bot.welcome_message or "Hi, how can I help you today?",
        "primary_color": "#2563eb",
        "accent_color": "#0f172a",
        "launcher_text": "Chat",
        "launcher_title": "Chat with us",
        "launcher_icon": "message",
        "bot_avatar_url": None,
        "position": "bottom-right",
        "placeholder_text": "Type your message...",
    }
    if bot.widget_config:
        if isinstance(bot.widget_config, dict):
            default_config.update(bot.widget_config)
        elif isinstance(bot.widget_config, str):
            try:
                extra = json.loads(bot.widget_config)
                if isinstance(extra, dict):
                    default_config.update(extra)
            except Exception:
                pass
    return default_config


@router.post("/chat/{bot_id}", response_model=PublicChatResponse)
def public_chat(
    data: PublicChatRequest,
    background_tasks: BackgroundTasks,
    bot_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
):
    bot = get_public_bot_or_404(db, bot_id)
    ensure_can_send_message(db, bot.organization_id)
    started_at = perf_counter()
    trace = ChatTrace(bot_id=bot.id, channel="widget")
    try:
        reply, sources, retrieved_chunks = answer_question(
            db=db,
            bot=bot,
            question=data.message,
            top_k=data.top_k,
            history=data.history,
            trace=trace,
        )
    except LLMRouterError as exc:
        trace.provider_error = True
        track_chat_completion(trace, status="error")
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    track_chat_completion(trace, status="success")
    response_time_ms = int((perf_counter() - started_at) * 1000)
    if data.session_id:
        background_tasks.add_task(
            track_widget_chat_message,
            bot_id=bot.id,
            session_id=data.session_id,
            user_message=data.message,
            assistant_response=reply,
            response_time_ms=response_time_ms,
            status="success",
            is_fallback=trace.used_fallback,
            had_knowledge_hit=trace.used_retrieval,
        )

    return {
        "session_id": data.session_id,
        "reply": reply,
        "answer": reply,
        "sources": sources,
        "retrieved_chunks": retrieved_chunks,
    }


@router.post("/chat/{bot_id}/stream")
def public_chat_stream(
    data: PublicChatRequest,
    bot_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
):
    bot = get_public_bot_or_404(db, bot_id)
    ensure_can_send_message(db, bot.organization_id)
    started_at = perf_counter()
    trace = ChatTrace(bot_id=bot.id, channel="widget_stream")

    def events():
        reply_parts = []
        try:
            for token in stream_answer_question(
                db=db,
                bot=bot,
                question=data.message,
                top_k=data.top_k,
                history=data.history,
                trace=trace,
            ):
                reply_parts.append(token)
                yield f"data: {json.dumps({'token': token})}\n\n"
            reply = "".join(reply_parts)
            if not reply.strip():
                reply = "Sorry, I had trouble generating a response. Please try again in a moment."
                reply_parts.append(reply)
                yield f"data: {json.dumps({'token': reply})}\n\n"
            if data.session_id:
                track_widget_chat_message(
                    bot_id=bot.id,
                    session_id=data.session_id,
                    user_message=data.message,
                    assistant_response=reply,
                    response_time_ms=int((perf_counter() - started_at) * 1000),
                    status="success",
                    is_fallback=trace.used_fallback,
                    had_knowledge_hit=trace.used_retrieval,
                )
            yield f"data: {json.dumps({'done': True})}\n\n"
            track_chat_completion(trace, status="success")
        except LLMRouterError as exc:
            trace.provider_error = True
            fallback = "Sorry, I had trouble generating a response. Please try again in a moment."
            if data.session_id:
                track_widget_chat_message(
                    bot_id=bot.id,
                    session_id=data.session_id,
                    user_message=data.message,
                    assistant_response=None,
                    response_time_ms=int((perf_counter() - started_at) * 1000),
                    status="error",
                    error_message=exc.message,
                )
            track_chat_completion(trace, status="error")
            yield f"data: {json.dumps({'token': fallback})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/share/{shared_token}")
def get_shared_transcript(shared_token: str, db: Session = Depends(get_db)):
    session = db.query(ConversationSession).filter(ConversationSession.shared_token == shared_token).first()
    if not session:
        raise HTTPException(status_code=404, detail="Shared transcript not found")

    messages = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_session_id == session.id)
        .order_by(ConversationMessage.created_at.asc())
        .all()
    )

    return {
        "session": {
            "title": session.title or f"Shared Chat {session.session_id[:8]}",
            "bot_name": session.bot.name if session.bot else "AI Assistant",
            "created_at": session.created_at,
        },
        "messages": [
            {
                "id": m.id,
                "user_message": m.user_message,
                "assistant_response": m.assistant_response,
                "created_at": m.created_at,
            }
            for m in messages
        ],
    }
