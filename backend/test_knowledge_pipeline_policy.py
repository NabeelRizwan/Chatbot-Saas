"""Offline tenant policy, atomic administration, and accepted-turn contracts."""
import asyncio
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from database.connection import Base
from database.models import AuditLog, Organization, User
from routes.admin_routes import KnowledgePipelineUpdate, update_knowledge_pipeline
from services.chat_execution.models import ChatTurn
from services.knowledge_policy import (PipelineSnapshot, capture_pipeline_policy,
    current_pipeline_policy, pipeline_policy_context, resolve_pipeline_policy)
import test_platform_admin_console as admin_fixture
from test_chat_execution_settlement import quota_turn


@pytest.fixture
def console():
    fixture = admin_fixture.PlatformAdminConsoleTests()
    fixture.setUp()
    try:
        yield fixture
    finally:
        fixture.tearDown()


def test_admin_switch_cas_noop_and_atomic_audit(console):
    path = "/admin/organizations/1/knowledge-pipeline"
    current = console.client.get(path, headers=console.headers[1]).json()
    assert current == {"organization_id": 1, "pipeline": "rag2_improved", "revision": 1}
    body = {"pipeline": "og", "expected": {"pipeline": "rag2_improved", "revision": 1}}
    result = console.client.patch(path, headers=console.headers[1], json=body)
    assert result.status_code == 200
    assert result.json() == {"organization_id": 1, "pipeline": "og", "revision": 2}
    assert console.client.patch(path, headers=console.headers[1], json=body).status_code == 409
    body["expected"] = {"pipeline": "og", "revision": 2}
    assert console.client.patch(path, headers=console.headers[1], json=body).json()["revision"] == 2
    with console.sessions() as db:
        audits = db.query(AuditLog).all()
        assert len(audits) == 1
        assert audits[0].action.endswith("rag2_improved@1->og@2")
        assert (audits[0].user_id, audits[0].organization_id) == (1, 1)
    assert console.client.get("/admin/organizations/999/knowledge-pipeline", headers=console.headers[1]).status_code == 404


@pytest.mark.parametrize("headers_key, expected", [(None, 401), (2, 403), (3, 403)])
def test_policy_requires_platform_admin_not_membership(console, headers_key, expected):
    path = "/admin/organizations/1/knowledge-pipeline"
    headers = console.headers[headers_key] if headers_key else {}
    assert console.client.get(path, headers=headers).status_code == expected
    assert console.client.patch(path, headers=headers, json={
        "pipeline": "og", "expected": {"pipeline": "rag2_improved", "revision": 1}}).status_code == expected


def test_invalid_and_client_injected_policy_rejected(console):
    from schemas.schemas import PublicChatRequest
    path = "/admin/organizations/1/knowledge-pipeline"
    assert console.client.patch(path, headers=console.headers[1], json={
        "pipeline": "unknown", "expected": {"pipeline": "rag2_improved", "revision": 1}}).status_code == 422
    # Public request extras cannot become a trusted execution snapshot.
    request = PublicChatRequest(message="Question", pipeline_snapshot={"pipeline": "og", "revision": 99})
    assert not hasattr(request, "pipeline_snapshot")


def test_concurrent_admin_updates_have_one_winner(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "concurrent.sqlite"))
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add(User(id=1, email="admin@example.test", name="Admin", password_hash="synthetic", is_admin=True))
        db.add(Organization(id=1, name="Tenant", slug="tenant"))
        db.commit()
    barrier = Barrier(2)
    def change():
        with sessions() as db:
            user = db.get(User, 1)
            barrier.wait(timeout=5)
            try:
                return update_knowledge_pipeline(1, KnowledgePipelineUpdate(pipeline="og",
                    expected={"pipeline": "rag2_improved", "revision": 1}),
                    Request({"type": "http", "headers": []}), user, db)["revision"]
            except HTTPException as exc:
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: change(), range(2)))
    assert sorted(outcomes) == [2, 409]
    with sessions() as db:
        assert db.get(Organization, 1).knowledge_pipeline_revision == 2
        assert db.query(AuditLog).count() == 1
    engine.dispose()


def test_policy_context_is_immutable_nested_and_tenant_scoped(console):
    with console.sessions() as db:
        org = db.get(Organization, 1)
        snapshot = resolve_pipeline_policy(db, org)
        with pytest.raises(ValidationError):
            snapshot.pipeline = "og"
        assert current_pipeline_policy() is None
        with pipeline_policy_context(snapshot):
            assert capture_pipeline_policy(db, org) is snapshot
            with pytest.raises(ValueError, match="tenant mismatch"):
                capture_pipeline_policy(db, SimpleNamespace(organization_id=2))
            db.query(Organization).filter(Organization.id == 1).update({"knowledge_pipeline": "og", "knowledge_pipeline_revision": 2})
            db.commit()
            assert capture_pipeline_policy(db, org).pipeline == "rag2_improved"
        assert current_pipeline_policy() is None
        assert resolve_pipeline_policy(db, org).pipeline == "og"


def test_old_payload_pins_og_and_identity_does_not_change():
    legacy = ChatTurn(organization_id=1, bot_id=2, session_id="s", turn_id="t", message="Question")
    assert legacy.accepted_pipeline == PipelineSnapshot(organization_id=1, pipeline="og", revision=0)
    current = legacy.model_copy(update={"pipeline_snapshot": PipelineSnapshot(
        organization_id=1, pipeline="rag2_improved", revision=4)})
    assert legacy.job_id == current.job_id
    with pytest.raises(ValidationError, match="tenant mismatch"):
        ChatTurn.model_validate(dict(legacy.model_dump(), pipeline_snapshot={
            "organization_id": 2, "pipeline": "og", "revision": 1}))


def test_accepted_queue_budget_survives_policy_and_configuration_switch(quota_turn):
    broker, legacy, dispatch, sessions = quota_turn
    assert broker.accepted_timeout(legacy) == 180
    modern = legacy.model_copy(update={"turn_id": "modern", "pipeline_snapshot": PipelineSnapshot(
        organization_id=legacy.organization_id, pipeline="rag2_improved", revision=3)})
    broker.enqueue(modern)
    assert broker.accepted_timeout(modern) == 1800
    broker.rag2_execution_timeout = 200
    with sessions() as db:
        org = db.get(Organization, modern.organization_id)
        org.knowledge_pipeline = "og"; org.knowledge_pipeline_revision = 4; db.commit()
    assert broker.payload(modern.job_id).accepted_pipeline.revision == 3
    assert broker.accepted_timeout(modern) == 1800
    assert broker.accepted_timeout(legacy) == 180


def test_worker_uses_old_accepted_policy_after_org_switch(quota_turn):
    from services.chat_execution.runner import execute_turn
    broker, turn, dispatch, sessions = quota_turn
    seen = []
    def answer(**kwargs):
        seen.append(current_pipeline_policy())
        return "Grounded answer", [], []
    with patch("services.rag_service.answer_question", side_effect=answer):
        result = execute_turn(turn, broker, lambda: False, expected_dispatch_id=dispatch)
    assert result["reply"] == "Grounded answer"
    assert seen == [PipelineSnapshot(organization_id=turn.organization_id, pipeline="og", revision=0)]


def test_dashboard_keepalive_disconnect_requests_cancel_without_releasing_quota(quota_turn):
    from services.chat_execution.dashboard import dashboard_events
    from database.models import MessageUsageReservation
    broker, turn, dispatch, sessions = quota_turn
    async def consume():
        stream = dashboard_events(broker, SimpleNamespace(job_id=turn.job_id, state="queued"), turn)
        assert '"queued": true' in await anext(stream)
        assert await anext(stream) == ": keepalive\n\n"
        await stream.aclose()
    asyncio.run(consume())
    assert broker.cancelled(turn.job_id, expected_dispatch_id=dispatch)
    with sessions() as db:
        assert db.query(MessageUsageReservation).one().status == "reserved"


def test_migration_backfills_existing_og_defaults_new_rag2_and_reverses(tmp_path):
    path = Path(__file__).parent / "migrations/versions/20261023_01_organization_knowledge_pipeline.py"
    spec = importlib.util.spec_from_file_location("policy_migration", path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///" + str(tmp_path / "migration.sqlite"))
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE organizations (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO organizations VALUES (7, 'Existing')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.execute(text("SELECT knowledge_pipeline, knowledge_pipeline_revision FROM organizations WHERE id=7")).one() == ("og", 1)
            connection.execute(text("INSERT INTO organizations (id, name) VALUES (8, 'New')"))
            assert connection.execute(text("SELECT knowledge_pipeline, knowledge_pipeline_revision FROM organizations WHERE id=8")).one() == ("rag2_improved", 1)
            migration.downgrade()
            assert connection.execute(text("SELECT id,name FROM organizations ORDER BY id")).all() == [(7, "Existing"), (8, "New")]
    engine.dispose()


def test_cache_revision_isolated_without_changing_index_fingerprint(monkeypatch):
    import fakeredis
    from services.llama_rag.retrieval_cache import EvidenceCache
    from utils.redis_client import set_redis_override
    monkeypatch.setenv("LLAMA_RETRIEVAL_CACHE_ENABLED", "true")
    monkeypatch.setenv("LLAMA_RETRIEVAL_PIPELINE_REVISION", "frozen-og-test-build")
    scope = {"organization_id": 1, "bot_id": 2, "fingerprint": "a" * 64}
    set_redis_override(fakeredis.FakeRedis(decode_responses=True))
    try:
        keys = []
        for pipeline, revision in [("og", 1), ("rag2_improved", 2), ("og", 3), ("og", 1)]:
            with pipeline_policy_context(PipelineSnapshot(organization_id=1, pipeline=pipeline, revision=revision)):
                keys.append(EvidenceCache.configured(scope, "Same question").key)
        assert len(set(keys[:3])) == 3
        assert keys[0] == keys[3]
        assert scope == {"organization_id": 1, "bot_id": 2, "fingerprint": "a" * 64}
    finally:
        set_redis_override(None)


def test_dashboard_queue_preserves_channel_history_settlement_and_replay(quota_turn):
    from database.models import Bot, ConversationMessage, ConversationSession, MessageUsageReservation
    from schemas.schemas import PublicChatRequest
    from services.chat_execution.dashboard import enqueue_dashboard_turn, dashboard_result, dashboard_events
    from services.chat_execution.models import DispatchInput
    from services.chat_execution.workflow import build_task
    from services.usage_service import reserve_message_quota
    broker, legacy, dispatch, sessions = quota_turn
    session_id = "dashboard:1:durable-test"
    with sessions() as db:
        bot = db.get(Bot, legacy.bot_id)
        snapshot = resolve_pipeline_policy(db, bot)
        key = reserve_message_quota(db, bot.organization_id, idempotency_key="dashboard-test", channel="playground_stream")
        with patch("services.chat_execution.dashboard.get_broker", return_value=broker), \
                patch("services.chat_execution.dashboard.is_enabled", return_value=True):
            queued, job, turn = enqueue_dashboard_turn(db, bot, PublicChatRequest(message="Follow up", history=[
                {"role": "user", "content": "Previous question"}, {"role": "assistant", "content": "Previous answer"}]),
                session_id=session_id, turn_id="dashboard-turn", usage_key=key,
                snapshot=snapshot, channel="playground_stream")
        org = db.get(Organization, bot.organization_id)
        org.knowledge_pipeline = "og"; org.knowledge_pipeline_revision += 1; db.commit()
    seen = []
    def answer(**kwargs):
        seen.append((current_pipeline_policy(), kwargs["trace"].channel, kwargs["history"]))
        return "Grounded result", [], [{"text": "Grounded evidence"}]
    state = broker.load(turn.job_id, turn.organization_id, turn.bot_id, session_id)
    task = build_task(broker.hatchet, broker_factory=lambda: broker)
    dispatch_input = DispatchInput(job_id=turn.job_id, dispatch_id=state["dispatch_id"],
        bot_key=turn.bot_key, conversation_key=turn.conversation_key)
    with patch("services.rag_service.answer_question", side_effect=answer):
        assert task(dispatch_input, SimpleNamespace(done=lambda: False))["state"] == "success"
        assert task(dispatch_input, SimpleNamespace(done=lambda: False))["state"] == "success"
    assert len(seen) == 1 and seen[0][0] == snapshot
    assert seen[0][1] == "playground_stream" and seen[0][2] == turn.history
    assert dashboard_result(broker, job, turn)["reply"] == "Grounded result"
    async def collect():
        return "".join([event async for event in dashboard_events(broker, job, turn)])
    body = asyncio.run(collect())
    assert "Grounded evidence" in body and '"done": true' in body
    with sessions() as db:
        assert db.query(ConversationMessage).filter_by(session_id=session_id).count() == 1
        assert db.query(ConversationSession).filter_by(session_id=session_id).one().channel == "playground_stream"
        assert db.query(MessageUsageReservation).filter_by(idempotency_key=key).one().status == "consumed"


def test_fresh_metadata_migration_keeps_new_default(tmp_path):
    path = Path(__file__).parent / "migrations/versions/20261023_01_organization_knowledge_pipeline.py"
    spec = importlib.util.spec_from_file_location("fresh_policy_migration", path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///" + str(tmp_path / "fresh.sqlite"))
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO organizations(id,name,slug,created_at) VALUES (1,'New','new',CURRENT_TIMESTAMP)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert connection.execute(text("SELECT knowledge_pipeline,knowledge_pipeline_revision FROM organizations")).one() == ("rag2_improved", 1)
    engine.dispose()


def test_hatchet_ceiling_covers_rag2_without_extending_og_application_deadline(quota_turn):
    from datetime import timedelta
    from services.chat_execution.workflow import build_task
    broker, turn, _, _ = quota_turn
    options = {}
    def register(**kwargs):
        options.update(kwargs)
        return lambda func: func
    build_task(SimpleNamespace(task=register), broker_factory=lambda: broker)
    assert options["execution_timeout"] == timedelta(seconds=1860)
    assert broker.accepted_timeout(turn) == 180
    assert options["retries"] == 0


@pytest.mark.parametrize("streaming", [False, True])
def test_legacy_api_key_rag2_uses_durable_queue_without_changing_reply_shape(quota_turn, monkeypatch, streaming):
    from database.models import Bot
    from routes import chat_routes
    from schemas.schemas import ChatRequest
    from services.chat_execution import dashboard
    broker, old_turn, _, sessions = quota_turn
    with sessions() as db:
        bot = db.get(Bot, old_turn.bot_id)
        monkeypatch.setenv("KNOWLEDGE_ENGINE", "llamaindex")
        monkeypatch.setenv("CHAT_EXECUTION_MODE", "hatchet")
        monkeypatch.setattr(chat_routes, "get_owned_bot", lambda *args, **kwargs: (None, bot))
        monkeypatch.setattr(chat_routes, "enforce_rate_limit", lambda **kwargs: None)
        monkeypatch.setattr(dashboard, "get_broker", lambda: broker)
        saved = broker.enqueue
        seen = []
        def completed(turn):
            seen.append(turn)
            reference = saved(turn)
            broker.finish(turn.job_id, "success", {"reply": "Queued answer", "answer": "Queued answer",
                "sources": [], "retrieved_chunks": []})
            return reference
        monkeypatch.setattr(broker, "enqueue", completed)
        request = ChatRequest(api_key="synthetic-key", bot_id=bot.id, message="Question")
        if streaming:
            response = chat_routes.chat_stream(request, db)
            async def collect():
                return "".join([part async for part in response.body_iterator])
            assert '"token": "Queued answer"' in asyncio.run(collect())
        else:
            assert chat_routes.chat(request, db)["reply"] == "Queued answer"
    assert len(seen) == 1
    assert seen[0].accepted_pipeline.pipeline == "rag2_improved"
    assert seen[0].channel == ("api_stream" if streaming else "api")
    assert "synthetic-key" not in seen[0].model_dump_json()
