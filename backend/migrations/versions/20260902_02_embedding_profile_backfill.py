"""Backfill compatible embedding-profile metadata without changing vectors.

Revision ID: 20260902_02
Revises: 20260902_01
"""
from alembic import op


revision = "20260902_02"
down_revision = "20260902_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing chunks already carry provider/model/version and the current
    # pgvector column is fixed at 768 dimensions. Copy only unambiguous active
    # profiles to their owning documents; vectors and corpus text are untouched.
    op.execute(
        """
        WITH compatible_profiles AS (
            SELECT
                document_id,
                MIN(embedding_provider) AS provider,
                MIN(embedding_model) AS model,
                MIN(embedding_version) AS version
            FROM chunks
            WHERE status = 'ready'
            GROUP BY document_id
            HAVING COUNT(DISTINCT embedding_provider) = 1
               AND COUNT(DISTINCT embedding_model) = 1
               AND COUNT(DISTINCT embedding_version) = 1
        )
        UPDATE documents AS document
        SET embedding_provider = COALESCE(document.embedding_provider, profile.provider),
            embedding_model = COALESCE(document.embedding_model, profile.model),
            embedding_version = COALESCE(document.embedding_version, profile.version),
            embedding_dimensions = COALESCE(document.embedding_dimensions, 768)
        FROM compatible_profiles AS profile
        WHERE document.id = profile.document_id
          AND (
              document.embedding_provider IS NULL
              OR document.embedding_model IS NULL
              OR document.embedding_version IS NULL
              OR document.embedding_dimensions IS NULL
          )
        """
    )
    op.execute(
        """
        WITH crawl_profiles AS (
            SELECT
                crawl_id,
                MIN(embedding_provider) AS provider,
                MIN(embedding_model) AS model,
                MIN(embedding_version) AS version,
                MIN(embedding_dimensions) AS dimensions
            FROM documents
            WHERE status = 'ready' AND crawl_id IS NOT NULL
            GROUP BY crawl_id
            HAVING COUNT(DISTINCT embedding_provider) = 1
               AND COUNT(DISTINCT embedding_model) = 1
               AND COUNT(DISTINCT embedding_version) = 1
               AND COUNT(DISTINCT embedding_dimensions) = 1
        )
        UPDATE website_crawls AS crawl
        SET embedding_provider = COALESCE(crawl.embedding_provider, profile.provider),
            embedding_model = COALESCE(crawl.embedding_model, profile.model),
            embedding_version = COALESCE(crawl.embedding_version, profile.version),
            embedding_dimensions = COALESCE(crawl.embedding_dimensions, profile.dimensions)
        FROM crawl_profiles AS profile
        WHERE crawl.id = profile.crawl_id
          AND (
              crawl.embedding_provider IS NULL
              OR crawl.embedding_model IS NULL
              OR crawl.embedding_version IS NULL
              OR crawl.embedding_dimensions IS NULL
          )
        """
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Embedding-profile metadata backfill is additive. Restore a database backup for rollback."
    )
