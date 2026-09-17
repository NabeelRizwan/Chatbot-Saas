"""Internal synthetic mechanics CLI. No HTTP route, provider or application DB.

All commands use a newly created in-memory SQLite test database and dispose it.
FTS lists are explicitly injected rank fixtures, NOT an emulation of PostgreSQL.
Real PostgreSQL validation requires separate explicit target authorization.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, event, insert, select, func
from database import canary_schema as schema
from services.canary_contracts import (Approval, Manifest, Policy, SYNTHETIC_PROFILE,
    Lane, State, route, synthetic_vector)
from services.canary_representation import source_pin, primary_routes
from services.canary_repository import CanaryRepository
from services.canary_retrieval import Hit, run_query
from services.structural_chunking import serialize_structural_document, digest
from services.structural_retrieval_entries import RetrievalEntryScope
from services import structural_retrieval_entries_v2 as m
from services.retrieval_contracts import HardKnowledgeScope
from scripts.evaluate_structural_text_adapter import parse_source

GOLD = Path(__file__).resolve().parents[1] / 'fixtures/canary_mechanics_v1/gold.json'
NOW = 1_800_000_000


def approval(org=70001,bot=70002):
    return Approval(environment='offline_test',database_identity=digest('canary-sqlite-memory-only'),
        ownership_marker='stage-a-synthetic-owned',operator_reference='stage-a-local-test',
        organization_id=org,bot_id=bot,created_at=NOW-1,expires_at=NOW+3600)


def fixture_batch(text=None, document_id=1):
    source=text if text is not None else json.loads(GOLD.read_text(encoding='utf-8'))['source']
    evidence=serialize_structural_document(parse_source(source,document_id=document_id))
    return m.build_retrieval_entries(evidence,scope=RetrievalEntryScope(revision=evidence.source_graph.revision.identity))


def make_manifest(pins, *, run='mechanical-run', lane=Lane.STRUCTURAL_CANARY, generation='generation-1',
                  policy=None, approved=None):
    return Manifest(run_id=run,lane=lane,generation=generation,approval=approved or approval(),
        profile=SYNTHETIC_PROFILE,policy=policy or Policy(),documents=tuple(pins),
        implementation_hash=m._implementation_hash(),query_contract_hash=digest('synthetic-query-contract-v1'),
        evaluation_hash=hashlib.sha256(GOLD.read_bytes()).hexdigest())


def hard_scope(manifest, ids=None):
    return HardKnowledgeScope(organization_id=manifest.approval.organization_id,bot_id=manifest.approval.bot_id,
        authorized_document_ids=ids,embedding_profile=manifest.profile.hard_identity())


@contextmanager
def offline_repository(approved=None):
    approved=approved or approval()
    engine=create_engine('sqlite+pysqlite:///:memory:')
    @event.listens_for(engine,'connect')
    def enforce_foreign_keys(dbapi, _):
        dbapi.execute('PRAGMA foreign_keys=ON')
    try:
        schema.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(insert(schema.marker).values(database_identity=approved.database_identity,
                marker=approved.ownership_marker,environment=approved.environment))
            yield CanaryRepository(connection,approved,clock=lambda:NOW)
    finally:
        engine.dispose()


def lexical_rank_fixture(batch,manifest):
    routes=primary_routes(batch); pin=manifest.documents[0]
    return tuple(Hit(route(manifest,pin,*routes[a.atom_key]),a.atom_key,i,1/i,
        tuple(e.entry_key for e in batch.make_index().entries_for_atom(a.atom_key,scope=batch.scope)))
        for i,a in enumerate(batch.atoms[:manifest.policy.candidate_limit],1))


def compare_mechanical_lanes():
    start=perf_counter(); batch=fixture_batch()
    with offline_repository() as repo:
        pin=repo.register_fixture_source(batch,source_id=1)
        structural=make_manifest((pin,))
        chunks=[dict(id=i,text=p.text,source_part=p.model_dump(mode='json')) for i,p in enumerate(batch.evidence.chunks,1)]
        legacy_pin=pin.model_copy(update={'entries':(), 'legacy_members':tuple(c['id'] for c in chunks),
            'batch_hash':digest(chunks)})
        legacy=make_manifest((legacy_pin,),lane=Lane.LEGACY_CONTROL)
        t=perf_counter()
        repo.create(structural,now=NOW); repo.create(legacy,now=NOW)
        repo.stage(structural,batch,now=NOW); repo.stage_legacy(legacy,legacy_pin,chunks,now=NOW)
        repo.transition(structural,State.INDEX_READY,now=NOW)
        repo.transition(structural,State.COMPARATIVE_EVAL,now=NOW)
        staging_ms=(perf_counter()-t)*1000
        query='Mechanical rank and exact-evidence test'; vector=synthetic_vector(query)
        sh=lexical_rank_fixture(batch,structural)
        lh=tuple(Hit(route(legacy,legacy_pin,'LEGACY_CHUNK',c['id']),str(c['id']),i,1/i)
            for i,c in enumerate(chunks[:legacy.policy.candidate_limit],1))
        traces={}
        for name,manifest,hits in (('structural',structural,sh),('legacy',legacy,lh)):
            traces[name]=run_query(repo,manifest,hard_scope(manifest),query=query,query_vector=vector,now=NOW,
                                   fts_call=lambda rows=hits:rows)
            traces[name]['lexical_backend']='INJECTED_RANK_FIXTURE_NOT_POSTGRESQL_FTS'
        # Unchanged serving formula reference is separate from symmetric reservations.
        from services.hybrid_retrieval import weighted_rrf, HybridConfig, ChannelCandidate
        reference=weighted_rrf(
            [ChannelCandidate(int(h['route']['key']),1,h['score'],h['rank'],'synthetic') for h in traces['legacy']['raw_dense']],
            [ChannelCandidate(int(h['route']['key']),1,h['score'],h['rank'],'rank_fixture') for h in traces['legacy']['raw_fts']],HybridConfig())
        counts=repo.counts(structural)
        repo.transition(structural,State.OFF,now=NOW)
        cleanup=repo.delete_run(structural)
        history=repo.conn.execute(select(func.count()).select_from(schema.sources)).scalar_one()
        return dict(measurement='SYNTHETIC_OFFLINE_MECHANICS_ONLY',postgresql='HOLD',
            manifests=2,counts=counts,staging_ms=staging_ms,traces=traces,
            serving_legacy_reference=[dict(chunk_id=r.chunk_id,score=r.score) for r in reference],
            cleanup=cleanup,remaining_run_rows=repo.counts(structural),source_history_retained=history,
            total_ms=(perf_counter()-start)*1000)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('prepare-fixtures','stage-synthetic','validate-index',
        'run-mechanical-query','compare-mechanical-lanes','expire-run','delete-run'))
    args=parser.parse_args()
    if args.command=='prepare-fixtures':
        batch=fixture_batch()
        result=dict(batch_hash=batch.canonical_hash(),entries=len(batch.entries),atoms=len(batch.atoms))
    elif args.command=='compare-mechanical-lanes':
        result=compare_mechanical_lanes()
    else:
        batch=fixture_batch()
        with offline_repository() as repo:
            pin=repo.register_fixture_source(batch,source_id=1)
            manifest=make_manifest((pin,))
            repo.create(manifest,now=NOW); repo.stage(manifest,batch,now=NOW)
            if args.command in ('validate-index','run-mechanical-query'):
                repo.transition(manifest,State.INDEX_READY,now=NOW)
            if args.command=='run-mechanical-query':
                repo.transition(manifest,State.CANARY_READ,now=NOW)
                result=run_query(repo,manifest,hard_scope(manifest),query='Mechanical fixture',
                    query_vector=synthetic_vector('Mechanical fixture'),now=NOW,
                    fts_call=lambda:lexical_rank_fixture(batch,manifest))
            elif args.command=='expire-run':
                repo.transition(manifest,State.EXPIRED,now=NOW)
                result={'state':'EXPIRED','counts':repo.counts(manifest)}
            elif args.command=='delete-run':
                repo.transition(manifest,State.OFF,now=NOW)
                result={'deleted':repo.delete_run(manifest),'remaining':repo.counts(manifest)}
            else:
                result={'state':repo._run(manifest)['state'],'counts':repo.counts(manifest)}
    result['command']=args.command
    result['storage']='DISPOSABLE_IN_MEMORY_SQLITE'
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))


if __name__=='__main__':
    main()
