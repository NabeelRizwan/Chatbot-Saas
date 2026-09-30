"""Explicitly adopt an existing native corpus into an existing SaaS bot.

Read-only by default. Requires an explicit DATABASE_URL environment variable;
never silently targets backend/.env. The mapping pins both source and manifest
hashes, so a document name or guessed URL can never grant source authority.
"""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bot-id', type=int, required=True)
    parser.add_argument('--organization-id', type=int, required=True)
    parser.add_argument('--dataset-id', required=True)
    parser.add_argument('--mapping', type=Path, required=True)
    parser.add_argument('--expected-database', required=True, help='host/database, or absolute SQLite database path')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    from sqlalchemy.engine import make_url
    url = make_url(os.environ.get('DATABASE_URL', ''))
    identity = str(Path(url.database).resolve()) if url.get_backend_name() == 'sqlite' else f'{url.host}/{url.database}'
    if identity != args.expected_database:
        raise SystemExit('DATABASE_TARGET_MISMATCH')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from database.connection import SessionLocal
    from database.models import Bot, Document
    from database.native_rag_models import NativeRagDataset, NativeRagDocument
    from services.native_rag.client import NativeClient, identifier
    from services.native_rag.config import PROFILE, NativeRagError
    from services.native_rag.knowledge import store_manifest, promote, validate_manifest, ready_documents
    mapping = json.loads(args.mapping.read_text(encoding='utf-8'))
    if not isinstance(mapping, list) or not mapping or len(mapping) > 10000:
        raise SystemExit('MAPPING_INVALID')
    if any(set(row) != {'document_id','native_document_id','source_sha256','manifest_sha256'} for row in mapping):
        raise SystemExit('MAPPING_SCHEMA_INVALID')
    if any(len({row[key] for row in mapping}) != len(mapping) for key in ('document_id','native_document_id')):
        raise SystemExit('DUPLICATE_MAPPING')
    client = NativeClient()
    if not client.health():
        raise SystemExit('NATIVE_SERVICE_NOT_READY')
    dataset_id = identifier(args.dataset_id)
    with SessionLocal() as db:
        bot = db.query(Bot).filter_by(id=args.bot_id,organization_id=args.organization_id).one_or_none()
        if bot is None:
            raise SystemExit('BOT_OWNER_MISMATCH')
        if {doc.id for doc in ready_documents(db,bot)} != {row['document_id'] for row in mapping}:
            raise SystemExit('MAPPING_MUST_COVER_ALL_CURRENT_READY_DOCUMENTS')
        prior = db.query(NativeRagDataset).filter_by(bot_id=bot.id).one_or_none()
        if prior is not None:
            raise SystemExit('BOT_ALREADY_BOUND_USE_NORMAL_REINDEX')
        if db.query(NativeRagDataset.id).filter_by(dataset_id=dataset_id).first():
            raise SystemExit('DATASET_ALREADY_OWNED')
        prepared = []
        for row in mapping:
            doc = db.query(Document).filter_by(id=row['document_id'],bot_id=bot.id,
                organization_id=bot.organization_id,status='ready',processing_status='completed').one_or_none()
            if doc is None or doc.content_hash != row['source_sha256']:
                raise SystemExit('DOCUMENT_SOURCE_MISMATCH')
            if db.query(NativeRagDocument.id).filter_by(document_id=doc.id).first():
                raise SystemExit('DOCUMENT_ALREADY_BOUND')
            snapshot = (doc.id,doc.version,doc.crawl_id,doc.content_hash)
            manifest = client.manifest(dataset_id, identifier(row['native_document_id']))
            if manifest.get('manifest_sha256') != row['manifest_sha256'] or manifest.get('document_id') != row['native_document_id']:
                raise SystemExit('NATIVE_MANIFEST_CHANGED')
            from types import SimpleNamespace
            validate_manifest(doc, SimpleNamespace(bot_id=bot.id,organization_id=bot.organization_id,
                dataset_id=dataset_id,tenant_id=client.config.tenant), manifest)
            prepared.append((snapshot,manifest))
        db.rollback()
        if not args.apply:
            print(json.dumps({'applied':False,'documents':len(prepared),
                              'chunks':sum(len(m['chunks']) for _,m in prepared),
                              'bot_id':args.bot_id,'organization_id':args.organization_id}))
            return
        # Lock only after network reads. Recheck ownership/source versions in
        # the same transaction as activation; no partial bot migration.
        if {doc.id for doc in ready_documents(db,bot).with_for_update()} != {row['document_id'] for row in mapping}:
            raise NativeRagError('native_adoption_inventory_changed')
        dataset = NativeRagDataset(bot_id=bot.id,organization_id=bot.organization_id,
            tenant_id=client.config.tenant,dataset_id=dataset_id)
        db.add(dataset); db.flush()
        chunks = 0
        for snapshot,manifest in prepared:
            doc = db.query(Document).filter_by(id=snapshot[0],bot_id=args.bot_id,
                organization_id=args.organization_id,status='ready',processing_status='completed').with_for_update().one()
            if (doc.id,doc.version,doc.crawl_id,doc.content_hash) != snapshot:
                raise NativeRagError('native_adoption_source_changed')
            store_manifest(db,doc,dataset,manifest,version=doc.version,crawl_id=doc.crawl_id,
                source_sha256=doc.content_hash,staging_id='native-adoption')
            promote(db,doc,'native-adoption')
            for key,value in PROFILE.items():
                setattr(doc,'embedding_'+key,value)
            doc.chunk_count=len(manifest['chunks']); chunks+=doc.chunk_count
        db.commit()
        print(json.dumps({'applied':args.apply,'documents':len(prepared),'chunks':chunks,
                          'bot_id':args.bot_id,'organization_id':args.organization_id}))


if __name__ == '__main__':
    main()
