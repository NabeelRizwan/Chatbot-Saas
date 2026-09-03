"""Run DB-backed admin regressions in an isolated schema, without paid APIs.

Run from backend: python scripts/test_admin_regressions.py
Only synthetic fixture data is written. No migrations or customer corpus writes.
"""
from contextlib import ExitStack, redirect_stdout
import io
import os
from pathlib import Path
import re
import runpy
import sys
import unittest
import uuid
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from cryptography.fernet import Fernet  # noqa: E402
import fakeredis  # noqa: E402
import fakeredis.aioredis  # noqa: E402
from sqlalchemy import create_engine, inspect, text  # noqa: E402
from database import connection  # noqa: E402
from database.models import Base  # noqa: E402
from services.embedding_service import _fallback_embedding  # noqa: E402
from utils.redis_client import set_redis_override  # noqa: E402


def main() -> int:
    schema = "admin_regression_test_" + uuid.uuid4().hex
    original_engine = connection.engine
    with original_engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(original_engine.url.set(query={"options": f"-c search_path={schema},public,extensions"}),
                           pool_size=20, max_overflow=10, hide_parameters=True)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT current_schema()")).scalar() == schema
        Base.metadata.create_all(engine, checkfirst=False)
        assert set(Base.metadata.tables) <= set(inspect(engine).get_table_names(schema=schema))
        connection.SessionLocal.configure(bind=engine)
        connection.engine = engine
        fake_sync, fake_async = fakeredis.FakeRedis(), fakeredis.aioredis.FakeRedis()
        set_redis_override(fake_sync, fake_async)

        class SyntheticEmbeddings:
            def embed(self, value): return _fallback_embedding(value)
            def embed_batch(self, values): return [self.embed(value) for value in values]

        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {
                "DATABASE_URL": engine.url.render_as_string(hide_password=False),
                "PLATFORM_KEY_ENCRYPTION_KEY": Fernet.generate_key().decode(),
                "APP_ENV": "development", "ALLOW_DETERMINISTIC_EMBEDDING_FALLBACK": "true",
            }))
            stack.enter_context(patch("services.embedding_service.get_embedding_provider", return_value=SyntheticEmbeddings()))
            # Secondary critique/polish calls must never escape to a provider.
            stack.enter_context(patch("services.conversational_engine.generate", return_value=""))
            stack.enter_context(patch("services.llm_router.generate", side_effect=AssertionError("Paid generation forbidden in admin tests")))
            stack.enter_context(patch("httpx.Client.send", side_effect=AssertionError("External HTTP forbidden in admin regressions")))
            stack.enter_context(patch("httpx.AsyncClient.send", side_effect=AssertionError("External HTTP forbidden in admin regressions")))
            stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("External HTTP forbidden in admin regressions")))
            # All tables already exist in the isolated schema; bypass legacy
            # compatibility DDL in suites that call init_db during setup.
            stack.enter_context(patch("database.connection.init_db"))
            suites_ok = True
            for name in ("test_phase11_security_suite", "test_production_platform_suite", "test_phase_g_atomic_usage_analytics"):
                set_redis_override(fake_sync, fake_async)
                suite = unittest.defaultTestLoader.loadTestsFromName(name)
                print(f"Running {name}", flush=True)
                with redirect_stdout(io.StringIO()):
                    result = unittest.TextTestRunner(verbosity=1).run(suite)
                suites_ok = result.wasSuccessful() and suites_ok
            pool_output = io.StringIO()
            with redirect_stdout(pool_output):
                try:
                    runpy.run_path(str(BACKEND_DIR / "verify_platform_keys.py"), run_name="__main__")
                except SystemExit as exc:
                    pool_ok = exc.code in (0, None)
                else:
                    pool_ok = True
            print("\n".join(line for line in pool_output.getvalue().splitlines() if "Results:" in line or "[FAIL]" in line))
            return 0 if suites_ok and pool_ok else 1
    finally:
        set_redis_override(None, None)
        connection.engine = original_engine
        connection.SessionLocal.configure(bind=original_engine)
        engine.dispose()
        assert re.fullmatch(r"admin_regression_test_[0-9a-f]{32}", schema)
        with original_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


if __name__ == "__main__":
    raise SystemExit(main())
