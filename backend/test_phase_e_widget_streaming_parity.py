import asyncio
import hashlib
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from database.models import Bot, ConversationMessage, ConversationSession
from database.connection import get_db
from routes import public_routes
from schemas.schemas import PublicChatRequest
from services.analytics_service import record_widget_chat_message
from services.public_access_service import (
    enforce_public_origin,
    issue_public_session,
    normalize_allowed_origins,
    validate_public_session,
)
from services.rag_service import _format_sources, semantic_cache_identity, stream_answer_question
from services.tenant_cache_service import TenantSafeCache


class _Query:
    def __init__(self, value):
        self.value = value

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.value


class _DB:
    def __init__(self, values=None):
        self.values = values or {}
        self.added = []
        self.commits = 0

    def query(self, model):
        return _Query(self.values.get(model))

    def add(self, value):
        self.added.append(value)
        if isinstance(value, ConversationSession):
            self.values[ConversationSession] = value

    def flush(self):
        if self.added and getattr(self.added[-1], "id", None) is None:
            self.added[-1].id = len(self.added)

    def commit(self):
        self.commits += 1

    def rollback(self):
        return None


def _bot(bot_id=71, status="active", origins=None):
    return Bot(
        id=bot_id,
        customer_id=9,
        organization_id=11,
        name="Phase E",
        provider="gemini",
        model_name="gemini-2.5-flash",
        status=status,
        tone="friendly",
        system_prompt="Be accurate",
        capabilities={"web_search": False, "file_analysis": True},
        allowed_origins=origins or [],
    )


def _request(origin="https://shop.example", path="/public/chat/71/stream"):
    headers = []
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
            "client": ("203.0.113.8", 4000),
            "server": ("api.example", 443),
        }
    )


async def _body(response):
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    return "".join(chunks)


class TestPhaseEWidgetStreamingParity(unittest.TestCase):
    def test_a_b_stream_buffers_the_canonical_quality_pipeline(self):
        bot = _bot()
        with patch(
            "services.rag_service.answer_question",
            return_value=("Approved final answer", [{"title": "Docs"}], []),
        ) as canonical, patch("services.llm_router.generate_stream") as direct_stream:
            result = list(
                stream_answer_question(
                    db=_DB(), bot=bot, question="Question", history=[], include_metadata=True
                )
            )
        canonical.assert_called_once()
        direct_stream.assert_not_called()
        self.assertEqual(result[0]["reply"], "Approved final answer")

    def test_c_stream_failure_is_sanitized(self):
        bot = _bot()
        db = _DB({Bot: bot, ConversationMessage: None})
        with patch("routes.public_routes.enforce_rate_limit"), patch(
            "routes.public_routes.ensure_can_send_message"
        ), patch(
            "routes.public_routes.stream_answer_question",
            side_effect=RuntimeError("secret-provider-key"),
        ), patch("routes.public_routes.track_widget_chat_message"), patch(
            "routes.public_routes.track_chat_completion"
        ):
            response = public_routes.public_chat_stream(
                PublicChatRequest(message="Hi"), bot_id=bot.id, db=db
            )
            body = asyncio.run(_body(response))
        self.assertIn('"type": "error"', body)
        self.assertNotIn("secret-provider-key", body)

    def test_d_stream_and_nonstream_share_rate_and_quota_gate(self):
        bot = _bot(origins=["https://shop.example"])
        data = PublicChatRequest(
            session_id="s1", session_token="token", turn_id="t1", message="Hi"
        )
        with patch("routes.public_routes.enforce_public_origin"), patch(
            "routes.public_routes.validate_public_session"
        ), patch("routes.public_routes.enforce_rate_limit") as limiter, patch(
            "routes.public_routes.ensure_can_send_message"
        ) as quota:
            public_routes._enforce_public_turn_access(
                db=_DB(), bot=bot, data=data, request=_request()
            )
        self.assertEqual(limiter.call_count, 3)
        quota.assert_called_once()

    def test_e_usage_is_recorded_once_when_error_retry_becomes_success(self):
        message = SimpleNamespace(
            status="error",
            assistant_response=None,
            response_time_ms=None,
            token_usage=None,
            error_message="failed",
            is_fallback=False,
            had_knowledge_hit=False,
        )
        bot = SimpleNamespace(organization_id=11)
        db = _DB({ConversationMessage: message, Bot: bot})
        with patch("services.analytics_service.record_usage") as usage:
            first = record_widget_chat_message(
                db=db,
                bot_id=71,
                session_id="s1",
                client_turn_id="t1",
                user_message="Hi",
                assistant_response="Done",
                response_time_ms=15,
            )
            second = record_widget_chat_message(
                db=db,
                bot_id=71,
                session_id="s1",
                client_turn_id="t1",
                user_message="Hi",
                assistant_response="Done",
                response_time_ms=15,
            )
        self.assertTrue(first)
        self.assertFalse(second)
        usage.assert_called_once()

    def test_successful_new_turn_persists_client_turn_id_once(self):
        session = SimpleNamespace(id=5, updated_at=None)
        bot = SimpleNamespace(organization_id=11)
        db = _DB({ConversationMessage: None, ConversationSession: session, Bot: bot})
        with patch("services.analytics_service.record_usage") as usage:
            created = record_widget_chat_message(
                db=db,
                bot_id=71,
                session_id="s1",
                client_turn_id="fresh-turn",
                user_message="Hi",
                assistant_response="Done",
                response_time_ms=15,
            )
        self.assertTrue(created)
        saved = next(value for value in db.added if isinstance(value, ConversationMessage))
        self.assertEqual(saved.client_turn_id, "fresh-turn")
        usage.assert_called_once()

    def test_f_g_same_literal_question_isolated_by_history_and_resolved_context(self):
        bot = _bot()
        product_a = semantic_cache_identity(
            bot, "What about its warranty?", [{"role": "user", "content": "Product A"}]
        )
        product_b = semantic_cache_identity(
            bot, "What about its warranty?", [{"role": "user", "content": "Product B"}]
        )
        product_a_again = semantic_cache_identity(
            bot, "What about its warranty?", [{"role": "user", "content": "Product A"}]
        )
        self.assertNotEqual(product_a["history_fingerprint"], product_b["history_fingerprint"])
        self.assertEqual(product_a, product_a_again)

    def test_h_i_config_and_knowledge_versions_bypass_stale_cache(self):
        bot = _bot()
        before = semantic_cache_identity(bot, "Hours?", [])
        bot.tone = "professional"
        after = semantic_cache_identity(bot, "Hours?", [])
        self.assertNotEqual(before["config_fingerprint"], after["config_fingerprint"])
        cache = TenantSafeCache()
        key_v1, _ = cache._build_keys(bot.id, "Hours", bot.organization_id, 1, "gemini")
        key_v2, _ = cache._build_keys(bot.id, "Hours", bot.organization_id, 2, "gemini")
        self.assertNotEqual(key_v1, key_v2)

    def test_j_k_stream_source_event_contains_only_public_metadata(self):
        bot = _bot()
        db = _DB({Bot: bot, ConversationMessage: None})
        source = {
            "document_id": 1,
            "filename": "product.html",
            "title": "Product",
            "source_url": "https://shop.example/product",
            "source_type": "website",
            "chunk_refs": [0],
            "cta_links": [{"label": "Buy", "url": "https://shop.example/buy"}],
        }
        with patch("routes.public_routes.enforce_rate_limit"), patch(
            "routes.public_routes.ensure_can_send_message"
        ), patch(
            "routes.public_routes.stream_answer_question",
            return_value=iter([{"reply": "Answer", "sources": [source], "retrieved_chunks": [{"content": "private"}]}]),
        ), patch("routes.public_routes.track_widget_chat_message"), patch(
            "routes.public_routes.track_chat_completion"
        ):
            body = asyncio.run(
                _body(public_routes.public_chat_stream(PublicChatRequest(message="Hi"), bot.id, db=db))
            )
        self.assertIn('"type": "sources"', body)
        self.assertIn("https://shop.example/buy", body)
        self.assertNotIn("retrieved_chunks", body)
        self.assertNotIn("private", body)
        self.assertNotIn("document_id", body)
        self.assertNotIn("chunk_refs", body)

    def test_source_formatter_drops_unsafe_urls_and_deduplicates_ctas(self):
        document = SimpleNamespace(
            id=1,
            filename="page",
            title="Page",
            source_type="website",
            source_url="javascript:alert(1)",
            canonical_url=None,
            metadata_json={},
        )
        chunk = SimpleNamespace(
            chunk_index=0,
            metadata_json={
                "cta_links": [
                    {"text": "Unsafe", "url": "javascript:alert(1)"},
                    {"text": "Safe", "url": "https://safe.example/go"},
                    {"text": "Duplicate", "url": "https://safe.example/go"},
                ]
            },
        )
        source = _format_sources([{"document": document, "chunk": chunk}])[0]
        self.assertIsNone(source["source_url"])
        self.assertEqual(source["cta_links"], [{"label": "Safe", "url": "https://safe.example/go"}])

    def test_s_t_origin_policy_denies_unauthorized_and_allows_exact_or_explicit_wildcard(self):
        bot = _bot(origins=["https://shop.example", "https://*.trusted.example"])
        self.assertEqual(enforce_public_origin(bot, _request("https://shop.example")), "https://shop.example")
        self.assertEqual(
            enforce_public_origin(bot, _request("https://store.trusted.example")),
            "https://store.trusted.example",
        )
        for bad in ("http://shop.example", "https://evil.example", "https://trusted.example"):
            with self.subTest(origin=bad), self.assertRaises(HTTPException) as caught:
                enforce_public_origin(bot, _request(bad))
            self.assertEqual(caught.exception.status_code, 403)

    def test_origin_normalization_honors_default_and_nondefault_ports(self):
        self.assertEqual(
            normalize_allowed_origins(
                ["HTTPS://SHOP.EXAMPLE:443", "https://shop.example", "https://shop.example:8443"]
            ),
            ["https://shop.example", "https://shop.example:8443"],
        )
        with self.assertRaises(ValueError):
            normalize_allowed_origins(["shop.example/path"])

    def test_production_requires_origin_or_explicit_direct_api_policy(self):
        with patch.dict(
            os.environ,
            {"APP_ENV": "production", "PUBLIC_DIRECT_API_ENABLED": "false"},
            clear=False,
        ):
            with self.assertRaises(HTTPException) as missing:
                enforce_public_origin(_bot(), _request(None))
            with self.assertRaises(HTTPException) as localhost:
                enforce_public_origin(_bot(), _request("http://localhost:3000"))
        self.assertEqual(missing.exception.status_code, 403)
        self.assertEqual(localhost.exception.status_code, 403)

    def test_u_draft_and_disabled_remain_publicly_hidden(self):
        for status in ("draft", "disabled"):
            with self.subTest(status=status), self.assertRaises(HTTPException) as caught:
                public_routes.get_public_bot_or_404(_DB({Bot: _bot(status=status)}), 71)
            self.assertEqual(caught.exception.status_code, 404)

    def test_v_session_token_is_bound_and_not_reusable(self):
        token = "visitor-a-secret"
        session = SimpleNamespace(public_token_hash=hashlib.sha256(token.encode()).hexdigest())
        db = _DB({ConversationSession: session})
        self.assertIs(validate_public_session(db, _bot(), "visitor-a", token), session)
        with self.assertRaises(HTTPException) as caught:
            validate_public_session(db, _bot(), "visitor-a", "visitor-b-secret")
        self.assertEqual(caught.exception.status_code, 401)

    def test_w_two_issued_visitors_receive_isolated_random_credentials(self):
        db = _DB()
        first = issue_public_session(db, _bot())
        second = issue_public_session(db, _bot())
        self.assertNotEqual(first[0], second[0])
        self.assertNotEqual(first[1], second[1])
        self.assertEqual(len(db.added), 2)
        self.assertNotEqual(db.added[0].public_token_hash, db.added[1].public_token_hash)

    def test_real_http_widget_session_and_chat_contract(self):
        bot = _bot(origins=["https://shop.example"])
        db = _DB({Bot: bot, ConversationMessage: None})
        app = FastAPI()
        app.include_router(public_routes.router, prefix="/public")
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)
        headers = {"Origin": "https://shop.example"}

        session_response = client.post(f"/public/widget/{bot.id}/session", headers=headers)
        self.assertEqual(session_response.status_code, 200)
        credential = session_response.json()
        self.assertNotEqual(credential["session_id"], credential["session_token"])

        with patch("routes.public_routes.enforce_rate_limit"), patch(
            "routes.public_routes.ensure_can_send_message"
        ), patch(
            "routes.public_routes.answer_question", return_value=("HTTP answer", [], [])
        ), patch("routes.public_routes.track_widget_chat_message"), patch(
            "routes.public_routes.track_chat_completion"
        ):
            chat_response = client.post(
                f"/public/chat/{bot.id}",
                headers=headers,
                json={
                    **credential,
                    "turn_id": "http-turn-1",
                    "message": "Hello",
                    "history": [],
                },
            )
        self.assertEqual(chat_response.status_code, 200)
        self.assertEqual(chat_response.json()["reply"], "HTTP answer")


if __name__ == "__main__":
    unittest.main()
