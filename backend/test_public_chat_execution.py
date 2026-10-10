import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException
from routes import public_routes as routes
from schemas.schemas import PublicChatRequest


@pytest.fixture
def queued(monkeypatch):
    bot = SimpleNamespace(id=7, organization_id=3)
    db = Mock()
    broker = Mock()
    broker.enqueue.return_value = SimpleNamespace(job_id="a" * 64, state="queued")
    broker.iterate.return_value = iter([{"type": "token", "token": "Answer"}, {"type": "done"}])
    broker.load.return_value = {"state": "success", "result": {"reply": "Answer", "answer": "Answer"}}
    monkeypatch.setattr(routes, "get_public_bot_or_404", lambda *_: bot)
    access = Mock(return_value="quota-turn")
    monkeypatch.setattr(routes, "_enforce_public_turn_access", access)
    monkeypatch.setattr(routes, "_existing_public_turn", lambda *_: None)
    monkeypatch.setattr(routes, "queued_chat_enabled", lambda: True)
    monkeypatch.setattr(routes, "get_broker", lambda: broker)
    return db, broker, access


def request():
    return PublicChatRequest(session_id="session", session_token="private-session-token",
        turn_id="turn", message="Question", history=[])


def test_queue_uses_authenticated_scope_and_does_not_store_session_token(queued):
    db, broker, access = queued
    response = routes.public_chat(request(), BackgroundTasks(), bot_id=7, db=db)
    assert response["reply"] == "Answer"
    access.assert_called_once()
    turn = broker.enqueue.call_args.args[0]
    assert (turn.organization_id, turn.bot_id, turn.usage_key) == (3, 7, "quota-turn")
    assert "private-session-token" not in turn.model_dump_json()
    db.rollback.assert_called_once()


def test_access_failure_never_reaches_queue(queued):
    db, broker, access = queued
    access.side_effect = HTTPException(401, "Invalid widget session")
    with pytest.raises(HTTPException) as caught:
        routes.public_chat(request(), BackgroundTasks(), bot_id=7, db=db)
    assert caught.value.status_code == 401
    broker.enqueue.assert_not_called()


def test_uncertain_dispatch_retries_stable_turn_without_releasing_reservation(queued):
    db, broker, _ = queued
    broker.enqueue.side_effect = RuntimeError("private engine detail")
    with patch.object(routes, "release_message_quota") as release:
        with pytest.raises(HTTPException) as caught:
            routes.public_chat(request(), BackgroundTasks(), bot_id=7, db=db)
    assert caught.value.detail == routes.SAFE_PUBLIC_ERROR
    release.assert_not_called()


def test_stream_relays_queue_keepalive_and_sanitizes_sources(queued):
    db, broker, _ = queued
    broker.iterate.return_value = iter([
        {"type": "keepalive"}, {"type": "token", "token": "Answer"},
        {"type": "sources", "sources": [{"title": "Private", "source_url": "javascript:bad()"}]},
        {"type": "done", "done": True}])
    response = routes.public_chat_stream(request(), bot_id=7, db=db)
    async def collect():
        return "".join([item async for item in response.body_iterator])
    body = asyncio.run(collect())
    assert ": keepalive" in body
    assert "javascript" not in body
    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    assert events[0]["queued"] is True
    assert events[-1]["done"] is True


def test_existing_success_does_not_schedule_or_generate_again(queued, monkeypatch):
    db, broker, _ = queued
    monkeypatch.setattr(routes, "_existing_public_turn", lambda *_: SimpleNamespace(status="success", assistant_response="Stored"))
    response = routes.public_chat(request(), BackgroundTasks(), bot_id=7, db=db)
    assert response["reply"] == "Stored"
    broker.enqueue.assert_not_called()
