"""Disposable PostgreSQL ownership boundary; Docker unless explicitly opted in.

Only an official pgvector image, random localhost port, no volumes, generated
credentials, and the exact container created here may be used or removed.
Remote mode accepts ONLY PHASE2_TEST_DATABASE_URL and owns a fresh schema, not
the supplied database. No application settings or dotenv are consulted here.
"""
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import os
import re
import secrets
import shutil
import subprocess
import time
import uuid


IMAGE = "pgvector/pgvector:pg16"
DOCKER_PREFIX = ["docker", "--context", "default"]


class DisposableUnavailable(RuntimeError):
    pass


def docker(*args, env=None):
    result = subprocess.run([*DOCKER_PREFIX, *args], capture_output=True, text=True, env=env, timeout=180)
    if result.returncode:
        raise DisposableUnavailable("Disposable Docker operation failed (details suppressed)")
    return result.stdout.strip()


@contextmanager
def disposable_postgres():
    if remote_test_mode():
        with remote_postgres() as engine:
            yield engine
        return
    with docker_postgres() as engine:
        yield engine


@contextmanager
def docker_postgres():
    if not shutil.which("docker"):
        raise DisposableUnavailable("Docker is not available; no configured/remote database fallback is permitted")
    # Pin the default context rather than inheriting a remote Docker context or
    # DOCKER_HOST. A remote daemon is outside this local-only task boundary.
    endpoint = docker("context", "inspect", "default", "--format", "{{.Endpoints.docker.Host}}")
    if not endpoint.startswith(("npipe://", "unix://")):
        raise DisposableUnavailable("Disposable validation requires a local Docker socket/context")
    docker("info", "--format", "{{.ServerVersion}}")
    name = "phase2-pg-" + uuid.uuid4().hex
    password = secrets.token_urlsafe(32)
    # Do not copy application/provider secrets into the child environment.
    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "TEMP", "TMP") if key in os.environ}
    env["POSTGRES_PASSWORD"] = password
    engine = None
    try:
        docker("run", "--detach", "--rm", "--name", name,
               "--label", "codex.phase2.disposable=true", "--publish", "127.0.0.1::5432",
               "--env", "POSTGRES_PASSWORD", "--env", "POSTGRES_USER=phase2",
               "--env", "POSTGRES_DB=phase2", IMAGE, env=env)
        published = docker("port", name, "5432/tcp")
        if not published.startswith("127.0.0.1:") or "\n" in published:
            raise DisposableUnavailable("Disposable port was not localhost-only")
        from sqlalchemy import create_engine, URL, text
        engine = create_engine(URL.create("postgresql+psycopg2", username="phase2", password=password,
                                        host="127.0.0.1", port=int(published.split(":")[1]), database="phase2"),
                               connect_args={"connect_timeout": 1})
        deadline = time.monotonic() + 45
        while True:
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise DisposableUnavailable("Disposable PostgreSQL did not become ready") from None
                time.sleep(.25)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        # This exact UUID-named container is the only cleanup target. No volume
        # or database supplied by the caller can be removed by this harness.
        subprocess.run([*DOCKER_PREFIX, "rm", "--force", name], capture_output=True, timeout=30)
        remaining = docker("ps", "--all", "--filter", "name=^/" + name + "$", "--format", "{{.Names}}")
        if remaining:
            raise DisposableUnavailable("Disposable container cleanup could not be verified")
        print("Disposable cleanup: container removed; no volumes were created.")


def remote_test_mode():
    return os.environ.get("PHASE2_REMOTE_TEST_MODE") == "true"


def _remote_url():
    from sqlalchemy.engine import make_url
    if not remote_test_mode():
        raise DisposableUnavailable("Remote test mode requires explicit true opt-in")
    raw = os.environ.get("PHASE2_TEST_DATABASE_URL")
    if not raw:
        raise DisposableUnavailable("Remote mode requires PHASE2_TEST_DATABASE_URL; no fallback permitted")
    try:
        url = make_url(raw)
        # Forbid libpq host/service/options overrides and implicit PG* targets.
        if (url.drivername not in {"postgres", "postgresql", "postgresql+psycopg2"}
                or not all((url.host, url.database, url.username, url.password))
                or not re.fullmatch(r"[A-Za-z0-9.:-]+", url.host)
                or not re.fullmatch(r"[A-Za-z0-9_-]+", url.database)
                or (url.port is not None and not 1 <= url.port <= 65535)
                or set(url.query) - {"sslmode"}
                or (url.query and url.query["sslmode"] not in
                    {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"})):
            raise ValueError
        return url.set(drivername="postgresql+psycopg2", port=url.port or 5432)
    except Exception:
        raise DisposableUnavailable("Invalid explicit remote test URL (details suppressed)") from None


# Include legacy/current app table names, not only the minimum requested list.
APPLICATION_TABLES = frozenset({
    "organizations", "bots", "documents", "chunks", "conversations", "messages",
    "users", "subscriptions", "ingestion_jobs", "customers", "plans", "websites",
    "website_crawls", "conversation_sessions", "conversation_messages",
    "organization_members", "platform_api_keys", "refresh_sessions", "alembic_version",
})
MARKER = "phase2_run_owner"
FIXTURE_TABLES = frozenset({"documents", "chunks", "websites", "website_crawls"})
FIXTURE_INDEXES = frozenset({
    "ix_chunks_bot_id", "ix_chunks_document_id", "ix_chunks_organization_id",
    "ix_documents_org_status", "ix_documents_bot_status", "ix_chunks_bot_status",
    "ix_chunks_embedding_cosine", "ix_chunks_content_fts_en_v1",
})


def _relations(conn, schema):
    from sqlalchemy import text
    return {name: (oid, kind) for name, oid, kind in conn.execute(text(
        "SELECT c.relname, c.oid, c.relkind FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:schema"
    ), {"schema": schema})}


def _assert_owner(conn, state):
    from sqlalchemy import text
    identity = conn.execute(text(
        "SELECT oid, nspowner FROM pg_catalog.pg_namespace WHERE nspname=:schema"
    ), {"schema": state["schema"]}).one_or_none()
    if identity is None or tuple(identity) != state["identity"]:
        raise DisposableUnavailable("Remote schema ownership changed; cleanup refused")
    objects = _relations(conn, state["schema"])
    if objects.get(MARKER) != state["owned"].get(MARKER):
        raise DisposableUnavailable("Remote ownership marker changed; cleanup refused")
    rows = conn.exec_driver_sql(f'SELECT run_id FROM "{state["schema"]}".{MARKER}').all()
    if [tuple(row) for row in rows] != [(state["run_id"],)]:
        raise DisposableUnavailable("Remote run ID does not own this schema; cleanup refused")
    # Never adopt another object, or a replacement with the same name.
    if any(state["owned"].get(name) != value for name, value in objects.items()):
        raise DisposableUnavailable("Unowned remote object detected; cleanup refused")
    missing = [value[0] for name, value in state["owned"].items() if name not in objects]
    if missing and conn.execute(text("SELECT oid FROM pg_catalog.pg_class WHERE oid = ANY(:ids)"),
                                {"ids": missing}).first() is not None:
        raise DisposableUnavailable("Owned remote object moved outside run schema; cleanup refused")
    return objects


def _inspect_remote(conn):
    from sqlalchemy import text
    conn.exec_driver_sql("SET TRANSACTION READ ONLY")
    version = conn.exec_driver_sql("SHOW server_version_num").scalar_one()
    vector = conn.exec_driver_sql(
        "SELECT e.extversion, n.nspname FROM pg_catalog.pg_extension e "
        "JOIN pg_catalog.pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector'"
    ).one_or_none()
    if vector is None:
        raise DisposableUnavailable("Remote pgvector extension must already exist; nothing installed")
    # Output only numeric versions; namespace enters startup options, so constrain it.
    if (not re.fullmatch(r"\d{5,6}", str(version))
            or not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", vector[0])
            or not re.fullmatch(r"[a-z_][a-z0-9_]*", vector[1])
            or vector[1].startswith("pg_")):
        raise DisposableUnavailable("Unsupported remote server/extension metadata")
    existing = conn.execute(text(
        "SELECT c.relname FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n "
        "ON n.oid=c.relnamespace WHERE n.nspname <> 'information_schema' "
        "AND n.nspname NOT LIKE 'pg\\_%' ESCAPE '\\'"
    )).scalars().all()
    # Check all non-system schemas, including abandoned runs, views and foreign tables.
    if APPLICATION_TABLES.intersection(existing) or migration_module().INDEX_NAME in existing:
        raise DisposableUnavailable("Existing application objects detected; remote database refused")
    if conn.execute(text(
        "SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname LIKE :pattern LIMIT 1"
    ), {"pattern": "phase2_test_%"}).first() is not None:
        raise DisposableUnavailable("Existing disposable schema detected; no previous run may be adopted")
    conn.rollback()
    print(f"Disposable remote PostgreSQL server_version_num={version}; pgvector={vector[0]}")
    return vector[1]


def _record_ddl(conn, cursor, statement, parameters, context, executemany):
    """Remember only relations attributable to a completed fixture CREATE statement."""
    state = conn.engine._phase2_remote_run
    match = re.match(r"CREATE (TABLE|INDEX(?: CONCURRENTLY)?) ([a-z_][a-z0-9_]*)\b", statement)
    if not match:
        return
    name = match[2]
    permitted = {name, name + "_pkey"} if match[1] == "TABLE" else {name}
    objects = _relations(conn, state["schema"])
    for key in permitted & objects.keys():
        state["owned"][key] = objects[key]


def _guard_ddl(conn, cursor, statement, parameters, context, executemany):
    state = conn.engine._phase2_remote_run
    if statement.startswith("CREATE"):
        table = re.match(r"CREATE TABLE ([a-z_][a-z0-9_]*)\s*\(", statement)
        index = re.match(r"CREATE INDEX(?: CONCURRENTLY)? ([a-z_][a-z0-9_]*) ON ([a-z_][a-z0-9_]*)\s", statement)
        if not ((table and table[1] in FIXTURE_TABLES)
                or (index and index[1] in FIXTURE_INDEXES and index[2] in FIXTURE_TABLES)):
            raise DisposableUnavailable("Only the declared disposable fixture DDL is permitted")
        objects = _assert_owner(conn, state)
        if conn.exec_driver_sql("SELECT current_schema()").scalar() != state["schema"]:
            raise DisposableUnavailable("Remote fixture schema is not the current schema")
        if index and index[2] not in objects:
            raise DisposableUnavailable("Remote index target is not owned by this run")
    # DROP INDEX IF EXISTS must never fall through to an extension/public schema.
    if statement.startswith("DROP INDEX"):
        from sqlalchemy import text
        if statement != migration_module().DROP_SQL:
            raise DisposableUnavailable("Only the declared disposable index downgrade is permitted")
        objects = _assert_owner(conn, state)
        name = migration_module().INDEX_NAME
        resolved = conn.execute(text("SELECT to_regclass(:name)::oid"), {"name": name}).scalar()
        if objects.get(name, (None,))[0] != resolved:
            raise DisposableUnavailable("Remote migration index is not owned by this run")
    elif statement.startswith("DROP"):
        raise DisposableUnavailable("Remote object deletion is owned by harness cleanup only")


def _cleanup_remote(engine, state):
    with engine.begin() as conn:
        objects = _assert_owner(conn, state)
        # RESTRICT is deliberate: foreign dependencies/objects make the entire
        # transaction roll back. Never use CASCADE or drop a supplied database.
        for name in ("chunks", "documents", "website_crawls", "websites", MARKER):
            if name in objects:
                conn.exec_driver_sql(f'DROP TABLE "{state["schema"]}"."{name}" RESTRICT')
        conn.exec_driver_sql(f'DROP SCHEMA "{state["schema"]}" RESTRICT')
    from sqlalchemy import text
    with engine.connect() as conn:
        if conn.execute(text("SELECT oid FROM pg_catalog.pg_namespace WHERE nspname=:schema"),
                        {"schema": state["schema"]}).first() is not None:
            raise DisposableUnavailable("Remote schema cleanup could not be verified")
        if _relations(conn, state["schema"]):
            raise DisposableUnavailable("Remote object cleanup could not be verified")
    print("Disposable remote cleanup verified: only this run's schema/objects removed.")


def _remote_engine(url, run_id, options):
    import logging
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool
    engine = create_engine(url, poolclass=NullPool, echo=False, hide_parameters=True,
                           logging_name=run_id, pool_logging_name=run_id,
                           connect_args={"connect_timeout": 5, "options": options})
    # Engine/pool loggers can otherwise print raw DBAPI errors at ambient log
    # levels. These UUID-specific loggers belong solely to this disposable run.
    for name in (f"sqlalchemy.engine.Engine.{run_id}", f"sqlalchemy.pool.impl.NullPool.{run_id}"):
        logging.getLogger(name).disabled = True
    return engine


@contextmanager
def remote_postgres():
    from sqlalchemy import event, text
    url = _remote_url()  # No Docker/application fallback, even on parse/connect failure.
    run_id = uuid.uuid4().hex
    state = dict(run_id=run_id, schema="phase2_test_" + run_id, owned={})
    control = engine = None
    created = False
    try:
        control = _remote_engine(url, run_id + "_control", "-c search_path=pg_catalog")
        with control.connect() as conn:
            extension_schema = _inspect_remote(conn)
            # All harnesses serialize on this same DB-local session lock. A stale
            # owned schema is refused by the preflight, not adopted or cleaned.
            locked = conn.exec_driver_sql("SELECT pg_try_advisory_lock(16021602)").scalar()
            if not locked:
                raise DisposableUnavailable("Another disposable remote run is active")
            conn.rollback()
            try:
                # Recheck under the lock before any fixture/ownership DDL.
                _inspect_remote(conn)
                with conn.begin():
                    conn.exec_driver_sql(f'CREATE SCHEMA "{state["schema"]}"')
                    conn.exec_driver_sql(f'REVOKE ALL ON SCHEMA "{state["schema"]}" FROM PUBLIC')
                    conn.exec_driver_sql(f'CREATE TABLE "{state["schema"]}".{MARKER} (run_id text NOT NULL)')
                    conn.execute(text(f'INSERT INTO "{state["schema"]}".{MARKER} VALUES (:run_id)'), {"run_id": run_id})
                    state["identity"] = tuple(conn.execute(text(
                        "SELECT oid, nspowner FROM pg_catalog.pg_namespace WHERE nspname=:schema"
                    ), {"schema": state["schema"]}).one())
                    state["owned"] = _relations(conn, state["schema"])
                created = True
                engine = _remote_engine(url, run_id,
                                        f'-c search_path={state["schema"]},pg_catalog,{extension_schema}')
                engine._phase2_remote_run = state
                event.listen(engine, "after_cursor_execute", _record_ddl)
                event.listen(engine, "before_cursor_execute", _guard_ddl)
                yield engine
            finally:
                # Closing NullPool's control connection releases the advisory lock
                # even if the server disconnects or ownership cleanup is refused.
                if engine is not None:
                    engine.dispose()
                if created:
                    _cleanup_remote(control, state)
    except DisposableUnavailable:
        raise
    except Exception:
        raise DisposableUnavailable("Remote disposable operation failed (details suppressed)") from None
    finally:
        if control is not None:
            control.dispose()


@contextmanager
def application_import_boundary(engine):
    """Remote scripts never import the application's dotenv/DB configuration.

    ORM metadata is still the real model module. Its default session is a tripwire;
    PostgreSQL fixtures receive the explicit engine, and offline tests own SQLite.
    """
    if not remote_test_mode():
        yield
        return
    import sys
    from types import ModuleType, SimpleNamespace
    from unittest.mock import patch
    from sqlalchemy.orm import declarative_base
    if "database.connection" in sys.modules or "database.models" in sys.modules:
        raise DisposableUnavailable("Remote runner requires fresh application imports")
    def forbidden(*args, **kwargs):
        raise AssertionError("Application database access forbidden in disposable remote tests")
    stub = ModuleType("database.connection")
    stub.Base = declarative_base()
    stub.BACKEND_DIR = Path(__file__).resolve().parents[1]
    stub.engine = SimpleNamespace(connect=forbidden)
    stub.SessionLocal = stub.get_db = forbidden
    with patch.dict(sys.modules, {"database.connection": stub}), patch("dotenv.load_dotenv", return_value=False):
        yield


def acceptance_test_result():
    """Unittest normally prints raw DBAPI errors, including possible credentials."""
    import unittest
    if not remote_test_mode():
        return unittest.TextTestResult
    class RemoteResult(unittest.TextTestResult):
        def _exc_info_to_string(self, err, test):
            return "Remote acceptance assertion/error; details suppressed to protect connection secrets."
    return RemoteResult


def migration_module():
    path = Path(__file__).resolve().parents[1] / "migrations/versions/20260910_01_postgres_fts.py"
    spec = importlib.util.spec_from_file_location("phase2_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def migrate(engine, direction="upgrade"):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        with context.begin_transaction(), Operations.context(context):
            getattr(migration_module(), direction)()


def create_schema(engine):
    """Minimal faithful recall schema; actual revision SQL is applied verbatim.

    Avoid running unrelated billing/credential/lifecycle migrations. This proves
    Phase 2 SQL, not full baseline bootstrapping. Column names/types and READY
    crawl/profile relationships are those used by production recall builders.
    """
    statements = [
        "CREATE EXTENSION vector",
        "CREATE TABLE documents (id integer PRIMARY KEY, bot_id integer NOT NULL, organization_id integer, "
        "filename text NOT NULL, title text, source_type text NOT NULL DEFAULT 'txt', "
        "status text NOT NULL DEFAULT 'ready', processing_status text NOT NULL DEFAULT 'completed', "
        "website_id integer, crawl_id integer, version integer NOT NULL DEFAULT 1)",
        "CREATE TABLE websites (id integer PRIMARY KEY, bot_id integer, organization_id integer, status text, active_crawl_id integer)",
        "CREATE TABLE website_crawls (id integer PRIMARY KEY, website_id integer, bot_id integer, organization_id integer, status text, version integer)",
        "CREATE TABLE chunks (id integer PRIMARY KEY, document_id integer REFERENCES documents(id), bot_id integer, "
        "organization_id integer, website_id integer, crawl_id integer, chunk_index integer NOT NULL DEFAULT 0, "
        "status text NOT NULL DEFAULT 'ready', content text NOT NULL, embedding vector(768) NOT NULL, "
        "embedding_provider text NOT NULL DEFAULT 'fixture', embedding_model text NOT NULL DEFAULT 'fixture', "
        "embedding_version integer NOT NULL DEFAULT 1)",
        "CREATE INDEX ix_chunks_bot_id ON chunks (bot_id)",
        "CREATE INDEX ix_chunks_document_id ON chunks (document_id)",
        "CREATE INDEX ix_chunks_organization_id ON chunks (organization_id)",
        "CREATE INDEX ix_documents_org_status ON documents (organization_id, processing_status)",
        "CREATE INDEX ix_documents_bot_status ON documents (bot_id, processing_status)",
        "CREATE INDEX ix_chunks_bot_status ON chunks (bot_id, status)",
    ]
    with engine.begin() as conn:
        remote = getattr(engine, "_phase2_remote_run", None)
        if remote is not None:
            _assert_owner(conn, remote)
        for statement in statements[1:] if remote is not None else statements:
            conn.exec_driver_sql(statement)


def deterministic_vector(axis=0):
    return "[" + ",".join("1" if i == axis else "0" for i in range(768)) + "]"


def seed_acceptance(engine):
    from sqlalchemy import text
    with engine.begin() as conn:
        for did in range(1, 13):
            org, bot = (2, 1) if did == 3 else (1, 2) if did == 4 else (1, 1)
            conn.execute(text("INSERT INTO documents (id,bot_id,organization_id,filename,title) VALUES (:id,:bot,:org,'brochure.txt','Common Brochure')"),
                         dict(id=did, bot=bot, org=org))
            body = ("Silver Package pricing target. Prices for $33. COA EPA SKU-123. A 60-day guarantee. "
                    "Results vary. Needles and needle. Phone support." if did == 1 else "needle " * 80)
            conn.execute(text("INSERT INTO chunks (id,document_id,bot_id,organization_id,content,embedding) VALUES (:id,:id,:bot,:org,:body,CAST(:vec AS vector))"),
                         dict(id=did, bot=bot, org=org, body=body, vec=deterministic_vector()))
        for index in range(150):
            conn.execute(text("INSERT INTO chunks (id,document_id,bot_id,organization_id,content,embedding) VALUES (:id,1,1,1,:body,CAST(:vec AS vector))"),
                         dict(id=100+index, body="pricing " + "irrelevant "*40 + f"target marker{index}", vec=deterministic_vector(1)))
        conn.execute(text("INSERT INTO chunks (id,document_id,bot_id,organization_id,content,embedding) VALUES (500,1,1,1,:body,CAST(:vec AS vector))"),
                     dict(body="pricing target "*20, vec=deterministic_vector(1)))
        for stmt in ["UPDATE documents SET status='processing' WHERE id=5",
                     "UPDATE documents SET status='deleted' WHERE id=6",
                     "UPDATE documents SET status='error' WHERE id=10",
                     "UPDATE chunks SET status='processing' WHERE id=11",
                     "UPDATE chunks SET embedding_model='incompatible' WHERE id=12",
                     "INSERT INTO websites VALUES (1,1,1,'ready',7)",
                     "INSERT INTO website_crawls VALUES (7,1,1,1,'ready',1),(8,1,1,1,'ready',1)",
                     "UPDATE documents SET source_type='website',website_id=1,crawl_id=CASE WHEN id=8 THEN 8 ELSE 7 END WHERE id IN (7,8,9)",
                     "UPDATE chunks SET website_id=1,crawl_id=CASE WHEN id=8 THEN 8 ELSE 7 END WHERE id IN (7,8,9)",
                     "UPDATE documents SET version=2 WHERE id=9"]:
            conn.exec_driver_sql(stmt)
