"""Regression checks at the boundaries between new UI features and existing chat."""
import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from database.models import User, Website, WebsiteCrawl
from schemas.experience import ExperienceSettingsInput, ProductInput
from schemas.experience_integrations import ExperienceIntegrations, public_destination
from services import experience_service as service
from services.experience_evidence import selected_source_metadata
from services.observability_service import ChatTrace, compact_chat_diagnostics
from services.public_access_service import enforce_public_origin
from services.rag_service import answer_question, stream_answer_question
from routes.experience_integration_routes import router as integration_router
import test_customer_experience as fixture_module


def browser(origin):
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [(b"origin", origin.encode())]})


class ExperienceHookTests(unittest.TestCase):
    tearDown = fixture_module.CustomerExperienceTests.tearDown
    enable = fixture_module.CustomerExperienceTests.enable
    faq = fixture_module.CustomerExperienceTests.faq

    def setUp(self):
        fixture_module.CustomerExperienceTests.setUp(self)
        self.client.app.include_router(integration_router)

    def test_hosted_origin_requires_both_flags_and_exact_configured_origin(self):
        with patch.dict(os.environ, {"APP_ENV": "production", "FRONTEND_URL": "https://app.example.com", "PUBLIC_DIRECT_API_ENABLED": "false"}):
            with self.assertRaises(HTTPException):
                enforce_public_origin(self.bot, browser("https://app.example.com"))
            service.save_settings(self.db, self.bot, ExperienceSettingsInput(enabled=True, hosted_chat_enabled=True))
            self.assertEqual(enforce_public_origin(self.bot, browser("https://app.example.com")), "https://app.example.com")
            for origin in ("http://app.example.com", "https://evil.app.example.com", "https://app.example.com:444", "https://app.example.com.evil.com"):
                with self.subTest(origin=origin), self.assertRaises(HTTPException):
                    enforce_public_origin(self.bot, browser(origin))
            for enabled, hosted in ((False, True), (True, False), (False, False)):
                service.save_settings(self.db, self.bot, ExperienceSettingsInput(enabled=enabled, hosted_chat_enabled=hosted))
                with self.assertRaises(HTTPException):
                    enforce_public_origin(self.bot, browser("https://app.example.com"))

    def test_hosted_setting_does_not_allow_another_bot(self):
        service.save_settings(self.db, self.bot, ExperienceSettingsInput(enabled=True, hosted_chat_enabled=True))
        with patch.dict(os.environ, {"APP_ENV": "production", "FRONTEND_URL": "https://app.example.com"}):
            with self.assertRaises(HTTPException):
                enforce_public_origin(self.other, browser("https://app.example.com"))
            # The prior allowlist continues to work when new features are disabled.
            self.assertEqual(enforce_public_origin(self.other, browser("https://other.example.com")), "https://other.example.com")

    def test_approved_faq_stream_uses_same_answer_and_keeps_trace_sources(self):
        self.enable()
        row = self.faq()
        trace = ChatTrace(bot_id=1, channel="widget")
        with patch("services.knowledge_runtime.answer_question") as native:
            events = list(stream_answer_question(self.db, self.bot, row["question"], trace=trace, include_metadata=True))
        native.assert_not_called()
        self.assertEqual(events[0]["reply"], row["answer"])
        diagnostics = compact_chat_diagnostics(trace)
        self.assertEqual(diagnostics["experience_sources"], [{"document_id": 1, "source_url": self.doc.source_url}])
        self.assertEqual(trace.intent, "approved_faq")

    def test_unmatched_question_preserves_history_top_k_and_other_pipeline_arguments(self):
        self.enable()
        self.faq()
        history = [{"role": "user", "content": "Product A"}, {"role": "assistant", "content": "Context"}]
        trace = ChatTrace(bot_id=1, channel="widget")
        native_result = ("Normal RAG", [{"document_id": 1, "source_url": self.doc.source_url}], [{"text": "Evidence"}])
        with patch("services.knowledge_runtime.answer_question", return_value=native_result) as native:
            result = answer_question(self.db, self.bot, "Which product is better?", top_k=8, history=history, trace=trace, org_id=1, session_id="existing-session")
        self.assertIs(result, native_result)
        self.assertEqual(native.call_args.kwargs["history"], history)
        self.assertEqual(native.call_args.kwargs["top_k"], 8)
        self.assertEqual(native.call_args.kwargs["session_id"], "existing-session")
        self.assertEqual(native.call_args.kwargs["org_id"], 1)
        self.assertEqual(compact_chat_diagnostics(trace)["experience_sources"], [{"document_id": 1, "source_url": self.doc.source_url}])

    def test_versioned_or_different_organization_request_cannot_short_circuit_to_faq(self):
        self.enable()
        row = self.faq()
        native_result = ("Underlying scoped path", [], [])
        for kwargs in ({"org_id": 2}, {"knowledge_version": 1}):
            with self.subTest(kwargs=kwargs), patch("services.knowledge_runtime.answer_question", return_value=native_result) as native:
                self.assertEqual(answer_question(self.db, self.bot, row["question"], **kwargs), native_result)
                native.assert_called_once()

    def test_metadata_is_bounded_and_excludes_context_text_and_unsafe_links(self):
        sources = [{"document_id": 1, "source_url": "https://example.com/a", "context": "Private context", "provider_api_key": "never-save"},
            {"doc_id": 2, "source_url": "javascript:alert(1)"}, {"document_id": True, "source_url": "https://user:password@example.com"},
            {"document_id": 1, "source_url": "https://example.com/a"}]
        self.assertEqual(selected_source_metadata(sources), [
            {"document_id": 1, "source_url": "https://example.com/a"}, {"document_id": 2}])
        self.assertEqual(len(selected_source_metadata([{"document_id": i} for i in range(1, 100)])), 32)

    def test_inactive_or_unprocessed_source_cannot_serve_faq_or_card(self):
        self.enable()
        row = self.faq()
        service.save_product(self.db, self.bot, ProductInput(title="Item", url=self.doc.source_url, source_document_id=1, enabled=True))
        for status, processing in (("inactive", "completed"), ("superseded", "completed"), ("ready", "pending"), ("ready", "failed")):
            self.doc.status, self.doc.processing_status = status, processing
            self.db.commit()
            with self.subTest(status=status, processing=processing):
                self.assertIsNone(service.lookup_approved_faq(self.db, self.bot, row["question"]))
                self.assertEqual(service.select_product_cards(self.db, self.bot, [{"document_id": 1}]), [])

    def test_replaced_crawl_or_disabled_website_cannot_serve_old_faq(self):
        self.enable()
        website = Website(id=1, bot_id=1, organization_id=1, root_url="https://shop.example.com", domain="shop.example.com", status="ready", active_crawl_id=1)
        crawl = WebsiteCrawl(id=1, website_id=1, bot_id=1, organization_id=1, status="ready", version=1)
        self.db.add_all([website, crawl])
        self.doc.source_type, self.doc.website_id, self.doc.crawl_id = "website", 1, 1
        self.db.commit()
        row = self.faq()
        self.assertIsNotNone(service.lookup_approved_faq(self.db, self.bot, row["question"]))
        website.active_crawl_id = 2
        self.db.commit()
        self.assertIsNone(service.lookup_approved_faq(self.db, self.bot, row["question"]))
        website.active_crawl_id, website.status = 1, "disabled"
        self.db.commit()
        self.assertIsNone(service.lookup_approved_faq(self.db, self.bot, row["question"]))

    def test_integration_routes_enforce_roles_tenants_and_public_gating(self):
        data = {"booking": {"provider": "calcom", "url": "https://cal.com/team/meeting", "enabled": True},
                "orders": {"provider": "shopify", "url": "https://shop.example.com/account", "enabled": False}}
        private, public = "/bot/1/experience/integrations", "/public/widget/1/experience/integrations"
        self.assertEqual(self.client.put(private, json=data).status_code, 200)
        self.assertEqual(self.client.get("/bot/2/experience/integrations").status_code, 404)
        self.assertEqual(self.client.get(public, headers={"Origin": "https://evil.example.com"}).status_code, 403)
        hidden = self.client.get(public, headers={"Origin": "https://shop.example.com"}).json()
        self.assertEqual(hidden["booking"]["url"], "")
        self.enable()
        visible = self.client.get(public, headers={"Origin": "https://shop.example.com"}).json()
        self.assertEqual(visible["booking"]["url"], "https://cal.com/team/meeting")
        self.assertEqual(visible["orders"]["url"], "")
        self.current_user = self.db.get(User, 2)
        self.assertEqual(self.client.get(private).status_code, 200)
        self.assertEqual(self.client.put(private, json=data).status_code, 403)

    def test_public_integrations_are_unavailable_for_inactive_bot(self):
        self.enable()
        self.bot.status = "disabled"
        self.db.commit()
        self.assertEqual(self.client.get("/public/widget/1/experience/integrations", headers={"Origin": "https://shop.example.com"}).status_code, 404)

    def test_integrations_reject_private_malformed_and_secret_destinations(self):
        values = ["javascript:alert(1)", "http://example.com", "https://user:pass@example.com", "https://localhost/a", "https://127.0.0.1/a", "https://127.1/a", "https://0x7f.0.0.1/a", "https://exa mple.com/a", "https://%65xample.com/a", "https://example.com?accessToken=private", "https://example.com?api-key=private", "https://example.com?Order_ID=private", "https://example.com?email=private"]
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                public_destination(value)
        self.assertEqual(public_destination("https://EXAMPLE.com:443/account?utm_source=chat"), "https://example.com/account?utm_source=chat")

    def test_enabled_integrations_require_real_config_and_matching_booking_provider(self):
        for value in ({"booking": {"enabled": True}}, {"orders": {"enabled": True, "provider": "shopify"}}, {"booking": {"enabled": True, "provider": "calendly", "url": "https://example.com/book"}}):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                ExperienceIntegrations.model_validate(value)
