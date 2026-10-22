"""Durable saved-question results share chat billing and worker fencing."""
from datetime import datetime
import json

from database.experience_models import SavedTestRun, SavedTestResult
from .models import ChatExecutionError

FINISHED = {"passed_checks", "needs_review", "manual_review"}
SAFE_ERROR = "Answer request failed. Check service diagnostics; retry in a new run."


def records(db, turn, *, lock=False):
    reference = turn.saved_test
    query = db.query(SavedTestRun).filter(SavedTestRun.id == reference.run_id,
        SavedTestRun.organization_id == turn.organization_id, SavedTestRun.bot_id == turn.bot_id)
    run = (query.with_for_update() if lock else query).populate_existing().first()
    result = db.query(SavedTestResult).filter(SavedTestResult.id == reference.result_id,
        SavedTestResult.run_id == reference.run_id).populate_existing().first() if run else None
    if run is None or result is None:
        raise ChatExecutionError("Saved question is no longer available")
    return run, result


def accepted_result(db, turn, bot):
    run, result = records(db, turn)
    if result.status in FINISHED and result.answer:
        return {"reply": result.answer, "answer": result.answer, "sources": result.sources,
                "retrieved_chunks": [], "session_id": turn.session_id}
    if (run.lease_token != turn.saved_test.lease_token or result.status != "running"
            or run.status != "running" or run.provider != bot.provider or run.model != bot.model_name):
        raise ChatExecutionError("Saved question execution authority changed")
    if result.question != turn.message:
        raise ChatExecutionError("Saved question execution input changed")
    return None


def settle_result(db, turn, *, answer=None, sources=None, latency_ms=None, error=False):
    from services.experience_service import score_phrases
    from services.usage_service import release_message_quota
    # The legacy quota helper starts its own transaction with rollback. Release
    # before touching result rows, then reacquire their lease for the final write.
    if error and turn.usage_key:
        release_message_quota(db, turn.organization_id, turn.usage_key)
    run, result = records(db, turn, lock=True)
    if result.status in FINISHED:
        return False
    if run.lease_token != turn.saved_test.lease_token or result.status != "running":
        if error:
            return False
        raise ChatExecutionError("Saved question execution lease changed")
    result.answer = answer
    result.sources = json.loads(json.dumps(sources or [], default=str))
    result.latency_ms = latency_ms
    result.error = SAFE_ERROR if error else None
    if error:
        result.status = "error"
    else:
        result.status, result.missing_phrases, result.forbidden_matches = score_phrases(
            answer, result.required_phrases, result.forbidden_phrases)
    db.flush()
    pending = db.query(SavedTestResult).filter(SavedTestResult.run_id == run.id,
        SavedTestResult.status == "pending").first()
    run.lease_token, run.lease_expires_at = None, None
    if pending is None:
        run.status, run.completed_at = "completed", datetime.utcnow()
    db.commit()
    return True


def refresh_run(db, bot, run):
    """Poll only an accepted saved turn; never dispatch or regenerate on GET."""
    if run.status != "running" or not run.lease_token:
        return
    from .broker import get_broker
    from .models import ChatTurn
    result = db.query(SavedTestResult).filter(SavedTestResult.run_id == run.id,
        SavedTestResult.status == "running").first()
    if result is None:
        return
    identity = f"saved-test:{run.id}:{result.id}"
    turn = ChatTurn(organization_id=bot.organization_id, bot_id=bot.id,
        session_id=identity, turn_id=identity, message=result.question)
    try:
        broker = get_broker()
        # Legacy synchronous runs have no payload and are left unchanged.
        if broker.redis.exists(broker.key(turn.job_id, "payload")):
            db.rollback()
            broker.load(turn.job_id, turn.organization_id, turn.bot_id, turn.session_id)
            db.expire_all()
    except Exception:
        # A temporary relay failure is not proof that work never started.
        db.rollback()


def execute_next(db, bot, run_id, snapshot):
    from datetime import timedelta
    from types import SimpleNamespace
    from uuid import uuid4
    from fastapi import HTTPException
    from sqlalchemy import or_
    from database.models import MessageUsageReservation
    from services.experience_service import record_or_404, scoped, serialize_run
    from services.usage_service import ensure_can_send_message
    from .dashboard import enqueue_dashboard_turn
    from .models import SavedTestReference
    from .limits import rag2_execution_timeout
    import os

    run = record_or_404(db, SavedTestRun, bot, run_id)
    refresh_run(db, bot, run)
    if run.status == "completed":
        return serialize_run(db, run)
    if run.provider != bot.provider or run.model != bot.model_name:
        raise HTTPException(409, "The bot model changed. Cancel this run and create a new one.")
    now, token = datetime.utcnow(), uuid4().hex
    lifetime = int(os.getenv("CHAT_EXECUTION_QUEUE_TIMEOUT_SECONDS", "120")) + rag2_execution_timeout() + 120
    claimed = scoped(db, SavedTestRun, bot).filter(SavedTestRun.id == run_id,
        SavedTestRun.status != "completed", or_(SavedTestRun.lease_expires_at.is_(None),
        SavedTestRun.lease_expires_at < now)).update({"lease_token": token,
        "lease_expires_at": now + timedelta(seconds=lifetime), "status": "running"}, synchronize_session=False)
    db.commit()
    if not claimed:
        db.expire_all()
        return serialize_run(db, record_or_404(db, SavedTestRun, bot, run_id))
    for previous in db.query(SavedTestResult).filter_by(run_id=run_id, status="running").all():
        previous.status = "error"
        previous.error = "Interrupted test. Start a new run to retry this question."
    result = db.query(SavedTestResult).filter_by(run_id=run_id, status="pending").order_by(SavedTestResult.position).first()
    run = record_or_404(db, SavedTestRun, bot, run_id)
    if result is None:
        run.status, run.completed_at, run.lease_token, run.lease_expires_at = "completed", now, None, None
        db.commit()
        return serialize_run(db, run)
    result.status = "running"
    result_id, question = result.id, result.question
    db.commit()
    identity = f"saved-test:{run_id}:{result_id}"
    key = None
    try:
        key = ensure_can_send_message(db, bot.organization_id, idempotency_key=identity, channel="saved_test")
        enqueue_dashboard_turn(db, bot, SimpleNamespace(message=question, history=[], top_k=4, retry=False),
            session_id=identity, turn_id=identity, usage_key=key, snapshot=snapshot, channel="saved_test",
            saved_test=SavedTestReference(run_id=run_id, result_id=result_id, lease_token=token))
    except Exception:
        db.rollback()
        # No reservation or a proven rejection is safe to finalize immediately.
        # Unknown scheduling outcomes remain running; polling never redispatches.
        reservation = db.query(MessageUsageReservation).filter_by(
            organization_id=bot.organization_id, idempotency_key=key).first() if key else None
        if key is None or (reservation is not None and reservation.status == "released"):
            run = record_or_404(db, SavedTestRun, bot, run_id)
            result = db.query(SavedTestResult).filter_by(id=result_id, run_id=run_id).one()
            if run.lease_token == token:
                result.status, result.error = "error", SAFE_ERROR
                run.lease_token, run.lease_expires_at = None, None
                db.flush()
                if not db.query(SavedTestResult).filter_by(run_id=run_id, status="pending").first():
                    run.status, run.completed_at = "completed", datetime.utcnow()
                db.commit()
        else:
            raise HTTPException(503, "Test scheduling confirmation is pending. Refresh this run; do not start it again.") from None
    db.expire_all()
    return serialize_run(db, record_or_404(db, SavedTestRun, bot, run_id))
