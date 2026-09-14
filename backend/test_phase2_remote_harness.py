"""Offline harness guards: fake PostgreSQL catalog/transactions, never a DB socket."""
from contextlib import contextmanager
from copy import deepcopy
import ast
import inspect
import io
import os
import re
import subprocess
import sys
import traceback
import unittest
from unittest.mock import patch

from scripts import phase2_disposable_postgres as harness


URL = "postgresql://fixture:secret-password@disposable.invalid:6543/fixture"


class ExplicitEnvironment(dict):
    def get(self, key, default=None):
        if key in {"DATABASE_URL", "DATABASE_URL_PRIVATE", "SUPABASE_DATABASE_URL"}:
            raise AssertionError("Ordinary application URL was inspected")
        return super().get(key, default)


class Rows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def __iter__(self):
        return iter(self.rows)

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    one_or_none = first

    def one(self):
        assert len(self.rows) == 1
        return self.rows[0]

    def scalar(self):
        return self.rows[0][0] if self.rows else None

    scalar_one = scalar

    def scalars(self):
        return Rows(row[0] for row in self.rows)


class Catalog:
    def __init__(self):
        self.schemas = {"public": (1, 10), "unrelated": (2, 10)}
        self.objects = {"public": {}, "unrelated": {}}
        self.markers = {}
        self.parents = {}
        self.version = "160010"
        self.vector = ("0.8.6", "public")
        self.lock = True
        self.next_oid = 100
        self.statements = []
        self.bindings = []
        self.mutations = []
        self.fail_connect = False
        self.fail_statement = None

    def oid(self):
        self.next_oid += 1
        return self.next_oid

    def relation(self, schema, name, kind="r", parent=None):
        self.objects.setdefault(schema, {})[name] = (self.oid(), kind)
        if parent:
            self.parents[(schema, name)] = parent


class FakeConnection:
    def __init__(self, engine):
        self.engine, self.db = engine, engine.db

    def __enter__(self):
        if self.db.fail_connect:
            raise RuntimeError(URL)
        return self

    def __exit__(self, *args):
        pass

    def rollback(self):
        pass

    @contextmanager
    def begin(self):
        snapshot = deepcopy((self.db.schemas, self.db.objects, self.db.markers, self.db.parents))
        try:
            yield self
        except BaseException:
            self.db.schemas, self.db.objects, self.db.markers, self.db.parents = snapshot
            raise

    def execute(self, statement, params=None):
        self.db.bindings.append((str(statement), dict(params or {})))
        return self.exec_driver_sql(str(statement), params)

    def exec_driver_sql(self, sql, params=None):
        params = params or {}
        self.db.statements.append(sql)
        for callback in self.engine.hooks.get("before_cursor_execute", []):
            callback(self, None, sql, params, None, False)
        if self.db.fail_statement and self.db.fail_statement in sql:
            raise RuntimeError(URL)
        result = self._execute(sql, params)
        for callback in self.engine.hooks.get("after_cursor_execute", []):
            callback(self, None, sql, params, None, False)
        return result

    def _execute(self, sql, params):
        db = self.db
        schema = self.engine.schema
        if sql == "SET TRANSACTION READ ONLY":
            return Rows()
        if sql == "SHOW server_version_num":
            return Rows([(db.version,)])
        if "FROM pg_catalog.pg_extension" in sql:
            return Rows([db.vector] if db.vector else [])
        if sql.startswith("SELECT c.relname, c.oid"):
            return Rows((name, *value) for name, value in db.objects.get(params["schema"], {}).items())
        if sql.startswith("SELECT c.relname FROM"):
            return Rows((name,) for objects in db.objects.values() for name in objects)
        if "nspname LIKE :pattern" in sql:
            assert params == {"pattern": "phase2_test_%"}
            pattern = re.escape(params["pattern"]).replace("_", ".").replace("%", ".*")
            return Rows((1,) for name in db.schemas if re.fullmatch(pattern, name, re.DOTALL))
        if sql.startswith("SELECT pg_try_advisory_lock"):
            return Rows([(db.lock,)])
        if "FROM pg_catalog.pg_namespace WHERE nspname=:schema" in sql:
            value = db.schemas.get(params["schema"])
            return Rows([value if "nspowner" in sql else (value[0],)] if value else [])
        if sql.startswith("SELECT oid FROM pg_catalog.pg_class"):
            return Rows((value[0],) for objects in db.objects.values() for value in objects.values()
                        if value[0] in params["ids"])
        if sql.startswith("SELECT run_id"):
            name = re.search(r'FROM "([a-z0-9_]+)"', sql)[1]
            return Rows([(db.markers[name],)])
        if sql == "SELECT current_schema()":
            return Rows([(schema,)])
        if "SELECT to_regclass" in sql:
            value = db.objects.get(schema, {}).get(params["name"])
            value = value or db.objects["public"].get(params["name"])
            return Rows([(value[0] if value else None,)])
        db.mutations.append(sql)
        if sql.startswith("CREATE SCHEMA"):
            name = sql.split('"')[1]
            assert name not in db.schemas
            db.schemas[name] = (db.oid(), 10)
            db.objects[name] = {}
        elif sql.startswith("REVOKE ALL"):
            pass
        elif sql.startswith("CREATE TABLE"):
            target = sql.split()[2]
            if "." in target:
                namespace, name = target.split(".")
                namespace = namespace.strip('"')
            else:
                namespace, name = schema, target
            db.relation(namespace, name)
            if "PRIMARY KEY" in sql:
                db.relation(namespace, name + "_pkey", "i", name)
        elif sql.startswith("INSERT INTO") and "run_id" in params:
            name = sql.split('"')[1]
            db.markers[name] = params["run_id"]
        elif sql.startswith("CREATE INDEX"):
            match = re.match(r"CREATE INDEX(?: CONCURRENTLY)? (\w+) ON (\w+)", sql)
            db.relation(schema, match[1], "i", match[2])
        elif sql.startswith("DROP INDEX"):
            db.objects[schema].pop(harness.migration_module().INDEX_NAME, None)
        elif sql.startswith("DROP TABLE"):
            namespace, name = sql.split('"')[1::2]
            db.objects[namespace].pop(name)
            for key, parent in list(db.parents.items()):
                if key[0] == namespace and parent == name:
                    db.objects[namespace].pop(key[1], None)
        elif sql.startswith("DROP SCHEMA"):
            name = sql.split('"')[1]
            assert not db.objects[name], "RESTRICT: schema is not empty"
            del db.objects[name]
            del db.schemas[name]
            db.markers.pop(name, None)
        else:
            raise AssertionError("Unexpected mocked statement: " + sql)
        return Rows()


class FakeEngine:
    def __init__(self, db, options):
        self.db, self.hooks, self.disposed = db, {}, False
        self.schema = options.split("search_path=")[1].split(",")[0]

    def connect(self):
        return FakeConnection(self)

    @contextmanager
    def begin(self):
        with self.connect() as conn, conn.begin():
            yield conn

    def dispose(self):
        self.disposed = True


class RemoteHarnessTests(unittest.TestCase):
    def setUp(self):
        self.db, self.engines, self.factory_calls = Catalog(), [], []
        self.env = ExplicitEnvironment(PHASE2_REMOTE_TEST_MODE="true", PHASE2_TEST_DATABASE_URL=URL,
                                       DATABASE_URL="must-not-inspect", DATABASE_URL_PRIVATE="must-not-inspect",
                                       SUPABASE_DATABASE_URL="must-not-inspect")
        self.enterContext(patch.object(os, "environ", self.env))
        self.factory = self.enterContext(patch("sqlalchemy.create_engine", side_effect=self.engine))
        from sqlalchemy import event
        original_listen = event.listen
        def listen(target, name, fn, *args, **kwargs):
            if isinstance(target, FakeEngine):
                target.hooks.setdefault(name, []).append(fn)
            else:
                original_listen(target, name, fn, *args, **kwargs)
        self.enterContext(patch("sqlalchemy.event.listen", side_effect=listen))
        self.output = io.StringIO()
        self.enterContext(patch("sys.stdout", self.output))
        self.docker = self.enterContext(patch.object(harness, "docker_postgres", side_effect=AssertionError("No Docker fallback")))

    def engine(self, url, **kwargs):
        self.factory_calls.append((url, kwargs))
        engine = FakeEngine(self.db, kwargs["connect_args"]["options"])
        self.engines.append(engine)
        return engine

    def run_fixture(self):
        with harness.disposable_postgres() as engine:
            harness.create_schema(engine)

    def blocked(self, action=None):
        with self.assertRaises(harness.DisposableUnavailable) as caught:
            (action or self.run_fixture)()
        self.assertNotIn(URL, str(caught.exception))
        self.assertNotIn("secret-password", self.output.getvalue() + str(caught.exception))
        self.docker.assert_not_called()
        return caught.exception

    def test_explicit_remote_url_required(self):
        del self.env["PHASE2_TEST_DATABASE_URL"]
        self.assertIn("requires PHASE2_TEST_DATABASE_URL", str(self.blocked()))
        self.factory.assert_not_called()

    def test_application_urls_never_inspected_or_used(self):
        self.run_fixture()
        self.assertEqual(len(self.factory_calls), 2)
        self.assertTrue(all(url.render_as_string(hide_password=False) == URL.replace("postgresql:", "postgresql+psycopg2:")
                            for url, _ in self.factory_calls))

    def test_empty_disposable_database_and_owned_cleanup(self):
        self.run_fixture()
        self.assertEqual(set(self.db.schemas), {"public", "unrelated"})
        self.assertTrue(all(engine.disposed for engine in self.engines))
        self.assertIn("server_version_num=160010; pgvector=0.8.6", self.output.getvalue())
        self.assertNotIn(URL, self.output.getvalue())
        self.assertFalse(any("CREATE EXTENSION" in sql or "DROP DATABASE" in sql or "CASCADE" in sql
                             for sql in self.db.mutations))

    def test_every_application_table_is_refused_in_any_schema(self):
        for name in harness.APPLICATION_TABLES:
            with self.subTest(name=name):
                self.db.objects["unrelated"] = {name: (900, "r")}
                self.assertIn("Existing application objects", str(self.blocked()))
                self.assertEqual(self.db.mutations, [])

    def test_application_view_or_foreign_table_is_also_refused(self):
        for kind in ("v", "f", "m"):
            self.db.objects["public"] = {"chunks": (900, kind)}
            self.assertIn("Existing application objects", str(self.blocked()))
        self.assertEqual(self.db.mutations, [])

    def test_existing_migration_index_is_refused(self):
        self.db.relation("public", harness.migration_module().INDEX_NAME, "i")
        self.assertIn("Existing application objects", str(self.blocked()))
        self.assertEqual(self.db.mutations, [])

    def test_stale_harness_schema_is_not_adopted(self):
        self.db.schemas["phase2_test_old"] = (777, 10)
        self.assertIn("Existing disposable schema", str(self.blocked()))
        self.assertEqual(self.db.mutations, [])

    def test_stale_schema_query_binds_exact_pattern_on_both_preflights(self):
        self.run_fixture()
        checks = [(sql, params) for sql, params in self.db.bindings if "nspname LIKE" in sql]
        self.assertEqual(len(checks), 2)
        for sql, params in checks:
            self.assertIn("nspname LIKE :pattern LIMIT 1", sql)
            self.assertNotIn("%", sql)
            self.assertEqual(params, {"pattern": "phase2_test_%"})
        self.assertEqual(set(self.db.schemas), {"public", "unrelated"})

    def test_stale_schema_pattern_preserves_existing_like_semantics(self):
        for name in ("phase2_test_" + "b" * 32, "phase2_test_", "phase2XtestYrun"):
            with self.subTest(schema=name):
                self.db.schemas[name] = (777, 10)
                self.assertIn("Existing disposable schema", str(self.blocked()))
                self.assertEqual(self.db.mutations, [])
                del self.db.schemas[name]

    def test_stale_schema_query_error_fails_closed_without_ddl(self):
        self.db.fail_statement = "nspname LIKE :pattern"
        self.assertIn("details suppressed", str(self.blocked()))
        self.assertEqual(self.db.mutations, [])
        self.assertEqual(len(self.factory_calls), 1)
        self.assertTrue(all(engine.disposed for engine in self.engines))

    def test_stale_schema_appearing_before_locked_recheck_is_refused(self):
        original = FakeConnection._execute
        def add_stale(conn, sql, params):
            result = original(conn, sql, params)
            if sql.startswith("SELECT pg_try_advisory_lock"):
                self.db.schemas["phase2_test_" + "c" * 32] = (777, 10)
            return result
        with patch.object(FakeConnection, "_execute", add_stale):
            self.assertIn("Existing disposable schema", str(self.blocked()))
        self.assertEqual(self.db.mutations, [])
        self.assertEqual(sum("nspname LIKE" in sql for sql, _ in self.db.bindings), 2)

    def test_bound_pattern_uses_installed_psycopg2_parameter_boundary(self):
        from psycopg2.extensions import adapt
        from sqlalchemy import text
        from sqlalchemy.dialects.postgresql.psycopg2 import PGDialect_psycopg2
        from unittest.mock import Mock
        self.run_fixture()
        sql, params = next((sql, params) for sql, params in self.db.bindings if "nspname LIKE" in sql)
        dialect = PGDialect_psycopg2()
        compiled = text(sql).compile(dialect=dialect)
        bound = compiled.construct_params(params)
        cursor = Mock()
        dialect.do_execute(cursor, str(compiled), bound)
        wire_sql, wire_params = cursor.execute.call_args.args
        self.assertEqual(dialect.paramstyle, "pyformat")
        self.assertIn("nspname LIKE %(pattern)s LIMIT 1", wire_sql)
        self.assertNotIn("phase2_test_", wire_sql)
        self.assertEqual(wire_params, {"pattern": "phase2_test_%"})
        self.assertIsNone(re.search(r"%(?!\(pattern\)s|%)", wire_sql))
        # Real psycopg2 adapts the value without a connection; cursor/server I/O is mocked.
        quoted = adapt(wire_params["pattern"]).getquoted().decode("ascii")
        self.assertEqual(quoted, "'phase2_test_%'")
        self.assertIn("LIKE 'phase2_test_%' LIMIT 1", wire_sql % {"pattern": quoted})

    def test_disposable_harness_has_no_literal_raw_driver_percent(self):
        tree = ast.parse(inspect.getsource(harness))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "exec_driver_sql" and node.args):
                argument = node.args[0]
                literals = argument.values if isinstance(argument, ast.JoinedStr) else [argument]
                for literal in literals:
                    if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
                        self.assertNotIn("%", literal.value, f"Unsafe raw wildcard at line {node.lineno}")

    def test_bound_preflight_accepts_postgresql_18_metadata(self):
        self.db.version = "180006"
        self.run_fixture()
        self.assertIn("server_version_num=180006; pgvector=0.8.6", self.output.getvalue())

    def test_pgvector_absence_stops_without_install(self):
        self.db.vector = None
        self.assertIn("pgvector extension must already exist", str(self.blocked()))
        self.assertEqual(self.db.mutations, [])

    def test_unreachable_server_has_sanitized_error(self):
        self.db.fail_connect = True
        self.blocked()
        self.assertTrue(self.engines[0].disposed)

    def test_bad_url_driver_host_overrides_and_missing_parts_are_refused(self):
        for value in ("invalid-secret-password", "sqlite:///fixture", URL + "?host=production.invalid",
                      URL + "?options=secret-password", URL + "?service=production", URL + "?sslmode=unknown",
                      "postgresql:///fixture", "postgresql://fixture@disposable.invalid/fixture",
                      "postgresql://fixture:secret-password@disposable.invalid",
                      URL.replace(":6543", ":0"), URL.replace(":6543", ":65536"),
                      URL.replace("disposable.invalid", "first.invalid,second.invalid"), URL + "=host-other"):
            with self.subTest(kind="invalid explicit URL"):
                self.env["PHASE2_TEST_DATABASE_URL"] = value
                self.blocked()
        self.factory.assert_not_called()

    def test_safe_sslmode_and_explicit_default_port(self):
        self.env["PHASE2_TEST_DATABASE_URL"] = URL.replace(":6543", "") + "?sslmode=require"
        self.run_fixture()
        url, kwargs = self.factory_calls[0]
        self.assertEqual(url.port, 5432)
        self.assertEqual(url.query, {"sslmode": "require"})
        self.assertTrue(kwargs["hide_parameters"])
        self.assertFalse(kwargs["echo"])

    def test_mode_is_case_sensitive_true_only(self):
        for value in (None, "false", "TRUE", "1", " true "):
            self.env["PHASE2_REMOTE_TEST_MODE"] = value
            self.assertFalse(harness.remote_test_mode())
            with self.assertRaises(harness.DisposableUnavailable):
                harness._remote_url()
        self.factory.assert_not_called()

    def test_run_marker_and_private_schema_are_created(self):
        with harness.disposable_postgres() as engine:
            state = engine._phase2_remote_run
            self.assertRegex(state["run_id"], r"^[a-f0-9]{32}$")
            self.assertEqual(state["schema"], "phase2_test_" + state["run_id"])
            self.assertEqual(self.db.markers[state["schema"]], state["run_id"])
            self.assertIn(harness.MARKER, state["owned"])
            self.assertTrue(any(sql.startswith("REVOKE ALL") for sql in self.db.mutations))

    def test_marker_value_mismatch_refuses_all_cleanup(self):
        def run():
            with harness.disposable_postgres() as engine:
                self.db.markers[engine._phase2_remote_run["schema"]] = "another-run"
        self.assertIn("run ID does not own", str(self.blocked(run)))
        self.assertFalse(any(sql.startswith("DROP") for sql in self.db.mutations))

    def test_replaced_marker_oid_refuses_cleanup(self):
        def run():
            with harness.disposable_postgres() as engine:
                self.db.relation(engine._phase2_remote_run["schema"], harness.MARKER)
        self.assertIn("marker changed", str(self.blocked(run)))
        self.assertFalse(any(sql.startswith("DROP") for sql in self.db.mutations))

    def test_schema_owner_change_refuses_cleanup(self):
        def run():
            with harness.disposable_postgres() as engine:
                schema = engine._phase2_remote_run["schema"]
                self.db.schemas[schema] = (self.db.schemas[schema][0], 99)
        self.assertIn("schema ownership changed", str(self.blocked(run)))
        self.assertFalse(any(sql.startswith("DROP") for sql in self.db.mutations))

    def test_unrelated_table_outside_run_schema_is_preserved(self):
        self.db.relation("unrelated", "unrelated_metrics")
        before = deepcopy(self.db.objects["unrelated"])
        self.run_fixture()
        self.assertEqual(self.db.objects["unrelated"], before)
        drops = [sql for sql in self.db.mutations if sql.startswith("DROP")]
        self.assertTrue(drops)
        self.assertTrue(all('"phase2_test_' in sql and sql.endswith(" RESTRICT") for sql in drops))

    def test_unknown_object_inside_run_schema_refuses_cleanup(self):
        def run():
            with harness.disposable_postgres() as engine:
                harness.create_schema(engine)
                self.db.relation(engine._phase2_remote_run["schema"], "not_ours")
        self.assertIn("Unowned remote object", str(self.blocked(run)))
        self.assertFalse(any(sql.startswith("DROP") for sql in self.db.mutations))

    def test_moved_owned_table_is_not_dropped_in_another_schema(self):
        def run():
            with harness.disposable_postgres() as engine:
                harness.create_schema(engine)
                schema = engine._phase2_remote_run["schema"]
                self.db.objects["unrelated"]["moved_documents"] = self.db.objects[schema].pop("documents")
        self.assertIn("moved outside", str(self.blocked(run)))
        self.assertFalse(any(sql.startswith("DROP") for sql in self.db.mutations))

    def test_body_exception_is_sanitized_and_cleaned(self):
        def run():
            with harness.disposable_postgres() as engine:
                harness.create_schema(engine)
                raise RuntimeError(URL)
        self.blocked(run)
        self.assertEqual(set(self.db.schemas), {"public", "unrelated"})

    def test_second_engine_setup_failure_still_cleans_marker(self):
        def factory(url, **kwargs):
            if self.engines:
                raise RuntimeError(URL)
            return self.engine(url, **kwargs)
        self.factory.side_effect = factory
        self.blocked()
        self.assertEqual(set(self.db.schemas), {"public", "unrelated"})

    def test_atomic_fixture_creation_failure_still_cleans_schema(self):
        self.db.fail_statement = "CREATE TABLE chunks"
        self.blocked()
        self.assertEqual(set(self.db.schemas), {"public", "unrelated"})

    def test_concurrent_harness_lock_failure_has_no_ddl(self):
        self.db.lock = False
        self.assertIn("Another disposable remote run", str(self.blocked()))
        self.assertEqual(self.db.mutations, [])

    def test_remote_extension_and_foreign_ddl_are_blocked(self):
        with harness.disposable_postgres() as engine:
            for sql in ("CREATE EXTENSION vector", "CREATE TABLE public.evil (id int)", "DROP TABLE public.users"):
                with self.assertRaises(harness.DisposableUnavailable), engine.begin() as conn:
                    conn.exec_driver_sql(sql)
        self.assertFalse(any("EXTENSION" in sql or "public.evil" in sql or "public.users" in sql for sql in self.db.mutations))

    def test_downgrade_cannot_resolve_foreign_index(self):
        with harness.disposable_postgres() as engine:
            harness.create_schema(engine)
            self.db.relation("public", harness.migration_module().INDEX_NAME, "i")
            with self.assertRaises(harness.DisposableUnavailable), engine.begin() as conn:
                conn.exec_driver_sql(harness.migration_module().DROP_SQL)
        self.assertIn(harness.migration_module().INDEX_NAME, self.db.objects["public"])

    def test_owned_fixture_indexes_recorded_and_removed(self):
        with harness.disposable_postgres() as engine:
            harness.create_schema(engine)
            with engine.begin() as conn:
                conn.exec_driver_sql("CREATE INDEX ix_chunks_embedding_cosine ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)")
            self.assertIn("ix_chunks_embedding_cosine", engine._phase2_remote_run["owned"])
        self.assertFalse(any(self.db.objects.values()))

    def test_owned_migration_index_replacement_and_cleanup(self):
        with harness.disposable_postgres() as engine:
            harness.create_schema(engine)
            # Execute strings against the fake catalog only, never Alembic/PG.
            for sql in (harness.migration_module().CREATE_SQL, harness.migration_module().DROP_SQL,
                        harness.migration_module().CREATE_SQL):
                with engine.begin() as conn:
                    conn.exec_driver_sql(sql)
            self.assertIn(harness.migration_module().INDEX_NAME, engine._phase2_remote_run["owned"])
        self.assertFalse(any(self.db.objects.values()))

    def test_missing_marker_refuses_cleanup(self):
        def run():
            with harness.disposable_postgres() as engine:
                self.db.objects[engine._phase2_remote_run["schema"]].pop(harness.MARKER)
        self.assertIn("marker changed", str(self.blocked(run)))
        self.assertFalse(any(sql.startswith("DROP") for sql in self.db.mutations))

    def test_unowned_invalid_index_from_interrupted_create_is_not_adopted(self):
        def run():
            with harness.disposable_postgres() as engine:
                harness.create_schema(engine)
                self.db.relation(engine._phase2_remote_run["schema"], harness.migration_module().INDEX_NAME, "i", "chunks")
        self.assertIn("Unowned remote object", str(self.blocked(run)))
        self.assertFalse(any(sql.startswith("DROP") for sql in self.db.mutations))

    def test_both_command_entrypoints_fail_before_import_or_fallback(self):
        from scripts import test_phase2_postgres, benchmark_phase2_hybrid_retrieval
        del self.env["PHASE2_TEST_DATABASE_URL"]
        self.assertEqual(test_phase2_postgres.main(), 2)
        self.assertEqual(benchmark_phase2_hybrid_retrieval.main(), 2)
        self.factory.assert_not_called()
        self.docker.assert_not_called()

    def test_remote_failure_traceback_does_not_contain_url_or_password(self):
        self.db.fail_connect = True
        try:
            self.run_fixture()
        except harness.DisposableUnavailable:
            value = traceback.format_exc()
        self.assertNotIn(URL, value)
        self.assertNotIn("secret-password", value)

    def test_unittest_result_suppresses_raw_driver_errors(self):
        stream = io.StringIO()
        class Failing(unittest.TestCase):
            def runTest(self):
                raise RuntimeError(URL)
        unittest.TextTestRunner(stream=stream, resultclass=harness.acceptance_test_result()).run(Failing())
        self.assertNotIn(URL, stream.getvalue())
        self.assertNotIn("secret-password", stream.getvalue())
        self.assertIn("details suppressed", stream.getvalue())

    def test_cleanup_verification_failure_is_reported(self):
        original = FakeConnection._execute
        def keep_schema(conn, sql, params):
            if sql.startswith("DROP SCHEMA"):
                return Rows()
            return original(conn, sql, params)
        with patch.object(FakeConnection, "_execute", keep_schema):
            self.blocked()


class DockerAndImportBoundaryTests(unittest.TestCase):
    def test_successful_docker_lifecycle_is_unchanged(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        engine = MagicMock()
        values = ["npipe://local", "28.0", "container", "127.0.0.1:54321", ""]
        with patch.dict(os.environ, {"PHASE2_REMOTE_TEST_MODE": "false", "PHASE2_TEST_DATABASE_URL": URL}), \
             patch.object(harness.shutil, "which", return_value="docker"), \
             patch.object(harness, "docker", side_effect=values) as docker, \
             patch.object(harness.uuid, "uuid4", return_value=SimpleNamespace(hex="a" * 32)), \
             patch.object(harness.secrets, "token_urlsafe", return_value="fixture-password"), \
             patch.object(harness.subprocess, "run") as remove, \
             patch("sys.stdout", io.StringIO()), \
             patch("sqlalchemy.create_engine", return_value=engine) as factory:
            with harness.disposable_postgres() as yielded:
                self.assertIs(yielded, engine)
            self.assertEqual(docker.call_args_list[0].args, ("context", "inspect", "default", "--format", "{{.Endpoints.docker.Host}}"))
            run = docker.call_args_list[2]
            self.assertEqual(run.args, ("run", "--detach", "--rm", "--name", "phase2-pg-" + "a" * 32,
                                      "--label", "codex.phase2.disposable=true", "--publish", "127.0.0.1::5432",
                                      "--env", "POSTGRES_PASSWORD", "--env", "POSTGRES_USER=phase2",
                                      "--env", "POSTGRES_DB=phase2", "pgvector/pgvector:pg16"))
            self.assertTrue(set(run.kwargs["env"]).issubset({"PATH", "SYSTEMROOT", "TEMP", "TMP", "POSTGRES_PASSWORD"}))
            self.assertEqual(remove.call_args.args[0], ["docker", "--context", "default", "rm", "--force", "phase2-pg-" + "a" * 32])
            self.assertEqual(factory.call_args.args[0].host, "127.0.0.1")
            self.assertEqual(factory.call_args.args[0].port, 54321)
            engine.dispose.assert_called_once()

    def test_false_mode_routes_only_to_existing_docker_context(self):
        @contextmanager
        def docker():
            yield "docker-engine"
        with patch.dict(os.environ, {"PHASE2_REMOTE_TEST_MODE": "false", "PHASE2_TEST_DATABASE_URL": URL}), \
             patch.object(harness, "docker_postgres", docker), \
             patch.object(harness, "remote_postgres", side_effect=AssertionError("No remote path")):
            with harness.disposable_postgres() as engine:
                self.assertEqual(engine, "docker-engine")
            self.assertIs(harness.acceptance_test_result(), unittest.TextTestResult)

    def test_unavailable_docker_does_not_use_remote_url(self):
        with patch.dict(os.environ, {"PHASE2_REMOTE_TEST_MODE": "false", "PHASE2_TEST_DATABASE_URL": URL}), \
             patch.object(harness.shutil, "which", return_value=None), \
             patch("sqlalchemy.create_engine") as factory:
            with self.assertRaises(harness.DisposableUnavailable):
                with harness.disposable_postgres():
                    self.fail("Docker unavailable")
            factory.assert_not_called()

    def test_docker_local_socket_guard_remains(self):
        with patch.dict(os.environ, {"PHASE2_REMOTE_TEST_MODE": "false"}), \
             patch.object(harness.shutil, "which", return_value="docker"), \
             patch.object(harness, "docker", return_value="tcp://remote.invalid:2376") as docker:
            with self.assertRaises(harness.DisposableUnavailable):
                with harness.disposable_postgres():
                    self.fail("Remote Docker prohibited")
            self.assertEqual(docker.call_count, 1)

    def test_docker_schema_keeps_existing_extension_and_ddl(self):
        db = Catalog()
        engine = FakeEngine(db, "-c search_path=public")
        # Only this legacy extension statement is stubbed; all existing DDL is inspected.
        original = FakeConnection._execute
        def extension(conn, sql, params):
            if sql == "CREATE EXTENSION vector":
                db.mutations.append(sql)
                return Rows()
            return original(conn, sql, params)
        with patch.object(FakeConnection, "_execute", extension):
            harness.create_schema(engine)
        self.assertEqual(db.mutations[0], "CREATE EXTENSION vector")
        self.assertTrue(harness.FIXTURE_TABLES.issubset(db.objects["public"]))

    def test_remote_boundary_refuses_preimported_app_settings(self):
        with patch.dict(os.environ, {"PHASE2_REMOTE_TEST_MODE": "true"}), \
             patch.dict(sys.modules, {"database.connection": object()}):
            with self.assertRaises(harness.DisposableUnavailable):
                with harness.application_import_boundary(None):
                    self.fail("Preloaded application settings")

    def test_fresh_remote_imports_ignore_app_settings_and_cannot_connect(self):
        # Fresh interpreter exercises actual imports and all Phase 2 offline tests;
        # a socket tripwire prevents any real database/HTTP transport.
        code = r'''
import os, socket, unittest
from unittest.mock import patch
os.environ['PHASE2_REMOTE_TEST_MODE']='true'
class Guard(dict):
    def get(self, key, default=None):
        if key in {'DATABASE_URL','DATABASE_URL_PRIVATE','SUPABASE_DATABASE_URL'}:
            raise AssertionError('Application URL was inspected')
        return super().get(key, default)
from scripts.phase2_disposable_postgres import application_import_boundary
with patch.object(os,'environ',Guard(os.environ)), patch.object(socket.socket,'connect',side_effect=AssertionError('External network forbidden')):
    with application_import_boundary(None):
        from database import connection
        try:
            connection.SessionLocal()
            raise RuntimeError('Default session was not blocked')
        except AssertionError:
            pass
        import test_phase2_hybrid_retrieval
        result=unittest.TextTestRunner(verbosity=0).run(unittest.defaultTestLoader.loadTestsFromName('test_phase2_hybrid_retrieval'))
        assert result.wasSuccessful()
'''
        result = subprocess.run([sys.executable, "-B", "-W", "ignore::DeprecationWarning", "-c", code],
                                capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
