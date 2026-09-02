"""Add portable storage, credential-profile, crawler, and embedding contracts.

Revision ID: 20260902_01
Revises: 20260821_01
"""
from alembic import op


revision = "20260902_01"
down_revision = "20260821_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS keeps fresh installs safe because the baseline revision uses
    # current SQLAlchemy metadata to create missing tables.
    statements = (
        "ALTER TABLE bots ADD COLUMN IF NOT EXISTS platform_credential_id INTEGER",
        "CREATE INDEX IF NOT EXISTS ix_bots_platform_credential_id ON bots (platform_credential_id)",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS storage_provider VARCHAR",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS storage_key TEXT",
        "CREATE INDEX IF NOT EXISTS ix_documents_storage_key ON documents (storage_key)",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_type VARCHAR",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS original_filename VARCHAR",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_content_hash VARCHAR",
        "CREATE INDEX IF NOT EXISTS ix_documents_source_content_hash ON documents (source_content_hash)",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedding_provider VARCHAR",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedding_model VARCHAR",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedding_version INTEGER",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedding_dimensions INTEGER",
        "ALTER TABLE website_crawls ADD COLUMN IF NOT EXISTS crawler_provider VARCHAR NOT NULL DEFAULT 'firecrawl'",
        "ALTER TABLE website_crawls ADD COLUMN IF NOT EXISTS embedding_provider VARCHAR",
        "ALTER TABLE website_crawls ADD COLUMN IF NOT EXISTS embedding_model VARCHAR",
        "ALTER TABLE website_crawls ADD COLUMN IF NOT EXISTS embedding_version INTEGER",
        "ALTER TABLE website_crawls ADD COLUMN IF NOT EXISTS embedding_dimensions INTEGER",
        "UPDATE bots SET platform_credential_id = platform_api_keys.id FROM platform_api_keys "
        "WHERE platform_api_keys.allocated_to_bot_id = bots.id AND bots.platform_credential_id IS NULL",
    )
    for statement in statements:
        op.execute(statement)

    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_bots_platform_credential_id'
            ) THEN
                ALTER TABLE bots
                ADD CONSTRAINT fk_bots_platform_credential_id
                FOREIGN KEY (platform_credential_id)
                REFERENCES platform_api_keys(id)
                ON DELETE SET NULL;
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    raise NotImplementedError(
        "This production-hardening migration is additive. Restore a database backup for rollback."
    )
