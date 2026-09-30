"""Native parsing/indexing with SaaS-owned staging and atomic activation."""
import hashlib
from datetime import datetime
from pathlib import Path
import re
import time
from types import SimpleNamespace

from database.models import Bot, IngestionJob
from database.native_rag_models import NativeRagDataset, NativeRagDocument, NativeRagChunk
from .client import NativeClient, identifier
from .config import NativeRagError, PROFILE
from .knowledge import store_manifest


def dataset_for(db, document, client):
    # Serialize dataset allocation on the existing bot row. The remote response
    # is not retried automatically if its outcome is ambiguous.
    bot = db.query(Bot).filter(Bot.id == document.bot_id,
        Bot.organization_id == document.organization_id).with_for_update().one_or_none()
    if bot is None:
        raise NativeRagError("native_ingestion_owner_invalid")
    row = db.query(NativeRagDataset).filter(NativeRagDataset.bot_id == bot.id).one_or_none()
    if row:
        if row.organization_id != bot.organization_id or row.tenant_id != client.config.tenant:
            raise NativeRagError("native_ingestion_tenant_invalid")
        return row
    value = client.request("POST", "/api/v1/datasets", body={
        "name": f"saas-{bot.organization_id}-{bot.id}", "permission": "me",
        "embedding_model": client.config.embedding_id, "chunk_method": "naive",
        "parser_config": {"chunk_token_num": 512, "delimiter": "\n", "html4excel": False,
                          "auto_keywords": 0, "auto_questions": 0,
                          "layout_recognize": "DeepDOC", "table_context_size": 0,
                          "image_context_size": 0, "topn_tags": 3, "children_delimiter": "",
                          "parent_child": {"use_parent_child": False, "children_delimiter": "\n"},
                          "raptor": {"use_raptor": False}, "graphrag": {"use_graphrag": False}}})
    identifier(value.get("id"))
    row = NativeRagDataset(bot_id=bot.id, organization_id=bot.organization_id,
        tenant_id=client.config.tenant, dataset_id=value["id"])
    db.add(row)
    db.commit()
    return row


def prepare(db, document, *, text, title, version, crawl_id, staging_id,
            check_cancelled, source_path=None, client=None):
    client = client or NativeClient()
    dataset = dataset_for(db, document, client)
    old = db.query(NativeRagDocument).filter(NativeRagDocument.document_id == document.id,
        NativeRagDocument.ingestion_job_id == staging_id,
        NativeRagDocument.status != "retired").all()
    if old:
        raise NativeRagError("native_staging_requires_reconciliation")
    check_cancelled()
    if source_path is not None:
        data = Path(source_path).read_bytes()
        name = Path(document.original_filename or document.filename or source_path).name
    else:
        data = text.encode("utf-8")
        name = (re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", title or "Website page").strip()[:160] or "Website page") + ".md"
    uploaded = client.request("POST", f"/api/v1/datasets/{dataset.dataset_id}/documents",
                              files={"file": (name, data, "application/octet-stream")})
    if not isinstance(uploaded, list) or len(uploaded) != 1:
        raise NativeRagError("native_upload_response_invalid")
    native_id = identifier(uploaded[0].get("id"))
    # Record the remote resource immediately so crashes/cancellation never erase
    # the exact identity requiring cleanup. It is not searchable from the SaaS.
    pending = NativeRagDocument(dataset_id=dataset.id, document_id=document.id,
        native_document_id=native_id, document_version=version, crawl_id=crawl_id,
        source_sha256=hashlib.sha256(text.encode()).hexdigest(), manifest_sha256="pending",
        ingestion_job_id=staging_id, status="uploading")
    db.add(pending)
    db.commit()
    try:
        client.request("POST", f"/api/v1/datasets/{dataset.dataset_id}/chunks", body={"document_ids": [native_id]})
        deadline = time.monotonic() + client.config.parse_timeout
        next_heartbeat = 0
        while True:
            # Release the read transaction before observing cancellation. Keep
            # long native parses visible to the existing stale-job watchdog.
            db.rollback()
            check_cancelled()
            if time.monotonic() >= next_heartbeat:
                job = db.query(IngestionJob).filter(IngestionJob.job_id == staging_id,
                    IngestionJob.bot_id == document.bot_id,
                    IngestionJob.organization_id == document.organization_id).with_for_update().one_or_none()
                if job:
                    if job.status not in {"crawling", "processing", "embedding", "validating"}:
                        raise NativeRagError("native_ingestion_job_stopped")
                    job.last_heartbeat = job.updated_at = datetime.utcnow()
                    db.commit()
                next_heartbeat = time.monotonic() + 30
            result = client.request("GET", f"/api/v1/datasets/{dataset.dataset_id}/documents", params={"id": native_id})
            docs = result.get("docs", []) if isinstance(result, dict) else []
            if len(docs) != 1 or docs[0].get("id") != native_id:
                raise NativeRagError("native_parse_identity_invalid")
            state = str(docs[0].get("run", ""))
            if state in {"DONE", "3"}:
                break
            if state in {"FAIL", "CANCEL", "4", "2"} or time.monotonic() >= deadline:
                raise NativeRagError("native_parse_failed_or_timed_out")
            time.sleep(1)
        manifest = client.manifest(dataset.dataset_id, native_id)
        if manifest.get("document_id") != native_id:
            raise NativeRagError("native_manifest_identity_invalid")
        db.delete(pending)
        db.flush()
        binding = store_manifest(db, document, dataset, manifest, version=version, crawl_id=crawl_id,
            source_sha256=hashlib.sha256(text.encode()).hexdigest(), staging_id=staging_id)
        db.commit()
        rows = db.query(NativeRagChunk).filter(NativeRagChunk.binding_id == binding.id).order_by(NativeRagChunk.chunk_index).all()
        return SimpleNamespace(binding=binding, specs=rows,
            embeddings=sum(row.metadata_json.get("available_int", 1) != 0 for row in rows), metadata=dict(PROFILE))
    except Exception:
        db.rollback()
        failed = db.query(NativeRagDocument).filter(NativeRagDocument.document_id == document.id,
            NativeRagDocument.native_document_id == native_id).one_or_none()
        if failed:
            failed.status = "failed"
            db.commit()
        raise
