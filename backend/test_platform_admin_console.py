"""Isolated API/service contracts: no customer data and no provider calls."""
import contextlib
import io
import logging
import os
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.connection import Base, get_db
from database.models import AuditLog, Bot, Chunk, Customer, Document, Organization, OrganizationMembership, PlatformApiKey, User
from routes import admin_routes, auth_routes, bot_routes
from scripts.set_platform_admin import main as bootstrap_main, promote_account
from services.auth_service import create_access_token, hash_password
from services.bot_service import SUPPORTED_MODELS, serialize_bot
from services.platform_key_service import get_decrypted_key_for_bot
from utils.encryption import _get_fernet, decrypt_key


class PlatformAdminConsoleTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.env = patch.dict(os.environ, {"PLATFORM_KEY_ENCRYPTION_KEY": Fernet.generate_key().decode()})
        self.env.start(); _get_fernet.cache_clear()
        self.cache = patch("routes.admin_routes.invalidate_bot_cache")
        self.cache.start()
        with self.sessions() as db:
            db.add_all([Customer(id=1, name="Customer Alpha", api_key="synthetic-customer-alpha"), Customer(id=2, name="Customer Beta", api_key="synthetic-customer-beta")])
            db.add_all([User(id=1, name="Operator", email="operator@example.test", password_hash="synthetic-hash", is_admin=True),
                        User(id=2, name="Customer", email="customer@example.test", password_hash="synthetic-hash"),
                        User(id=3, name="Owner", email="owner@example.test", password_hash="synthetic-hash")])
            db.flush()
            db.add_all([Organization(id=1, name="Org Alpha", slug="alpha", owner_user_id=3), Organization(id=2, name="Org Beta", slug="beta")])
            db.add_all([OrganizationMembership(user_id=3, organization_id=1, role="owner"), OrganizationMembership(user_id=2, organization_id=1, role="viewer")])
            db.add_all([Bot(id=1, name="Alpha", organization_id=1, customer_id=1), Bot(id=2, name="Beta", organization_id=2, customer_id=2)])
            db.commit()
            self.headers = {i: {"Authorization": "Bearer " + create_access_token(db.get(User, i))[0]} for i in (1, 2, 3)}
        self.app = FastAPI()
        self.app.include_router(admin_routes.router, prefix="/admin")
        self.app.include_router(auth_routes.router, prefix="/auth")
        self.app.include_router(bot_routes.router, prefix="/bot")

        def isolated_db():
            with self.sessions() as db:
                yield db
        self.app.dependency_overrides[get_db] = isolated_db
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close(); self.cache.stop(); self.env.stop(); _get_fernet.cache_clear(); self.engine.dispose()

    def add(self, provider="gemini", secret="synthetic-provider-secret", label="Primary"):
        response = self.client.post("/admin/platform-keys", json={"provider": provider, "api_key": secret, "label": label}, headers=self.headers[1])
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def bot(self, bot_id=1):
        return next(bot for bot in self.client.get("/admin/bots", headers=self.headers[1]).json()["items"] if bot["id"] == bot_id)

    def configure(self, provider, model, key_id, *, bot_id=1, expected=None):
        actual = self.bot(bot_id)
        snapshot = {field: actual[field] for field in ("provider", "model_name", "credential_profile_id")}
        return self.client.patch(f"/admin/bots/{bot_id}/provider-config", headers=self.headers[1], json={
            "provider": provider, "model_name": model, "credential_profile_id": key_id, "expected": expected or snapshot})

    def test_all_admin_endpoints_require_server_admin(self):
        for route in admin_routes.router.routes:
            path = "/admin" + route.path.replace("{key_id}", "1").replace("{bot_id}", "1")
            for method in route.methods:
                for headers, expected in (({}, 401), ({"Cookie": "chatbot_refresh=synthetic-refresh-cookie"}, 401), (self.headers[2], 403), (self.headers[3], 403), ({"Authorization": "Bearer widget-session-token"}, 401)):
                    response = self.client.request(method, path, headers=headers, json={})
                    self.assertEqual(response.status_code, expected, (method, path, response.text))
        self.assertEqual(self.client.get("/admin/session", headers=self.headers[1]).json(), {"user_id": 1, "is_admin": True})

    def test_role_is_read_from_database_not_jwt_or_org_owner(self):
        with self.sessions() as db:
            db.get(User, 1).is_admin = False; db.commit()
        self.assertEqual(self.client.get("/admin/session", headers=self.headers[1]).status_code, 403)

    def test_customer_cannot_promote_or_cross_tenant(self):
        response = self.client.patch("/auth/profile", json={"is_admin": True}, headers=self.headers[3])
        self.assertFalse(response.json()["is_admin"])
        self.assertIn(self.client.get("/bot/2", headers=self.headers[3]).status_code, (403, 404))
        for path in ("/admin/bootstrap", "/auth/set-platform-admin"):
            self.assertEqual(self.client.post(path, headers=self.headers[3]).status_code, 404)

    def test_registration_never_promotes_even_with_legacy_environment(self):
        with patch.dict(os.environ, {"BOOTSTRAP_ADMIN_EMAIL": "new@example.test"}), patch("routes.auth_routes.create_organization") as create_org, patch("routes.auth_routes.get_or_create_subscription"):
            create_org.return_value.id = 1
            response = self.client.post("/auth/register", json={"name": "New", "email": "new@example.test", "password": "Synthetic-pass-123", "is_admin": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["user"]["is_admin"])

    def test_secret_encrypted_and_never_returned_or_logged(self):
        log = io.StringIO(); handler = logging.StreamHandler(log); logging.getLogger().addHandler(handler)
        secret = "synthetic-distinct-provider-secret"
        try:
            saved = self.add(secret=secret)
            with self.sessions() as db:
                stored = db.get(PlatformApiKey, saved["id"]).encrypted_key
                self.assertNotIn(secret.encode(), stored)
                self.assertEqual(decrypt_key(stored), secret)
            with patch("services.platform_key_service.decrypt_key", side_effect=AssertionError("Must not decrypt for display")):
                listing = self.client.get("/admin/platform-keys", headers=self.headers[1])
            for output in (str(saved), listing.text, log.getvalue()):
                self.assertNotIn(secret, output); self.assertNotIn(stored.decode(), output)
                for forbidden in ("encrypted_key", "masked_key", "api_key", "ciphertext"):
                    self.assertNotIn(forbidden, output)
        finally:
            logging.getLogger().removeHandler(handler)

    def test_error_and_validation_responses_do_not_echo_secret(self):
        short_secret = "shrtkey"
        result = self.client.post("/admin/platform-keys", json={"provider": "gemini", "api_key": short_secret, "label": "Test"}, headers=self.headers[1])
        self.assertEqual(result.status_code, 422); self.assertNotIn(short_secret, result.text)
        secret = "synthetic-error-flow-secret"
        stream = io.StringIO(); handler = logging.StreamHandler(stream); logging.getLogger().addHandler(handler)
        try:
            with patch("routes.admin_routes.keys.admin_add_key", side_effect=SQLAlchemyError(secret)):
                result = self.client.post("/admin/platform-keys", json={"provider": "gemini", "api_key": secret, "label": "Test"}, headers=self.headers[1])
            self.assertEqual(result.status_code, 503)
            self.assertNotIn(secret, result.text + stream.getvalue())
        finally:
            logging.getLogger().removeHandler(handler)

    def test_provider_catalog_and_multiple_profiles(self):
        catalog = self.client.get("/admin/provider-options", headers=self.headers[1]).json()
        self.assertEqual({row["id"]: set(row["models"]) for row in catalog["providers"]}, SUPPORTED_MODELS)
        for provider in ("gemini", "gemini", "openai", "claude", "grok"):
            self.add(provider)
        page = self.client.get("/admin/platform-keys?provider=gemini&limit=1", headers=self.headers[1]).json()
        self.assertEqual((page["total"], len(page["items"])), (2, 1))
        self.assertEqual(self.client.get("/admin/platform-keys?limit=101", headers=self.headers[1]).status_code, 422)

    def test_assignment_provider_safety_and_bot_isolation(self):
        gemini = self.add(); openai = self.add("openai")
        before_b = self.bot(2)
        response = self.configure("gemini", "gemini-2.5-flash", gemini["id"])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["credential_profile_id"], gemini["id"])
        self.assertEqual(self.configure("gemini", "gemini-2.5-flash", openai["id"]).status_code, 400)
        self.assertEqual(self.configure("openai", "gpt-4.1-mini", openai["id"]).status_code, 200)
        self.assertEqual(self.bot(2), before_b)
        with self.sessions() as db:
            self.assertEqual(db.get(PlatformApiKey, gemini["id"]).status, "available")
            self.assertEqual(get_decrypted_key_for_bot(db, 1), "synthetic-provider-secret")
            self.assertIsNone(get_decrypted_key_for_bot(db, 2))

    def test_assignment_is_one_bot_only_and_rejects_disabled(self):
        key = self.add()
        self.assertEqual(self.configure("gemini", "gemini-2.5-flash", key["id"]).status_code, 200)
        self.assertEqual(self.configure("gemini", "gemini-2.5-flash", key["id"], bot_id=2).status_code, 409)
        self.client.post(f'/admin/platform-keys/{key["id"]}/disable', headers=self.headers[1])
        self.assertEqual(self.configure("gemini", "gemini-2.5-flash", key["id"]).status_code, 400)

    def test_disable_delete_enable_and_audit(self):
        key = self.add(); path = f'/admin/platform-keys/{key["id"]}'
        self.configure("gemini", "gemini-2.5-flash", key["id"])
        self.assertEqual(self.client.delete(path, headers=self.headers[1]).status_code, 400)
        self.assertEqual(self.client.post(path + "/disable", headers=self.headers[1]).status_code, 200)
        self.assertIsNone(self.bot()["credential_profile_id"])
        with self.sessions() as db:
            self.assertIsNone(get_decrypted_key_for_bot(db, 1))
        self.assertEqual(self.client.post(path + "/enable", headers=self.headers[1]).json()["status"], "available")
        self.assertEqual(self.client.put(path, headers=self.headers[1], json={"label": "Replacement"}).json()["label"], "Replacement")
        self.assertEqual(self.client.delete(path, headers=self.headers[1]).status_code, 200)
        with self.sessions() as db:
            logs = db.query(AuditLog).all()
            self.assertTrue(all(log.user_id == 1 and log.created_at for log in logs))
            self.assertTrue(any("credential.deleted" in log.action for log in logs))

    def test_invalid_model_byok_and_stale_updates_fail_atomically(self):
        key = self.add()
        before = self.bot()
        self.assertEqual(self.configure("openai", "fabricated-model", key["id"]).status_code, 422)
        self.assertEqual(self.bot(), before)
        snapshot = {field: before[field] for field in ("provider", "model_name", "credential_profile_id")}
        self.configure("gemini", "gemini-2.5-flash", key["id"])
        self.assertEqual(self.configure("gemini", "gemini-1.5-pro", None, expected=snapshot).status_code, 409)
        with self.sessions() as db:
            db.get(Bot, 1).provider_api_key = "synthetic-encrypted-byok"; db.commit()
        self.assertEqual(self.configure("gemini", "gemini-1.5-pro", None).status_code, 409)

    def test_generation_change_does_not_write_knowledge_or_embeddings(self):
        with self.sessions() as db:
            doc = Document(bot_id=1, organization_id=1, filename="synthetic", source_type="text", raw_text="Synthetic knowledge",
                           embedding_provider="gemini", embedding_model="gemini-embedding-001", embedding_dimensions=768, embedding_version=1)
            db.add(doc); db.flush()
            db.add(Chunk(bot_id=1, organization_id=1, document_id=doc.id, content="Synthetic knowledge", embedding=[0.0] * 768))
            db.commit()
            before = (repr(db.execute(select(Document.__table__)).all()), repr(db.execute(select(Chunk.__table__)).all()))
        writes = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE")): writes.append(statement.lower())
        event.listen(self.engine, "before_cursor_execute", capture)
        key = self.add("openai")
        self.assertEqual(self.configure("openai", "gpt-4.1-mini", key["id"]).status_code, 200)
        with self.sessions() as db:
            after = (repr(db.execute(select(Document.__table__)).all()), repr(db.execute(select(Chunk.__table__)).all()))
        self.assertEqual(before, after)
        self.assertFalse(any("documents" in statement or "chunks" in statement for statement in writes))

    def test_customer_bot_serialization_omits_platform_private_metadata(self):
        key = self.add(label="Private platform label")
        self.configure("gemini", "gemini-2.5-flash", key["id"])
        with self.sessions() as db:
            body = serialize_bot(db.get(Bot, 1))
        self.assertNotIn("platform_credential_id", body); self.assertNotIn("platform_credential_label", body)
        self.assertNotIn("Private platform label", str(body))

    def test_organization_bot_search_is_bounded_and_safe(self):
        response = self.client.get("/admin/organizations?search=Alpha&limit=1", headers=self.headers[1]).json()
        self.assertEqual(response["items"][0]["bot_count"], 1)
        response = self.client.get("/admin/bots?search=Customer%20Beta", headers=self.headers[1]).json()
        self.assertEqual([bot["id"] for bot in response["items"]], [2])
        self.assertNotIn("password", str(response)); self.assertNotIn("api_key", str(response))
        self.assertEqual(self.client.get("/admin/overview", headers=self.headers[1]).json()["organizations"], 2)

    def test_bootstrap_explicit_idempotent_no_password_disclosure(self):
        with self.sessions() as db:
            with self.assertRaises(ValueError): promote_account(db)
            with self.assertRaises(ValueError): promote_account(db, user_id=999)
            self.assertEqual(promote_account(db, email="OWNER@example.test"), (3, True))
            self.assertEqual(promote_account(db, user_id=3), (3, False))
            self.assertEqual(db.query(AuditLog).filter(AuditLog.action == "platform.admin.promoted_cli:user:3").count(), 1)
            db.get(User, 2).disabled = True; db.commit()
            with self.assertRaises(ValueError): promote_account(db, user_id=2)
            db.get(User, 2).disabled = False; db.commit()
        output = io.StringIO()
        with patch("scripts.set_platform_admin.SessionLocal", self.sessions), contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            self.assertEqual(bootstrap_main(["--user-id", "3", "--yes"]), 0)
            with patch("builtins.input", return_value="CANCEL"):
                self.assertEqual(bootstrap_main(["--user-id", "2"]), 1)
            with self.assertRaises(SystemExit): bootstrap_main([])
        self.assertNotIn("synthetic-hash", output.getvalue())
        with self.sessions() as db: self.assertFalse(db.get(User, 2).is_admin)


if __name__ == "__main__":
    unittest.main()
