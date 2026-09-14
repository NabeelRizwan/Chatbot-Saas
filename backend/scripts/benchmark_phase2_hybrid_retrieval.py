"""Deterministic *raw recall* comparison on an owned disposable PostgreSQL DB.

No provider, corpus, secret, configured DB or production access. JSON to stdout;
generated data exists only inside the owned container/schema. Run from backend:
python -B scripts/benchmark_phase2_hybrid_retrieval.py
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import statistics
import sys
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.phase2_disposable_postgres import (DisposableUnavailable, disposable_postgres,
                                               create_schema, deterministic_vector, migrate,
                                               application_import_boundary)


def seed(engine):
    from sqlalchemy import text
    documents, chunks, cases = [], [], []
    for org in range(1, 21):
        for page in range(1, 151):
            did = (org-1)*150+page
            title = f'Silver Package {page}'
            documents.append(dict(id=did, bot=org, org=org, title=title))
            for part in range(5):
                cid = (did-1)*5+part+1
                body = f'{title}. Common navigation pricing information. '
                body += f'catalog reference SKU{org:02}{page:03}. '
                body += ('refund ' + 'navigation '*25 + 'repeat.') if part < 4 else 'refund repeat policy. '
                axis = 2
                if page == 150 and part == 4:
                    body = ('Refund repeat policy. Refund repeat policy. Results may vary over weeks. '
                            'Pricing target pricing target. Silver capsules priced $33. Free shipping over $60. '
                            f'COA EPA SKU{org:02}{page:03}.')
                    axis = 0
                if page == 149 and part == 4:
                    body = 'Regain account credentials using recovery instructions.'
                    axis = 1
                chunks.append(dict(id=cid, did=did, bot=org, org=org, body=body, vec=deterministic_vector(axis), part=part))
        target = ((org-1)*150+150-1)*5+5
        semantic = target-5
        ids = list(range((org-1)*150+1, org*150+1))
        for query, gold, axis, category in [
            ('refund repeat', {target}, 0, 'deep'),
            (f'"COA EPA" SKU{org:02}150', {target}, 0, 'exact'),
            ('pricing target', {target}, 2, 'lexical_only'),
            ('restore login', {semantic}, 1, 'dense_only'),
            ('33 60', {target}, 0, 'numeric'),
            ('result week', {target}, 0, 'morphology'),
        ]:
            cases.append(dict(org=org, bot=org, query=query, gold=gold, axis=axis, category=category, ids=ids))
    with engine.begin() as conn:
        conn.execute(text('INSERT INTO documents (id,bot_id,organization_id,title,filename) VALUES (:id,:bot,:org,:title,:title)'), documents)
        conn.execute(text('INSERT INTO chunks (id,document_id,bot_id,organization_id,content,embedding,chunk_index) VALUES (:id,:did,:bot,:org,:body,CAST(:vec AS vector),:part)'), chunks)
        # Exact existing baseline vector index: no changed operator/options.
        conn.exec_driver_sql('CREATE INDEX ix_chunks_embedding_cosine ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)')
        conn.exec_driver_sql('ANALYZE chunks')
        conn.exec_driver_sql('ANALYZE documents')
    return cases


def summarize_plan(plan):
    nodes = []
    def visit(node):
        nodes.append({k: node[k] for k in ('Node Type', 'Index Name', 'Actual Rows', 'Actual Loops',
                     'Rows Removed by Filter', 'Rows Removed by Index Recheck', 'Sort Key',
                     'Shared Hit Blocks', 'Shared Read Blocks') if k in node})
        for child in node.get('Plans', []):
            visit(child)
    visit(plan[0]['Plan'])
    return dict(nodes=nodes, planning_ms=plan[0].get('Planning Time'), execution_ms=plan[0].get('Execution Time'))


def plans(engine, sessions, profile, case):
    from database.models import Chunk, Document
    from services.knowledge_scope import ready_chunks
    from services.postgres_fts import fts_statement
    results = {}
    with sessions() as db:
        fts = fts_statement(db, case['query'], case['bot'], case['org'], case['ids'], profile, 48)
        distance = Chunk.embedding.cosine_distance(json.loads(deterministic_vector(case['axis']))).label('distance')
        dense = ready_chunks(db.query(Chunk.id, Document.id, distance).join(Document, Chunk.document_id == Document.id),
                             case['bot'], case['org'], case['ids']).filter(
            Chunk.embedding_provider == profile.provider, Chunk.embedding_model == profile.model,
            Chunk.embedding_version == profile.version).order_by(distance, Document.id, Chunk.id).limit(48).statement
        for name, statement, forced in [('fts_natural', fts, False), ('fts_index_capability_forced', fts, True), ('dense_natural', dense, False)]:
            compiled = statement.compile(engine, compile_kwargs={'render_postcompile': True})
            # SQLAlchemy bind processors (notably pgvector) normally run inside
            # execute. Prefixing the compiled SQL still needs those processors.
            params = {key: compiled._bind_processors[key](value) if key in compiled._bind_processors else value
                      for key, value in compiled.params.items()}
            with engine.begin() as conn:
                if forced:
                    conn.exec_driver_sql('SET LOCAL enable_seqscan = off')
                result = conn.exec_driver_sql('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + str(compiled), params).scalar()
            results[name] = summarize_plan(result)
    return results


def benchmark(engine):
    from sqlalchemy.orm import sessionmaker
    from services import rag_service as rag
    from services.postgres_fts import fts_candidates
    from services.hybrid_retrieval import ChannelCandidate, HybridConfig, weighted_rrf
    cases = seed(engine)
    migrate(engine)
    sessions = sessionmaker(bind=engine)
    profile = SimpleNamespace(provider='fixture', model='fixture', version=1, dimensions=768)
    totals = {key: dict(recall10=[], recall48=[], mrr=[], milliseconds=[]) for key in
              ('legacy_lexical', 'postgres_fts', 'dense_only', 'fts_only', 'dense_fts_rrf')}
    rescue = dict(exact=0, deep=0, lexical_only=0, dense_only=0)
    fts_times, fusion_times, violations = [], [], 0
    with patch.object(rag, 'SessionLocal', sessions), patch.dict(os.environ, {'RAG_LEXICAL_BACKEND': 'postgres_fts'}):
        for case in cases:
            limit = 48
            started = perf_counter()
            legacy = rag._lexical_candidate_ids(case['bot'], case['org'], case['query'].lower().split(), limit, case['ids'])
            legacy_ms = (perf_counter()-started)*1000
            started = perf_counter()
            dense = rag._vector_candidate_ids(case['bot'], case['org'], json.loads(deterministic_vector(case['axis'])), limit, profile, case['ids'])
            dense_ms = (perf_counter()-started)*1000
            started = perf_counter()
            fts = fts_candidates(sessions, case['query'], case['bot'], case['org'], case['ids'], profile, limit)
            fts_ms = (perf_counter()-started)*1000
            started = perf_counter()
            fused = weighted_rrf([ChannelCandidate(cid, did, distance, rank, 'dense')
                                  for rank, (cid, did, distance) in enumerate(dense, 1)], fts.candidates, HybridConfig(lexical_backend='postgres_fts'))
            fusion_ms = (perf_counter()-started)*1000
            fts_times.append(fts_ms)
            fusion_times.append(fusion_ms)
            results = {
                'legacy_lexical': (legacy, legacy_ms),
                'postgres_fts': ([(c.chunk_id, c.document_id) for c in fts.candidates], fts_ms),
                'dense_only': ([(cid, did) for cid, did, _ in dense], dense_ms),
                'fts_only': ([(c.chunk_id, c.document_id) for c in fts.candidates], fts_ms),
                # Measured serial diagnostic, not invented concurrent timing.
                'dense_fts_rrf': ([(c.chunk_id, c.document_id) for c in fused[:limit]], dense_ms+fts_ms+fusion_ms),
            }
            for key, (rows, duration) in results.items():
                ids = [row[0] for row in rows]
                violations += sum(did not in case['ids'] for _, did in rows)
                totals[key]['recall10'].append(len(case['gold'] & set(ids[:10]))/len(case['gold']))
                totals[key]['recall48'].append(len(case['gold'] & set(ids[:48]))/len(case['gold']))
                totals[key]['mrr'].append(next((1/r for r, cid in enumerate(ids, 1) if cid in case['gold']), 0))
                totals[key]['milliseconds'].append(duration)
            hybrid_ids = {cid for cid, _ in results['dense_fts_rrf'][0]}
            comparison = 'postgres_fts' if case['category'] == 'dense_only' else 'dense_only' if case['category'] == 'lexical_only' else 'legacy_lexical'
            if case['category'] in rescue and case['gold'] & hybrid_ids and not case['gold'] & {cid for cid, _ in results[comparison][0]}:
                rescue[case['category']] += 1
    summary = {}
    for key, values in totals.items():
        timings = sorted(values['milliseconds'])
        summary[key] = {'Recall@10': statistics.mean(values['recall10']), 'Recall@48': statistics.mean(values['recall48']),
                        'MRR': statistics.mean(values['mrr']), 'p50_ms': statistics.median(timings),
                        'p95_ms': timings[min(len(timings)-1, int(len(timings)*.95))]}
    return dict(shape=dict(organizations=20, bots=20, documents=3000, chunks=15000, queries=len(cases)),
                metrics=summary, rescue_counts=rescue, tenant_isolation_violations=violations,
                mean_fts_ms=statistics.mean(fts_times), mean_fusion_ms=statistics.mean(fusion_times),
                timing_note='Hybrid total is measured serial channel time plus fusion, not production/concurrent latency.',
                plans=plans(engine, sessions, profile, cases[1]))


def main():
    try:
        with disposable_postgres() as engine, application_import_boundary(engine):
            from database import connection
            with ExitStack() as stack:
                stack.enter_context(patch.object(connection.engine, 'connect', side_effect=AssertionError('Configured DB forbidden')))
                stack.enter_context(patch('services.rag_service.generate_embedding', side_effect=AssertionError('Embedding API forbidden')))
                stack.enter_context(patch('services.rag_planning.generate_auxiliary', side_effect=AssertionError('Planner API forbidden')))
                stack.enter_context(patch('services.rag_service.generate', side_effect=AssertionError('Generation API forbidden')))
                stack.enter_context(patch('httpx.Client.send', side_effect=AssertionError('Live HTTP forbidden')))
                create_schema(engine)
                result = benchmark(engine)
                print(json.dumps(result, indent=2))
                return 1 if result['tenant_isolation_violations'] else 0
    except DisposableUnavailable as exc:
        print('PostgreSQL plans/benchmark BLOCKED: ' + str(exc))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
