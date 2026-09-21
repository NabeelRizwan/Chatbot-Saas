import asyncio
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest
from services.rag_engine_adapters import CurrentRagEngineAdapter, RagFlowDerivedEngineAdapter, EngineSelection
from .fixtures import engine, scope


def test_current_adapter_forwards_unchanged_call():
    # Import actual accepted service under the suite's no-network guard.
    from services import rag_service
    with patch.object(rag_service, "answer_question", return_value=("answer", [], [])) as answer:
        assert CurrentRagEngineAdapter().answer(db=None, bot=7, question="Q") == ("answer", [], [])
        answer.assert_called_once_with(db=None, bot=7, question="Q")


def test_neutral_context_to_existing_generation_and_system_instruction():
    from services import llm_router, rag_service
    e, s = engine(), scope()
    e.ingest(s, "manual", "Email service has a four hour response target.", title="Service")
    adapter = RagFlowDerivedEngineAdapter(e, lambda db, bot: s)
    bot = SimpleNamespace(id=7, organization_id=8, provider="gemini", system_prompt="Trusted bot instruction", tone="neutral")
    history = [{"role": "user", "content": "Tell me about email service."}]
    with patch.object(llm_router, "generate", return_value="A qualified answer.") as generate:
        reply, sources, chunks = asyncio.run(adapter.answer(db=None, bot=bot, question="What is its response target?", history=history))
    assert reply == "A qualified answer." and sources and chunks
    args = generate.call_args.kwargs
    assert args["bot"] is bot and "four hour response target" in args["prompt"]
    assert "Tell me about email service" in args["prompt"]
    assert args["system_instruction"] == rag_service._get_system_instruction(bot, rag_service.DEFAULT_SUPPORT_PROMPT, strict_grounding=False)
    assert "four hour response target" not in args["system_instruction"]


def test_optional_router_auth_and_bot_boundary():
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from database.connection import get_db
    from services.auth_service import get_current_user
    from services import bot_service, usage_service
    from routes.rag_engine_dev_routes import create_router
    adapter = Mock()
    adapter.answer.return_value = ("answer", [{"url": "https://example.test"}], [])
    user = SimpleNamespace(id=1)
    bot = SimpleNamespace(id=7, organization_id=8)
    with patch.object(bot_service, "get_bot_or_404", return_value=bot) as authorize, \
         patch.object(usage_service, "ensure_can_send_message", return_value="usage"), \
         patch.object(usage_service, "consume_message_quota"), \
         patch.object(usage_service, "release_message_quota"):
        app = FastAPI()
        app.include_router(create_router(EngineSelection("ragflow", "development", True), lambda: adapter))
        app.dependency_overrides[get_db] = lambda: None
        def reject(): raise HTTPException(401, "Login required")
        app.dependency_overrides[get_current_user] = reject
        with TestClient(app) as client:
            assert client.post("/internal/development/rag/7", json={"message": "Q"}).status_code == 401
            assert not adapter.answer.called
            app.dependency_overrides[get_current_user] = lambda: user
            authorize.side_effect = HTTPException(404, "Not found")
            assert client.post("/internal/development/rag/99", json={"message": "Q"}).status_code == 404
            assert not adapter.answer.called
            authorize.side_effect = None
            result = client.post("/internal/development/rag/7", json={"message": "Q"})
            assert result.status_code == 200
            assert set(result.json()) == {"reply", "answer", "sources", "retrieved_chunks"}
            authorize.assert_called_with(None, 7, user=user, minimum_role="viewer")


def test_application_import_does_not_mount_optional_engine():
    from database import connection
    from services import billing_service
    # main.py has a pre-existing default-plan initialization at import. Stub it
    # explicitly so smoke import cannot open the configured application DB.
    with patch.object(connection, "SessionLocal", return_value=Mock()), \
         patch.object(billing_service, "ensure_default_plans"):
        app = importlib.import_module("main").app
    assert not any(path.startswith("/internal/development/rag") for path in app.openapi()["paths"])
