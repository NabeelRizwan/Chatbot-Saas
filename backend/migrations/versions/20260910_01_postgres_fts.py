"""Add content-only English FTS expression GIN, without rewriting chunk rows.

Revision ID: 20260910_01
Revises: 20260903_01

One-off release only. CONCURRENTLY runs outside a transaction and can leave an
invalid index on interruption. Do not retry with IF NOT EXISTS: inspect the
named index, remove only an invalid Phase 2 index, then rerun this revision.
Switch all replicas back to legacy before downgrading. No vector index touched.
"""
from alembic import op

revision = "20260910_01"
down_revision = "20260903_01"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_chunks_content_fts_en_v1"
CREATE_SQL = "CREATE INDEX CONCURRENTLY ix_chunks_content_fts_en_v1 ON chunks USING gin (to_tsvector('english'::regconfig, coalesce(content, '')))"
DROP_SQL = "DROP INDEX CONCURRENTLY IF EXISTS ix_chunks_content_fts_en_v1"


def upgrade():
    with op.get_context().autocommit_block():
        op.execute(CREATE_SQL)


def downgrade():
    with op.get_context().autocommit_block():
        op.execute(DROP_SQL)
