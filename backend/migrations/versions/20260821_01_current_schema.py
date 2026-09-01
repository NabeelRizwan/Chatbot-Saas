"""Establish the current Phase A-H schema as the versioned baseline.

This intentionally supports both an empty database and an existing legacy
database. SQLAlchemy creates missing current tables first; the compatibility
upgrade then adds or transforms columns on tables that already existed.

Revision ID: 20260821_01
Revises: None
"""

from pathlib import Path

from alembic import op

from database import models  # noqa: F401
from database.connection import Base


revision = "20260821_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # create_all is intentionally limited to the baseline revision: it creates
    # the current table set on an empty database and fills in entirely missing
    # tables on an existing database without dropping customer data.
    Base.metadata.create_all(bind=bind)

    # Databases that were already Phase-C compatible are upgraded through the
    # checked-in Phase D-H SQL in the same deterministic order. Transaction
    # wrappers are removed because Alembic owns the surrounding transaction.
    migrations_dir = Path(__file__).resolve().parents[1]
    for filename in (
        "phase_d_atomic_ingestion.sql",
        "phase_e_widget_streaming.sql",
        "phase_g_atomic_usage.sql",
        "phase_h_knowledge_operations.sql",
    ):
        sql = (migrations_dir / filename).read_text(encoding="utf-8")
        sql = "\n".join(
            line
            for line in sql.splitlines()
            if line.strip().upper() not in {"BEGIN;", "COMMIT;"}
        )
        statements = []
        for raw_statement in sql.split(";"):
            statement = "\n".join(
                line for line in raw_statement.splitlines()
                if not line.lstrip().startswith("--")
            ).strip()
            if statement and statement.upper() not in {"BEGIN", "COMMIT"}:
                statements.append(statement)
        for statement in statements:
            bind.exec_driver_sql(statement)

    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_cosine "
        "ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)",
        "CREATE INDEX IF NOT EXISTS ix_chunks_bot_id ON chunks (bot_id)",
        "CREATE INDEX IF NOT EXISTS ix_bots_organization_id ON bots (organization_id)",
        "CREATE INDEX IF NOT EXISTS ix_documents_org_status "
        "ON documents (organization_id, processing_status)",
        "CREATE INDEX IF NOT EXISTS ix_documents_bot_status "
        "ON documents (bot_id, processing_status)",
        "CREATE INDEX IF NOT EXISTS ix_chunks_bot_status ON chunks (bot_id, status)",
    ):
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    raise NotImplementedError(
        "The Phase I baseline does not claim destructive rollback support. "
        "Restore a PostgreSQL backup instead."
    )
