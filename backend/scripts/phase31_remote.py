"""Explicit disposable Phase 3.1 target/ownership boundary. No application URL fallback.

The URL is never formatted into messages. Existing extension objects are retained.
Extensions newly installed in our owned schema (vector fixture prerequisite and
pg_trgm by the ACTUAL migration) may be removed only after OID/namespace checks.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import re
import uuid

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from scripts.phase2_disposable_postgres import DisposableUnavailable

PREFIX = "phase3_acceptance_"
MARKER = "phase3_run_owner"
LOCK = 16031603


def configured_urls():
    # Reading settings for comparison does not populate the process environment.
    from dotenv import dotenv_values
    root = Path(__file__).resolve().parents[2]
    settings = {}
    for path in (root / ".env", root / "backend/.env", root / "backend/.env.local"):
        if path.is_file():
            settings.update(dotenv_values(path, interpolate=False))
    settings.update(os.environ)
    return [v for k, v in settings.items() if v and k not in {"PHASE3_TEST_DATABASE_URL"}
            and ("DATABASE_URL" in k or "POSTGRES_URL" in k or k in {"SQLALCHEMY_DATABASE_URI", "DB_URL"})]


def endpoint(url):
    return ((url.host or "").casefold().rstrip("."), url.port or 5432, url.database)


def authorized_url(configured=None):
    if os.environ.get("PHASE3_ALLOW_REMOTE_DISPOSABLE") != "1":
        raise DisposableUnavailable("Phase 3.1 explicit remote opt-in required")
    raw = os.environ.get("PHASE3_TEST_DATABASE_URL")
    if not raw:
        raise DisposableUnavailable("Phase 3.1 explicit disposable URL required")
    try:
        url = make_url(raw)
        if (url.drivername not in {"postgres", "postgresql", "postgresql+psycopg2"}
                or not url.host or not url.database or not url.username or not url.password
                or not url.port or not 1 <= url.port <= 65535
                or set(url.query) - {"sslmode"}
                or (url.query and url.query["sslmode"] not in {"require", "verify-ca", "verify-full", "prefer"})):
            raise ValueError()
    except Exception:
        raise DisposableUnavailable("Phase 3.1 disposable URL structure refused") from None
    for other in configured_urls() if configured is None else configured:
        try:
            candidate = make_url(other)
        except Exception:
            continue
        if endpoint(candidate) == endpoint(url):
            raise DisposableUnavailable("Phase 3.1 configured application target refused")
    return url.set(drivername="postgresql+psycopg2")


def user_objects(conn, *, outside=None):
    return conn.execute(text("""SELECT n.nspname,c.relname,c.oid,c.relkind
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname NOT LIKE :system AND n.nspname <> 'information_schema'
        AND (:outside IS NULL OR n.nspname <> :outside) ORDER BY n.nspname,c.relname"""),
        {"system": "pg_%", "outside": outside}).all()


def preflight(conn):
    facts = dict(conn.execute(text("""SELECT current_setting('server_version') AS server_version,
        current_setting('server_version_num') AS server_version_num,
        current_database() IS NOT NULL AS disposable_database_connected,
        current_user IS NOT NULL AS authenticated_role""")).mappings().one())
    unexpected = conn.execute(text("""SELECT c.relname FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname NOT LIKE :system AND n.nspname <> 'information_schema'
        AND c.relkind IN ('r','p','v','m','f','S')
        AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_depend d
        WHERE d.classid='pg_catalog.pg_class'::regclass AND d.objid=c.oid AND d.deptype='e')"""),
        {"system": "pg_%"}).all()
    if unexpected:
        raise DisposableUnavailable("Phase 3.1 empty-database guard refused existing user objects")
    if conn.execute(text("SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname LIKE :a OR nspname LIKE :b LIMIT 1"),
                    {"a": PREFIX + "%", "b": "phase3_test_%"}).first():
        raise DisposableUnavailable("Phase 3.1 stale owned-schema guard refused target")
    extensions = conn.execute(text("""SELECT e.extname,e.extversion,n.nspname,e.oid
        FROM pg_catalog.pg_extension e JOIN pg_catalog.pg_namespace n ON n.oid=e.extnamespace
        WHERE e.extname IN ('vector','pg_trgm')""")).all()
    packages = dict(conn.execute(text("SELECT name,default_version FROM pg_available_extensions WHERE name IN ('vector','pg_trgm')")).all())
    if set(packages) != {"vector", "pg_trgm"}:
        raise DisposableUnavailable("Phase 3.1 required extension package unavailable; no software installation permitted")
    if any(not re.fullmatch(r"[a-z_][a-z0-9_]*", row[2]) for row in extensions):
        raise DisposableUnavailable("Phase 3.1 extension namespace guard refused target")
    facts.update(application_target_guard=True, empty_database_guard=True,
                 extensions={r[0]: r[1] for r in extensions}, available_extensions=packages)
    return facts, extensions


def register(conn):
    from scripts.test_phase3_postgres import record_fixture_tables
    record_fixture_tables(conn)
    state = conn.info["phase3_owned"]
    state["functions"] = conn.execute(text("SELECT p.oid FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=:s"),
                                      {"s": state["schema"]}).scalars().all()
    state["extensions"] = conn.execute(text("SELECT oid,extname FROM pg_extension WHERE extnamespace=:oid"),
                                       {"oid": state["owner"][0]}).all()


@contextmanager
def disposable_database():
    url = authorized_url()
    engine = create_engine(url, pool_size=22, max_overflow=0, pool_timeout=15,
                           connect_args={"connect_timeout": 8}, echo=False, hide_parameters=True)
    url = None
    try:
        with engine.connect() as conn:
            if not conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK}).scalar():
                raise DisposableUnavailable("Phase 3.1 advisory lock refused overlapping run")
            facts, extensions = preflight(conn)
            outside = user_objects(conn)
            schema, run = PREFIX + uuid.uuid4().hex, uuid.uuid4().hex
            assert re.fullmatch(r"phase3_acceptance_[a-f0-9]{32}", schema)
            search = ', '.join('"' + n + '"' for n in dict.fromkeys([schema] + [e[2] for e in extensions]))
            conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            conn.exec_driver_sql(f'REVOKE ALL ON SCHEMA "{schema}" FROM PUBLIC')
            conn.exec_driver_sql(f'SET search_path TO {search}')
            conn.exec_driver_sql(f'CREATE TABLE "{schema}".{MARKER} (run_id text NOT NULL)')
            conn.execute(text(f'INSERT INTO "{schema}".{MARKER} VALUES (:run)'), {"run": run})
            owner = conn.execute(text("SELECT oid,nspowner FROM pg_namespace WHERE nspname=:s"), {"s": schema}).one()
            marker = conn.execute(text("SELECT CAST(:name AS regclass)::oid"), {"name": schema + "." + MARKER}).scalar()
            if not any(e[0] == "vector" for e in extensions):
                # Package availability was proven read-only. Enabling it only in
                # this new owned schema is a fixture prerequisite, not an install
                # or modification of public/production schemas.
                conn.exec_driver_sql(f'CREATE EXTENSION vector WITH SCHEMA "{schema}"')
            functions = conn.execute(text("SELECT p.oid FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=:s"), {"s": schema}).scalars().all()
            created_extensions = conn.execute(text("SELECT oid,extname FROM pg_extension WHERE extnamespace=:oid ORDER BY oid"), {"oid": owner[0]}).all()
            state = {"schema": schema, "owner": owner, "tables": {MARKER: marker}, "functions": functions, "extensions": created_extensions}
            conn.info["phase3_owned"] = state
            conn.commit()
            @event.listens_for(engine, "connect")
            def set_owned_path(dbapi, _):
                with dbapi.cursor() as cursor:
                    cursor.execute(f'SET search_path TO {search}')
                dbapi.commit()
            try:
                yield engine, conn, facts
            finally:
                conn.rollback()
                current = conn.execute(text("SELECT oid,nspowner FROM pg_namespace WHERE nspname=:s"), {"s": schema}).one_or_none()
                rows = conn.execute(text("SELECT c.relname,c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:s AND c.relkind IN ('r','p')"), {"s": schema}).all()
                functions = conn.execute(text("SELECT p.oid FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=:s"), {"s": schema}).scalars().all()
                if current != owner or dict(rows) != state["tables"] or set(functions) != set(state["functions"]):
                    raise DisposableUnavailable("Phase 3.1 cleanup ownership changed; deletion refused")
                if conn.execute(text(f'SELECT run_id FROM "{schema}".{MARKER}')).scalars().all() != [run]:
                    raise DisposableUnavailable("Phase 3.1 cleanup marker changed; deletion refused")
                if user_objects(conn, outside=schema) != outside:
                    raise DisposableUnavailable("Phase 3.1 external objects changed; cleanup refused")
                names = ', '.join(f'"{schema}"."{name}"' for name, _ in rows)
                conn.exec_driver_sql("DROP TABLE " + names + " RESTRICT")
                conn.exec_driver_sql(f'DROP FUNCTION IF EXISTS "{schema}".resource_catalog_revision_v1() RESTRICT')
                ext = conn.execute(text("SELECT oid,extname FROM pg_extension WHERE extnamespace=:oid"), {"oid": owner[0]}).all()
                if set(ext) != set(state["extensions"]) or any(name not in {"pg_trgm","vector"} for _, name in ext):
                    raise DisposableUnavailable("Phase 3.1 extension ownership changed; cleanup refused")
                for _, name in ext:
                    # Only NEW, captured extensions in THIS run's schema. Existing
                    # extensions elsewhere are never removed; dependencies refuse.
                    conn.exec_driver_sql(f'DROP EXTENSION "{name}" RESTRICT')
                conn.exec_driver_sql(f'DROP SCHEMA "{schema}" RESTRICT')
                conn.commit()
                if conn.execute(text("SELECT 1 FROM pg_namespace WHERE nspname=:s"), {"s": schema}).first() or user_objects(conn) != outside:
                    raise DisposableUnavailable("Phase 3.1 cleanup verification failed")
                facts["cleanup"] = {"schema_absent": True, "marker_tables_indexes_absent": True,
                                    "unrelated_objects_unchanged": True, "existing_extensions_retained": True}
                print("PHASE31 CLEANUP VERIFIED: owned schema/marker/fixtures absent; unrelated objects unchanged", flush=True)
                conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK})
                conn.info.pop("phase3_owned", None)
    finally:
        engine.dispose()
