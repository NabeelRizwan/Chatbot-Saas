"""Authenticated dashboard delivery through the normal durable turn lifecycle."""
import json

import anyio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from database.models import ConversationSession
from .broker import SAFE_ERROR, get_broker, is_enabled
from .models import ChatTurn


def enqueue_dashboard_turn(db, bot, data, *, session_id, turn_id, usage_key, snapshot, channel, saved_test=None):
    # Even pre-dispatch failures may be repeats of an already running identity.
    # Resolve the broker before releasing anything; uncertainty must fail closed.
    try:
        broker = get_broker()
    except Exception as exc:
        raise HTTPException(503, SAFE_ERROR) from exc
    try:
        turn = ChatTurn(organization_id=bot.organization_id, bot_id=bot.id,
            session_id=session_id, turn_id=turn_id, message=data.message,
            history=data.history, top_k=data.top_k, retry=getattr(data, "retry", False), usage_key=usage_key,
            pipeline_snapshot=snapshot, channel=channel, saved_test=saved_test)
    except ValidationError as exc:
        identity = ChatTurn(organization_id=bot.organization_id, bot_id=bot.id,
            session_id=session_id, turn_id=turn_id, message="Invalid request", usage_key=usage_key)
        db.rollback()
        broker.release_if_undispatched(identity)
        raise HTTPException(422, "Chat request exceeds the supported execution limits.") from exc
    if not is_enabled():
        db.rollback()
        broker.release_if_undispatched(turn)
        raise HTTPException(503, "The knowledge execution queue is unavailable.")
    try:
        session = db.query(ConversationSession).filter(ConversationSession.bot_id == bot.id,
            ConversationSession.organization_id == bot.organization_id,
            ConversationSession.session_id == session_id).first()
        if session is None:
            db.add(ConversationSession(bot_id=bot.id, organization_id=bot.organization_id,
                                       session_id=session_id, channel=channel))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                if db.query(ConversationSession).filter(ConversationSession.bot_id == bot.id,
                ConversationSession.organization_id == bot.organization_id,
                ConversationSession.session_id == session_id).first() is None:
                    raise
    except Exception as exc:
        db.rollback()
        broker.release_if_undispatched(turn)
        raise HTTPException(503, SAFE_ERROR) from exc
    db.rollback()
    try:
        job = broker.enqueue(turn)
    except Exception as exc:
        # Uncertain dispatch retains its reservation until worker settlement.
        raise HTTPException(503, SAFE_ERROR) from exc
    return broker, job, turn


def dashboard_result(broker, job, turn):
    for event in broker.iterate(job.job_id, turn.organization_id, turn.bot_id, turn.session_id):
        if event.get("type") == "error":
            raise HTTPException(503, SAFE_ERROR)
    state = broker.load(job.job_id, turn.organization_id, turn.bot_id, turn.session_id)
    if state.get("state") != "success":
        raise HTTPException(503, SAFE_ERROR)
    return state["result"]


async def dashboard_events(broker, job, turn):
    terminal = False
    events = broker.iterate(job.job_id, turn.organization_id, turn.bot_id, turn.session_id)
    try:
        yield "data: " + json.dumps({"type": "meta", "session_id": turn.session_id,
            "turn_id": turn.turn_id, "queued": job.state == "queued", "buffered": True}) + "\n\n"
        while True:
            event = await anyio.to_thread.run_sync(lambda: next(events, None))
            if event is None:
                break
            if event.get("type") == "keepalive":
                yield ": keepalive\n\n"
                continue
            if event.get("type") == "done":
                state = await anyio.to_thread.run_sync(lambda: broker.load(
                    job.job_id, turn.organization_id, turn.bot_id, turn.session_id))
                result = state.get("result", {})
                yield "data: " + json.dumps({"sources": result.get("sources", []),
                    "retrieved_chunks": result.get("retrieved_chunks", [])}) + "\n\n"
                terminal = True
            # An error event can be a cancellation request while work still runs;
            # durable cancellation below never releases the reservation early.
            yield "data: " + json.dumps(event) + "\n\n"
            if event.get("type") in {"done", "error"}:
                return
    finally:
        if not terminal:
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(lambda: broker.cancel(
                    job.job_id, turn.organization_id, turn.bot_id, turn.session_id))
        events.close()
