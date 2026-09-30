"""Persist native deletion work in the same transaction as SaaS ORM deletion."""
from sqlalchemy import event, or_
from sqlalchemy.orm import Session


@event.listens_for(Session, "before_flush")
def queue_native_deletions(session, flush_context, instances):
    from database.models import Bot, Document, Organization
    from database.native_rag_models import NativeRagDataset, NativeRagDocument, NativeRagChunk
    from services.native_rag.cleanup import enqueue
    documents = {row.id for row in session.deleted if isinstance(row, Document)}
    bots = {row.id for row in session.deleted if isinstance(row, Bot)}
    organizations = {row.id for row in session.deleted if isinstance(row, Organization)}
    if not (documents or bots or organizations):
        return
    with session.no_autoflush:
        affected = session.query(NativeRagDocument.dataset_id).filter(NativeRagDocument.document_id.in_(documents))
        datasets = session.query(NativeRagDataset).filter(or_(
            NativeRagDataset.bot_id.in_(bots), NativeRagDataset.organization_id.in_(organizations),
            NativeRagDataset.id.in_(affected))).all()
        for dataset in datasets:
            remove_dataset = dataset.bot_id in bots or dataset.organization_id in organizations
            bindings = session.query(NativeRagDocument).filter(NativeRagDocument.dataset_id == dataset.id)
            if not remove_dataset:
                bindings = bindings.filter(NativeRagDocument.document_id.in_(documents))
            for binding in bindings.all():
                enqueue(session, dataset, "document", binding.native_document_id)
                # Explicit ORM cleanup also works in SQLite test environments
                # where foreign-key cascade pragmas may not be enabled.
                for chunk in session.query(NativeRagChunk).filter(NativeRagChunk.binding_id == binding.id).all():
                    session.delete(chunk)
                session.delete(binding)
            if remove_dataset:
                enqueue(session, dataset, "dataset", dataset.dataset_id)
                session.delete(dataset)
