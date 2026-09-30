"""SaaS-owned, versioned source authority. Native IDs never come from the widget."""
import hashlib
import json
from types import SimpleNamespace

from sqlalchemy import and_, or_, exists
from database.models import Document, Website, WebsiteCrawl
from database.native_rag_models import NativeRagDataset, NativeRagDocument, NativeRagChunk
from services.structural_chunking import count_tokens
from services.retrieval_contracts import HardKnowledgeScope, ProfileIdentity
from .client import NativeClient, identifier
from .config import PROFILE, SEARCH_POLICY, NativeRagError


def ready_documents(db, bot):
    active = exists().where(and_(Website.id == Document.website_id,
        Website.bot_id == bot.id, Website.organization_id == bot.organization_id,
        Website.status == "ready", Website.active_crawl_id == Document.crawl_id,
        WebsiteCrawl.id == Document.crawl_id, WebsiteCrawl.website_id == Website.id,
        WebsiteCrawl.bot_id == bot.id, WebsiteCrawl.organization_id == bot.organization_id,
        WebsiteCrawl.status == "ready", WebsiteCrawl.version == Document.version))
    return db.query(Document).filter(
        Document.bot_id == bot.id, Document.organization_id == bot.organization_id,
        Document.status == "ready", Document.processing_status == "completed",
        or_(and_(Document.source_type != "website", Document.website_id.is_(None),
                 Document.crawl_id.is_(None)), active))


def ready_sources(db, bot):
    return (ready_documents(db, bot).add_entity(NativeRagDocument).add_entity(NativeRagDataset)
        .join(NativeRagDocument, NativeRagDocument.document_id == Document.id)
        .join(NativeRagDataset, NativeRagDataset.id == NativeRagDocument.dataset_id)
        .filter(Document.bot_id == bot.id, Document.organization_id == bot.organization_id,
            NativeRagDataset.bot_id == bot.id, NativeRagDataset.organization_id == bot.organization_id,
            Document.status == "ready", Document.processing_status == "completed",
            NativeRagDocument.status == "ready", NativeRagDocument.document_version == Document.version,
            NativeRagDocument.source_sha256 == Document.content_hash,
            or_(and_(Document.crawl_id.is_(None), NativeRagDocument.crawl_id.is_(None)),
                NativeRagDocument.crawl_id == Document.crawl_id)))


def snapshot(rows):
    return tuple(sorted((doc.id, doc.version, doc.crawl_id, doc.content_hash, doc.source_url,
        doc.title, binding.id, binding.native_document_id, binding.manifest_sha256,
        dataset.id, dataset.tenant_id, dataset.dataset_id) for doc, binding, dataset in rows))


class NativeScope:
    def __init__(self, db, bot, client=None):
        self.db, self.bot = db, bot
        self.client = client or NativeClient()
        self.rows = ready_sources(db, bot).populate_existing().all()
        if len(self.rows) > 10000 or len({row[0].id for row in self.rows}) != len(self.rows):
            raise NativeRagError("native_source_inventory_invalid")
        if {doc.id for doc in ready_documents(db, bot)} != {row[0].id for row in self.rows}:
            raise NativeRagError("native_migration_required")
        self.expected = snapshot(self.rows)
        if any(dataset.tenant_id != self.client.config.tenant for _, _, dataset in self.rows):
            raise NativeRagError("native_tenant_mismatch")
        if len({row[2].id for row in self.rows}) > 1:
            raise NativeRagError("native_dataset_ambiguous")
        docs = tuple(doc.id for doc, _, _ in self.rows)
        hard = HardKnowledgeScope(organization_id=bot.organization_id, bot_id=bot.id,
            authorized_document_ids=docs,
            embedding_profile=ProfileIdentity(PROFILE["provider"], PROFILE["model"], PROFILE["version"], PROFILE["dimensions"]),
            active_document_versions=tuple((doc.id, doc.version, doc.crawl_id) for doc, _, _ in self.rows))
        self.contract = SimpleNamespace(execution=SimpleNamespace(hard_scope=hard,
            scope_decision=SimpleNamespace(effective_document_ids=docs)), permitted_document_ids=list(docs))

    def check(self):
        # End the read transaction so PostgreSQL also observes revocation under
        # repeatable-read configurations. This scope never writes on chat paths.
        self.db.rollback()
        if (snapshot(ready_sources(self.db, self.bot).populate_existing().all()) != self.expected or
                {doc.id for doc in ready_documents(self.db, self.bot)} != {row[0].id for row in self.rows}):
            raise NativeRagError("native_authority_changed")

    def retrieve(self, query, contract, top_k):
        if contract is not self.contract or top_k != 128:
            raise NativeRagError("native_scope_changed")
        self.check()
        if not self.rows:
            return []
        dataset = self.rows[0][2].dataset_id
        documents = {binding.native_document_id: (doc, binding) for doc, binding, _ in self.rows}
        raw = self.client.search(query, dataset, list(documents))
        self.check()
        output, seen = [], set()
        for hit in raw:
            if (not isinstance(hit, dict) or hit.get("kb_id") != dataset or hit.get("doc_id") not in documents or
                    not isinstance(hit.get("chunk_id"), str) or hit["chunk_id"] in seen):
                raise NativeRagError("native_result_scope_invalid")
            seen.add(hit["chunk_id"])
            document, binding = documents[hit["doc_id"]]
            chunk = self.db.query(NativeRagChunk).filter(
                NativeRagChunk.binding_id == binding.id,
                NativeRagChunk.native_chunk_id == hit["chunk_id"]).one_or_none()
            if (chunk is None or chunk.content != hit.get("content_with_weight") or
                    chunk.title != hit.get("docnm_kwd") or
                    hashlib.sha256(chunk.content.encode()).hexdigest() != chunk.content_hash):
                raise NativeRagError("native_source_integrity_failed")
            # Numeric IDs are real SaaS mirror-row identities; the original
            # RAGFlow IDs remain explicit metadata, never fabricated PG chunks.
            source = SimpleNamespace(id=chunk.id, document_id=document.id,
                organization_id=document.organization_id, bot_id=document.bot_id,
                website_id=document.website_id, crawl_id=document.crawl_id,
                content=chunk.content, content_hash=chunk.content_hash, status="ready",
                chunk_index=chunk.chunk_index, token_count=chunk.token_count,
                embedding_provider=PROFILE["provider"], embedding_model=PROFILE["model"], embedding_version=1,
                metadata_json={**chunk.metadata_json, "native_chunk_id": chunk.native_chunk_id,
                               "native_document_id": binding.native_document_id, "native_binding_id": binding.id})
            # Use the native title for exact tested BGE inputs while retaining
            # the database-owned URL and all SaaS lifecycle fields.
            doc = SimpleNamespace(**{key: getattr(document, key) for key in (
                "id", "bot_id", "organization_id", "filename", "source_url", "canonical_url",
                "source_type", "website_id", "crawl_id", "version", "content_hash", "status",
                "processing_status", "metadata_json")}, title=chunk.title)
            output.append({"chunk": source, "document": doc, "score": hit.get("similarity", 0),
                           "match_reasons": ["Native RAGFlow W128 + BGE"],
                           "native_scores": {key: hit.get(key) for key in ("similarity", "term_similarity", "vector_similarity")}})
        self.check()
        return output


def validate_manifest(document, dataset, manifest):
    if (manifest.get("policy") != SEARCH_POLICY or manifest.get("tenant_id") != dataset.tenant_id or
            manifest.get("dataset_id") != dataset.dataset_id):
        raise NativeRagError("native_manifest_scope_invalid")
    identifier(manifest.get("document_id"))
    chunks = manifest.get("chunks")
    if not isinstance(chunks, list) or not 0 < len(chunks) <= 20000:
        raise NativeRagError("native_manifest_empty_or_oversized")
    digest = hashlib.sha256(json.dumps(chunks, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if digest != manifest.get("manifest_sha256") or len({c["id"] for c in chunks}) != len(chunks):
        raise NativeRagError("native_manifest_integrity_failed")
    if document.bot_id != dataset.bot_id or document.organization_id != dataset.organization_id:
        raise NativeRagError("native_manifest_owner_invalid")
    for row in chunks:
        identifier(row["id"])
        content, title = row.get("content"), row.get("title")
        if (not isinstance(content, str) or not content.strip() or not isinstance(title, str) or
                hashlib.sha256(content.encode()).hexdigest() != row.get("sha256") or
                not isinstance(row.get("metadata"), dict)):
            raise NativeRagError("native_manifest_content_invalid")
    return chunks, digest


def store_manifest(db, document, dataset, manifest, *, version, crawl_id, source_sha256, staging_id):
    chunks, digest = validate_manifest(document, dataset, manifest)
    binding = NativeRagDocument(dataset_id=dataset.id, document_id=document.id,
        native_document_id=manifest["document_id"], document_version=version, crawl_id=crawl_id,
        source_sha256=source_sha256, manifest_sha256=digest, ingestion_job_id=staging_id, status="staging")
    db.add(binding)
    db.flush()
    for index, row in enumerate(chunks):
        content, title = row.get("content"), row.get("title")
        db.add(NativeRagChunk(binding_id=binding.id, native_chunk_id=row["id"], content=content,
            title=title, content_hash=row["sha256"], chunk_index=index, token_count=count_tokens(content),
            metadata_json=row["metadata"]))
    db.flush()
    return binding


def promote(db, document, staging_id):
    rows = db.query(NativeRagDocument).filter(NativeRagDocument.document_id == document.id,
        NativeRagDocument.ingestion_job_id == staging_id, NativeRagDocument.status == "staging").all()
    if len(rows) != 1:
        raise NativeRagError("native_staging_binding_missing")
    binding = rows[0]
    if (binding.document_version, binding.crawl_id, binding.source_sha256) != (
            document.version, document.crawl_id, document.content_hash):
        raise NativeRagError("native_promotion_version_mismatch")
    from .cleanup import retire
    for previous in db.query(NativeRagDocument).filter(NativeRagDocument.document_id == document.id,
            NativeRagDocument.status == "ready").all():
        retire(db, previous)
    binding.status, binding.ingestion_job_id = "ready", None
