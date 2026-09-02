"""Live PostgreSQL migration acceptance tests for Phase I.

The tests use isolated, randomly named PostgreSQL schemas on the configured
database. They never copy secrets into output and always drop their schemas.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database.connection import engine as admin_engine  # noqa: E402
from services.migration_service import migration_state, upgrade_to_head  # noqa: E402


def _schema_url(schema: str) -> str:
    url = admin_engine.url.set(
        query={"options": f"-c search_path={schema},public,extensions"}
    )
    return url.render_as_string(hide_password=False)


def _new_schema(label: str) -> str:
    schema = f"phase_i_{label}_{uuid.uuid4().hex[:10]}"
    assert schema.startswith("phase_i_")
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    return schema


def _drop_schema(schema: str) -> None:
    if not schema.startswith("phase_i_"):
        raise AssertionError(f"Refusing to drop unexpected schema: {schema}")
    with admin_engine.begin() as connection:
        connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


def _assert_current(url: str, schema: str) -> None:
    test_engine = create_engine(url)
    try:
        with test_engine.connect() as connection:
            current, head = migration_state(connection, schema)
            assert current == head == "20260902_02"
    finally:
        test_engine.dispose()


def _assert_isolated(test_engine, expected_schema: str) -> None:
    with test_engine.connect() as connection:
        actual_schema = connection.exec_driver_sql("SELECT current_schema()").scalar()
    assert actual_schema == expected_schema, (
        f"Refusing schema mutation: expected {expected_schema}, got {actual_schema}"
    )


def test_fresh_database_and_idempotent_rerun() -> None:
    schema = _new_schema("fresh")
    url = _schema_url(schema)
    try:
        upgrade_to_head(url, schema)
        test_engine = create_engine(url)
        try:
            _assert_isolated(test_engine, schema)
            tables = set(inspect(test_engine).get_table_names())
            required = {
                "users", "organizations", "bots", "documents", "chunks",
                "ingestion_jobs", "websites", "website_crawls",
                "conversation_sessions", "conversation_messages",
                "message_usage_reservations", "alembic_version",
            }
            assert required <= tables, required - tables
        finally:
            test_engine.dispose()
        _assert_current(url, schema)
        upgrade_to_head(url, schema)
        _assert_current(url, schema)
    finally:
        _drop_schema(schema)


def test_pre_phase_d_compatible_upgrade() -> None:
    schema = _new_schema("legacy")
    url = _schema_url(schema)
    test_engine = create_engine(url)
    try:
        _assert_isolated(test_engine, schema)
        upgrade_to_head(url, schema)
        with test_engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE alembic_version")
            connection.exec_driver_sql(
                "ALTER TABLE website_crawls "
                "DROP COLUMN pages_eligible, DROP COLUMN pages_skipped, "
                "DROP COLUMN duplicate_urls_removed, DROP COLUMN max_depth_reached, "
                "DROP COLUMN coverage_percent, DROP COLUMN audit_metadata"
            )
            connection.exec_driver_sql(
                "ALTER TABLE ingestion_jobs DROP COLUMN arq_job_id, "
                "DROP COLUMN attempt_count, DROP COLUMN audit_metadata, "
                "DROP COLUMN cancellation_requested_at"
            )
            connection.exec_driver_sql(
                "ALTER TABLE documents DROP COLUMN ingestion_job_id, "
                "DROP COLUMN logical_size_bytes"
            )
            connection.exec_driver_sql(
                "ALTER TABLE chunks DROP COLUMN ingestion_job_id"
            )
            connection.exec_driver_sql(
                "ALTER TABLE bots DROP COLUMN allowed_origins"
            )
            connection.exec_driver_sql(
                "ALTER TABLE conversation_sessions DROP COLUMN public_token_hash"
            )
            connection.exec_driver_sql(
                "ALTER TABLE conversation_messages DROP COLUMN client_turn_id, "
                "DROP COLUMN retrieval_attempted"
            )
            connection.exec_driver_sql(
                "ALTER TABLE message_usage_reservations "
                "DROP COLUMN last_heartbeat_at, DROP COLUMN expires_at"
            )

        upgrade_to_head(url, schema)
        inspector = inspect(test_engine)
        assert "pages_eligible" in {
            item["name"] for item in inspector.get_columns("website_crawls")
        }
        assert "allowed_origins" in {
            item["name"] for item in inspector.get_columns("bots")
        }
        assert "platform_credential_id" in {
            item["name"] for item in inspector.get_columns("bots")
        }
        assert {"storage_provider", "storage_key", "embedding_model"} <= {
            item["name"] for item in inspector.get_columns("documents")
        }
        assert "last_heartbeat_at" in {
            item["name"] for item in inspector.get_columns("message_usage_reservations")
        }
        _assert_current(url, schema)
    finally:
        test_engine.dispose()
        _drop_schema(schema)


def test_unmigrated_database_is_not_current_and_failure_is_fatal() -> None:
    schema = _new_schema("unready")
    url = _schema_url(schema)
    test_engine = create_engine(url)
    try:
        _assert_isolated(test_engine, schema)
        with test_engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE alembic_version "
                "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
        with test_engine.connect() as connection:
            current, head = migration_state(connection, schema)
            assert current is None
            assert head == "20260902_02"

        invalid_url = admin_engine.url.set(database="phase_i_database_does_not_exist")
        try:
            upgrade_to_head(invalid_url.render_as_string(hide_password=False))
        except Exception:
            pass
        else:
            raise AssertionError("A failed migration unexpectedly returned success")
    finally:
        test_engine.dispose()
        _drop_schema(schema)


if __name__ == "__main__":
    tests = [
        test_fresh_database_and_idempotent_rerun,
        test_pre_phase_d_compatible_upgrade,
        test_unmigrated_database_is_not_current_and_failure_is_fatal,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS phase_i_migrations ({len(tests)} tests)")
