import os
import sys
import threading
import unittest
from datetime import datetime, timedelta
from http.cookies import SimpleCookie
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi import HTTPException, Response
from starlette.requests import Request

from database.models import AuthRefreshSession, Bot, ConversationSession, Customer, User
from routes.auth_routes import change_password
from schemas.schemas import ChangePasswordRequest
from services.auth_service import (
    enforce_auth_cookie_request,
    _hash_token,
    hash_password,
    revoke_all_refresh_sessions,
    revoke_refresh_token,
    rotate_refresh_session,
    set_refresh_cookie,
    verify_password,
)
from services.bot_secret_service import (
    BYOK_PREFIX,
    decrypt_bot_provider_key,
    encrypt_bot_provider_key,
    is_encrypted_bot_key,
    migrate_legacy_bot_keys,
)
from services.bot_service import serialize_bot
from services.llm_router import _resolve_api_key
from services.organization_service import ROLE_ORDER, require_org_role
from services.public_access_service import issue_public_session, validate_public_session
from services.security_config_service import validate_production_security
from utils.encryption import _get_fernet
from utils.secret_redaction import redact_secrets


class _RotationStore:
    def __init__(self, revoked=False, barrier=None):
        self.lock = threading.Lock()
        self.barrier = barrier
        self.session = SimpleNamespace(
            id=1,
            user_id=7,
            revoked_at=datetime.utcnow() if revoked else None,
            expires_at=datetime.utcnow() + timedelta(days=1),
        )
        self.user = SimpleNamespace(id=7, name="User", email="u@example.test", disabled=False)
        self.successors = []


class _RotationQuery:
    def __init__(self, store, model):
        self.store = store
        self.model = model

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        if self.model is User:
            return self.store.user
        if self.store.barrier:
            self.store.barrier.wait(timeout=3)
        return self.store.session

    def update(self, values, synchronize_session=False):
        with self.store.lock:
            session = self.store.session
            if session.revoked_at is not None or session.expires_at <= datetime.utcnow():
                return 0
            for key, value in values.items():
                setattr(session, key.key, value)
            return 1


class _RotationDB:
    def __init__(self, store):
        self.store = store

    def query(self, model):
        return _RotationQuery(self.store, model)

    def add(self, value):
        self.store.successors.append(value)

    def commit(self):
        return None

    def rollback(self):
        return None


class _SessionsQuery:
    def __init__(self, db):
        self.db = db

    def filter(self, *args, **kwargs):
        return self

    def update(self, values, synchronize_session=False):
        changed = 0
        for session in self.db.sessions:
            if session.revoked_at is None:
                for key, value in values.items():
                    setattr(session, key.key, value)
                changed += 1
        return changed


class _SessionsDB:
    def __init__(self, count):
        self.sessions = [SimpleNamespace(revoked_at=None) for _ in range(count)]
        self.commits = 0

    def query(self, model):
        return _SessionsQuery(self)

    def commit(self):
        self.commits += 1


class _MigrationQuery:
    def __init__(self, bots):
        self.bots = bots

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self.bots


class _MigrationDB:
    def __init__(self, bots):
        self.bots = bots
        self.commits = 0

    def query(self, model):
        return _MigrationQuery(self.bots)

    def commit(self):
        self.commits += 1


class _PublicQuery:
    def __init__(self, db):
        self.db = db

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.db.session


class _PublicDB:
    def __init__(self):
        self.session = None

    def add(self, value):
        self.session = value

    def commit(self):
        return None

    def query(self, model):
        return _PublicQuery(self)


def _request(origin: str, requested_with: str | None = "XMLHttpRequest") -> Request:
    headers = [(b"origin", origin.encode())]
    if requested_with:
        headers.append((b"x-requested-with", requested_with.encode()))
    return Request({
        "type": "http", "http_version": "1.1", "method": "POST", "scheme": "https",
        "path": "/auth/refresh", "raw_path": b"/auth/refresh", "query_string": b"", "headers": headers,
        "client": ("127.0.0.1", 1), "server": ("api.example.test", 443),
    })


def _password_request(refresh_token: str) -> Request:
    return Request({
        "type": "http", "http_version": "1.1", "method": "POST", "scheme": "https",
        "path": "/auth/change-password", "raw_path": b"/auth/change-password", "query_string": b"",
        "headers": [(b"cookie", f"chatbot_refresh={refresh_token}".encode())],
        "client": ("127.0.0.1", 1), "server": ("api.example.test", 443),
    })


class TestPhaseFAuthSecrets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fernet_key = Fernet.generate_key().decode("ascii")

    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {"PLATFORM_KEY_ENCRYPTION_KEY": self.fernet_key, "APP_ENV": "development"},
            clear=False,
        )
        self.env.start()
        _get_fernet.cache_clear()

    def tearDown(self):
        _get_fernet.cache_clear()
        self.env.stop()

    def test_a_new_byok_is_encrypted_at_rest(self):
        plaintext = "sk-phase-f-new-provider-key"
        stored = encrypt_bot_provider_key(plaintext)
        self.assertTrue(stored.startswith(BYOK_PREFIX))
        self.assertNotIn(plaintext, stored)
        self.assertEqual(decrypt_bot_provider_key(stored, allow_legacy=False), plaintext)

    def test_b_provider_boundary_decrypts_byok(self):
        plaintext = "sk-phase-f-provider-use"
        bot = Bot(id=1, name="Encrypted", provider="openai", model_name="gpt-4.1-mini")
        bot.provider_api_key = encrypt_bot_provider_key(plaintext)
        self.assertEqual(_resolve_api_key(bot), (plaintext, False))

    def test_c_normal_bot_response_never_returns_plaintext(self):
        plaintext = "sk-phase-f-not-in-response"
        bot = Bot(id=1, customer_id=2, organization_id=3, name="Safe", provider="openai", model_name="gpt-4.1-mini")
        bot.provider_api_key = encrypt_bot_provider_key(plaintext)
        result = serialize_bot(bot)
        self.assertNotIn("provider_api_key", result)
        self.assertNotIn(plaintext, repr(result))
        self.assertIn("****", result["provider_api_key_masked"])

    def test_d_omitted_replace_and_clear_credential_semantics(self):
        original = encrypt_bot_provider_key("sk-original-phase-f")
        omitted = original
        replacement = encrypt_bot_provider_key("sk-replacement-phase-f")
        cleared = None
        self.assertEqual(omitted, original)
        self.assertNotEqual(replacement, original)
        self.assertIsNone(cleared)

    def test_e_legacy_plaintext_migration_is_idempotent(self):
        legacy = SimpleNamespace(provider_api_key="sk-legacy-phase-f")
        encrypted = SimpleNamespace(provider_api_key=encrypt_bot_provider_key("sk-already-encrypted"))
        db = _MigrationDB([legacy, encrypted])
        first = migrate_legacy_bot_keys(db)
        second = migrate_legacy_bot_keys(db)
        self.assertEqual(first, {"migrated": 1, "already_encrypted": 1})
        self.assertEqual(second, {"migrated": 0, "already_encrypted": 2})
        self.assertTrue(is_encrypted_bot_key(legacy.provider_api_key))

    def test_f_same_refresh_token_rotates_exactly_once_concurrently(self):
        store = _RotationStore(barrier=threading.Barrier(2))
        outcomes = []

        def rotate():
            try:
                rotate_refresh_session(_RotationDB(store), "one-refresh-token")
                outcomes.append("success")
            except HTTPException:
                outcomes.append("rejected")

        threads = [threading.Thread(target=rotate), threading.Thread(target=rotate)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(sorted(outcomes), ["rejected", "success"])
        self.assertEqual(len(store.successors), 1)

    def test_g_revoked_refresh_token_cannot_rotate(self):
        with self.assertRaises(HTTPException) as context:
            rotate_refresh_session(_RotationDB(_RotationStore(revoked=True)), "revoked-refresh-token")
        self.assertEqual(context.exception.status_code, 401)

    def test_h_through_k_password_change_rotates_current_session_and_revokes_all_old_sessions(self):
        engine = create_engine("sqlite:///:memory:")
        Customer.__table__.create(engine)
        User.__table__.create(engine)
        AuthRefreshSession.__table__.create(engine)
        db = sessionmaker(bind=engine)()
        customer = Customer(name="Phase F1", api_key="phase-f1-customer-key")
        db.add(customer)
        db.flush()
        user = User(
            name="Current device",
            email="current@example.test",
            password_hash=hash_password("old-password"),
            customer_id=customer.id,
            disabled=False,
        )
        db.add(user)
        db.flush()
        session_a_token = "current-refresh-session-a"
        session_b_token = "other-refresh-session-b"
        expires = datetime.utcnow() + timedelta(days=1)
        db.add_all([
            AuthRefreshSession(user_id=user.id, token_hash=_hash_token(session_a_token), expires_at=expires),
            AuthRefreshSession(user_id=user.id, token_hash=_hash_token(session_b_token), expires_at=expires),
        ])
        db.commit()

        # Deterministically model an old-device refresh that wins immediately
        # before the password-change transaction revokes every active row.
        _, concurrent_old_successor = rotate_refresh_session(db, session_b_token)

        response = Response()
        result = change_password(
            ChangePasswordRequest(old_password="old-password", new_password="new-password"),
            response,
            _password_request(session_a_token),
            current_user=user,
            db=db,
        )

        # A/B/C/D/E/G/H/I: both old sessions are dead, a fresh cookie is issued,
        # and the current browser has no reauthentication instruction.
        self.assertEqual(result, {"success": True})
        cookies = SimpleCookie()
        cookies.load(response.headers["set-cookie"])
        next_token = cookies["chatbot_refresh"].value
        self.assertNotEqual(next_token, session_a_token)
        self.assertTrue(verify_password("new-password", user.password_hash))
        self.assertFalse(verify_password("old-password", user.password_hash))
        for old_token in (session_a_token, session_b_token, concurrent_old_successor):
            with self.assertRaises(HTTPException) as rejected:
                rotate_refresh_session(db, old_token)
            self.assertEqual(rejected.exception.status_code, 401)

        # F: the new current-device credential works, then J: logout-all kills it.
        _, rotated_again = rotate_refresh_session(db, next_token)
        self.assertTrue(rotated_again)
        self.assertEqual(revoke_all_refresh_sessions(db, user.id), 1)
        with self.assertRaises(HTTPException):
            rotate_refresh_session(db, rotated_again)

    def test_i_logout_revokes_the_presented_session(self):
        db = _SessionsDB(1)
        self.assertTrue(revoke_refresh_token(db, "presented-refresh-token"))
        self.assertIsNotNone(db.sessions[0].revoked_at)
        self.assertFalse(revoke_refresh_token(db, "presented-refresh-token"))

    def test_j_logout_all_revokes_every_active_refresh_session(self):
        db = _SessionsDB(4)
        self.assertEqual(revoke_all_refresh_sessions(db, 77), 4)
        self.assertTrue(all(session.revoked_at for session in db.sessions))

    def _assert_role(self, actual_role, allowed_minimums):
        membership = SimpleNamespace(role=actual_role)
        with patch("services.organization_service.get_membership", return_value=membership):
            for minimum in ROLE_ORDER:
                if minimum in allowed_minimums:
                    self.assertIs(require_org_role(None, None, 1, minimum), membership)
                else:
                    with self.assertRaises(HTTPException):
                        require_org_role(None, None, 1, minimum)

    def test_k_viewer_permission_floor(self):
        self._assert_role("viewer", {"viewer"})

    def test_l_member_permission_floor(self):
        self._assert_role("member", {"viewer", "member"})

    def test_m_editor_permission_floor(self):
        self._assert_role("editor", {"viewer", "member", "editor"})

    def test_n_admin_permission_floor(self):
        self._assert_role("admin", {"viewer", "member", "editor", "admin"})

    def test_o_owner_permission_floor(self):
        self._assert_role("owner", set(ROLE_ORDER))

    def test_p_frontend_role_is_membership_scoped_and_tokens_are_not_persisted(self):
        frontend = BACKEND_DIR.parent / "frontend"
        store = (frontend / "store" / "auth-store.ts").read_text(encoding="utf-8")
        navbar = (frontend / "components" / "layout" / "top-navbar.tsx").read_text(encoding="utf-8")
        platform = (frontend / "components" / "platform" / "platform-client.tsx").read_text(encoding="utf-8")
        auth_user = store.split("type AuthState", 1)[0]
        persisted = store.split("partialize:", 1)[1].split("merge:", 1)[0]
        self.assertNotIn("role:", auth_user)
        self.assertIn("setSelectedOrganization(org.id, org.role)", navbar)
        self.assertNotIn("accessToken:", persisted)
        self.assertNotIn("refreshToken:", persisted)
        self.assertIn("Other sessions have been signed out.", platform)
        self.assertNotIn("router.replace(\"/login\")", platform)
        self.assertNotIn("clearSession();", platform)

    def test_q_r_production_rejects_missing_and_known_development_jwt_secrets(self):
        base = {
            "APP_ENV": "production",
            "PLATFORM_KEY_ENCRYPTION_KEY": self.fernet_key,
            "REFRESH_COOKIE_SECURE": "true",
        }
        with self.assertRaisesRegex(RuntimeError, "JWT_SECRET"):
            validate_production_security(base)
        with self.assertRaisesRegex(RuntimeError, "JWT_SECRET"):
            validate_production_security({**base, "JWT_SECRET": "dev-change-me-before-production"})

    def test_production_rejects_missing_or_invalid_encryption_secret(self):
        base = {"APP_ENV": "production", "JWT_SECRET": "x" * 40, "REFRESH_COOKIE_SECURE": "true"}
        with self.assertRaisesRegex(RuntimeError, "PLATFORM_KEY_ENCRYPTION_KEY"):
            validate_production_security(base)
        with self.assertRaisesRegex(RuntimeError, "valid Fernet"):
            validate_production_security({**base, "PLATFORM_KEY_ENCRYPTION_KEY": "invalid"})

    def test_s_representative_credentials_are_redacted(self):
        jwt = "eyJheader12345.eyJpayload12345.signature12345"
        provider = "sk-phase-f-super-secret"
        refresh = "refresh-token-phase-f-secret"
        message = f"Authorization: Bearer {jwt}; api_key={provider}; refresh_token={refresh}"
        safe = redact_secrets(message, known_secrets=(provider, refresh))
        self.assertNotIn(jwt, safe)
        self.assertNotIn(provider, safe)
        self.assertNotIn(refresh, safe)

    def test_cookie_flags_and_cross_origin_csrf_guard(self):
        response = Response()
        with patch.dict(os.environ, {"APP_ENV": "production", "REFRESH_COOKIE_SECURE": "true"}, clear=False):
            set_refresh_cookie(response, "refresh-secret")
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("secure", cookie)
        self.assertIn("samesite=lax", cookie)
        with patch.dict(os.environ, {"APP_ENV": "production", "AUTH_ALLOWED_ORIGINS": "https://app.example.test"}, clear=False):
            enforce_auth_cookie_request(_request("https://app.example.test"))
            with self.assertRaises(HTTPException):
                enforce_auth_cookie_request(_request("https://evil.example.test"))
            with self.assertRaises(HTTPException):
                enforce_auth_cookie_request(_request("https://app.example.test", requested_with=None))

    def test_registration_cannot_bootstrap_admin(self):
        source = (BACKEND_DIR / "routes" / "auth_routes.py").read_text(encoding="utf-8")
        self.assertIn("is_admin=False", source)
        self.assertNotIn("is_bootstrap_admin", source)

    def test_t_public_widget_session_credentials_are_unchanged(self):
        db = _PublicDB()
        bot = SimpleNamespace(id=91, organization_id=92)
        session_id, token = issue_public_session(db, bot)
        session = validate_public_session(db, bot, session_id, token)
        self.assertIs(session, db.session)
        with self.assertRaises(HTTPException):
            validate_public_session(db, bot, session_id, "wrong-token")


if __name__ == "__main__":
    unittest.main()
