"""Durable saved tests and proven-undispatched quota rejection contracts."""
from types import SimpleNamespace
from unittest.mock import patch
import time

import pytest
from fastapi import HTTPException

from database.models import Bot, ConversationMessage, MessageUsageReservation, Organization
from database.experience_models import SavedTestCase, SavedTestRun, SavedTestResult
from schemas.experience import TestRunInput as RunInput
from schemas.schemas import PublicChatRequest
from services.chat_execution.models import ChatTurn, DispatchInput, UndispatchedChatExecutionError
from services.chat_execution.workflow import build_task
from services.knowledge_policy import capture_pipeline_policy, current_pipeline_policy
from services.usage_service import reserve_message_quota
from services import experience_service
from test_chat_execution_settlement import quota_turn


def another_turn(sessions, original, *, turn_id="another"):
    with sessions() as db:
        key = reserve_message_quota(db, original.organization_id, idempotency_key=turn_id, channel="playground")
    return original.model_copy(update={"turn_id": turn_id, "usage_key": key})


def reservation(sessions, turn):
    with sessions() as db:
        return db.query(MessageUsageReservation).filter_by(idempotency_key=turn.usage_key).one().status


def test_queue_full_releases_only_proven_undispatched_reservation(quota_turn, monkeypatch):
    broker, active, _, sessions = quota_turn
    turn = another_turn(sessions, active)
    monkeypatch.setenv("CHAT_EXECUTION_MAX_PENDING_PER_BOT", "1")
    with pytest.raises(UndispatchedChatExecutionError):
        broker.enqueue(turn)
    assert reservation(sessions, turn) == "released"
    assert reservation(sessions, active) == "reserved"
    assert not broker.redis.exists(broker.key(turn.job_id))


def test_oversized_new_payload_releases_but_active_identity_retry_does_not(quota_turn):
    broker, active, _, sessions = quota_turn
    large = [{"role": "user", "content": "x" * 16000}] * 8
    new = another_turn(sessions, active).model_copy(update={"history": large})
    with pytest.raises(UndispatchedChatExecutionError):
        broker.enqueue(new)
    assert reservation(sessions, new) == "released"
    with pytest.raises(UndispatchedChatExecutionError):
        broker.enqueue(active.model_copy(update={"history": large}))
    assert reservation(sessions, active) == "reserved"


def test_ambiguous_hatchet_dispatch_keeps_reservation(quota_turn):
    broker, active, _, sessions = quota_turn
    turn = another_turn(sessions, active)
    with patch.object(broker.hatchet, "run", side_effect=TimeoutError("uncertain acknowledgement")):
        with pytest.raises(RuntimeError, match="scheduling"):
            broker.enqueue(turn)
    assert reservation(sessions, turn) == "reserved"
    assert broker.redis.hget(broker.key(turn.job_id), "state") == "queued"


def test_session_setup_failure_releases_when_redis_proves_no_dispatch(quota_turn, monkeypatch):
    from services.chat_execution import dashboard
    broker, active, _, sessions = quota_turn
    turn = another_turn(sessions, active)
    monkeypatch.setattr(dashboard, "get_broker", lambda: broker)
    monkeypatch.setattr(dashboard, "is_enabled", lambda: True)
    with sessions() as db:
        bot = db.get(Bot, active.bot_id)
        snapshot = capture_pipeline_policy(db, bot)
        with patch.object(db, "query", side_effect=RuntimeError("session database failure")):
            with pytest.raises(HTTPException) as error:
                dashboard.enqueue_dashboard_turn(db, bot, PublicChatRequest(message="Question"),
                    session_id="new-session", turn_id=turn.turn_id, usage_key=turn.usage_key,
                    snapshot=snapshot, channel="playground")
        assert error.value.status_code == 503
    assert reservation(sessions, turn) == "released"


@pytest.fixture
def saved_case(quota_turn, monkeypatch):
    from services.chat_execution import dashboard, broker as broker_module
    broker, old, _, sessions = quota_turn
    monkeypatch.setenv("KNOWLEDGE_ENGINE", "llamaindex")
    monkeypatch.setenv("CHAT_EXECUTION_MODE", "hatchet")
    monkeypatch.setattr(dashboard, "get_broker", lambda: broker)
    monkeypatch.setattr(broker_module, "get_broker", lambda: broker)
    with sessions() as db:
        bot = db.get(Bot, old.bot_id)
        case = SavedTestCase(bot_id=bot.id, organization_id=bot.organization_id, question="What is the colour?",
            expected_answer="PRIVATE REFERENCE NOT FOR MODEL", required_phrases=["blue"], forbidden_phrases=["red"])
        db.add(case); db.commit()
        created = experience_service.create_test_run(db, bot, RunInput(case_ids=[case.id]), None)
        run_id = created["id"]
    return broker, old, sessions, run_id


def start_saved(saved_case):
    broker, old, sessions, run_id = saved_case
    with sessions() as db:
        response = experience_service.execute_next_case(db, db.get(Bot, old.bot_id), run_id)
    identity = f"saved-test:{run_id}:{response['results'][0]['id']}"
    turn_id = ChatTurn(organization_id=old.organization_id, bot_id=old.bot_id,
        session_id=identity, turn_id=identity, message="Question").job_id
    turn = broker.payload(turn_id)
    state = broker.load(turn.job_id, turn.organization_id, turn.bot_id, turn.session_id)
    dispatch = DispatchInput(job_id=turn.job_id, dispatch_id=state["dispatch_id"],
        bot_key=turn.bot_key, conversation_key=turn.conversation_key)
    return response, turn, dispatch


def test_saved_case_returns_running_pins_policy_and_settles_once_without_customer_messages(saved_case):
    broker, old, sessions, run_id = saved_case
    with patch("services.rag_service.answer_question") as no_inline:
        response, turn, dispatch = start_saved(saved_case)
        assert response["status"] == "running" and response["results"][0]["status"] == "running"
        no_inline.assert_not_called()
    assert "PRIVATE REFERENCE" not in turn.model_dump_json()
    assert turn.channel == "saved_test" and turn.accepted_pipeline.pipeline == "rag2_improved"
    with sessions() as db:
        org = db.get(Organization, old.organization_id)
        org.knowledge_pipeline = "og"; org.knowledge_pipeline_revision += 1; db.commit()
    seen = []
    def answer(**kwargs):
        seen.append(current_pipeline_policy())
        assert kwargs["history"] == []
        return "It is blue.", [], []
    task = build_task(broker.hatchet, broker_factory=lambda: broker)
    with patch("services.rag_service.answer_question", side_effect=answer):
        assert task(dispatch, SimpleNamespace(done=lambda: False))["state"] == "success"
        assert task(dispatch, SimpleNamespace(done=lambda: False))["state"] == "success"
    assert seen == [turn.accepted_pipeline]
    with sessions() as db:
        result = db.get(SavedTestResult, turn.saved_test.result_id)
        assert result.status == "passed_checks" and result.answer == "It is blue."
        assert db.get(SavedTestRun, run_id).status == "completed"
        assert db.query(ConversationMessage).count() == 0
    assert reservation(sessions, turn) == "consumed"


def test_saved_og_case_keeps_accepted_policy_when_admin_switches_before_answer(saved_case):
    from services import usage_service
    broker, old, sessions, original_run = saved_case
    with sessions() as db:
        bot = db.get(Bot, old.bot_id)
        experience_service.cancel_run(db, bot, original_run)
        org = db.get(Organization, old.organization_id)
        org.knowledge_pipeline = "og"
        org.knowledge_pipeline_revision += 1
        second = SavedTestCase(bot_id=bot.id, organization_id=bot.organization_id,
            question="What is the second colour?", required_phrases=["blue"], forbidden_phrases=[])
        db.add(second); db.commit()
        cases = db.query(SavedTestCase).filter_by(bot_id=bot.id).order_by(SavedTestCase.id).all()
        run_id = experience_service.create_test_run(db, bot, RunInput(case_ids=[case.id for case in cases]), None)["id"]
        accepted = capture_pipeline_policy(db, bot)

    original_quota = usage_service.ensure_can_send_message
    def reserve_then_switch(db, organization_id, **kwargs):
        key = original_quota(db, organization_id, **kwargs)
        with sessions() as admin_db:
            org = admin_db.get(Organization, organization_id)
            org.knowledge_pipeline = "rag2_improved"
            org.knowledge_pipeline_revision += 1
            admin_db.commit()
        return key

    seen = []
    def answer(**kwargs):
        seen.append(current_pipeline_policy())
        return "It is blue.", [], []

    with patch.object(usage_service, "ensure_can_send_message", side_effect=reserve_then_switch), \
            patch("services.rag_service._answer_question_for_policy", side_effect=answer), sessions() as db:
        first = experience_service.execute_next_case(db, db.get(Bot, old.bot_id), run_id)
    assert first["results"][0]["status"] == "passed_checks"
    assert seen == [accepted]
    assert current_pipeline_policy() is None

    with patch("services.rag_service.answer_question") as no_inline, sessions() as db:
        next_response = experience_service.execute_next_case(db, db.get(Bot, old.bot_id), run_id)
        no_inline.assert_not_called()
    next_result = next_response["results"][1]
    assert next_result["status"] == "running"
    identity = f"saved-test:{run_id}:{next_result['id']}"
    job_id = ChatTurn(organization_id=old.organization_id, bot_id=old.bot_id,
        session_id=identity, turn_id=identity, message=next_result["question"]).job_id
    next_turn = broker.payload(job_id)
    assert next_turn.accepted_pipeline.pipeline == "rag2_improved"
    assert next_turn.accepted_pipeline.revision == accepted.revision + 1


def test_duplicate_saved_execute_does_not_dispatch_twice_and_cancel_waits(saved_case):
    broker, old, sessions, run_id = saved_case
    _, turn, _ = start_saved(saved_case)
    with patch.object(broker, "enqueue", wraps=broker.enqueue) as enqueue:
        with sessions() as db:
            bot = db.get(Bot, old.bot_id)
            assert experience_service.execute_next_case(db, bot, run_id)["status"] == "running"
            with pytest.raises(HTTPException) as error:
                experience_service.cancel_run(db, bot, run_id)
            assert error.value.status_code == 409
        enqueue.assert_not_called()
    assert reservation(sessions, turn) == "reserved"


def test_saved_queue_expiry_is_reconciled_without_generation(saved_case):
    from services.chat_execution.saved_tests import refresh_run
    broker, old, sessions, run_id = saved_case
    _, turn, _ = start_saved(saved_case)
    broker.redis.hset(broker.key(turn.job_id), "queue_deadline", time.time() - 1)
    with patch("services.rag_service.answer_question") as answer, sessions() as db:
        refresh_run(db, db.get(Bot, old.bot_id), db.get(SavedTestRun, run_id))
        assert db.get(SavedTestRun, run_id).status == "completed"
        assert db.get(SavedTestResult, turn.saved_test.result_id).status == "error"
        answer.assert_not_called()
    assert reservation(sessions, turn) == "released"


def test_saved_provider_failure_releases_and_redacts(saved_case):
    broker, old, sessions, run_id = saved_case
    _, turn, dispatch = start_saved(saved_case)
    task = build_task(broker.hatchet, broker_factory=lambda: broker)
    with patch("services.rag_service.answer_question", side_effect=RuntimeError("private-provider-secret")):
        assert task(dispatch, SimpleNamespace(done=lambda: False))["state"] == "error"
    with sessions() as db:
        result = db.get(SavedTestResult, turn.saved_test.result_id)
        assert result.status == "error" and "private-provider-secret" not in result.error
        assert db.get(SavedTestRun, run_id).status == "completed"
    assert reservation(sessions, turn) == "released"


def test_saved_reference_cannot_cross_tenant_or_replace_lease(saved_case):
    from services.chat_execution.saved_tests import accepted_result, settle_result
    from services.chat_execution.models import ChatExecutionError
    broker, old, sessions, run_id = saved_case
    _, turn, _ = start_saved(saved_case)
    with sessions() as db:
        bot = db.get(Bot, old.bot_id)
        with pytest.raises(ChatExecutionError):
            accepted_result(db, turn.model_copy(update={"organization_id": old.organization_id + 999}), bot)
        stale = turn.model_copy(update={"saved_test": turn.saved_test.model_copy(update={"lease_token": "stale"})})
        with pytest.raises(ChatExecutionError):
            settle_result(db, stale, answer="Do not save")
        assert db.get(SavedTestResult, turn.saved_test.result_id).answer is None


def test_saved_model_change_before_worker_fails_without_call(saved_case):
    broker, old, sessions, run_id = saved_case
    _, turn, dispatch = start_saved(saved_case)
    with sessions() as db:
        db.get(Bot, old.bot_id).model_name = "gemini-3.8-flash"
        db.commit()
    task = build_task(broker.hatchet, broker_factory=lambda: broker)
    with patch("services.rag_service.answer_question") as answer:
        assert task(dispatch, SimpleNamespace(done=lambda: False))["state"] == "error"
        answer.assert_not_called()
    assert reservation(sessions, turn) == "released"
    with sessions() as db:
        assert db.get(SavedTestRun, run_id).status == "completed"
        assert db.get(SavedTestResult, turn.saved_test.result_id).status == "error"


def test_saved_queue_full_is_recorded_as_error_and_releases_quota(saved_case, monkeypatch):
    broker, old, sessions, run_id = saved_case
    monkeypatch.setenv("CHAT_EXECUTION_MAX_PENDING_PER_BOT", "1")
    with sessions() as db, patch("services.rag_service.answer_question") as answer:
        response = experience_service.execute_next_case(db, db.get(Bot, old.bot_id), run_id)
        assert response["status"] == "completed"
        assert response["results"][0]["status"] == "error"
        identity = f"saved-test:{run_id}:{response['results'][0]['id']}"
        assert db.query(MessageUsageReservation).filter_by(idempotency_key=identity).one().status == "released"
        answer.assert_not_called()
