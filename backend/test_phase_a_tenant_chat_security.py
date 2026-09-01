import asyncio
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError

from database.models import Bot, Document, IngestionJob
from routes import analytics_routes, chat_routes, conversation_routes, knowledge_routes, public_routes
from schemas.schemas import BotCreate, ChatRequest, KnowledgeCrawlRequest, PublicChatRequest
from services.bot_service import create_bot, get_bot_or_404
from services.queue_service import get_job_status


class _Query:
    def __init__(self, value):
        self.value = value

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.value


class _DB:
    def __init__(self, values=None):
        self.values = values or {}
        self.query_calls = []

    def query(self, model):
        self.query_calls.append(model)
        return _Query(self.values.get(model))


class TestPhaseATenantAuthorizationAndChat(unittest.TestCase):
    def setUp(self):
        self.user_a = SimpleNamespace(id=101, customer_id=501, memberships=[])
        self.bot_a = SimpleNamespace(
            id=201,
            organization_id=301,
            customer_id=501,
            name="Tenant A Bot",
            model_name="gemini-2.5-flash",
            provider="gemini",
            status="active",
        )
        self.bot_b = SimpleNamespace(
            id=202,
            organization_id=302,
            customer_id=502,
            name="Tenant B Bot",
            model_name="gemini-2.5-flash",
            provider="gemini",
            status="active",
        )

    def test_a_bot_creation_requires_organization_at_schema_and_service_boundaries(self):
        with self.assertRaises(ValidationError):
            BotCreate(name="Unowned Bot")

        construct = getattr(BotCreate, "model_construct", None) or BotCreate.construct
        invalid_data = construct(
            organization_id=None,
            name="Unowned Bot",
            provider="gemini",
            model_name="gemini-2.5-flash",
        )
        db = _DB()
        with self.assertRaises(HTTPException) as ctx:
            create_bot(db, invalid_data, user=self.user_a)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(db.query_calls, [], "Creation must fail before database side effects")

    def test_b_tenant_a_cannot_access_tenant_b_bot(self):
        db = _DB({Bot: self.bot_b})
        with patch(
            "services.bot_service.require_org_role",
            side_effect=HTTPException(status_code=404, detail="Organization not found"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                get_bot_or_404(db, self.bot_b.id, user=self.user_a)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_b_nonexistent_bot_is_not_found_before_chat_execution(self):
        db = _DB({Bot: None})
        request = PublicChatRequest(message="Missing")
        with patch("routes.chat_routes.answer_question") as answer:
            with self.assertRaises(HTTPException) as ctx:
                chat_routes.dashboard_playground_chat(
                    bot_id=999999,
                    data=request,
                    current_user=self.user_a,
                    db=db,
                )
        self.assertEqual(ctx.exception.status_code, 404)
        answer.assert_not_called()

    def test_c_tenant_a_cannot_upload_knowledge_to_tenant_b_bot(self):
        db = _DB({Bot: self.bot_b})
        upload = SimpleNamespace(size=10, filename="blocked.txt", content_type="text/plain")
        with patch(
            "services.bot_service.require_org_role",
            side_effect=HTTPException(status_code=404, detail="Organization not found"),
        ), patch("routes.knowledge_routes.create_file_document") as create_document:
            with self.assertRaises(HTTPException) as ctx:
                knowledge_routes.upload_document(
                    background_tasks=BackgroundTasks(),
                    bot_id=self.bot_b.id,
                    file=upload,
                    current_user=self.user_a,
                    db=db,
                )
        self.assertEqual(ctx.exception.status_code, 404)
        create_document.assert_not_called()

    def test_d_tenant_a_cannot_crawl_into_tenant_b_bot(self):
        db = _DB({Bot: self.bot_b})
        request = KnowledgeCrawlRequest(bot_id=self.bot_b.id, url="https://tenant-b.example")
        with patch(
            "services.bot_service.require_org_role",
            side_effect=HTTPException(status_code=404, detail="Organization not found"),
        ), patch("routes.knowledge_routes.create_website_document") as create_document:
            with self.assertRaises(HTTPException) as ctx:
                knowledge_routes.crawl_website(
                    data=request,
                    background_tasks=BackgroundTasks(),
                    current_user=self.user_a,
                    db=db,
                )
        self.assertEqual(ctx.exception.status_code, 404)
        create_document.assert_not_called()

    def test_e_tenant_a_cannot_access_tenant_b_conversations(self):
        db = _DB()
        with patch(
            "routes.conversation_routes.require_org_role",
            side_effect=HTTPException(status_code=404, detail="Organization not found"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                conversation_routes.list_conversations(
                    organization_id=self.bot_b.organization_id,
                    bot_id=None,
                    status=None,
                    search=None,
                    tag=None,
                    include_archived=False,
                    is_pinned=None,
                    sort_by="activity",
                    current_user=self.user_a,
                    db=db,
                )
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(db.query_calls, [], "Membership must be checked before conversation queries")

    def test_f_tenant_a_cannot_access_tenant_b_bot_analytics(self):
        db = _DB()
        with patch(
            "routes.analytics_routes.get_bot_or_404",
            side_effect=HTTPException(status_code=404, detail="Organization not found"),
        ), patch("routes.analytics_routes.get_bot_analytics_summary") as summary:
            with self.assertRaises(HTTPException) as ctx:
                analytics_routes.get_bot_summary(
                    bot_id=self.bot_b.id,
                    current_user=self.user_a,
                    db=db,
                )
        self.assertEqual(ctx.exception.status_code, 404)
        summary.assert_not_called()

    def test_g_null_organization_bot_and_document_fail_closed(self):
        null_bot = SimpleNamespace(id=203, organization_id=None)
        db = _DB({Bot: null_bot})
        with self.assertRaises(HTTPException) as bot_ctx:
            get_bot_or_404(db, null_bot.id, user=self.user_a)
        self.assertEqual(bot_ctx.exception.status_code, 409)

        null_document = SimpleNamespace(id=401, bot_id=null_bot.id, organization_id=None)
        db = _DB({Document: null_document, Bot: null_bot})
        with self.assertRaises(HTTPException) as document_ctx:
            knowledge_routes._get_document(db, null_document.id, user=self.user_a)
        self.assertEqual(document_ctx.exception.status_code, 409)

    def test_h_valid_dashboard_non_stream_chat_executes_and_checks_quota(self):
        db = _DB()
        request = PublicChatRequest(message="Hello")
        with patch("services.bot_service.get_bot_or_404", return_value=self.bot_a), patch(
            "routes.chat_routes.ensure_can_send_message"
        ) as quota, patch(
            "routes.chat_routes.answer_question", return_value=("Hi", [], [])
        ), patch("routes.chat_routes.track_chat_completion"):
            result = chat_routes.dashboard_playground_chat(
                bot_id=self.bot_a.id,
                data=request,
                current_user=self.user_a,
                db=db,
            )
        self.assertEqual(result["reply"], "Hi")
        quota.assert_called_once_with(db, self.bot_a.organization_id)

    def test_h_valid_dashboard_stream_chat_executes_and_checks_quota(self):
        db = _DB()
        request = PublicChatRequest(message="Stream")
        with patch("services.bot_service.get_bot_or_404", return_value=self.bot_a), patch(
            "routes.chat_routes.ensure_can_send_message"
        ) as quota, patch(
            "routes.chat_routes.stream_answer_question",
            return_value=iter([{"reply": "Hi", "sources": [], "retrieved_chunks": []}]),
        ), patch("routes.chat_routes.track_chat_completion"):
            response = chat_routes.dashboard_playground_chat_stream(
                bot_id=self.bot_a.id,
                data=request,
                current_user=self.user_a,
                db=db,
            )

            async def collect_body():
                chunks = []
                async for chunk in response.body_iterator:
                    chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
                return "".join(chunks)

            body = asyncio.run(collect_body())
        self.assertIn('"token": "Hi"', body)
        self.assertIn('"done": true', body)
        quota.assert_called_once_with(db, self.bot_a.organization_id)

    def test_h_legacy_api_key_playground_chat_executes_and_checks_quota(self):
        db = _DB()
        request = ChatRequest(api_key="tenant-a-key", bot_id=self.bot_a.id, message="Hello")
        customer = SimpleNamespace(id=self.user_a.customer_id)
        with patch("routes.chat_routes.get_owned_bot", return_value=(customer, self.bot_a)), patch(
            "routes.chat_routes.enforce_rate_limit"
        ) as limiter, patch("routes.chat_routes.ensure_can_send_message") as quota, patch(
            "routes.chat_routes.answer_question", return_value=("Hi", [], [])
        ), patch("routes.chat_routes.track_chat_completion"):
            result = chat_routes.chat(data=request, db=db)
        self.assertEqual(result["reply"], "Hi")
        limiter.assert_called_once()
        quota.assert_called_once_with(db, self.bot_a.organization_id)

    def test_i_quota_rejection_stops_dashboard_chat_before_rag(self):
        db = _DB()
        request = PublicChatRequest(message="Blocked")
        quota_error = HTTPException(status_code=429, detail="Monthly message limit reached")
        with patch("services.bot_service.get_bot_or_404", return_value=self.bot_a), patch(
            "routes.chat_routes.ensure_can_send_message", side_effect=quota_error
        ), patch("routes.chat_routes.answer_question") as answer:
            with self.assertRaises(HTTPException) as ctx:
                chat_routes.dashboard_playground_chat(
                    bot_id=self.bot_a.id,
                    data=request,
                    current_user=self.user_a,
                    db=db,
                )
        self.assertEqual(ctx.exception.status_code, 429)
        answer.assert_not_called()

    def test_j_public_widget_chat_remains_separate_from_dashboard_auth(self):
        db = _DB()
        request = PublicChatRequest(message="Public hello", session_id=None)
        with patch("routes.public_routes.get_public_bot_or_404", return_value=self.bot_a), patch(
            "routes.public_routes.enforce_rate_limit"
        ) as limiter, patch(
            "routes.public_routes.ensure_can_send_message"
        ) as quota, patch(
            "routes.public_routes.answer_question", return_value=("Public reply", [], [])
        ), patch("routes.public_routes.track_chat_completion"):
            result = public_routes.public_chat(
                data=request,
                background_tasks=BackgroundTasks(),
                bot_id=self.bot_a.id,
                db=db,
            )
        self.assertEqual(result["reply"], "Public reply")
        limiter.assert_called_once()
        quota.assert_called_once_with(db, self.bot_a.organization_id)

    def test_j_public_resolver_denies_draft_bots(self):
        draft_bot = SimpleNamespace(id=204, organization_id=301, status="draft")
        db = _DB({Bot: draft_bot})
        with self.assertRaises(HTTPException) as ctx:
            public_routes.get_public_bot_or_404(db, draft_bot.id)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_nested_job_lookup_rejects_null_or_mismatched_organization(self):
        null_job = SimpleNamespace(job_id="job-null", bot_id=self.bot_a.id, organization_id=None)
        db = _DB({IngestionJob: null_job})
        self.assertIsNone(
            get_job_status(
                db,
                null_job.job_id,
                bot_id=self.bot_a.id,
                organization_id=self.bot_a.organization_id,
            )
        )


if __name__ == "__main__":
    unittest.main()
