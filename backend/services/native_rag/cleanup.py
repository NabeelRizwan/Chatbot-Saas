"""Retryable native source cleanup; active bindings are never deleted."""
from database.native_rag_models import NativeRagDataset, NativeRagDocument, NativeRagChunk, NativeRagCleanup
from .client import NativeClient, identifier
from .config import NativeRagError


def enqueue(db, dataset, kind, resource_id):
    identifier(resource_id)
    key = (dataset.tenant_id, dataset.dataset_id, kind, resource_id)
    if any(isinstance(row, NativeRagCleanup) and (row.tenant_id, row.dataset_id, row.kind, row.resource_id) == key
           for row in db.new):
        return
    existing = db.query(NativeRagCleanup).filter(NativeRagCleanup.tenant_id == key[0],
        NativeRagCleanup.dataset_id == key[1], NativeRagCleanup.kind == kind,
        NativeRagCleanup.resource_id == resource_id).one_or_none()
    if existing is None:
        db.add(NativeRagCleanup(tenant_id=key[0], dataset_id=key[1], kind=kind, resource_id=resource_id))


def retire(db, binding):
    dataset = db.get(NativeRagDataset, binding.dataset_id)
    if dataset:
        enqueue(db, dataset, "document", binding.native_document_id)
    binding.status = "retired"


def abort_staging(db, staging_id):
    for row in db.query(NativeRagDocument).filter(NativeRagDocument.ingestion_job_id == staging_id).all():
        retire(db, row)


def process_pending(db, *, client=None, limit=10):
    client = client or NativeClient()
    completed = 0
    ids = [row[0] for row in db.query(NativeRagCleanup.id).filter(NativeRagCleanup.status == "pending")
           .order_by(NativeRagCleanup.kind.desc(), NativeRagCleanup.attempts, NativeRagCleanup.id).limit(limit).all()]
    for task_id in ids:
        task = db.query(NativeRagCleanup).filter(NativeRagCleanup.id == task_id,
            NativeRagCleanup.status == "pending").with_for_update(skip_locked=True).one_or_none()
        if task is None:
            continue
        try:
            if task.tenant_id != client.config.tenant:
                raise NativeRagError("native_cleanup_tenant_mismatch")
            dataset = db.query(NativeRagDataset).filter(NativeRagDataset.dataset_id == task.dataset_id).one_or_none()
            if task.kind == "document":
                active = (db.query(NativeRagDocument.id).join(NativeRagDataset,
                    NativeRagDataset.id == NativeRagDocument.dataset_id)
                    .filter(NativeRagDataset.dataset_id == task.dataset_id,
                            NativeRagDocument.native_document_id == task.resource_id,
                            NativeRagDocument.status == "ready").first())
                if active:
                    raise NativeRagError("native_cleanup_source_active")
                # A crash after remote deletion but before the local commit is
                # recoverable. Absence must be confirmed by an authenticated,
                # scoped list; a network/API error is never treated as absence.
                datasets = client.request("GET", "/api/v1/datasets", params={"id": identifier(task.dataset_id)})
                if not isinstance(datasets, list) or any(row.get("id") != task.dataset_id for row in datasets):
                    raise NativeRagError("native_cleanup_inventory_invalid")
                if datasets:
                    remote = client.request("GET", f"/api/v1/datasets/{task.dataset_id}/documents",
                                            params={"id": identifier(task.resource_id)})
                    if not isinstance(remote, dict) or not isinstance(remote.get("docs"), list):
                        raise NativeRagError("native_cleanup_inventory_invalid")
                    if any(row.get("id") != task.resource_id for row in remote["docs"]):
                        raise NativeRagError("native_cleanup_inventory_invalid")
                    if remote["docs"]:
                        client.request("DELETE", f"/api/v1/datasets/{task.dataset_id}/documents",
                                       body={"ids": [task.resource_id]})
                if dataset:
                    bindings = db.query(NativeRagDocument).filter(NativeRagDocument.dataset_id == dataset.id,
                        NativeRagDocument.native_document_id == task.resource_id).all()
                    for binding in bindings:
                        db.query(NativeRagChunk).filter(NativeRagChunk.binding_id == binding.id).delete(synchronize_session=False)
                        db.delete(binding)
            elif task.kind == "dataset" and dataset is None:
                remote = client.request("GET", "/api/v1/datasets", params={"id": identifier(task.dataset_id)})
                if not isinstance(remote, list) or any(row.get("id") != task.dataset_id for row in remote):
                    raise NativeRagError("native_cleanup_inventory_invalid")
                if remote:
                    client.request("DELETE", "/api/v1/datasets", body={"ids": [task.dataset_id]})
            else:
                raise NativeRagError("native_cleanup_dataset_active")
            task.status, task.error_code = "done", None
            completed += 1
        except Exception as error:
            db.rollback()
            task = db.get(NativeRagCleanup, task_id)
            task.attempts += 1
            task.error_code = str(error) if isinstance(error, NativeRagError) else "native_cleanup_failed"
        db.commit()
    return completed
