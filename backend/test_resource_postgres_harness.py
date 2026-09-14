"""Offline guard/DDL checks; these are NOT real PostgreSQL acceptance."""
from contextlib import contextmanager
from io import StringIO
import inspect
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import MetaData
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from database.connection import Base
from database import models
from database.resource_schema_v1 import TABLE_NAMES, install_postgres_indexes_and_triggers
from scripts import test_phase3_postgres as harness


class LocalHarnessTests(unittest.TestCase):
    def test_only_explicit_loopback_disposable_target(self):
        synthetic = "postgresql://fixture:fixture@127.0.0.1:5432/phase3_test_fixture"
        with patch.dict("os.environ", {"PHASE3_TEST_DATABASE_URL": synthetic}, clear=True):
            url = harness.explicit_local_url()
        self.assertEqual(url.database, "phase3_test_fixture")
        self.assertEqual(url.drivername, "postgresql+psycopg2")

    def test_remote_application_and_libpq_override_targets_refused(self):
        values = ("postgresql://fixture:fixture@external.invalid:5432/phase3_test_fixture",
                  "postgresql://fixture:fixture@localhost:5432/app",
                  "postgresql://fixture:fixture@localhost:5432/phase3_test_fixture?host=external.invalid",
                  "postgresql://fixture:fixture@localhost:5432/phase3_test_fixture?sslmode=unknown",
                  "postgresql://localhost:5432/phase3_test_fixture",
                  "not-a-dsn")
        for value in values:
            with self.subTest(value=value), patch.dict("os.environ", {"PHASE3_TEST_DATABASE_URL": value}, clear=True):
                with self.assertRaises(harness.DisposableUnavailable) as err:
                    harness.explicit_local_url()
                self.assertNotIn(value, str(err.exception))
                self.assertNotIn("fixture:fixture", str(err.exception))

    def test_application_and_phase2_remote_variables_cannot_select_target(self):
        @contextmanager
        def docker_only():
            yield "owned-local"
        with patch.dict("os.environ", {"DATABASE_URL": "forbidden", "DATABASE_URL_PRIVATE": "forbidden",
              "PHASE2_REMOTE_TEST_MODE": "true", "PHASE2_TEST_DATABASE_URL": "forbidden"}, clear=True), \
             patch.object(harness, "docker_postgres", docker_only):
            self.assertIsNone(harness.explicit_local_url())
            with harness.local_database() as engine:
                self.assertEqual(engine, "owned-local")

    def test_missing_docker_is_blocked_without_connection(self):
        with patch.dict("os.environ", {}, clear=True), patch("shutil.which", return_value=None), \
             patch("sqlalchemy.create_engine", side_effect=AssertionError("must not connect")), \
             patch("sys.stdout", new_callable=StringIO) as output:
            self.assertEqual(harness.main(), 2)
        self.assertIn("BLOCKED", output.getvalue())

    def test_raw_database_errors_not_logged(self):
        @contextmanager
        def failing():
            raise RuntimeError("synthetic-credential-marker")
            yield
        with patch.object(harness, "local_database", failing), patch("sys.stdout", new_callable=StringIO) as output:
            self.assertEqual(harness.main(), 1)
        self.assertNotIn("synthetic-credential-marker", output.getvalue())

    def test_target_engine_disposed_even_on_failure(self):
        engine = Mock()
        with patch.object(harness, "explicit_local_url", return_value="synthetic-target"), \
             patch("sqlalchemy.create_engine", return_value=engine) as create:
            with self.assertRaises(ValueError):
                with harness.local_database():
                    raise ValueError("test")
        engine.dispose.assert_called_once()
        self.assertEqual(create.call_args.kwargs, {"connect_args": {"connect_timeout": 8}, "echo": False, "hide_parameters": True})

    def test_application_imports_require_fresh_process(self):
        with self.assertRaises(harness.DisposableUnavailable):
            with harness.isolated_application_imports():
                self.fail("loaded application imports cannot select a DB")

    def test_fixture_registration_rejects_unowned_tables(self):
        conn = Mock()
        conn.info = {"phase3_owned": {"schema": "phase3_test_synthetic", "tables": {harness.MARKER: 1}}}
        conn.execute.return_value.all.return_value = [(harness.MARKER, 1), ("unrelated_fixture", 2)]
        with self.assertRaises(harness.DisposableUnavailable):
            harness.record_fixture_tables(conn)

    def test_fixture_registration_rejects_replaced_marker(self):
        conn = Mock()
        conn.info = {"phase3_owned": {"schema": "phase3_test_synthetic", "tables": {harness.MARKER: 1}}}
        conn.execute.return_value.all.return_value = [(harness.MARKER, 2)]
        with self.assertRaises(harness.DisposableUnavailable):
            harness.record_fixture_tables(conn)

    def test_migration_ddl_and_composite_scope_compile(self):
        for name in TABLE_NAMES:
            sql = str(CreateTable(Base.metadata.tables[name]).compile(dialect=postgresql.dialect()))
            self.assertIn("organization_id", sql)
            self.assertIn("bot_id", sql)
            self.assertIn("FOREIGN KEY", sql)
        sql = str(CreateTable(Base.metadata.tables["knowledge_resource_documents"]).compile(dialect=postgresql.dialect()))
        self.assertIn("FOREIGN KEY(document_id, organization_id, bot_id)", sql)
        self.assertIn("FOREIGN KEY(resource_id, organization_id, bot_id)", sql)
        migration = harness.migration_module()
        self.assertEqual(migration.down_revision, "20260910_01")
        source = inspect.getsource(migration)
        self.assertNotIn("DROP EXTENSION", source)
        self.assertNotIn("UPDATE chunks", source)

    def test_postgres_indexes_and_revision_search_path(self):
        conn = Mock()
        conn.dialect = postgresql.dialect()
        conn.execute.return_value.scalar_one.return_value = "phase3_test_fixture"
        install_postgres_indexes_and_triggers(conn)
        statements = [call.args[0] for call in conn.exec_driver_sql.call_args_list]
        self.assertIn("'simple'::regconfig", statements[0])
        self.assertIn("USING gin", statements[0])
        self.assertIn("gin_trgm_ops", statements[1])
        self.assertIn('SET search_path TO pg_catalog, "phase3_test_fixture", pg_temp', statements[2])
        self.assertIn("FROM bots", statements[2])
        self.assertIn("ON CONFLICT", statements[2])
        self.assertEqual(len(statements), 6)

    def test_cleanup_uses_owned_schema_restrict_not_database_or_extension(self):
        source = inspect.getsource(harness.owned_schema)
        for forbidden in ("DROP DATABASE", "DROP EXTENSION", " CASCADE", "DATABASE_URL"):
            self.assertNotIn(forbidden, source)
        for guard in ("pg_try_advisory_lock", "REVOKE ALL", "marker_oid", "ownership changed", "RESTRICT", "cleanup verification"):
            self.assertIn(guard, source)
        self.assertIn("nspname LIKE :pattern", source)


if __name__ == "__main__":
    unittest.main()
