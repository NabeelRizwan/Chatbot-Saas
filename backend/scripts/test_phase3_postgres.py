"""Phase 3 acceptance ONLY in an empty, disposable LOCAL PostgreSQL database.

An explicit PHASE3_TEST_DATABASE_URL must name a loopback phase3_test_* database.
Without it, only the existing local Docker ownership helper is permitted. No
Railway/remote fallback, dotenv, application URL, embedding or model calls.
Exit 2 = blocked. Never print a connection exception or environment value.
"""
from contextlib import contextmanager, ExitStack
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.phase2_disposable_postgres import docker_postgres, DisposableUnavailable

PREFIX = "phase3_test_"
MARKER = "phase3_run_owner"


def explicit_local_url():
    from sqlalchemy.engine import make_url
    raw = os.environ.get("PHASE3_TEST_DATABASE_URL")
    if not raw:
        return None
    try:
        url = make_url(raw)
        if (url.drivername not in {"postgres", "postgresql", "postgresql+psycopg2"}
                or url.host not in {"127.0.0.1", "localhost", "::1"}
                or not re.fullmatch(r"phase3_test_[a-z0-9_]{1,48}", url.database or "")
                or not url.username or not url.password or not url.port or not 1 <= url.port <= 65535
                or set(url.query) - {"sslmode"}
                or (url.query and url.query["sslmode"] not in {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"})):
            raise ValueError()
        return url.set(drivername="postgresql+psycopg2")
    except Exception:
        raise DisposableUnavailable("Explicit Phase 3 target failed local disposable URL guard") from None


@contextmanager
def local_database():
    from sqlalchemy import create_engine
    url = explicit_local_url()
    if url is None:
        # Call the Docker-only helper directly: Phase2 remote variables are
        # neither read nor remapped, and cannot select another database.
        with docker_postgres() as engine:
            yield engine
    else:
        engine = create_engine(url, connect_args={"connect_timeout": 8}, echo=False, hide_parameters=True)
        try:
            yield engine
        finally:
            engine.dispose()


@contextmanager
def isolated_application_imports():
    from sqlalchemy.orm import declarative_base
    if "database.connection" in sys.modules or "database.models" in sys.modules:
        raise DisposableUnavailable("Phase 3 PostgreSQL runner requires fresh application imports")
    def forbidden(*args, **kwargs):
        raise AssertionError("Application/provider access forbidden")
    stub = ModuleType("database.connection")
    stub.Base = declarative_base()
    stub.BACKEND_DIR = Path(__file__).resolve().parents[1]
    stub.engine = SimpleNamespace(connect=forbidden)
    stub.SessionLocal = stub.get_db = forbidden
    with ExitStack() as stack:
        stack.enter_context(patch.dict(sys.modules, {"database.connection": stub}))
        stack.enter_context(patch("dotenv.load_dotenv", return_value=False))
        stack.enter_context(patch("httpx.Client.send", side_effect=forbidden))
        stack.enter_context(patch("httpx.AsyncClient.send", side_effect=forbidden))
        stack.enter_context(patch("requests.sessions.Session.request", side_effect=forbidden))
        yield


def migration_module():
    path = Path(__file__).resolve().parents[1] / "migrations/versions/20260912_01_resource_catalog.py"
    spec = importlib.util.spec_from_file_location("phase3_catalog_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def migrate(connection, direction):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with Operations.context(MigrationContext.configure(connection)):
        getattr(migration_module(), direction)()


@contextmanager
def owned_schema(engine):
    from sqlalchemy import text
    run = uuid.uuid4().hex
    schema = PREFIX + run
    assert re.fullmatch(r"phase3_test_[a-f0-9]{32}", schema)
    with engine.connect() as connection:
        if not connection.execute(text("SELECT pg_try_advisory_lock(16031603)")).scalar():
            raise DisposableUnavailable("Phase 3 disposable database is already in use")
        # Empty-database preflight is stronger than a list of known app tables.
        user_tables = connection.execute(text("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE c.relkind IN ('r','p') AND n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'" )).all()
        if user_tables:
            raise DisposableUnavailable("Phase 3 empty-database guard refused existing user tables")
        if connection.execute(text("SELECT 1 FROM pg_namespace WHERE nspname LIKE :pattern LIMIT 1"), {"pattern": PREFIX + "%"}).first():
            raise DisposableUnavailable("Phase 3 stale-schema guard refused target")
        # Extensions are local disposable prerequisites, never customer changes.
        connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
        connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public")
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        connection.exec_driver_sql(f'REVOKE ALL ON SCHEMA "{schema}" FROM PUBLIC')
        connection.exec_driver_sql(f'SET search_path TO "{schema}", public')
        connection.exec_driver_sql(f'CREATE TABLE "{schema}".{MARKER} (run_id text NOT NULL)')
        connection.execute(text(f'INSERT INTO "{schema}".{MARKER} (run_id) VALUES (:run)'), {"run": run})
        owner = connection.execute(text("SELECT oid,nspowner FROM pg_namespace WHERE nspname=:schema"), {"schema": schema}).one()
        marker_oid = connection.execute(text("SELECT CAST(:name AS regclass)::oid"), {"name": schema + "." + MARKER}).scalar()
        connection.info["phase3_owned"] = {"schema": schema, "tables": {MARKER: marker_oid}}
        connection.commit()
        try:
            yield connection
        finally:
            connection.rollback()
            current = connection.execute(text("SELECT oid,nspowner FROM pg_namespace WHERE nspname=:schema"), {"schema": schema}).one_or_none()
            if current != owner:
                raise DisposableUnavailable("Phase 3 schema ownership changed; cleanup refused")
            rows = connection.execute(text("SELECT c.relname,c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:schema AND c.relkind IN ('r','p')"), {"schema": schema}).all()
            if dict(rows) != connection.info["phase3_owned"]["tables"] or dict(rows).get(MARKER) != marker_oid:
                raise DisposableUnavailable("Phase 3 unowned relation/marker; cleanup refused")
            if connection.execute(text(f'SELECT run_id FROM "{schema}".{MARKER}')).scalars().all() != [run]:
                raise DisposableUnavailable("Phase 3 marker contents changed; cleanup refused")
            # Multi-table RESTRICT removes only the named fixture tables, allowing
            # dependencies between those tables but refusing outside dependents.
            names = ", ".join(f'"{schema}"."{name}"' for name, _ in rows)
            connection.exec_driver_sql("DROP TABLE " + names + " RESTRICT")
            connection.exec_driver_sql(f'DROP FUNCTION IF EXISTS "{schema}".resource_catalog_revision_v1() RESTRICT')
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" RESTRICT')
            connection.commit()
            if connection.execute(text("SELECT 1 FROM pg_namespace WHERE nspname=:schema"), {"schema": schema}).first():
                raise DisposableUnavailable("Phase 3 cleanup verification failed")
            print("PHASE3 CLEANUP: owned schema, marker, tables and indexes absent; extensions retained")
            connection.execute(text("SELECT pg_advisory_unlock(16031603)"))
            connection.info.pop("phase3_owned", None)


def record_fixture_tables(connection):
    """Called after each owned DDL transaction, before committing it."""
    from sqlalchemy import text
    from database.connection import Base
    state = connection.info["phase3_owned"]
    rows = connection.execute(text("SELECT c.relname,c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname=:schema AND c.relkind IN ('r','p')"), {"schema": state["schema"]}).all()
    allowed = set(Base.metadata.tables) | {MARKER}
    if any(name not in allowed for name, _ in rows) or dict(rows).get(MARKER) != state["tables"][MARKER]:
        raise DisposableUnavailable("Phase 3 fixture ownership registration refused")
    state["tables"] = dict(rows)


def run_acceptance(conn):
    from sqlalchemy import MetaData, text
    from sqlalchemy.orm import Session
    from database.connection import Base
    from database import models
    from database.resource_schema_v1 import TABLE_NAMES
    from services.resource_discovery import ResourceDiscoveryService, ResolutionState
    from services.resource_channels import SQLResourceChannel, ResourceProbe
    from services.retrieval_contracts import HardKnowledgeScope
    from services.resource_catalog import ResourceCatalogProjector
    from test_resource_discovery_benchmark import populate, evaluate
    from test_resource_discovery import ResourceFixture
    from types import MethodType
    # Faithful original tables without the NEW migration's composite targets.
    old = MetaData()
    for table in Base.metadata.tables.values():
        if table.name not in TABLE_NAMES:
            clone = table.to_metadata(old)
            for constraint in tuple(clone.constraints):
                if constraint.name in {"uq_bots_resource_tenant", "uq_documents_resource_tenant"}:
                    clone.constraints.remove(constraint)
    old.create_all(conn)
    record_fixture_tables(conn)
    conn.commit()
    migrate(conn, "upgrade")
    record_fixture_tables(conn)
    conn.commit()
    checks = []
    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)
        print("PASS: " + name)
    check("migration_upgrade", all(conn.dialect.has_table(conn, name) for name in TABLE_NAMES))
    facts = {"server_version": conn.execute(text("SELECT current_setting('server_version')")).scalar(),
             "pg_trgm": conn.execute(text("SELECT extversion FROM pg_extension WHERE extname='pg_trgm'")).scalar(),
             "pgvector": conn.execute(text("SELECT extversion FROM pg_extension WHERE extname='vector'")).scalar()}
    check("pg_trgm_extension", bool(facts["pg_trgm"]))
    indexes = conn.execute(text("SELECT c.relname,i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema()" )).all()
    for name in ("ix_resource_terms_exact_v1", "ix_resource_terms_fts_simple_v1", "ix_resource_terms_trgm_v1", "ix_resource_docs_anchor_v1"):
        check(name, dict(indexes).get(name) is True)
    check("simple_configuration_not_english_stemming", conn.execute(text(
        "SELECT NOT (to_tsvector('simple', 'running') @@ plainto_tsquery('simple', 'run')) "
        "AND (to_tsvector('english', 'running') @@ plainto_tsquery('english', 'run'))")).scalar() is True)
    facts["trigram_direction"] = dict(conn.execute(text(
        "SELECT similarity('silver package', 'the silver package extended') AS whole, "
        "word_similarity('silver package', 'the silver package extended') AS extent, "
        "strict_word_similarity('silver package', 'the silver package extended') AS word_extent, "
        "('the silver package extended' %>> 'silver package') AS indexed_extent")).mappings().one())
    check("strict_trigram_operator_direction", facts["trigram_direction"]["indexed_extent"] is True)
    with Session(bind=conn) as db:
        from services.retrieval_contracts import ProfileIdentity
        fixture = SimpleNamespace(db=db, hard=HardKnowledgeScope(1, 1, embedding_profile=ProfileIdentity(
            "gemini", "gemini-embedding-001", 1, 768)), service=ResourceDiscoveryService())
        fixture.add = MethodType(ResourceFixture.add, fixture)
        fixture.project = MethodType(ResourceFixture.project, fixture)
        fixture.contract = MethodType(ResourceFixture.contract, fixture)
        db.add_all([models.Customer(id=1, name="Synthetic", api_key="fixture"), models.Organization(id=1, name="Fixture", slug="fixture")])
        db.flush()
        db.add(models.Bot(id=1, organization_id=1, customer_id=1, name="Fixture"))
        db.commit()
        fixture.bot = db.get(models.Bot, 1)
        populate(fixture)
        benchmarks = [evaluate(fixture, split) for split in ("development", "heldout")]
        check("real_generic_benchmark", all(all(b['gates'].values()) for b in benchmarks))
        def discover(q, hard=None):
            return fixture.service.discover(db, hard or fixture.hard, [ResourceProbe(q)])
        check("exact_canonical", discover("Cedar Meridian product").resolutions[0].state == ResolutionState.RESOLVED)
        check("exact_alias", discover("Cedar Meridian Desk").resolutions[0].state == ResolutionState.RESOLVED)
        check("alias_collision", discover("Pro").resolutions[0].state == ResolutionState.AMBIGUOUS)
        check("partial_reordered", bool(discover("Meridian Cedar").candidates))
        check("trigram_typo", bool(SQLResourceChannel("trigram").search(db, fixture.hard, ResourceProbe("Cedar Meridan product"), 32).signals))
        check("short_fuzzy_protection", not SQLResourceChannel("trigram").search(db, fixture.hard, ResourceProbe("AI"), 32).signals)
        check("unicode", discover("Café Cedar 東京").resolutions[0].state == ResolutionState.RESOLVED)
        check("hard_document_empty", not discover("Cedar Meridian product", HardKnowledgeScope(1, 1, ())).candidates)
        check("foreign_org", not discover("Cedar Meridian product", HardKnowledgeScope(2, 1)).candidates)
        check("foreign_bot", not discover("Cedar Meridian product", HardKnowledgeScope(1, 2)).candidates)
        # Better exact aliases in foreign scopes still cannot enter any channel.
        fixture.add(1000, "Cedar Meridian product", bot=2)
        fixture.add(1001, "Cedar Meridian product", org=2, bot=3)
        for hard, ids in ((HardKnowledgeScope(1, 2), [1000]), (HardKnowledgeScope(2, 3), [1001])):
            ResourceCatalogProjector().project(db, hard, ids)
        db.commit()
        check("stronger_foreign_candidates_excluded", all(c.resource.document_ids == (10,) for c in
            discover("Cedar Meridian product").resolutions[0].alternatives if c.canonical_exact))
        doc = db.get(models.Document, 10)
        for value in ("processing", "failed", "deleted"):
            doc.status = value
            db.flush()
            check("lifecycle_" + value, not discover("Cedar Meridian product").resolutions[0].candidate)
        doc.status = "ready"
        db.commit()
        from dataclasses import replace
        from services.resource_catalog import catalog_revision
        revision = catalog_revision(db, fixture.hard)
        doc.metadata_json = {**doc.metadata_json, "aliases": ["New Meridian Alias"]}
        fixture.project(10)
        check("alias_mutation_revision", catalog_revision(db, fixture.hard) > revision)
        check("inserted_alias_searchable", discover("New Meridian Alias").resolutions[0].state == ResolutionState.RESOLVED)
        chunk = db.get(models.Chunk, 10)
        for obj, field, value in ((doc, "processing_status", "pending"), (doc, "version", 2),
                                  (chunk, "status", "failed"), (chunk, "embedding_version", 7)):
            old_value = getattr(obj, field)
            setattr(obj, field, value)
            db.flush()
            check("ineligible_" + field, not discover("New Meridian Alias").candidates)
            setattr(obj, field, old_value)
            db.flush()
        # The actual runtime active-crawl predicates are exercised, not a SQL surrogate.
        db.add(models.Website(id=1, bot_id=1, organization_id=1, root_url="https://synthetic.test", domain="synthetic.test", status="ready", active_crawl_id=1))
        db.flush()
        db.add(models.WebsiteCrawl(id=1, website_id=1, bot_id=1, organization_id=1, status="ready", version=1))
        db.flush()
        fixture.add(1100, "Harbor Active Page", source_type="website", website_id=1, crawl_id=1)
        webchunk = db.get(models.Chunk, 1100)
        webchunk.website_id, webchunk.crawl_id = 1, 1
        fixture.project(1100)
        check("active_crawl_eligible", bool(discover("Harbor Active Page").resolutions[0].candidate))
        website = db.get(models.Website, 1)
        website.active_crawl_id = 2
        db.flush()
        check("stale_crawl_excluded", not discover("Harbor Active Page").candidates)
        website.active_crawl_id = 1
        db.flush()
        check("source_restriction", not discover("Harbor Active Page", replace(fixture.hard, authorized_source_ids=(2,))).candidates)
        check("parameterized_special_input", discover("'; DROP TABLE knowledge_resources; --").resolutions[0].state != ResolutionState.RESOLVED)
        # Natural plans, no enable_seqscan override. Populate realistically sized
        # resource terms before inspecting actual index selection.
        for i in range(2000, 5000):
            fixture.add(i, f"Scale Resource {i}", kind="custom", aliases=[f"Scale Alias {i}"])
        for start in range(2000, 5000, 150):
            fixture.project(*range(start, min(start + 150, 5000)))
        db.execute(text("ANALYZE"))
        plans = {}
        for channel in ("exact", "fts", "trigram"):
            stmt = SQLResourceChannel(channel).statement(db, fixture.hard, ResourceProbe("Cedar Meridian product"), 32)
            compiled = stmt.compile(dialect=conn.dialect, compile_kwargs={"render_postcompile": True})
            plans[channel] = conn.exec_driver_sql("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + str(compiled), compiled.params).scalar()
        count = db.query(models.Document).count()
        db.commit()
    migrate(conn, "downgrade")
    record_fixture_tables(conn)
    conn.commit()
    check("downgrade", not conn.dialect.has_table(conn, "knowledge_resources"))
    check("fixture_documents_preserved", conn.execute(text("SELECT count(*) FROM documents")).scalar() == count)
    migrate(conn, "upgrade")
    record_fixture_tables(conn)
    conn.commit()
    check("reupgrade", conn.dialect.has_table(conn, "knowledge_resources"))
    print(json.dumps({"facts": facts, "checks": checks, "benchmarks": benchmarks, "natural_plans": plans}, default=str))


def main():
    try:
        if os.environ.get("PHASE3_ALLOW_REMOTE_DISPOSABLE") == "1":
            from scripts.phase31_acceptance import main as remote_main
            return remote_main()
        with local_database() as engine, isolated_application_imports(), owned_schema(engine) as conn:
            run_acceptance(conn)
        print("PHASE 3 REAL POSTGRESQL ACCEPTED")
        return 0
    except DisposableUnavailable as exc:
        print("PHASE 3 POSTGRESQL BLOCKED: " + str(exc))
        return 2
    except Exception as exc:
        # Assertion messages in this module are fixed check names. DBAPI errors
        # can embed connection values or SQL parameters, so never print them.
        name = str(exc) if type(exc) is AssertionError and re.fullmatch(r"[a-z0-9_]+", str(exc)) else type(exc).__name__
        print("PHASE 3 POSTGRESQL FAILED: " + name + " (details suppressed)")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
