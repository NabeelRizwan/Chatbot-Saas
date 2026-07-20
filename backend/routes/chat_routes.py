import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import User
from schemas.schemas import ChatRequest, ChatResponse, PublicChatRequest
from services.auth_service import get_current_user
from services.llm_router import LLMRouterError
from services.observability_service import ChatTrace, track_chat_completion
from services.rag_service import answer_question, stream_answer_question
from services.usage_service import ensure_can_send_message
from utils.helpers import get_owned_bot

router = APIRouter()


@router.post("/", response_model=ChatResponse)
def chat(data: ChatRequest, db: Session = Depends(get_db)):
    _, bot = get_owned_bot(db, api_key=data.api_key, bot_id=data.bot_id)
    ensure_can_send_message(db, bot.organization_id)
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
        trace.provider_error = True
        track_chat_completion(trace, status="error")
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

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
    ensure_can_send_message(db, bot.organization_id)
    trace = ChatTrace(bot_id=bot.id, channel="playground_stream")

    def events():
        emitted = False
        try:
            for token in stream_answer_question(
                db=db,
                bot=bot,
                question=data.message,
                top_k=data.top_k,
                history=data.history,
                trace=trace,
            ):
                emitted = True
                yield f"data: {json.dumps({'token': token})}\n\n"
            if not emitted:
                yield f"data: {json.dumps({'token': 'Sorry, I had trouble generating a response. Please try again in a moment.'})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
            track_chat_completion(trace, status="success")
        except LLMRouterError as exc:
            trace.provider_error = True
            track_chat_completion(trace, status="error")
            yield f"data: {json.dumps({'token': 'Sorry, I had trouble generating a response. Please try again in a moment.'})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"

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
    
    ensure_can_send_message(db, bot.organization_id)
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
        trace.provider_error = True
        track_chat_completion(trace, status="error")
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    track_chat_completion(trace, status="success")
    response_time_ms = int((perf_counter() - started_at) * 1000)
    
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
    
    ensure_can_send_message(db, bot.organization_id)
    trace = ChatTrace(bot_id=bot.id, channel="playground_stream")

    def events():
        emitted = False
        try:
            for token in stream_answer_question(
                db=db,
                bot=bot,
                question=data.message,
                top_k=data.top_k,
                history=data.history,
                trace=trace,
            ):
                emitted = True
                yield f"data: {json.dumps({'token': token})}\n\n"
            if not emitted:
                yield f"data: {json.dumps({'token': 'Sorry, I had trouble generating a response. Please try again in a moment.'})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
            track_chat_completion(trace, status="success")
        except LLMRouterError as exc:
            trace.provider_error = True
            track_chat_completion(trace, status="error")
            yield f"data: {json.dumps({'token': 'Sorry, I had trouble generating a response. Please try again in a moment.'})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")

