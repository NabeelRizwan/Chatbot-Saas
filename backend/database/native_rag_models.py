"""Knowledge-only native index bindings; accounts/bots/settings keep their schema."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, ForeignKey, UniqueConstraint
from database.connection import Base


class NativeRagDataset(Base):
    __tablename__ = "native_rag_datasets"
    id = Column(Integer, primary_key=True)
    bot_id = Column(Integer, ForeignKey("bots.id", ondelete="CASCADE"), nullable=False, unique=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(String(32), nullable=False)
    dataset_id = Column(String(32), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class NativeRagDocument(Base):
    __tablename__ = "native_rag_documents"
    __table_args__ = (UniqueConstraint("dataset_id", "native_document_id", name="uq_native_document"),)
    id = Column(Integer, primary_key=True)
    dataset_id = Column(Integer, ForeignKey("native_rag_datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    native_document_id = Column(String(32), nullable=False)
    document_version = Column(Integer, nullable=False)
    crawl_id = Column(Integer, nullable=True)
    source_sha256 = Column(String(64), nullable=False)
    manifest_sha256 = Column(String(64), nullable=False)
    ingestion_job_id = Column(String, nullable=True, index=True)
    status = Column(String(16), nullable=False, default="staging", index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class NativeRagChunk(Base):
    __tablename__ = "native_rag_chunks"
    __table_args__ = (UniqueConstraint("binding_id", "native_chunk_id", name="uq_native_chunk"),)
    id = Column(Integer, primary_key=True)
    binding_id = Column(Integer, ForeignKey("native_rag_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    native_chunk_id = Column(String(128), nullable=False)
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)
    title = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    token_count = Column(Integer, nullable=False)
    metadata_json = Column(JSON, nullable=False, default=dict)


class NativeRagCleanup(Base):
    """Durable deletion receipt; intentionally survives local source deletion."""
    __tablename__ = "native_rag_cleanup"
    __table_args__ = (UniqueConstraint("tenant_id", "dataset_id", "kind", "resource_id", name="uq_native_cleanup"),)
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(32), nullable=False)
    dataset_id = Column(String(32), nullable=False)
    kind = Column(String(16), nullable=False)
    resource_id = Column(String(32), nullable=False)
    status = Column(String(16), nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    error_code = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
