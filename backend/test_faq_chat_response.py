"""Approved FAQ citations survive real HTTP response validation on both pipelines."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from database.connection import get_db
from database.models import Bot, Customer, MessageUsageReservation, Organization, OrganizationMembership, User
from database import experience_models  # register the real experience tables for the fixture
from routes.chat_routes import router
from schemas.experience import ExperienceSettingsInput, FaqInput
from schemas.schemas import ChatResponse
from services.auth_service import get_current_user
from services.chat_execution.models import DispatchInput
from services.chat_execution.workflow import build_task
from services.experience_service import save_faq, save_settings
from test_chat_execution_settlement import quota_turn


@pytest.mark.parametrize("pipeline", ["og", "rag2_improved"])
@pytest.mark.parametrize("channel", ["api", "dashboard"])
def test_approved_faq_source_serializes_on_real_nonstream_routes(quota_turn, monkeypatch, pipeline, channel):
    from services.chat_execution import dashboard
    broker, original, _, sessions = quota_turn
    monkeypatch.setenv("KNOWLEDGE_ENGINE", "llamaindex")
    monkeypatch.setattr("routes.chat_routes.enforce_rate_limit", lambda **kwargs: None)
    monkeypatch.setattr(dashboard, "get_broker", lambda: broker)
    monkeypatch.setattr(dashboard, "is_enabled", lambda: True)
    question, answer = "How long is delivery?", "Delivery takes three days."
    source = {"document_id": None, "title": question, "source_url": "https://example.com/delivery", "source_type": "approved_faq"}
    with sessions() as db:
        bot = db.get(Bot, original.bot_id)
        db.get(Organization, bot.organization_id).knowledge_pipeline = pipeline
        owner = User(email="faq-owner@example.test", name="FAQ owner", password_hash="offline-only")
        db.add(owner); db.commit(); owner_id = owner.id
        db.add(OrganizationMembership(organization_id=bot.organization_id, user_id=owner_id, role="owner")); db.commit()
        api_key = db.get(Customer, bot.customer_id).api_key
        save_settings(db, bot, ExperienceSettingsInput(enabled=True, approved_faq_enabled=True))
        save_faq(db, bot, FaqInput(question=question, answer=answer, source_url=source["source_url"], approved=True, enabled=True), owner_id)

    task = build_task(broker.hatchet, broker_factory=lambda: broker)
    enqueue = broker.enqueue
    def enqueue_and_settle(turn):
        job = enqueue(turn)
        dispatch = DispatchInput(job_id=turn.job_id, dispatch_id=broker.redis.hget(broker.key(turn.job_id), "dispatch_id"),
            bot_key=turn.bot_key, conversation_key=turn.conversation_key)
        assert task(dispatch, SimpleNamespace(done=lambda: False))["state"] == "success"
        return job
    monkeypatch.setattr(broker, "enqueue", enqueue_and_settle)

    def database():
        with sessions() as db:
            yield db
    def current_user(db=Depends(get_db)):
        return db.get(User, owner_id)
    app = FastAPI(); app.include_router(router, prefix="/chat")
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = current_user
    path = "/chat/" if channel == "api" else f"/chat/{original.bot_id}"
    body = {"message": question, "history": []}
    if channel == "api": body.update(api_key=api_key, bot_id=original.bot_id)
    else: body.update(session_id="faq-http-witness", turn_id="faq-http-turn")
    with patch("services.knowledge_runtime.answer_question", side_effect=AssertionError("Approved FAQ must not call retrieval or a provider")) as native, \
            TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(path, json=body)
        assert response.status_code == 200, response.text
        assert response.json()["reply"] == answer
        assert response.json()["sources"] == [source]
        assert response.json()["retrieved_chunks"] == []
        native.assert_not_called()
    with sessions() as db:
        accepted = db.query(MessageUsageReservation).filter(MessageUsageReservation.channel.in_(["api", "playground"])).all()
        assert len(accepted) == 1 and accepted[0].status == "consumed"


@pytest.mark.parametrize("source", [
    {"document_id": 5, "title": "Document", "source_type": "document"},
    {"document_id": None, "filename": "Source", "chunk_refs": [], "source_type": "document"},
    {"document_id": None, "title": "Missing explicit FAQ type", "source_url": "https://example.test"},
    {"document_id": 5, "filename": "Source", "source_type": "approved_faq", "title": "Malformed document"},
])
def test_malformed_document_sources_are_not_accepted_as_faq(source):
    with pytest.raises(ValidationError):
        ChatResponse.model_validate({"reply": "Answer", "sources": [source]})


def test_normal_document_and_legacy_string_sources_remain_valid():
    source = {"document_id": 5, "filename": "Source", "chunk_refs": [7], "source_type": "document"}
    response = ChatResponse.model_validate({"reply": "Answer", "sources": [source, "https://example.test"]})
    assert response.sources[0].document_id == 5
    assert response.sources[0].chunk_refs == [7]
    assert response.sources[1] == "https://example.test"
