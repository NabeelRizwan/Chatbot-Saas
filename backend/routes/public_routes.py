import json
from time import perf_counter
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import Bot, ConversationSession, ConversationMessage
from schemas.schemas import (
    PublicChatRequest,
    PublicChatResponse,
    PublicSessionResponse,
    PublicTurnAbortRequest,
    PublicWidgetConfigResponse,
)
from services.analytics_service import record_widget_chat_message, track_widget_chat_message
from services.llm_router import LLMRouterError
from services.observability_service import ChatTrace, compact_chat_diagnostics, track_chat_completion
from services.rag_service import answer_question, iter_approved_answer_chunks, stream_answer_question
from services.usage_service import (
    consume_message_quota,
    ensure_can_send_message,
    heartbeat_message_quota,
    release_message_quota,
    set_message_quota_context,
)
from services.public_access_service import (
    enforce_public_origin,
    issue_public_session,
    validate_public_session,
)

from utils.rate_limiter import enforce_rate_limit

router = APIRouter()
SAFE_PUBLIC_ERROR = "We couldn't complete that reply. Please retry in a moment."


def _public_stream_sources(sources: list[dict]) -> list[dict]:
    def safe_url(value):
        if not isinstance(value, str):
            return None
        try:
            parsed = urlsplit(value)
        except ValueError:
            return None
        return value if parsed.scheme.lower() in {"http", "https"} and parsed.hostname else None

    public_sources = []
    seen_sources = set()
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        source_url = safe_url(source.get("source_url"))
        cta_links = []
        seen_ctas = set()
        for cta in source.get("cta_links", []) or []:
            if not isinstance(cta, dict):
                continue
            url = safe_url(cta.get("url"))
            if not url or url in seen_ctas:
                continue
            seen_ctas.add(url)
            cta_links.append(
                {"label": str(cta.get("label") or "View")[:120], "url": url}
            )
        identity = (source_url, str(source.get("title") or source.get("filename") or "Source"))
        if identity in seen_sources or (not source_url and not cta_links):
            continue
        seen_sources.add(identity)
        public_sources.append(
            {
                "title": identity[1][:200],
                "source_url": source_url,
                "source_type": str(source.get("source_type") or "website")[:80],
                "cta_links": cta_links,
            }
        )
    return public_sources


def get_public_bot_or_404(db: Session, bot_id: int) -> Bot:
    bot = db.query(Bot).filter(Bot.id == bot_id).first()
    if not bot or bot.status != "active":
        raise HTTPException(status_code=404, detail="Bot not found")
    return bot


@router.get("/widget/{bot_id}", response_model=PublicWidgetConfigResponse)
def get_widget_config(
    bot_id: int = Path(..., gt=0),
    request: Request = None,
    db: Session = Depends(get_db),
):
    bot = get_public_bot_or_404(db, bot_id)
    enforce_public_origin(bot, request)
    default_config = {
        "bot_id": bot.id,
        "bot_name": bot.name,
        "welcome_message": bot.welcome_message or "Hi, how can I help you today?",
        "primary_color": "#2563eb",
        "accent_color": "#0f172a",
        "launcher_text": "Chat",
        "launcher_title": "Chat with us",
        "launcher_icon": "message",
        "bot_avatar_url": bot.avatar_url,
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
    # The builder/customizer's primary per-bot field wins over legacy config.
    default_config["welcome_message"] = (
        (bot.welcome_message or "").strip()
        or str(default_config.get("welcome_message") or "").strip()
        or "Hi, how can I help you today?"
    )
    return default_config


@router.post("/widget/{bot_id}/session", response_model=PublicSessionResponse)
def create_widget_session(
    bot_id: int = Path(..., gt=0),
    request: Request = None,
    db: Session = Depends(get_db),
):
    bot = get_public_bot_or_404(db, bot_id)
    enforce_public_origin(bot, request)
    session_id, session_token = issue_public_session(db, bot)
    return {"session_id": session_id, "session_token": session_token}


def _enforce_public_turn_access(
    *,
    db: Session,
    bot: Bot,
    data: PublicChatRequest | PublicTurnAbortRequest,
    request: Request | None,
    check_quota: bool = True,
) -> str | None:
    enforce_public_origin(bot, request)
    validate_public_session(
        db,
        bot,
        data.session_id,
        data.session_token,
        allow_internal_test_call=request is None,
    )
    if request is None:
        # Preserve direct unit-call compatibility while real HTTP receives all
        # three independently scoped controls.
        enforce_rate_limit(
            scope="public_chat",
            org_id=bot.organization_id,
            bot_id=bot.id,
            client_id=data.session_id,
        )
    else:
        client_ip = request.client.host if request.client else "unknown"
        for client_id in (f"session:{data.session_id}", f"ip:{client_ip}", "bot-wide"):
            enforce_rate_limit(
                scope="public_chat",
                org_id=bot.organization_id,
                bot_id=bot.id,
                client_id=client_id,
            )
    if check_quota:
        key = (
            f"widget:{bot.id}:{data.session_id}:{getattr(data, 'turn_id', None)}"
            if data.session_id and getattr(data, "turn_id", None)
            else None
        )
        set_message_quota_context(db, idempotency_key=key, channel="widget")
        return ensure_can_send_message(db, bot.organization_id)
    return None


def _existing_public_turn(db: Session, bot_id: int, session_id: str | None, turn_id: str | None):
    if not session_id or not turn_id:
        return None
    return (
        db.query(ConversationMessage)
        .filter(ConversationMessage.bot_id == bot_id)
        .filter(ConversationMessage.session_id == session_id)
        .filter(ConversationMessage.client_turn_id == turn_id)
        .first()
    )


@router.post("/chat/{bot_id}", response_model=PublicChatResponse)
def public_chat(
    data: PublicChatRequest,
    background_tasks: BackgroundTasks,
    bot_id: int = Path(..., gt=0),
    request: Request = None,
    db: Session = Depends(get_db),
):
    bot = get_public_bot_or_404(db, bot_id)
    if request is not None and not data.turn_id:
        raise HTTPException(status_code=422, detail="turn_id is required")
    usage_key = _enforce_public_turn_access(db=db, bot=bot, data=data, request=request)
    existing = _existing_public_turn(db, bot.id, data.session_id, data.turn_id)
    if existing and existing.status == "success" and existing.assistant_response:
        return {
            "session_id": data.session_id,
            "reply": existing.assistant_response,
            "answer": existing.assistant_response,
            "sources": [],
            "retrieved_chunks": [],
        }

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
        release_message_quota(db, bot.organization_id, usage_key)
        trace.provider_error = True
        track_chat_completion(trace, status="error")
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except Exception:
        release_message_quota(db, bot.organization_id, usage_key)
        track_chat_completion(trace, status="error")
        raise

    track_chat_completion(trace, status="success")
    response_time_ms = int((perf_counter() - started_at) * 1000)
    if data.session_id:
        # Persist the billable success before acknowledging it. This closes the
        # former crash window between the HTTP response and a background task.
        track_widget_chat_message(
            bot_id=bot.id,
            session_id=data.session_id,
            user_message=data.message,
            assistant_response=reply,
            response_time_ms=response_time_ms,
            status="success",
            is_fallback=trace.used_fallback,
            had_knowledge_hit=bool(sources or retrieved_chunks),
            retrieval_attempted=trace.used_retrieval,
            client_turn_id=data.turn_id,
            allow_aborted_retry=data.retry,
            usage_reservation_key=usage_key,
            token_usage=compact_chat_diagnostics(trace),
        )
    else:
        consume_message_quota(db, bot.organization_id, usage_key)

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
    request: Request = None,
    db: Session = Depends(get_db),
):
    bot = get_public_bot_or_404(db, bot_id)
    if request is not None and not data.turn_id:
        raise HTTPException(status_code=422, detail="turn_id is required")
    usage_key = _enforce_public_turn_access(db=db, bot=bot, data=data, request=request)
    started_at = perf_counter()
    trace = ChatTrace(bot_id=bot.id, channel="widget_stream")

    def events():
        reply = ""
        sources = []
        approved_chunks = []
        last_heartbeat = perf_counter()
        try:
            existing = _existing_public_turn(db, bot.id, data.session_id, data.turn_id)
            yield f"data: {json.dumps({'type': 'meta', 'session_id': data.session_id, 'turn_id': data.turn_id, 'buffered': True})}\n\n"
            if existing and existing.status == "success" and existing.assistant_response:
                reply = existing.assistant_response
            else:
                legacy_parts = []
                for result in stream_answer_question(
                    db=db,
                    bot=bot,
                    question=data.message,
                    top_k=data.top_k,
                    history=data.history,
                    trace=trace,
                    include_metadata=True,
                ):
                    if perf_counter() - last_heartbeat >= 30:
                        heartbeat_message_quota(db, bot.organization_id, usage_key)
                        last_heartbeat = perf_counter()
                    if isinstance(result, dict):
                        reply = str(result.get("reply") or "")
                        sources = _public_stream_sources(result.get("sources") or [])
                    else:
                        legacy_parts.append(str(result))
                if not reply:
                    reply = "".join(legacy_parts)
                    approved_chunks = legacy_parts
            if not reply.strip():
                raise RuntimeError("The safe answer pipeline returned an empty response")
            # Deliver the approved answer before persistence so customers are not
            # blocked on analytics/DB write after the quality pipeline finishes.
            delivery_started = perf_counter()
            if not approved_chunks:
                approved_chunks = iter_approved_answer_chunks(reply)
            for token in approved_chunks:
                yield f"data: {json.dumps({'type': 'token', 'token': token})}\n\n"
            if sources:
                yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'done': True})}\n\n"
            trace.timings_ms["sse_delivery_ms"] = int((perf_counter() - delivery_started) * 1000)
            should_record_success = (
                not existing
                or (
                    data.retry
                    and getattr(existing, "status", None) in {"error", "aborted"}
                )
            )
            if should_record_success and data.session_id:
                track_widget_chat_message(
                    bot_id=bot.id,
                    session_id=data.session_id,
                    user_message=data.message,
                    assistant_response=reply,
                    response_time_ms=int((perf_counter() - started_at) * 1000),
                    status="success",
                    is_fallback=trace.used_fallback,
                    had_knowledge_hit=bool(sources),
                    retrieval_attempted=trace.used_retrieval,
                    client_turn_id=data.turn_id,
                    allow_aborted_retry=data.retry,
                    usage_reservation_key=usage_key,
                    token_usage=compact_chat_diagnostics(trace),
                )
            track_chat_completion(trace, status="success")
        except Exception:
            trace.provider_error = True
            if data.session_id:
                track_widget_chat_message(
                    bot_id=bot.id,
                    session_id=data.session_id,
                    user_message=data.message,
                    assistant_response=None,
                    response_time_ms=int((perf_counter() - started_at) * 1000),
                    status="error",
                    error_message=SAFE_PUBLIC_ERROR,
                    client_turn_id=data.turn_id,
                    usage_reservation_key=usage_key,
                )
            track_chat_completion(trace, status="error")
            yield f"data: {json.dumps({'type': 'error', 'message': SAFE_PUBLIC_ERROR, 'retryable': True})}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/{bot_id}/abort", status_code=204)
def abort_public_turn(
    data: PublicTurnAbortRequest,
    bot_id: int = Path(..., gt=0),
    request: Request = None,
    db: Session = Depends(get_db),
):
    bot = get_public_bot_or_404(db, bot_id)
    enforce_public_origin(bot, request)
    validate_public_session(
        db, bot, data.session_id, data.session_token, allow_internal_test_call=request is None
    )
    record_widget_chat_message(
        db=db,
        bot_id=bot.id,
        session_id=data.session_id,
        user_message=None,
        assistant_response=None,
        response_time_ms=None,
        status="aborted",
        error_message="Visitor aborted the pending turn",
        client_turn_id=data.turn_id,
        usage_reservation_key=f"widget:{bot.id}:{data.session_id}:{data.turn_id}",
    )
    return None


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
