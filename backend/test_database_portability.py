"""Offline portability checks and explicitly opt-in fresh PostgreSQL acceptance.

Never falls back to the application's DATABASE_URL for live acceptance.
The live test leaves its disposable database in place and does not delete data.
"""
from __future__ import annotations

import os
import re
import secrets
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

from alembic.script import ScriptDirectory
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, create_mock_engine, inspect, text
from sqlalchemy.engine import make_url


BACKEND_DIR = Path(__file__).resolve().parent
HEAD = "20260903_01"


def production_environment(database_url: str) -> dict[str, str]:
    """Synthetic config only; neither reads nor supplies real provider secrets."""
    return {
        "PYTHON_DOTENV_DISABLED": "1",
        "APP_ENV": "production",
        "DATABASE_URL": database_url,
        "REDIS_URL": "redis://127.0.0.1:1/0",
        "JWT_SECRET": secrets.token_hex(32),
        "PLATFORM_KEY_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
        "INGESTION_QUEUE_MODE": "arq",
        "ALLOW_DETERMINISTIC_EMBEDDING_FALLBACK": "false",
        "ALLOW_LEGACY_PLAINTEXT_BYOK": "false",
        "REFRESH_COOKIE_SECURE": "true",
        "CORS_ALLOWED_ORIGINS": "https://app.example.test",
        "OBJECT_STORAGE_PROVIDER": "s3",
        "OBJECT_STORAGE_ENDPOINT": "https://bucket.example.test",
        "OBJECT_STORAGE_BUCKET": "fresh-test",
        "OBJECT_STORAGE_ACCESS_KEY_ID": "synthetic-test-access",
        "OBJECT_STORAGE_SECRET_ACCESS_KEY": "synthetic-test-secret",
        "OBJECT_STORAGE_REGION": "test-region",
    }


def child_environment(database_url: str) -> dict[str, str]:
    # Do not inherit local .env, DATABASE_URL, or real provider/storage secrets.
    environment = {
        key: value for key, value in os.environ.items()
        if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR"}
    }
    return {**environment, **production_environment(database_url)}


def validate_disposable_url(value: str):
    url = make_url(value)
    if (
        url.get_backend_name() != "postgresql"
        or not re.fullmatch(r"fresh_bootstrap_[a-z0-9_]+", url.database or "")
        or "supabase" in (url.host or "").lower()
        or set(url.query) - {"sslmode", "connect_timeout"}
    ):
        raise ValueError("Use a separate fresh_bootstrap_<suffix> PostgreSQL database; Supabase and connection overrides are forbidden.")
    return url


class DatabasePortabilityTests(unittest.TestCase):
    def test_database_url_is_sufficient_without_supabase_configuration(self):
        script = (
            "from database.connection import engine; "
            "from services.migration_service import alembic_config; "
            "import os; "
            "assert not os.getenv('SUPABASE_URL') and not os.getenv('SUPABASE_KEY'); "
            "assert engine.url.host == 'postgres.example.test'; "
            "assert alembic_config().get_main_option('sqlalchemy.url') == os.environ['DATABASE_URL']"
        )
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=BACKEND_DIR,
            env=child_environment("postgresql://audit:synthetic@postgres.example.test/fresh_bootstrap_config"),
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_single_committed_migration_head(self):
        from services.migration_service import alembic_config
        scripts = ScriptDirectory.from_config(alembic_config())
        self.assertEqual(scripts.get_heads(), [HEAD])
        self.assertEqual(len(list(scripts.walk_revisions())), 4)

    def test_schema_gate_accepts_head(self):
        from services import migration_service
        with patch.object(migration_service, "migration_state", return_value=(HEAD, HEAD)):
            self.assertEqual(migration_service.require_migrations_current(MagicMock()), (HEAD, HEAD))

    def test_schema_gate_rejects_empty_and_outdated_database(self):
        from services import migration_service
        for current in (None, "20260902_02"):
            with self.subTest(current=current), patch.object(
                migration_service, "migration_state", return_value=(current, HEAD)
            ), self.assertRaisesRegex(RuntimeError, "one-off release step"):
                migration_service.require_migrations_current(MagicMock())

    def test_postgres_schema_keeps_vector_capacity_and_foreign_key_contract(self):
        from database.models import Base
        ddl = []
        mock_engine = create_mock_engine(
            "postgresql://", lambda statement, *args, **kwargs: ddl.append(
                str(statement.compile(dialect=mock_engine.dialect))
            )
        )
        Base.metadata.create_all(mock_engine)
        schema = "\n".join(ddl)
        self.assertIn("embedding VECTOR(768) NOT NULL", schema)
        self.assertIn("ck_platform_key_bot_capacity CHECK (max_bot_assignments >= 1)", schema)
        self.assertIn("FOREIGN KEY(platform_credential_id) REFERENCES platform_api_keys (id)", schema)
        self.assertIn("max_bot_assignments INTEGER DEFAULT '2' NOT NULL", schema)
        baseline = (BACKEND_DIR / "migrations/versions/20260821_01_current_schema.py").read_text()
        self.assertIn("CREATE EXTENSION IF NOT EXISTS vector", baseline)
        self.assertIn("USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)", baseline)

    def test_production_config_accepts_generic_infrastructure_without_supabase(self):
        from services.security_config_service import validate_production_security
        validate_production_security(production_environment("postgresql://audit@postgres.example.test/new_database"))

    def test_production_config_requires_database_and_redis_urls(self):
        from services.security_config_service import validate_production_security
        for field in ("DATABASE_URL", "REDIS_URL"):
            environment = production_environment("postgresql://audit@postgres.example.test/new_database")
            del environment[field]
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, field):
                validate_production_security(environment)

    def test_empty_bucket_health_needs_no_old_object(self):
        from services.object_storage import get_object_storage
        client = MagicMock()
        with patch.dict(os.environ, production_environment("postgresql://unused"), clear=True), patch(
            "boto3.client", return_value=client
        ) as factory:
            self.assertTrue(get_object_storage().healthcheck())
        self.assertEqual(client.mock_calls, [call.head_bucket(Bucket="fresh-test")])
        self.assertEqual(factory.call_args.kwargs["endpoint_url"], "https://bucket.example.test")

    def test_inaccessible_bucket_fails_health(self):
        from services.object_storage import get_object_storage
        with patch.dict(os.environ, production_environment("postgresql://unused"), clear=True), patch(
            "boto3.client"
        ) as factory:
            factory.return_value.head_bucket.side_effect = RuntimeError("unavailable")
            self.assertFalse(get_object_storage().healthcheck())

    def test_redis_connection_uses_only_configured_url_and_ping(self):
        from utils import redis_client
        client = MagicMock()
        with patch.dict(os.environ, {"REDIS_URL": "rediss://cache.example.test:6380/2"}), patch.multiple(
            redis_client, _REDIS_CLIENT=None, _OVERRIDE_CLIENT=None,
            _LAST_CONNECT_ATTEMPT=0.0, _LAST_PING_TIME=0.0, _REDIS_AVAILABLE=False,
        ), patch.object(redis_client.redis.ConnectionPool, "from_url") as pool, patch.object(
            redis_client.redis, "Redis", return_value=client
        ):
            self.assertIs(redis_client.get_redis(), client)
        self.assertEqual(pool.call_args.args, ("rediss://cache.example.test:6380/2",))
        self.assertEqual(client.mock_calls, [call.ping()])

    def test_live_acceptance_refuses_non_test_or_supabase_targets(self):
        for value in (
            "postgresql://localhost/production",
            "postgresql://example.supabase.co/fresh_bootstrap_test",
            "sqlite:///fresh_bootstrap_test",
            "postgresql://localhost/fresh_bootstrap_test?host=old-host",
            "postgresql://localhost/fresh_bootstrap_test?options=-csearch_path=customer",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_disposable_url(value)
        self.assertEqual(validate_disposable_url("postgresql://localhost/fresh_bootstrap_test").database, "fresh_bootstrap_test")


class FreshRedisTests(unittest.IsolatedAsyncioTestCase):
    async def test_queue_pool_uses_redis_url(self):
        from services import queue_service
        with patch.dict(os.environ, {"REDIS_URL": "rediss://cache.example.test:6380/2"}), patch.object(
            queue_service, "create_pool", new_callable=AsyncMock
        ) as create_pool:
            await queue_service.get_redis_pool()
        settings = create_pool.call_args.args[0]
        self.assertEqual((settings.host, settings.port, settings.database, settings.ssl), ("cache.example.test", 6380, 2, True))

    async def test_fresh_worker_creates_heartbeat_without_old_keys(self):
        from fakeredis import FakeServer, FakeStrictRedis
        from fakeredis.aioredis import FakeRedis
        from services import health_service
        from workers import worker
        server = FakeServer()
        sync_redis = FakeStrictRedis(server=server, decode_responses=True)
        async_redis = FakeRedis(server=server, decode_responses=True)
        ctx = {"redis": async_redis}
        self.assertEqual(await async_redis.dbsize(), 0)
        try:
            with patch.dict(os.environ, {"APP_ENV": "production", "INGESTION_QUEUE_MODE": "arq"}), patch.object(
                health_service, "engine"
            ), patch.object(health_service, "migration_state", return_value=(HEAD, HEAD)), patch.object(
                health_service, "get_redis", return_value=sync_redis
            ), patch.object(health_service, "get_object_storage") as storage:
                storage.return_value.healthcheck.return_value = True
                ready, status = health_service.readiness_status()
                self.assertFalse(ready)
                self.assertEqual(status["dependencies"]["worker"], "unavailable")
                await worker.startup(ctx)
                self.assertEqual(await async_redis.keys("*"), [worker.WORKER_HEARTBEAT_KEY])
                self.assertGreater(await async_redis.ttl(worker.WORKER_HEARTBEAT_KEY), 0)
                self.assertTrue(health_service.readiness_status()[0])
        finally:
            await worker.shutdown(ctx)
            await async_redis.aclose()
            sync_redis.close()


class FreshPostgresAcceptance(unittest.TestCase):
    @unittest.skipUnless(os.getenv("FRESH_BOOTSTRAP_DATABASE_URL"), "No separate disposable PostgreSQL URL supplied; old DATABASE_URL is never used")
    def test_exact_production_migration_and_application_import(self):
        from database.models import Base
        from services.migration_service import require_migrations_current
        url = validate_disposable_url(os.environ["FRESH_BOOTSTRAP_DATABASE_URL"])
        environment = child_environment(url.render_as_string(hide_password=False))
        test_engine = create_engine(url, connect_args={"connect_timeout": 5})

        def run(*args):
            result = subprocess.run(
                [sys.executable, *args], cwd=BACKEND_DIR, env=environment,
                capture_output=True, text=True, timeout=300,
            )
            # Do not leak connection credentials in a failed driver traceback.
            self.assertEqual(result.returncode, 0, "Fresh database subprocess failed; inspect this disposable database privately")

        def row_counts(connection):
            return {
                table: connection.exec_driver_sql(f'SELECT count(*) FROM "{table}"').scalar_one()
                for table in Base.metadata.tables
            }

        try:
            with test_engine.connect() as connection:
                self.assertEqual(connection.exec_driver_sql("SELECT current_schema()").scalar_one(), "public")
                existing = connection.execute(text(
                    "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname NOT IN ('pg_catalog','information_schema') "
                    "AND n.nspname NOT LIKE 'pg_%' AND c.relkind IN ('r','p','v','m','f','S')"
                )).scalar_one()
                self.assertEqual(existing, 0, "Refusing to migrate a database with existing user relations")
                self.assertTrue(connection.exec_driver_sql("SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name='vector')").scalar_one(), "pgvector server package is required")
                with self.assertRaisesRegex(RuntimeError, "one-off release step"):
                    require_migrations_current(connection)

            run("scripts/run_migrations.py")
            with test_engine.connect() as connection:
                self.assertEqual(require_migrations_current(connection), (HEAD, HEAD))
                self.assertTrue(connection.exec_driver_sql("SELECT extversion FROM pg_extension WHERE extname='vector'").scalar_one())
                inspector = inspect(connection)
                self.assertTrue(set(Base.metadata.tables) <= set(inspector.get_table_names()))
                self.assertTrue(all(count == 0 for count in row_counts(connection).values()))
                self.assertEqual(connection.exec_driver_sql("SELECT count(*) FROM alembic_version").scalar_one(), 1)
                vector_type = connection.exec_driver_sql("SELECT format_type(atttypid, atttypmod) FROM pg_attribute WHERE attrelid='chunks'::regclass AND attname='embedding'").scalar_one()
                self.assertEqual(vector_type, "vector(768)")
                vector_index = connection.exec_driver_sql("SELECT indexdef FROM pg_indexes WHERE schemaname='public' AND indexname='ix_chunks_embedding_cosine'").scalar_one()
                self.assertIn("USING ivfflat", vector_index)
                self.assertIn("vector_cosine_ops", vector_index)
                for table in Base.metadata.tables.values():
                    self.assertTrue({i.name for i in table.indexes} <= {i["name"] for i in inspector.get_indexes(table.name)})
                    expected_fks = {(tuple(c.name for c in fk.columns), fk.referred_table.name) for fk in table.foreign_key_constraints}
                    actual_fks = {(tuple(fk["constrained_columns"]), fk["referred_table"]) for fk in inspector.get_foreign_keys(table.name)}
                    self.assertTrue(expected_fks <= actual_fks, table.name)
                capacity = next(c for c in inspector.get_columns("platform_api_keys") if c["name"] == "max_bot_assignments")
                self.assertFalse(capacity["nullable"])
                self.assertIn("2", capacity["default"])
                checks = {c["name"]: c["sqltext"] for c in inspector.get_check_constraints("platform_api_keys")}
                self.assertIn("max_bot_assignments >= 1", checks["ck_platform_key_bot_capacity"])

            run("scripts/run_migrations.py")
            with test_engine.connect() as connection:
                self.assertTrue(all(count == 0 for count in row_counts(connection).values()))
            run("-c", "from scripts.start_api import prepare_database_for_startup; prepare_database_for_startup(); import main; assert main.app")
            with test_engine.connect() as connection:
                self.assertEqual(require_migrations_current(connection), (HEAD, HEAD))
                self.assertEqual(set(connection.exec_driver_sql("SELECT code FROM plans").scalars()), {"free", "pro", "team"})
                self.assertEqual(row_counts(connection), {table: 3 if table == "plans" else 0 for table in Base.metadata.tables})
        finally:
            test_engine.dispose()


if __name__ == "__main__":
    unittest.main()
