import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import fakeredis
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.connection import Base
from database.models import (Bot, ConversationMessage, ConversationSession, Customer,
                             MessageUsageReservation, Organization, Plan, Subscription, UsageMonthly)
from services.chat_execution.broker import ChatExecutionBroker
from services.chat_execution.models import ChatTurn, DispatchInput
from services.chat_execution.runner import execute_turn, release_pending
from services.chat_execution.settlement import turn_settlement
from services.chat_execution.workflow import build_task
from services.usage_service import heartbeat_message_quota, reserve_message_quota
from test_chat_execution_fencing import LocalHatchet


@pytest.fixture
def quota_turn(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'settlement.sqlite').as_posix()}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        uid = uuid4().hex
        org = Organization(name=uid, slug=uid)
        plan = Plan(code=uid, name=uid, limits_json={"monthly_messages": 100})
        customer = Customer(name=uid, api_key=uid)
        db.add_all([org, plan, customer])
        db.commit()
        bot = Bot(name=uid, organization_id=org.id, customer_id=customer.id, status="active")
        db.add_all([bot, Subscription(organization_id=org.id, plan_id=plan.id, status="active",
                                     current_period_start=datetime.utcnow())])
        db.commit()
        db.add(ConversationSession(bot_id=bot.id, organization_id=org.id, session_id=uid))
        db.commit()
        key = reserve_message_quota(db, org.id, idempotency_key=f"widget:{bot.id}:{uid}:turn", channel="widget")
        turn = ChatTurn(organization_id=org.id, bot_id=bot.id, session_id=uid,
                        turn_id="turn", message="Question", usage_key=key)
    with patch("database.connection.engine", engine), patch("database.connection.SessionLocal", sessions):
        broker = ChatExecutionBroker(redis_client=fakeredis.FakeRedis(decode_responses=True), hatchet=LocalHatchet())
        broker.enqueue(turn)
        dispatch = broker.redis.hget(broker.key(turn.job_id), "dispatch_id")
        yield broker, turn, dispatch, sessions
    engine.dispose()


def assert_reserved(sessions, turn):
    with sessions() as db:
        assert heartbeat_message_quota(db, turn.organization_id, turn.usage_key)
        assert db.query(MessageUsageReservation).count() == 1
        assert db.query(MessageUsageReservation).one().status == "reserved"


def test_expiry_release_cannot_invalidate_concurrent_retry(quota_turn):
    broker, turn, dispatch, sessions = quota_turn
    broker.redis.hset(broker.key(turn.job_id), "queue_deadline", time.time() - 1)
    entered, resume, retry_started = threading.Event(), threading.Event(), threading.Event()

    def paused_release(*args, **kwargs):
        entered.set()
        assert resume.wait(5)
        return release_pending(*args, **kwargs)

    def retry():
        # Public preflight can run before the old reservation is released.
        with sessions() as db:
            reserve_message_quota(db, turn.organization_id, idempotency_key=turn.usage_key, channel="widget")
        retry_started.set()
        return broker.enqueue(turn.model_copy(update={"retry": True}))

    with ThreadPoolExecutor(max_workers=2) as pool, patch(
            "services.chat_execution.runner.release_pending", side_effect=paused_release):
        observer = pool.submit(broker.load, turn.job_id, turn.organization_id, turn.bot_id, turn.session_id)
        assert entered.wait(5)
        pending = pool.submit(retry)
        assert retry_started.wait(5)
        try:
            time.sleep(0.05)
            assert not pending.done()
        finally:
            resume.set()
        assert observer.result(timeout=5)["state"] == "expired"
        assert pending.result(timeout=5).state == "queued"
    assert broker.redis.hget(broker.key(turn.job_id), "dispatch_id") != dispatch
    release_pending(turn, broker=broker, expected_dispatch_id=dispatch)
    assert_reserved(sessions, turn)


def test_prestart_old_worker_cannot_release_retry(quota_turn):
    broker, turn, dispatch, sessions = quota_turn

    def replace_before_cancel_check(*_args, **_kwargs):
        broker.finish(turn.job_id, "expired", expected_dispatch_id=dispatch)
        release_pending(turn, broker=broker, expected_dispatch_id=dispatch)
        broker.enqueue(turn.model_copy(update={"retry": True}))
        return True

    task = build_task(LocalHatchet(), broker_factory=lambda: broker)
    with patch.object(broker, "cancelled", side_effect=replace_before_cancel_check):
        result = task(DispatchInput(job_id=turn.job_id, dispatch_id=dispatch,
                      bot_key=turn.bot_key, conversation_key=turn.conversation_key), SimpleNamespace(done=lambda: False))
    assert result["state"] == "superseded"
    assert_reserved(sessions, turn)


@pytest.mark.parametrize("old_failure", [False, True])
def test_delayed_old_worker_cannot_release_or_persist_over_retry(quota_turn, old_failure):
    broker, turn, dispatch, sessions = quota_turn
    assert broker.start(turn.job_id, dispatch)
    entered, resume = threading.Event(), threading.Event()

    def old_answer(**_kwargs):
        entered.set()
        assert resume.wait(5)
        if old_failure:
            raise ValueError("Old provider finished late")
        return "Old answer", [], []

    with ThreadPoolExecutor(max_workers=1) as pool, patch("services.rag_service.answer_question", side_effect=old_answer):
        old = pool.submit(execute_turn, turn, broker, lambda: False, expected_dispatch_id=dispatch)
        assert entered.wait(5)
        broker.redis.hset(broker.key(turn.job_id), "started_at", time.time() - broker.execution_timeout - 91)
        assert broker.load(turn.job_id, turn.organization_id, turn.bot_id, turn.session_id)["state"] == "error"
        broker.enqueue(turn.model_copy(update={"retry": True}))
        resume.set()
        with pytest.raises((InterruptedError, ValueError)):
            old.result(timeout=5)
    assert_reserved(sessions, turn)
    with sessions() as db:
        assert db.query(ConversationMessage).count() == 0
    new_dispatch = broker.redis.hget(broker.key(turn.job_id), "dispatch_id")
    assert broker.start(turn.job_id, new_dispatch)
    with patch("services.rag_service.answer_question", return_value=("New answer", [], [])):
        result = execute_turn(turn.model_copy(update={"retry": True}), broker, lambda: False,
                              expected_dispatch_id=new_dispatch)
    assert broker.finish(turn.job_id, "success", result, expected_dispatch_id=new_dispatch)
    with sessions() as db:
        assert db.query(MessageUsageReservation).count() == 1
        assert db.query(MessageUsageReservation).one().status == "consumed"
        assert db.query(UsageMonthly).one().messages_sent == 1
        assert db.query(ConversationMessage).one().assistant_response == "New answer"


def test_transition_guard_releases_after_committed_quota_then_exception(quota_turn):
    broker, turn, dispatch, sessions = quota_turn
    with pytest.raises(ValueError):
        with turn_settlement(turn) as db:
            reserve_message_quota(db, turn.organization_id, idempotency_key=turn.usage_key)
            with turn_settlement(turn) as nested:
                assert nested is db
            raise ValueError("Controlled settlement failure")
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(broker.finish, turn.job_id, "error", expected_dispatch_id=dispatch).result(timeout=5)
    assert_reserved(sessions, turn)


@pytest.mark.parametrize("failure_stage", ["acquire", "unlock"])
def test_uncertain_postgres_lock_ownership_never_returns_connection_to_pool(quota_turn, failure_stage):
    _, turn, _, _ = quota_turn
    connection = MagicMock()
    connection.dialect.name = "postgresql"
    connection.__enter__.return_value = connection

    def execute(statement, *_args):
        sql = str(statement)
        if failure_stage == "acquire" and "pg_advisory_lock(" in sql:
            raise OSError("Lost lock acknowledgement")
        if failure_stage == "unlock" and "pg_advisory_unlock(" in sql:
            raise OSError("Lost unlock acknowledgement")
        return MagicMock(scalar=lambda: True)

    connection.execute.side_effect = execute
    engine = SimpleNamespace(connect=lambda: connection)
    with patch("database.connection.engine", engine), pytest.raises(OSError):
        with turn_settlement(turn):
            pass
    connection.invalidate.assert_called_once()


@pytest.mark.parametrize("phase", ["admission", "persistence"])
def test_queue_transitions_work_with_one_available_database_connection(quota_turn, phase):
    broker, turn, dispatch, sessions = quota_turn
    limited = create_engine(sessions.kw["bind"].url, pool_size=1, max_overflow=0, pool_timeout=0.5)
    limited_sessions = sessionmaker(bind=limited)
    try:
        with patch("database.connection.engine", limited), patch("database.connection.SessionLocal", limited_sessions):
            if phase == "admission":
                from routes import public_routes
                with limited_sessions() as db:
                    bot = db.query(Bot).filter_by(id=turn.bot_id).one()
                    assert limited.pool.checkedout() == 1
                    data = SimpleNamespace(**turn.model_dump())
                    with patch.object(public_routes, "get_broker", return_value=broker):
                        _, job, _ = public_routes._enqueue_public_turn(db, bot, data, turn.usage_key)
                    assert job.state == "queued"
            else:
                assert broker.start(turn.job_id, dispatch)
                def answer(**kwargs):
                    kwargs["db"].query(Bot).filter_by(id=turn.bot_id).one()
                    assert limited.pool.checkedout() == 1
                    return "New answer", [], []
                with patch("services.rag_service.answer_question", side_effect=answer):
                    result = execute_turn(turn, broker, lambda: False, expected_dispatch_id=dispatch)
                assert result["reply"] == "New answer"
        assert limited.pool.checkedout() == 0
    finally:
        limited.dispose()
