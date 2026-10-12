"""Optional PostgreSQL transaction checks, isolated in a disposable test schema."""
import os
import re
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest.mock import patch
from uuid import uuid4
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from database.connection import Base, get_db
from database.models import Bot, Customer, Organization, OrganizationMembership, User
from database.experience_models import ExperienceLead, ExperienceSettings, LeadSubmission, SavedTestRun
from database.experience_integration_models import ExperienceIntegration
from routes.experience_integration_routes import router as integrations_router
from routes.experience_routes import router as experience_router
from schemas.experience import ExperienceSettingsInput, FaqInput, LeadInput, TestCaseInput as CaseInput, TestRunInput as RunInput
from services import experience_service as service
from services.auth_service import get_current_user


@unittest.skipUnless(os.getenv("CUSTOMER_EXPERIENCE_POSTGRES_TESTS") == "1", "Enable only against the isolated local PostgreSQL test database")
class ExperiencePostgresTests(unittest.TestCase):
    def setUp(self):
        database_url = os.environ["DATABASE_URL"]
        parsed = urlsplit(database_url)
        self.assertIn(parsed.hostname, {"localhost", "127.0.0.1"})
        self.assertIn("experience", parsed.path)
        self.schema = "experience_test_" + uuid4().hex
        self.assertRegex(self.schema, r"^experience_test_[a-f0-9]{32}$")
        self.control = create_engine(database_url)
        with self.control.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = create_engine(database_url, connect_args={"options": f"-csearch_path={self.schema},public"}, pool_size=10)
        Base.metadata.create_all(self.engine, checkfirst=False)
        self.session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.session() as db:
            db.add(Customer(id=1, name="Concurrency test", api_key="test-only"))
            db.add(User(id=1, email="concurrency@example.test", name="Operator", password_hash="test-only"))
            db.add_all([Organization(id=1, name="A", slug="a"), Organization(id=2, name="B", slug="b")])
            db.commit()
            bot = Bot(id=1, name="Test bot", customer_id=1, organization_id=1)
            db.add(bot)
            db.commit()
            service.save_settings(db, bot, ExperienceSettingsInput(enabled=True, lead_form_enabled=True, approved_faq_enabled=True))

    def tearDown(self):
        self.engine.dispose()
        with self.control.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        self.control.dispose()

    def submit(self, index, unique=False):
        with self.session() as db:
            bot = db.get(Bot, 1)
            return service.capture_lead(db, bot, LeadInput(session_id="visitor", session_token="test", idempotency_key=f"submission-{index if unique else 1}", name="Visitor", email="person@example.test", message=f"message-{index if unique else 1}", consent=True))

    def test_duplicate_public_submissions_are_atomic(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(self.submit, range(8)))
        self.assertEqual(results, [{"received": True}] * 8)
        with self.session() as db:
            self.assertEqual(db.query(ExperienceLead).count(), 1)
            self.assertEqual(db.query(LeadSubmission).count(), 1)

    def test_distinct_submissions_dedupe_contact_without_losing_messages(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda n: self.submit(n, unique=True), range(8)))
        self.assertEqual(results, [{"received": True}] * 8)
        with self.session() as db:
            self.assertEqual(db.query(ExperienceLead).count(), 1)
            self.assertEqual(db.query(LeadSubmission).count(), 8)

    def test_long_multilingual_alias_uses_bounded_unique_index(self):
        with self.session() as db:
            bot = db.get(Bot, 1)
            question = "中" * 950
            service.save_faq(db, bot, FaqInput(question=question, answer="Approved", approved=True, enabled=True), 1)
            self.assertEqual(service.lookup_approved_faq(db, bot, question)["reply"], "Approved")

    def test_database_blocks_wrong_tenant_and_run_creation_is_serialized(self):
        with self.session() as db:
            bot = db.get(Bot, 1)
            case = service.save_case(db, bot, CaseInput(question="A saved question"))
            row = db.query(ExperienceSettings).one()
            row.organization_id = 2
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()
        def create(_):
            with self.session() as db:
                try:
                    return service.create_test_run(db, db.get(Bot, 1), RunInput(case_ids=[case["id"]]), 1)["id"]
                except HTTPException as exc:
                    db.rollback()
                    return exc.status_code
        with ThreadPoolExecutor(max_workers=4) as executor:
            outcomes = list(executor.map(create, range(4)))
        self.assertEqual(outcomes.count(409), 3)
        with self.session() as db:
            self.assertEqual(db.query(SavedTestRun).count(), 1)

    def test_two_browsers_cannot_execute_one_saved_question_twice(self):
        with self.session() as db:
            bot = db.get(Bot, 1)
            case = service.save_case(db, bot, CaseInput(question="A saved question", required_phrases=["Correct"]))
            run_id = service.create_test_run(db, bot, RunInput(case_ids=[case["id"]]), 1)["id"]
        started, finish = Event(), Event()
        def answer(**kwargs):
            started.set()
            if not finish.wait(10):
                raise RuntimeError("Test executor timed out")
            return "Correct answer", [], []
        def execute():
            with self.session() as db:
                try:
                    return service.execute_next_case(db, db.get(Bot, 1), run_id)
                except HTTPException as exc:
                    db.rollback()
                    return exc.status_code
        with patch("services.rag_service.answer_question", side_effect=answer) as provider, \
             patch("services.usage_service.ensure_can_send_message", return_value="test-reservation"), \
             patch("services.usage_service.consume_message_quota"), \
             ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(execute)
            self.assertTrue(started.wait(5))
            second = executor.submit(execute)
            try:
                self.assertEqual(second.result(timeout=5), 409)
            finally:
                finish.set()
            result = first.result(timeout=5)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["results"][0]["status"], "passed_checks")
            provider.assert_called_once()

    def concurrent_puts(self, path, payloads):
        with self.session() as db:
            db.add(OrganizationMembership(user_id=1, organization_id=1, role="editor"))
            db.commit()
            user = db.get(User, 1)
        def database():
            with self.session() as db:
                yield db
        app = FastAPI()
        app.include_router(integrations_router)
        app.include_router(experience_router)
        app.dependency_overrides[get_db] = database
        app.dependency_overrides[get_current_user] = lambda: user
        ready = Barrier(2)
        with TestClient(app) as client:
            def save(payload):
                ready.wait(timeout=5)
                return client.put(path, json=payload)
            with ThreadPoolExecutor(max_workers=2) as executor:
                responses = list(executor.map(save, payloads))
        self.assertEqual([response.status_code for response in responses], [200, 200])
        return responses

    def test_two_editor_tabs_can_create_integrations_without_unique_key_error(self):
        payloads = [{"booking": {"enabled": True, "provider": "calcom", "url": f"https://cal.com/team-{index}/meeting"}} for index in range(2)]
        self.concurrent_puts("/bot/1/experience/integrations", payloads)
        with self.session() as db:
            rows = db.query(ExperienceIntegration).all()
            self.assertEqual(len(rows), 1)
            self.assertIn(rows[0].config_json["booking"]["url"], [payload["booking"]["url"] for payload in payloads])

    def test_two_editor_tabs_can_create_experience_settings_without_unique_key_error(self):
        with self.session() as db:
            db.query(ExperienceSettings).delete()
            db.commit()
        self.concurrent_puts("/bot/1/experience/settings", [{"enabled": True}, {"enabled": False}])
        with self.session() as db:
            self.assertEqual(db.query(ExperienceSettings).count(), 1)
