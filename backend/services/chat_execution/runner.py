import time
import threading
import os
import logging

from .broker import SAFE_ERROR, ChatExecutionBroker
from .models import ChatExecutionError, ChatTurn
from .settlement import turn_settlement


def execute_turn(turn: ChatTurn, broker: ChatExecutionBroker, cancelled, *, expected_dispatch_id=None) -> dict:
    """Run the existing pipeline and commit its normal billable result first."""
    from database.connection import SessionLocal
    from database.models import Bot, ConversationMessage, ConversationSession
    from services.analytics_service import record_widget_chat_message
    from services.observability_service import ChatTrace, compact_chat_diagnostics, track_chat_completion
    from services.rag_service import answer_question
    from services.usage_service import heartbeat_message_quota, release_message_quota, consume_message_quota
    from services.llama_rag.client_runtime import retrieval_request_context
    from services.provider_capacity import provider_capacity_context
    from services.llm_router import generation_stream_context
    from services.rag_service import iter_approved_answer_chunks

    started = time.perf_counter()
    trace = ChatTrace(bot_id=turn.bot_id, channel="widget_queued")
    with SessionLocal() as db:
        bot = db.query(Bot).filter(Bot.id == turn.bot_id,
            Bot.organization_id == turn.organization_id, Bot.status == "active").first()
        session = db.query(ConversationSession).filter(
            ConversationSession.bot_id == turn.bot_id,
            ConversationSession.organization_id == turn.organization_id,
            ConversationSession.session_id == turn.session_id).first()
        if not bot or not session:
            db.rollback()
            release_pending(turn, broker=broker, expected_dispatch_id=expected_dispatch_id)
            raise ChatExecutionError("Chat access changed while the request was waiting")
        existing = db.query(ConversationMessage).filter(
            ConversationMessage.bot_id == turn.bot_id,
            ConversationMessage.session_id == turn.session_id,
            ConversationMessage.client_turn_id == turn.turn_id).first()
        if existing and existing.status == "success" and existing.assistant_response:
            return {"reply": existing.assistant_response, "answer": existing.assistant_response,
                    "session_id": turn.session_id, "sources": [], "retrieved_chunks": []}
        if cancelled() or (existing and existing.status == "aborted" and not turn.retry):
            db.rollback()
            release_pending(turn, broker=broker, expected_dispatch_id=expected_dispatch_id)
            raise InterruptedError("Chat turn cancelled")
        if turn.usage_key and not heartbeat_message_quota(db, turn.organization_id, turn.usage_key):
            raise InterruptedError("Chat usage reservation is no longer active")
        cancel_event = threading.Event()
        monitor_stop = threading.Event()
        def monitor():
            heartbeat_at = time.monotonic()
            while not monitor_stop.wait(0.25):
                try:
                    if cancelled():
                        cancel_event.set()
                    if time.monotonic() - heartbeat_at >= 25:
                        with SessionLocal() as heartbeat_db:
                            if turn.usage_key and not heartbeat_message_quota(heartbeat_db, turn.organization_id, turn.usage_key):
                                cancel_event.set()
                        heartbeat_at = time.monotonic()
                except Exception:
                    # Losing the cancellation/lease store stops new downstream calls.
                    cancel_event.set()
                    return
        monitor_thread = threading.Thread(target=monitor, name="chat-turn-lease", daemon=True)
        monitor_thread.start()
        streamed = []
        def on_delta(text):
            if cancelled() or cancel_event.is_set():
                raise InterruptedError("Chat turn cancelled")
            if not streamed:
                trace.timings_ms["first_visible_text_ms"] = int((time.perf_counter() - started) * 1000)
            for part in iter_approved_answer_chunks(text):
                broker.publish(turn.job_id, {"type": "token", "token": part},
                               expected_dispatch_id=expected_dispatch_id)
            streamed.append(len(text))
        sink = on_delta if os.getenv("CHAT_STREAM_MODE", "buffered") == "progressive" else None
        try:
            with retrieval_request_context(timeout=broker.execution_timeout, cancel_event=cancel_event), \
                    provider_capacity_context(timeout=broker.execution_timeout, cancel_event=cancel_event), \
                    generation_stream_context(sink, cancel_event=cancel_event):
                reply, sources, chunks = answer_question(
                    db=db, bot=bot, question=turn.message, top_k=turn.top_k,
                    history=turn.history, trace=trace, session_id=turn.session_id)
            if cancelled() or cancel_event.is_set():
                raise InterruptedError("Chat turn cancelled")
            if not reply.strip():
                raise ChatExecutionError("The answer pipeline returned no reply")
            db.rollback()  # The settlement owns its own connection; do not retain the retrieval transaction.
            with turn_settlement(turn) as settlement_db:
                if not _current_dispatch(broker, turn, expected_dispatch_id):
                    raise InterruptedError("Chat turn was superseded before persistence")
                settled_db = settlement_db or db
                # Refresh cancellation and tenant state before persisting any result.
                settled_db.expire_all()
                bot = settled_db.query(Bot).filter(Bot.id == turn.bot_id,
                    Bot.organization_id == turn.organization_id, Bot.status == "active").first()
                if not bot:
                    raise ChatExecutionError("Chat access changed")
                if turn.usage_key and not consume_message_quota(settled_db, turn.organization_id, turn.usage_key, commit=False):
                    raise InterruptedError("Chat usage reservation was released before persistence")
                recorded = record_widget_chat_message(
                    db=settled_db, bot_id=turn.bot_id, session_id=turn.session_id,
                    user_message=turn.message, assistant_response=reply,
                    response_time_ms=int((time.perf_counter() - started) * 1000),
                    status="success", client_turn_id=turn.turn_id,
                    allow_aborted_retry=turn.retry, usage_reservation_key=turn.usage_key,
                    token_usage=compact_chat_diagnostics(trace), is_fallback=trace.used_fallback,
                    had_knowledge_hit=bool(sources or chunks), retrieval_attempted=trace.used_retrieval)
                if not recorded:
                    settled_db.rollback()
                    existing = settled_db.query(ConversationMessage).filter(
                        ConversationMessage.bot_id == turn.bot_id,
                        ConversationMessage.session_id == turn.session_id,
                        ConversationMessage.client_turn_id == turn.turn_id).first()
                    if not existing or existing.status != "success":
                        raise InterruptedError("Chat turn was cancelled before persistence")
                    reply = existing.assistant_response
            track_chat_completion(trace, status="success")
            return {"reply": reply, "answer": reply, "session_id": turn.session_id,
                    "sources": sources, "retrieved_chunks": chunks, "_streamed": bool(streamed)}
        except BaseException as exc:
            logging.getLogger(__name__).warning("queued_chat_failed category=%s", type(exc).__name__)
            trace.diagnostics["chat_execution_failure"] = {"category": type(exc).__name__}
            db.rollback()
            with turn_settlement(turn) as settlement_db:
                if _current_dispatch(broker, turn, expected_dispatch_id):
                    record_widget_chat_message(
                        db=settlement_db or db, bot_id=turn.bot_id, session_id=turn.session_id,
                        user_message=turn.message, assistant_response=None,
                        response_time_ms=int((time.perf_counter() - started) * 1000),
                        status="aborted" if isinstance(exc, InterruptedError) else "error",
                        client_turn_id=turn.turn_id, usage_reservation_key=turn.usage_key,
                        error_message=SAFE_ERROR, token_usage=compact_chat_diagnostics(trace))
            track_chat_completion(trace, status="error")
            raise
        finally:
            monitor_stop.set()
            monitor_thread.join(timeout=1)


def _current_dispatch(broker, turn, expected_dispatch_id):
    return expected_dispatch_id is None or broker.redis.hget(broker.key(turn.job_id), "dispatch_id") == expected_dispatch_id


def release_pending(turn: ChatTurn, *, broker: ChatExecutionBroker, expected_dispatch_id: str):
    from services.usage_service import release_message_quota
    with turn_settlement(turn) as db:
        if db is not None and _current_dispatch(broker, turn, expected_dispatch_id):
            release_message_quota(db, turn.organization_id, turn.usage_key)
