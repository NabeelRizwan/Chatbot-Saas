"""Optional observer of successful durable ingestion; never a serving publisher.

No configured database/session factory, providers, retrieval or framework imports.
The caller supplies the same authorized engine as the legacy operation. All graph
writes use StructuralRepository; job audit JSON contains counts/hashes, NOT text.
"""
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from hashlib import sha256
import json
import logging
from pathlib import Path
from time import perf_counter

from services.structural_shadow_config import load_shadow_config

AUDIT_KEY = 'structural_shadow_v1'
MAX_DOCUMENTS = 1000
log = logging.getLogger('backend.structural_shadow')


class ShadowRefusal(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def mark_pending(job, documents):
    """Called in legacy promotion: bounded metadata only; no parser/sidecar SQL."""
    if not job or not load_shadow_config().allows(job.organization_id, job.bot_id):
        return
    items = list(documents)
    state = {'mode': 'shadow', 'status': 'pending', 'documents': items, 'results': {}}
    if not items or len(items) > MAX_DOCUMENTS:
        state = {'mode': 'shadow', 'status': 'failed', 'failure_category': 'DOCUMENT_BOUND', 'documents': [], 'results': {}}
    job.audit_metadata = {**(job.audit_metadata or {}), AUDIT_KEY: state}


@dataclass(frozen=True)
class ShadowSource:
    organization_id: int
    bot_id: int
    document_id: int
    version: int
    artifact: bytes
    source_format: str
    fidelity: str
    artifact_ref: str | None = None
    legacy_chunks: int = 0
    legacy_tokens: int | None = None

    def __post_init__(self):
        if any(type(n) is not int or n <= 0 for n in (
            self.organization_id, self.bot_id, self.document_id, self.version
        )) or type(self.artifact) is not bytes or not 0 < len(self.artifact) <= 20*1024*1024:
            raise ShadowRefusal('SOURCE_BOUND')
        if self.source_format not in {'markdown', 'text', 'pdf', 'docx'}:
            raise ShadowRefusal('UNSUPPORTED_FORMAT')


@lru_cache(maxsize=4)
def parser_signature(fmt):
    names = ('structural_text_adapter.py', 'structural_text_rules.py') if fmt in {'markdown', 'text'} else (
        'structural_docling_adapter.py', '../scripts/structural_docling_worker.py')
    return sha256(b''.join((Path(__file__).parent / n).read_bytes().replace(b'\r\n', b'\n') for n in names)).hexdigest()


def source_identity(source):
    from services.structural_document import SourceIdentity
    h = sha256(source.artifact).hexdigest()
    return SourceIdentity(organization_id=source.organization_id, bot_id=source.bot_id,
        document_id=source.document_id, source_version=source.version,
        document_version_id=f'shadow-v{source.version}-{h}', source_sha256=h)


def revision_identity(source, *, parser_recipe=None, chunk_policy=None):
    from services.structural_chunking import ChunkPolicy, digest, local_tokenizer
    from services.structural_document import RevisionIdentity
    policy = chunk_policy or ChunkPolicy()
    recipe = digest({'parser': parser_recipe or parser_signature(source.source_format),
        'format': source.source_format, 'fidelity': source.fidelity, 'chunk': policy.model_dump(),
        'tokenizer': local_tokenizer()[1],
        'serializer': sha256((Path(__file__).parent / 'structural_chunking.py').read_bytes().replace(b'\r\n', b'\n')).hexdigest()})
    immutable = source_identity(source)
    # Revision IDs are unique per document across ALL source versions in 4.1B,
    # not merely within one document_version_id. Bind both source and recipe.
    return RevisionIdentity(source=immutable, structure_revision_id='shadow-' + digest({
        'source': immutable.model_dump(mode='json'), 'recipe': recipe}))


def check_cancel(cancelled):
    if cancelled():
        raise ShadowRefusal('CANCELLED')


def build_shadow(source, *, model_cache=None, cancelled=lambda: False, identity=None, chunk_policy=None):
    """Pure transformation; no SQL, storage, provider, or serving side effects."""
    from services.structural_chunking import serialize_structural_document
    identity = identity or revision_identity(source, chunk_policy=chunk_policy)
    if identity.source != source_identity(source):
        raise ShadowRefusal('SOURCE_IDENTITY')
    check_cancel(cancelled)
    start = perf_counter()
    if source.source_format in {'markdown', 'text'}:
        from services.structural_text_adapter import parse_structural_text
        graph = parse_structural_text(source.artifact, identity=identity,
            source_format=source.source_format, fidelity=source.fidelity)
    else:
        from services.structural_docling_adapter import convert_artifact
        graph = convert_artifact(source.artifact, identity=identity, source_format=source.source_format,
            fidelity=source.fidelity, model_cache=model_cache, cancelled=cancelled)
    parsed = perf_counter()
    check_cancel(cancelled)
    batch = serialize_structural_document(graph, policy=chunk_policy)
    serialized = perf_counter()
    check_cancel(cancelled)
    return batch, {'parse_ms': (parsed-start)*1000, 'serialize_ms': (serialized-parsed)*1000}


def union_length(intervals):
    end = total = 0
    for lo, hi in sorted(intervals):
        total += max(0, hi-max(lo, end))
        end = max(end, hi)
    return total


def cost_flags(chunks, tokens, legacy_chunks, legacy_tokens):
    return {'legacy_chunks': legacy_chunks, 'legacy_tokens': legacy_tokens,
        'prospective_chunks': chunks, 'prospective_tokens': tokens,
        'chunk_ratio': chunks/legacy_chunks if legacy_chunks else None,
        'token_ratio': tokens/legacy_tokens if legacy_tokens else None,
        'review_flags': ([ 'STRUCTURAL_CHUNK_COUNT_REVIEW' ] if legacy_chunks and chunks > legacy_chunks*1.5 else []) +
                        ([ 'STRUCTURAL_TOKEN_COST_REVIEW' ] if legacy_tokens and tokens > legacy_tokens*1.3 else [])}


def summarize(source, batch):
    nodes = {n.identity.node_key: n for n in batch.source_graph.nodes}
    intervals = {}
    for c in batch.chunks:
        for s in c.mappings:
            m = s.mapping
            intervals.setdefault(m.node.node_key, []).append((m.node_slice.start, m.node_slice.end))
    represented = sum(union_length(v) for v in intervals.values())
    for x in batch.excluded:
        intervals.setdefault(x.node.node_key, []).append((x.node_slice.start, x.node_slice.end))
    total = sum(len(n.text.encode()) for n in nodes.values())
    accounted = sum(union_length(v) for v in intervals.values())
    def primary(c):
        return {s.mapping.node.node_key for s in c.mappings if s.usage == 'primary'}
    def furniture_candidate(c):
        # Analysis only: explicit roles or a tiny link-dense unit. This NEVER
        # excludes, reclassifies, truncates or changes a serialization decision.
        keys = primary(c)
        return any(nodes[k].semantic_role.value in {'navigation','furniture'} for k in keys) or (
            c.token_count < 100 and sum(nodes[k].attributes.link is not None for k in keys) >= 3)
    unknown = sum(bool(n.text) and n.semantic_role.value == 'unknown' for n in nodes.values())
    tiny = sum(c.token_count < 50 for c in batch.chunks)
    # An upper-bound candidate count, NOT an optimization suggestion. Adjacent
    # small complete specs fit the token ceiling but v1 kept their units apart.
    blocked = sum(a.complete_unit and b.complete_unit and a.part_count == b.part_count == 1
        and a.bundle_key != b.bundle_key and a.token_count+b.token_count <= 650
        for a,b in zip(batch.chunks, batch.chunks[1:]))
    return {**cost_flags(len(batch.chunks), sum(c.token_count for c in batch.chunks), source.legacy_chunks, source.legacy_tokens),
        'nodes': len(nodes), 'edges': len(batch.source_graph.edges), 'source_bytes': len(source.artifact),
        'node_text_bytes': total, 'represented_node_bytes': represented, 'accounted_node_bytes': accounted,
        'unaccounted_node_bytes': total-accounted, 'source_evidence_coverage': accounted/total if total else 1,
        'unknown_role_nodes': unknown, 'unknown_role_rate': unknown/len(nodes),
        'unknown_role_specs': sum(any(nodes[k].semantic_role.value == 'unknown' for k in primary(c)) for c in batch.chunks),
        'heading_only_specs': sum(c.kind == 'heading' for c in batch.chunks),
        'navigation_furniture_specs': sum(any(nodes[k].semantic_role.value in {'navigation','furniture'} for k in primary(c)) for c in batch.chunks),
        'navigation_furniture_candidate_specs': sum(furniture_candidate(c) for c in batch.chunks),
        'excluded_navigation_furniture_nodes': len({x.node.node_key for x in batch.excluded if x.reason in {'navigation','furniture'}}),
        'tiny_specs': tiny, 'inherited_only_specs': sum(not primary(c) for c in batch.chunks),
        'adjacent_small_units_kept_separate': blocked, 'chunk_kinds': dict(Counter(c.kind for c in batch.chunks)),
        'quality_status': batch.source_graph.revision.quality.disposition.value,
        'quality_classification': batch.source_graph.revision.quality.classification.value,
        'source_hash': batch.source_graph.revision.identity.source.source_sha256,
        'structural_hash': batch.source_graph.canonical_hash(), 'serialization_hash': batch.canonical_hash(),
        'recipe_hash': batch.recipe_hash, 'parser_policy': batch.source_graph.revision.parser_version,
        'chunk_policy': 'structure-chunk-v1', 'fidelity': source.fidelity, 'ocr_used': False}


def aggregate(results):
    rows = [r for r in results if r.get('status') == 'validated']
    return {'validated_documents': len(rows), **cost_flags(
        sum(r['prospective_chunks'] for r in rows), sum(r['prospective_tokens'] for r in rows),
        sum(r['legacy_chunks'] for r in rows),
        sum(r['legacy_tokens'] for r in rows) if all(r['legacy_tokens'] is not None for r in rows) else None)}


def capture_source(conn, source):
    from services.structural_repository import StructuralRepository, StorageScope
    repo = StructuralRepository(conn, StorageScope(source.organization_id, source.bot_id, frozenset({source.document_id})))
    repo.create_document_version(source_identity(source), source_identity=f'owned-document:{source.document_id}',
        source_format=source.source_format, fidelity=source.fidelity,
        source_text=source.artifact.decode('utf-8') if source.source_format in {'markdown','text'} else None,
        source_artifact_ref=source.artifact_ref)
    return repo


def persist_graph(conn, source, batch):
    """Short bounded transaction, after parsing. Caller commits or rolls back."""
    from services.structural_repository import RevisionCounts, StructuralConflict
    from services.structural_chunking import digest
    graph = batch.source_graph
    if graph.revision.identity.source != source_identity(source):
        raise ShadowRefusal('SOURCE_IDENTITY')
    repo = capture_source(conn, source)
    # The storage descriptor fingerprints the parser AND serializer recipes. The
    # direct adapter graph/spec hashes above stay separately auditable, unchanged.
    descriptor = graph.revision.model_copy(update={'chunker_version': 'structure-chunk-v1',
        'configuration_sha256': digest({'parser': graph.revision.configuration_sha256,
            'serializer': batch.recipe_hash, 'shadow_recipe': graph.revision.identity.structure_revision_id})})
    stored = repo.create_structure_revision(descriptor, RevisionCounts(len(graph.nodes), len(graph.edges), 0))
    if stored.identity != descriptor.identity:
        raise StructuralConflict('shadow build identity mismatch')
    if stored.state.value == 'validated':
        repo.validate_revision_counts(source.document_id, stored.identity.structure_revision_id)
        return descriptor.build_fingerprint()
    if stored.state.value != 'staging':
        raise StructuralConflict('terminal shadow build cannot be resurrected')
    for start in range(0, len(graph.nodes), 500):
        repo.stage_nodes(stored.identity, graph.nodes[start:start+500])
    for start in range(0, len(graph.edges), 500):
        repo.stage_edges(stored.identity, graph.edges[start:start+500])
    repo.mark_revision_validated(source.document_id, stored.identity.structure_revision_id)
    return descriptor.build_fingerprint()


def failure_category(exc):
    from services.structural_text_adapter import StructuralParseError
    from services.structural_docling_adapter import DoclingAdapterError
    from services.structural_chunking import SerializationError
    if isinstance(exc, (StructuralParseError, DoclingAdapterError)):
        return type(exc).__name__ + ':' + exc.code
    if isinstance(exc, ShadowRefusal):
        return str(exc)
    return 'SERIALIZATION_FAILED' if isinstance(exc, SerializationError) else 'SHADOW_OPERATION_FAILED'


def _job(db, job_id, org, bot, *, lock=False):
    from database.models import IngestionJob
    q = db.query(IngestionJob).filter(IngestionJob.job_id == job_id,
        IngestionJob.organization_id == org, IngestionJob.bot_id == bot)
    return (q.with_for_update() if lock else q).populate_existing().first()


def _audit_result(db, job_id, org, bot, key, result):
    job = _job(db, job_id, org, bot, lock=True)
    if job is None:
        raise ShadowRefusal('JOB_SCOPE')
    if result.get('status') == 'validated' and (job.status != 'ready' or job.cancellation_requested_at is not None):
        # The job row lock is the final cancellation/commit serialization point.
        # This exception rolls back the same transaction's prospective graph.
        raise ShadowRefusal('CANCELLED')
    audit = dict(job.audit_metadata or {})
    shadow = dict(audit[AUDIT_KEY])
    results = dict(shadow.get('results', {}))
    prior = results.get(key, {})
    # A duplicate/late observer may not replace a completed successful result.
    if prior.get('status') != 'validated':
        results[key] = result
    shadow.update(results=results, aggregate=aggregate(results.values()))
    terminal = {'validated','failed','cancelled'}
    shadow['status'] = 'complete' if len(results) == len(shadow['documents']) and all(r.get('status') in terminal for r in results.values()) else 'pending'
    audit[AUDIT_KEY] = shadow
    job.audit_metadata = audit
    db.commit()


def _owned_source(db, job, item):
    from database.models import Bot, Chunk, Document, Website
    from sqlalchemy import func
    doc = db.query(Document).join(Bot, Bot.id == Document.bot_id).filter(
        Document.id == item['document_id'], Document.organization_id == job.organization_id,
        Document.bot_id == job.bot_id, Bot.organization_id == job.organization_id,
        Document.status == 'ready', Document.processing_status == 'completed',
        Document.version == item['version']).first()
    if doc is None:
        raise ShadowRefusal('SOURCE_NOT_CURRENT_READY')
    if doc.website_id is not None and not db.query(Website.id).filter(
        Website.id == doc.website_id, Website.organization_id == job.organization_id,
        Website.bot_id == job.bot_id, Website.active_crawl_id == doc.crawl_id).first():
        raise ShadowRefusal('SOURCE_NOT_ACTIVE_CRAWL')
    count, tokens = db.query(func.count(Chunk.id), func.sum(Chunk.token_count)).filter(
        Chunk.document_id == doc.id, Chunk.organization_id == job.organization_id,
        Chunk.bot_id == job.bot_id, Chunk.status == 'ready', Chunk.ingestion_job_id.is_(None)).one()
    fmt = {'website':'markdown','text':'text','txt':'text','pdf':'pdf','docx':'docx'}.get(doc.source_type)
    if fmt is None:
        raise ShadowRefusal('UNSUPPORTED_FORMAT')
    ref = None
    if fmt == 'markdown' or doc.source_type == 'text':
        data = (doc.raw_text or '').encode('utf-8')
    else:
        # New uploads have tenant-owned immutable keys + expected content hash.
        # Unverified legacy arbitrary filesystem paths are NOT shadow inputs.
        if not doc.storage_provider or not doc.storage_key or not doc.source_content_hash:
            raise ShadowRefusal('IMMUTABLE_ARTIFACT_REQUIRED')
        from services.document_processing_service import materialize_document_source
        with materialize_document_source(doc) as path:
            with open(path, 'rb') as stream:
                data = stream.read(20*1024*1024+1)
        if sha256(data).hexdigest() != doc.source_content_hash:
            raise ShadowRefusal('SOURCE_HASH')
        ref = f'{doc.storage_provider}:{doc.storage_key}'
        if fmt == 'text':
            data.decode('utf-8')  # No silent lossy text conversion in shadow.
    return ShadowSource(job.organization_id, job.bot_id, doc.id, doc.version, data, fmt,
        'extracted_markdown' if fmt == 'markdown' else 'original', ref, count, tokens)


def resume_shadow_job(engine, job_id, organization_id, bot_id, document_id):
    """Safe READY-job redelivery hook. Optional observer errors never propagate.

    A crash leaves pending/running audit records. Redelivery repeats only the
    observer, never acquisition/embedding/promotion. Source/version is rechecked.
    """
    config = load_shadow_config()
    if not job_id or not config.allows(organization_id, bot_id):
        return
    from sqlalchemy.orm import Session
    try:
        with Session(engine) as db:
            job = _job(db, job_id, organization_id, bot_id)
            if not job or job.document_id != document_id or job.status != 'ready':
                return
            shadow = (job.audit_metadata or {}).get(AUDIT_KEY, {})
            items = shadow.get('documents', [])
            if shadow.get('status') != 'pending' or not 0 < len(items) <= MAX_DOCUMENTS:
                return
            db.rollback()
            for item in items:
                key = str(item['document_id'])
                job = _job(db, job_id, organization_id, bot_id)
                prior = (job.audit_metadata or {}).get(AUDIT_KEY, {}).get('results', {}).get(key, {})
                if prior.get('status') in {'validated','failed','cancelled'}:
                    db.rollback()
                    continue
                result = {'mode':'shadow', 'document_id':item['document_id'], 'source_version':item['version'],
                    'organization_id':organization_id, 'bot_id':bot_id, 'started_at':now(),
                    'status':'running', 'failure_category':None, 'completed_at':None,
                    'nodes':0, 'edges':0, 'prospective_chunks':0, 'prospective_tokens':0,
                    'parse_ms':None, 'serialize_ms':None, 'source_evidence_coverage':None,
                    'unknown_role_nodes':None, 'unknown_role_rate':None,
                    'quality_status':'not_assessed', 'review_flags':[], 'source_hash':None,
                    'document_version_id':None, 'structure_revision_id':None, 'source_bytes':None,
                    'parser_policy':None, 'chunk_policy':'structure-chunk-v1', 'fidelity':None,
                    'ocr_used':False, 'model_policy':None}
                try:
                    source = _owned_source(db, job, item)
                    db.rollback()  # NO open source-read transaction during parsing.
                    identity = revision_identity(source)
                    result.update(source_hash=identity.source.source_sha256,
                        document_version_id=identity.source.document_version_id,
                        structure_revision_id=identity.structure_revision_id, source_bytes=len(source.artifact),
                        parser_policy=source.source_format, chunk_policy='structure-chunk-v1', fidelity=source.fidelity,
                        ocr_used=False, model_policy='docling-structure-v1' if source.source_format in {'pdf','docx'} else None)
                    _audit_result(db, job_id, organization_id, bot_id, key, result)
                    capture_source(db.connection(), source)
                    db.commit()
                    def cancelled():
                        with Session(engine) as check:
                            current = _job(check, job_id, organization_id, bot_id)
                            return not current or current.status != 'ready' or current.cancellation_requested_at is not None
                    check_cancel(cancelled)
                    batch, times = build_shadow(source, identity=identity, model_cache=config.model_cache, cancelled=cancelled)
                    result.update(summarize(source, batch), **times)
                    check_cancel(cancelled)
                    # Serialize against the existing document lock, then recheck
                    # current lifecycle/version before any sidecar publication.
                    repo = capture_source(db.connection(), source)
                    current = repo._document_lock(source.document_id)
                    if current['version'] != source.version or current['status'] != 'ready' or current['processing_status'] != 'completed':
                        raise ShadowRefusal('SOURCE_CHANGED_DURING_SHADOW')
                    if current.get('website_id') is not None:
                        from sqlalchemy import text
                        active = db.execute(text('SELECT active_crawl_id FROM websites WHERE id=:id AND organization_id=:org AND bot_id=:bot'),
                            {'id':current['website_id'],'org':organization_id,'bot':bot_id}).scalar()
                        if active != current['crawl_id']:
                            raise ShadowRefusal('SOURCE_NOT_ACTIVE_CRAWL')
                    check_cancel(cancelled)
                    result['build_fingerprint'] = persist_graph(db.connection(), source, batch)
                    result.update(status='validated', completed_at=now())
                    # Graph + completed telemetry commit together; no orphan success.
                    _audit_result(db, job_id, organization_id, bot_id, key, result)
                except Exception as exc:
                    db.rollback()
                    code = failure_category(exc)
                    result.update(status='cancelled' if code in {'CANCELLED','DoclingAdapterError:CANCELLED'} else 'failed',
                                  failure_category=code, completed_at=now())
                    _audit_result(db, job_id, organization_id, bot_id, key, result)
    except Exception:
        # Storage outages leave the durable pending manifest for redelivery.
        # Never log raw source/DSN/errors or call legacy failure cleanup.
        log.error('structural_shadow_audit_unavailable org=%s bot=%s', organization_id, bot_id)
