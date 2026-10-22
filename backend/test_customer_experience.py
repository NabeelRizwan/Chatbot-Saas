"""Experience controls use real local SQL transactions and no provider/network calls."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///" + (Path(tempfile.gettempdir()) / "experience-import.sqlite").as_posix())
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:1/0")

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.connection import Base, get_db
from database.models import Bot, ConversationMessage, ConversationSession, Customer, Document, Organization, OrganizationMembership, User
from database.experience_models import ApprovedFaq, ExperienceLead, ExperienceProduct, ExperienceSettings, LeadSubmission, SavedTestCase, SavedTestRun, SavedTestResult
from schemas.experience import ExperienceSettingsInput, FaqInput, LeadInput, ProductInput, TestCaseInput as CaseInput, TestRunInput as RunInput
from services import experience_service as service
from services.auth_service import get_current_user
from services.public_access_service import issue_public_session
from routes.experience_routes import router, public_router


class CustomerExperienceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        names = ["customers", "users", "organizations", "organization_memberships", "bots", "websites", "website_crawls", "documents", "conversation_sessions", "conversation_messages"]
        tables = [Base.metadata.tables[name] for name in names] + [table for name, table in Base.metadata.tables.items() if name.startswith("experience_")]
        Base.metadata.create_all(self.engine, tables=tables)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.db.add_all([Customer(id=1, name="A", api_key="test-a"), Customer(id=2, name="B", api_key="test-b"),
            User(id=1, email="owner@a.test", name="Owner", password_hash="test"),
            User(id=2, email="viewer@a.test", name="Viewer", password_hash="test"),
            Organization(id=1, name="A", slug="a", knowledge_pipeline="og"), Organization(id=2, name="B", slug="b", knowledge_pipeline="og"),
            OrganizationMembership(user_id=1, organization_id=1, role="owner"),
            OrganizationMembership(user_id=2, organization_id=1, role="viewer")])
        self.bot = Bot(id=1, name="A", customer_id=1, organization_id=1, allowed_origins=["https://shop.example.com"])
        self.other = Bot(id=2, name="B", customer_id=2, organization_id=2, allowed_origins=["https://other.example.com"])
        self.doc = Document(id=1, bot_id=1, organization_id=1, filename="Source", source_type="text", source_url="https://shop.example.com/product", content_hash="original", status="ready", processing_status="completed")
        self.db.add_all([self.bot, self.other, self.doc])
        self.db.commit()
        self.current_user = self.db.get(User, 1)
        app = FastAPI()
        app.include_router(router)
        app.include_router(public_router)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.current_user
        self.client = TestClient(app)
        self.rate_limit = patch("routes.experience_routes.enforce_rate_limit")
        self.rate_limit.start()

    def tearDown(self):
        self.client.close()
        self.rate_limit.stop()
        self.db.close()
        self.engine.dispose()

    def enable(self):
        return service.save_settings(self.db, self.bot, ExperienceSettingsInput(enabled=True,
            approved_faq_enabled=True, product_cards_enabled=True, lead_form_enabled=True))

    def faq(self, **updates):
        body = dict(question="How long is delivery?", answer="Delivery takes three days.", aliases=["When will my order arrive?"], approved=True, enabled=True, source_document_id=1)
        body.update(updates)
        return service.save_faq(self.db, self.bot, FaqInput(**body), 1)

    def lead(self, **updates):
        body = dict(session_id="session-a", session_token="not-a-live-secret", idempotency_key="submit-1234", name="Customer", email="Person@example.com", message="Please contact me", consent=True)
        body.update(updates)
        return LeadInput(**body)

    def test_default_is_off_and_does_not_write(self):
        self.assertFalse(service.get_settings(self.db, self.bot)["enabled"])
        self.assertIsNone(service.lookup_approved_faq(self.db, self.bot, "A question"))
        self.assertEqual(self.db.query(ExperienceSettings).count(), 0)

    def test_database_rejects_mismatched_bot_and_organization(self):
        self.db.execute(text("PRAGMA foreign_keys=ON"))
        self.db.add(ExperienceSettings(bot_id=1, organization_id=2))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_canonical_pipeline_preserves_normal_fallback_and_serves_approved_answer(self):
        from services.rag_service import answer_question
        native_result = ("Ordinary RAG answer", [], [])
        with patch("services.knowledge_runtime.answer_question", return_value=native_result) as native:
            self.assertEqual(answer_question(self.db, self.bot, "Normal question"), native_result)
            native.assert_called_once()
        self.enable()
        row = self.faq()
        with patch("services.knowledge_runtime.answer_question") as native:
            result = answer_question(self.db, self.bot, row["question"])
            self.assertEqual(result[0], row["answer"])
            native.assert_not_called()

    def test_frozen_migration_adds_and_removes_only_experience_tables(self):
        import importlib.util
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from sqlalchemy import inspect
        path = Path(__file__).parent / "migrations/versions/20261012_01_customer_experience.py"
        spec = importlib.util.spec_from_file_location("experience_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with self.engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration.upgrade()  # Existing complete bootstrap schema is accepted.
                migration.downgrade()
                remaining = set(inspect(connection).get_table_names())
                self.assertIn("bots", remaining)
                self.assertFalse(any(name.startswith("experience_") for name in remaining))
                migration.upgrade()
                self.assertTrue(set(migration.TABLE_COLUMNS).issubset(inspect(connection).get_table_names()))
            self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM bots")).scalar(), 2)

    def test_approved_matching_preserves_negation_and_requires_explicit_alias(self):
        self.enable()
        self.faq()
        hit = service.lookup_approved_faq(self.db, self.bot, "  WHEN will my order arrive?  ")
        self.assertEqual(hit["reply"], "Delivery takes three days.")
        self.assertIsNone(service.lookup_approved_faq(self.db, self.bot, "How long is not delivery?"))
        self.assertIsNone(service.lookup_approved_faq(self.db, self.bot, "Can you estimate the shipping time?"))
        self.assertIsNone(service.lookup_approved_faq(self.db, self.other, "How long is delivery?"))

    def test_approval_and_enabled_are_both_required(self):
        self.enable()
        row = self.faq(approved=False)
        self.assertIsNone(service.lookup_approved_faq(self.db, self.bot, row["question"]))

    def test_alias_collision_is_rejected_without_corrupting_existing_answer(self):
        self.enable()
        row = self.faq()
        with self.assertRaises(HTTPException) as ctx:
            self.faq(question="Different question?", answer="Wrong", aliases=["How long is delivery?"])
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(service.lookup_approved_faq(self.db, self.bot, row["question"])["reply"], row["answer"])
        self.assertEqual(self.db.query(ApprovedFaq).count(), 1)

    def test_source_change_and_deletion_suspend_faq_until_reapproved(self):
        self.enable()
        row = self.faq()
        self.doc.content_hash = "changed"
        self.db.commit()
        self.assertIsNone(service.lookup_approved_faq(self.db, self.bot, row["question"]))
        model = self.db.get(ApprovedFaq, row["id"])
        self.assertEqual(service.source_status(self.db, self.bot, model), "changed")
        self.db.query(Document).filter(Document.id == self.doc.id).delete(synchronize_session=False)
        self.db.commit()
        self.assertEqual(service.source_status(self.db, self.bot, model), "missing")
        self.assertIsNone(service.lookup_approved_faq(self.db, self.bot, row["question"]))

    def test_cross_tenant_source_binding_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            service.save_product(self.db, self.other, ProductInput(title="Other", url="https://example.com/p", source_document_id=1))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_product_cards_only_follow_saved_supporting_sources(self):
        self.enable()
        service.save_product(self.db, self.bot, ProductInput(title="Product", url=self.doc.source_url, source_document_id=1, enabled=True))
        self.assertEqual(service.select_product_cards(self.db, self.bot, []), [])
        self.assertEqual(service.select_product_cards(self.db, self.bot, [{"source_url": "https://example.com/other"}]), [])
        self.assertEqual(len(service.select_product_cards(self.db, self.bot, [{"source_url": self.doc.source_url}])), 1)
        self.doc.version += 1
        self.db.commit()
        self.assertEqual(service.select_product_cards(self.db, self.bot, [{"document_id": 1}]), [])

    def test_unsafe_urls_and_prices_are_rejected(self):
        for url in ("javascript:alert(1)", "https://user:pass@example.com", "https://127.0.0.1/p", "https://127.1/p", "https://0x7f.0.0.1/p", "https://%65xample.com/p", "https://exa mple.com/p", "https://localhost/x", "https://example.com\\@evil.com"):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                ProductInput(title="Product", url=url)
        for price in ("NaN", "-1", "Infinity", "2.00001"):
            with self.subTest(price=price), self.assertRaises(ValidationError):
                ProductInput(title="Product", url="https://example.com", price_amount=price)

    def test_public_product_and_faq_links_keep_normal_query_strings_and_fragments(self):
        url = "https://shop.example.com/products/item?variant=123&size=large#details"
        self.assertEqual(ProductInput(title="Product", url=url, image_url="https://cdn.example.com/image.png?width=640").url, url)
        self.assertEqual(FaqInput(question="Which size?", answer="See details", source_url=url).source_url, url)

    def test_contact_capture_requires_consent_and_enabled_form(self):
        with self.assertRaises(ValidationError):
            self.lead(consent=False)
        with self.assertRaises(HTTPException):
            service.capture_lead(self.db, self.bot, self.lead())
        self.enable()
        service.capture_lead(self.db, self.bot, self.lead())
        self.assertEqual(self.db.query(ExperienceLead).count(), 1)

    def test_contact_dedupe_idempotency_and_submissions_keep_first_identity(self):
        self.enable()
        first = self.lead()
        service.capture_lead(self.db, self.bot, first)
        service.capture_lead(self.db, self.bot, first)
        service.capture_lead(self.db, self.bot, self.lead(idempotency_key="submit-5678", session_id="different-session", email="person@example.com", name="Different", message="Another request"))
        self.assertEqual(self.db.query(ExperienceLead).count(), 1)
        self.assertEqual(self.db.query(LeadSubmission).count(), 2)
        self.assertEqual(self.db.query(ExperienceLead).one().name, "Customer")
        with self.assertRaises(HTTPException) as ctx:
            service.capture_lead(self.db, self.bot, self.lead(message="Mutated request"))
        self.assertEqual(ctx.exception.status_code, 409)

    def test_routes_enforce_tenant_and_role_boundaries(self):
        self.assertEqual(self.client.get("/bot/2/experience").status_code, 404)
        self.current_user = self.db.get(User, 2)
        self.assertEqual(self.client.get("/bot/1/experience").status_code, 200)
        self.assertEqual(self.client.put("/bot/1/experience/settings", json={"enabled": True}).status_code, 403)
        self.assertEqual(self.client.get("/bot/1/experience/leads").status_code, 403)

    def test_public_lead_requires_allowed_origin_and_matching_session(self):
        self.enable()
        session_id, session_token = issue_public_session(self.db, self.bot)
        body = self.lead(session_id=session_id, session_token=session_token).model_dump()
        path = "/public/widget/1/experience/leads"
        self.assertEqual(self.client.post(path, json=body, headers={"Origin": "https://evil.example.com"}).status_code, 403)
        self.assertEqual(self.client.post(path, json=dict(body, session_token="wrong"), headers={"Origin": "https://shop.example.com"}).status_code, 401)
        response = self.client.post(path, json=body, headers={"Origin": "https://shop.example.com"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {"received": True})

    def test_public_products_never_accept_client_sources_or_another_session_turn(self):
        self.enable()
        service.save_product(self.db, self.bot, ProductInput(title="Product", url=self.doc.source_url, enabled=True))
        session_id, session_token = issue_public_session(self.db, self.bot)
        session = self.db.query(ConversationSession).filter_by(session_id=session_id).one()
        self.db.add(ConversationMessage(conversation_session_id=session.id, bot_id=1, organization_id=1,
            session_id=session_id, client_turn_id="turn-a", token_usage={"experience_sources": [{"source_url": self.doc.source_url}]}))
        self.db.commit()
        body = dict(session_id=session_id, session_token=session_token, turn_id="turn-a")
        path, headers = "/public/widget/1/experience/products/for-turn", {"Origin": "https://shop.example.com"}
        self.assertEqual(len(self.client.post(path, json=body, headers=headers).json()["products"]), 1)
        body["turn_id"] = "other-turn"
        self.assertEqual(self.client.post(path, json=body, headers=headers).json()["products"], [])
        body["sources"] = [{"source_url": self.doc.source_url}]
        self.assertEqual(self.client.post(path, json=body, headers=headers).status_code, 422)

    def test_saved_cases_snapshot_and_same_pipeline_without_customer_messages(self):
        case = service.save_case(self.db, self.bot, CaseInput(question="How long is delivery?", expected_answer="Three days", required_phrases=["three"], forbidden_phrases=["guaranteed"]))
        run = service.create_test_run(self.db, self.bot, RunInput(case_ids=[case["id"]]), 1)
        service.save_case(self.db, self.bot, CaseInput(question="Edited question"), case["id"])
        with patch("services.rag_service.answer_question", return_value=("Usually three days", [], [])) as answer, \
             patch("services.usage_service.ensure_can_send_message", return_value="reservation"), \
             patch("services.usage_service.consume_message_quota"):
            finished = service.execute_next_case(self.db, self.bot, run["id"])
            self.assertEqual(answer.call_args.kwargs["question"], "How long is delivery?")
            self.assertEqual(answer.call_args.kwargs["history"], [])
            self.assertEqual(finished["results"][0]["status"], "passed_checks")
            self.assertEqual(finished["status"], "completed")
            service.execute_next_case(self.db, self.bot, run["id"])
            self.assertEqual(answer.call_count, 1)
        self.assertEqual(self.db.query(ConversationMessage).count(), 0)

    def test_test_run_conflicts_and_error_redaction(self):
        case = service.save_case(self.db, self.bot, CaseInput(question="Sample question"))
        run = service.create_test_run(self.db, self.bot, RunInput(case_ids=[case["id"]]), 1)
        with self.assertRaises(HTTPException):
            service.create_test_run(self.db, self.bot, RunInput(case_ids=[case["id"]]), 1)
        record = self.db.get(SavedTestRun, run["id"])
        record.lease_expires_at = datetime.utcnow() + timedelta(seconds=60)
        self.db.commit()
        with self.assertRaises(HTTPException):
            service.execute_next_case(self.db, self.bot, run["id"])
        record.lease_expires_at = None
        self.db.commit()
        with patch("services.rag_service.answer_question", side_effect=RuntimeError("secret-provider-credential")), \
             patch("services.usage_service.ensure_can_send_message", return_value="reservation"), \
             patch("services.usage_service.release_message_quota") as release:
            finished = service.execute_next_case(self.db, self.bot, run["id"])
            self.assertEqual(finished["results"][0]["status"], "error")
            self.assertNotIn("secret", finished["results"][0]["error"])
            release.assert_called_once()

    def test_literal_checks_do_not_claim_factual_accuracy(self):
        self.assertEqual(service.score_phrases("An answer", [], [])[0], "manual_review")
        self.assertEqual(service.score_phrases("An answer", ["missing"], [])[0], "needs_review")
        self.assertEqual(service.score_phrases("Not guaranteed", [], ["guaranteed"])[0], "needs_review")


if __name__ == "__main__":
    unittest.main()
