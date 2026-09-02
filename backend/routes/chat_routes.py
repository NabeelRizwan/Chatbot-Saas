import json
from time import monotonic
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import User
from schemas.schemas import ChatRequest, ChatResponse, PublicChatRequest
from services.auth_service import get_current_user
from services.llm_router import LLMRouterError
from services.observability_service import ChatTrace, compact_chat_diagnostics, track_chat_completion
from services.rag_service import answer_question, iter_approved_answer_chunks, stream_answer_question
from services.analytics_service import record_widget_chat_message
from services.usage_service import (
    consume_message_quota,
    ensure_can_send_message,
    heartbeat_message_quota,
    release_message_quota,
    set_message_quota_context,
)
from utils.rate_limiter import enforce_rate_limit
from utils.helpers import get_owned_bot

router = APIRouter()


@router.post("/", response_model=ChatResponse)
def chat(data: ChatRequest, db: Session = Depends(get_db)):
    _, bot = get_owned_bot(db, api_key=data.api_key, bot_id=data.bot_id)
    enforce_rate_limit(scope="auth_chat", org_id=bot.organization_id, bot_id=bot.id)
    set_message_quota_context(db, idempotency_key=None, channel="api")
    usage_key = ensure_can_send_message(db, bot.organization_id)

    trace = ChatTrace(bot_id=bot.id, channel="playground")
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

    consume_message_quota(db, bot.organization_id, usage_key)
    track_chat_completion(trace, status="success")
    return {
        "reply": reply,
        "answer": reply,
        "sources": sources,
        "retrieved_chunks": retrieved_chunks,
    }


@router.post("/stream")
def chat_stream(data: ChatRequest, db: Session = Depends(get_db)):
    _, bot = get_owned_bot(db, api_key=data.api_key, bot_id=data.bot_id)
    set_message_quota_context(db, idempotency_key=None, channel="api_stream")
    usage_key = ensure_can_send_message(db, bot.organization_id)
    trace = ChatTrace(bot_id=bot.id, channel="playground_stream")

    def events():
        emitted = False
        settled = False
        last_heartbeat = monotonic()
        try:
            for result in stream_answer_question(
                db=db,
                bot=bot,
                question=data.message,
                top_k=data.top_k,
                history=data.history,
                trace=trace,
                include_metadata=True,
            ):
                if monotonic() - last_heartbeat >= 30:
                    heartbeat_message_quota(db, bot.organization_id, usage_key)
                    last_heartbeat = monotonic()
                if not isinstance(result, dict):
                    raise RuntimeError("The answer pipeline returned invalid streaming metadata")
                reply = str(result.get("reply") or "")
                if not reply:
                    raise RuntimeError("The answer pipeline returned an empty response")
                emitted = True
                for token in iter_approved_answer_chunks(reply):
                    yield f"data: {json.dumps({'token': token})}\n\n"
                yield f"data: {json.dumps({'sources': result.get('sources') or [], 'retrieved_chunks': result.get('retrieved_chunks') or []})}\n\n"
            if not emitted:
                raise RuntimeError("The answer pipeline returned an empty response")
            yield f"data: {json.dumps({'done': True})}\n\n"
            consume_message_quota(db, bot.organization_id, usage_key)
            settled = True
            track_chat_completion(trace, status="success")
        except Exception:
            release_message_quota(db, bot.organization_id, usage_key)
            settled = True
            trace.provider_error = True
            track_chat_completion(trace, status="error")
            yield f"data: {json.dumps({'token': 'Sorry, I had trouble generating a response. Please try again in a moment.'})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        finally:
            if not settled:
                release_message_quota(db, bot.organization_id, usage_key)

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/{bot_id}", response_model=ChatResponse)
def dashboard_playground_chat(
    bot_id: int,
    data: PublicChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from services.bot_service import get_bot_or_404
    from time import perf_counter
    bot = get_bot_or_404(db, bot_id, user=current_user, minimum_role="viewer")
    
    turn_id = data.turn_id or uuid4().hex
    session_id = f"dashboard:{current_user.id}:{data.session_id or bot.id}"
    set_message_quota_context(
        db,
        idempotency_key=f"dashboard:{bot.id}:{session_id}:{turn_id}",
        channel="playground",
    )
    usage_key = ensure_can_send_message(db, bot.organization_id)
    started_at = perf_counter()
    trace = ChatTrace(bot_id=bot.id, channel="playground")
    
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

    response_time_ms = int((perf_counter() - started_at) * 1000)
    persist_started_at = perf_counter()
    if isinstance(usage_key, str):
        record_widget_chat_message(
            db=db,
            bot_id=bot.id,
            session_id=session_id,
            client_turn_id=turn_id,
            user_message=data.message,
            assistant_response=reply,
            response_time_ms=response_time_ms,
            status="success",
            is_fallback=trace.used_fallback,
            had_knowledge_hit=bool(sources or retrieved_chunks),
            retrieval_attempted=trace.used_retrieval,
            usage_reservation_key=usage_key,
            channel="playground",
            token_usage=compact_chat_diagnostics(trace),
        )
    if trace:
        trace.mark("persistence_ms", persist_started_at)
    track_chat_completion(trace, status="success")
    
    return {
        "reply": reply,
        "answer": reply,
        "sources": sources,
        "retrieved_chunks": retrieved_chunks,
        "latency_ms": response_time_ms,
        "model_name": bot.model_name,
        "provider": bot.provider,
            "_debug": {
            "intent": trace.intent,
            "cache_hit": trace.cache_hit,
            "confidence": trace.confidence,
            "used_retrieval": trace.used_retrieval,
            "memory_turns": trace.memory_turns,
            "timings_ms": trace.timings_ms,
            "diagnostics": trace.compact_diagnostics(),
        },
    }


@router.post("/{bot_id}/stream")
def dashboard_playground_chat_stream(
    bot_id: int,
    data: PublicChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from services.bot_service import get_bot_or_404
    bot = get_bot_or_404(db, bot_id, user=current_user, minimum_role="viewer")
    
    turn_id = data.turn_id or uuid4().hex
    session_id = f"dashboard:{current_user.id}:{data.session_id or bot.id}"
    set_message_quota_context(
        db,
        idempotency_key=f"dashboard:{bot.id}:{session_id}:{turn_id}",
        channel="playground_stream",
    )
    usage_key = ensure_can_send_message(db, bot.organization_id)
    trace = ChatTrace(bot_id=bot.id, channel="playground_stream")

    def events():
        emitted = False
        parts = []
        settled = False
        last_heartbeat = monotonic()
        try:
            sources = []
            retrieved_chunks = []
            for result in stream_answer_question(
                db=db,
                bot=bot,
                question=data.message,
                top_k=data.top_k,
                history=data.history,
                trace=trace,
                include_metadata=True,
            ):
                if monotonic() - last_heartbeat >= 30:
                    heartbeat_message_quota(db, bot.organization_id, usage_key)
                    last_heartbeat = monotonic()
                if not isinstance(result, dict):
                    raise RuntimeError("The answer pipeline returned invalid streaming metadata")
                reply = str(result.get("reply") or "")
                if not reply:
                    raise RuntimeError("The answer pipeline returned an empty response")
                sources = result.get("sources") or []
                retrieved_chunks = result.get("retrieved_chunks") or []
                emitted = True
                parts.append(reply)
                for token in iter_approved_answer_chunks(reply):
                    yield f"data: {json.dumps({'token': token})}\n\n"
                yield f"data: {json.dumps({'sources': sources, 'retrieved_chunks': retrieved_chunks})}\n\n"
            if not emitted:
                raise RuntimeError("The answer pipeline returned an empty response")
            yield f"data: {json.dumps({'done': True})}\n\n"
            if isinstance(usage_key, str):
                record_widget_chat_message(
                    db=db,
                    bot_id=bot.id,
                    session_id=session_id,
                    client_turn_id=turn_id,
                    user_message=data.message,
                    assistant_response="".join(parts),
                    response_time_ms=None,
                    status="success",
                    is_fallback=trace.used_fallback,
                    had_knowledge_hit=bool(sources or retrieved_chunks),
                    retrieval_attempted=trace.used_retrieval,
                    usage_reservation_key=usage_key,
                    channel="playground_stream",
                    token_usage=compact_chat_diagnostics(trace),
                )
            settled = True
            track_chat_completion(trace, status="success")
        except Exception:
            release_message_quota(db, bot.organization_id, usage_key)
            settled = True
            trace.provider_error = True
            track_chat_completion(trace, status="error")
            yield f"data: {json.dumps({'token': 'Sorry, I had trouble generating a response. Please try again in a moment.'})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        finally:
            if not settled:
                release_message_quota(db, bot.organization_id, usage_key)

    return StreamingResponse(events(), media_type="text/event-stream")
