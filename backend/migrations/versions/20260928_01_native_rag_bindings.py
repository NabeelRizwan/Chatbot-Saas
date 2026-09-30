"""Add knowledge bindings for native RAGFlow; no account/bot/settings changes."""
from alembic import op
import sqlalchemy as sa

revision = "20260928_01"
down_revision = "20260916_01"
branch_labels = None
depends_on = None


def upgrade():
    # The baseline creates current metadata on a fresh installation. Validate
    # that complete shape instead of recreating its already-existing tables.
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    expected = {"native_rag_datasets", "native_rag_documents", "native_rag_chunks", "native_rag_cleanup"}
    if expected & existing:
        if not expected <= existing:
            raise RuntimeError("Partial native schema requires reconciliation")
        from database.native_rag_models import NativeRagDataset, NativeRagDocument, NativeRagChunk, NativeRagCleanup
        inspector = sa.inspect(op.get_bind())
        for model in (NativeRagDataset, NativeRagDocument, NativeRagChunk, NativeRagCleanup):
            columns = {c["name"] for c in inspector.get_columns(model.__tablename__)}
            if columns != set(model.__table__.columns.keys()):
                raise RuntimeError("Existing native schema does not match this migration")
        return
    op.create_table("native_rag_datasets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("bot_id", sa.Integer, sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("dataset_id", sa.String(32), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime, nullable=False))
    op.create_table("native_rag_documents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("dataset_id", sa.Integer, sa.ForeignKey("native_rag_datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("native_document_id", sa.String(32), nullable=False),
        sa.Column("document_version", sa.Integer, nullable=False),
        sa.Column("crawl_id", sa.Integer),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("ingestion_job_id", sa.String),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("dataset_id", "native_document_id", name="uq_native_document"))
    for field in ("dataset_id", "document_id", "ingestion_job_id", "status"):
        op.create_index("ix_native_rag_documents_" + field, "native_rag_documents", [field])
    op.create_table("native_rag_chunks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("binding_id", sa.Integer, sa.ForeignKey("native_rag_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("native_chunk_id", sa.String(128), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("token_count", sa.Integer, nullable=False),
        sa.Column("metadata_json", sa.JSON, nullable=False),
        sa.UniqueConstraint("binding_id", "native_chunk_id", name="uq_native_chunk"))
    op.create_index("ix_native_rag_chunks_binding_id", "native_rag_chunks", ["binding_id"])
    op.create_table("native_rag_cleanup",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.String(32), nullable=False),
        sa.Column("dataset_id", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("resource_id", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("tenant_id", "dataset_id", "kind", "resource_id", name="uq_native_cleanup"))
    op.create_index("ix_native_rag_cleanup_status", "native_rag_cleanup", ["status"])


def downgrade():
    connection = op.get_bind()
    for table in ("native_rag_cleanup", "native_rag_chunks", "native_rag_documents", "native_rag_datasets"):
        if connection.execute(sa.text("SELECT 1 FROM " + table + " LIMIT 1")).first():
            raise RuntimeError("Native knowledge exists; export it before a destructive schema rollback")
    for table in ("native_rag_cleanup", "native_rag_chunks", "native_rag_documents", "native_rag_datasets"):
        op.drop_table(table)
