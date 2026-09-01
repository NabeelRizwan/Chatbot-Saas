"""Print non-sensitive Phase I schema/value counts for migration verification."""

import os
import sys

from sqlalchemy import text


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from database.connection import engine  # noqa: E402


CHECKS = {
    "bots_allowed_origins": (
        "SELECT count(*) total, count(*) FILTER "
        "(WHERE NOT allowed_origins = '[]'::jsonb) nondefault FROM bots"
    ),
    "website_crawls": (
        "SELECT count(*) total, count(*) FILTER "
        "(WHERE pages_eligible != 0 OR pages_skipped != 0 OR coverage_percent != 0) "
        "nondefault FROM website_crawls"
    ),
    "ingestion_jobs": (
        "SELECT count(*) total, count(*) FILTER "
        "(WHERE arq_job_id IS NOT NULL OR attempt_count != 0 "
        "OR cancellation_requested_at IS NOT NULL) nondefault FROM ingestion_jobs"
    ),
    "conversation_sessions": (
        "SELECT count(*) total, count(*) FILTER (WHERE public_token_hash IS NOT NULL) "
        "nondefault FROM conversation_sessions"
    ),
    "conversation_messages": (
        "SELECT count(*) total, count(*) FILTER "
        "(WHERE client_turn_id IS NOT NULL OR retrieval_attempted) "
        "nondefault FROM conversation_messages"
    ),
    "reservations": (
        "SELECT count(*) total, count(*) FILTER (WHERE status = 'reserved') active "
        "FROM message_usage_reservations"
    ),
}


with engine.connect() as connection:
    print("CONNECTION", connection.exec_driver_sql(
        "SELECT current_database(), current_schema()"
    ).one())
    print("SEARCH_PATH", connection.exec_driver_sql("SHOW search_path").scalar_one())
    restored = connection.execute(
        text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema = 'public' AND ("
            "(table_name='bots' AND column_name='allowed_origins') OR "
            "(table_name='website_crawls' AND column_name='pages_eligible') OR "
            "(table_name='ingestion_jobs' AND column_name='cancellation_requested_at') OR "
            "(table_name='conversation_sessions' AND column_name='public_token_hash') OR "
            "(table_name='conversation_messages' AND column_name='client_turn_id') OR "
            "(table_name='message_usage_reservations' AND column_name='last_heartbeat_at'))"
        )
    ).scalar_one()
    print(f"RESTORED_COLUMNS {restored}/6")
    for name, query in CHECKS.items():
        row = connection.execute(text(query)).mappings().one()
        print(name, dict(row))
    revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    print("MIGRATION", revision)
    print(
        "RESERVATION_HEARTBEAT_QUERY",
        connection.exec_driver_sql(
            "SELECT count(last_heartbeat_at), count(expires_at) "
            "FROM message_usage_reservations"
        ).one(),
    )
