"""Frozen real-corpus benchmark runner; no gold inputs or retrieval modifications.

Imports the original chunk text/order without parsing or editing it. This is a
test data adapter, not an application ingestion path. Only the new test index
and its create-only authority marker are writable.
"""
import asyncio
import base64
import copy
from dataclasses import asdict
import gzip
import hashlib
import json
import logging
import os
from pathlib import Path
import time

from answer_quality_once import (AnswerObserver, NoProvider, StopRun, dispatch_observation,
    evidence_json, normal_answer, require, verify_files)

PROJECT = '068a5695-2cf6-4c7f-89fc-3d24a225e4a5'
MARKER = 'real90-hardest15-20260922-v1'
HERE = Path(__file__).resolve().parent
SPEC = HERE / 'real90_hardest15_execution.json'
CORPUS = HERE / 'real90_original_chunks.json'
FREEZE = HERE / 'real90_hardest15_freeze.json'


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def load_inputs():
    spec = json.loads(SPEC.read_text(encoding='utf-8'))
    envelope = json.loads(CORPUS.read_text(encoding='utf-8'))
    raw = gzip.decompress(base64.b64decode(envelope['data'], validate=True))
    require(digest(raw) == envelope['sha256'], 'CORPUS_DIGEST_MISMATCH')
    corpus = json.loads(raw)
    require(len(spec['questions']) == 15 and len({q['id'] for q in spec['questions']}) == 15,
            'QUESTION_INVENTORY_CHANGED')
    require(set(spec) == {'name', 'selection_sha256', 'organization', 'bot', 'generation', 'questions'},
            'EXECUTION_FIELDS_NOT_ALLOWLISTED')
    for q in spec['questions']:
        require(set(q) == {'id', 'question', 'mode', 'history'}, 'GOLD_IN_EXECUTION_INPUT')
        require(q['mode'] in ('normal', 'agentic_high'), 'INVALID_FROZEN_MODE')
        require(q['mode'] != 'normal' or not q['history'], 'NORMAL_HISTORY_NOT_SUPPORTED')
    require(len(corpus['documents']) == envelope['documents'], 'DOCUMENT_COUNT_CHANGED')
    require(sum(len(d['chunks']) for d in corpus['documents']) == envelope['chunks'], 'CHUNK_COUNT_CHANGED')
    for doc in corpus['documents']:
        require(set(doc) == {'id', 'source', 'version', 'title', 'url', 'source_sha256', 'chunks'},
                'CORPUS_FIELDS_NOT_ALLOWLISTED')
        require(len({c['order'] for c in doc['chunks']}) == len(doc['chunks']), 'DUPLICATE_CHUNK_ORDER')
        for chunk in doc['chunks']:
            require(set(chunk) == {'id', 'order', 'text', 'sha256', 'headings'}, 'CHUNK_FIELDS_NOT_ALLOWLISTED')
            require(digest(chunk['text']) == chunk['sha256'], 'CHUNK_TEXT_CHANGED')
    return spec, corpus, envelope['sha256']


class Authority:
    def __init__(self, client, scope, corpus_digest):
        from ragflow_dev.authority import CONTROL_INDEX
        self.client, self.scope, self.index = client, scope, CONTROL_INDEX
        self.record = json.loads(json.dumps({'state': 'active', 'scope': asdict(scope),
            'corpus_sha256': corpus_digest, 'execution_sha256': digest(SPEC.read_bytes())}))
        require(not client.indices.exists(index=scope.index), 'NEW_TEST_INDEX_ALREADY_EXISTS')
        client.create(index=self.index, id=MARKER, document=self.record, refresh='wait_for')

    def authorized(self, scope):
        return scope == self.scope and self.client.get(index=self.index, id=MARKER)['_source'] == self.record

    def finish(self):
        current = self.client.get(index=self.index, id=MARKER)
        require(current['_source'] == self.record, 'AUTHORITY_CHANGED')
        self.client.index(index=self.index, id=MARKER, document=dict(self.record, state='closed_no_rerun'),
            if_seq_no=current['_seq_no'], if_primary_term=current['_primary_term'], refresh='wait_for')


def chunk_rows(engine, scope, doc):
    """Existing engine row representation, with saved exact chunks as input.

    Original chunk IDs/order/headings are provenance, not benchmark annotations.
    No parser, newly inferred relationship, gold, special product rule or content
    condensation is used. Tokenization/embedding are the frozen native models.
    """
    from ragflow_derived.contracts import safe_url
    source = scope.source(doc['source'])
    rows = []
    for chunk in doc['chunks']:
        text = chunk['text']
        require(digest(text) == chunk['sha256'], 'CHUNK_TEXT_CHANGED')
        row = {'id': digest(json.dumps([scope.key, source.key, chunk['order'], chunk['sha256']])),
            'kb_id': scope.bot_id, 'scope_key_kwd': scope.key, 'source_version_kwd': source.key,
            'source_id': source.source_id, 'doc_id': source.document_id, 'version_kwd': source.version,
            'generation_kwd': scope.generation, 'artifact_sha_kwd': doc['source_sha256'],
            'content_sha_kwd': chunk['sha256'], 'available_int': 1, 'docnm_kwd': doc['title'][:512],
            'url_kwd': safe_url(doc['url']), 'content_with_weight': text,
            'content_ltks': engine.tokenizer.tokenize(text),
            'title_tks': engine.tokenizer.tokenize(doc['title'][:512]),
            'chunk_order_int': chunk['order'], 'structure_kwd': json.dumps(chunk['headings']),
            'source_type_kwd': 'website', 'doc_type_kwd': 'text'}
        row['content_sm_ltks'] = engine.tokenizer.fine_grained_tokenize(row['content_ltks'])
        rows.append(row)
    return rows


def import_corpus(engine, scope, corpus):
    from ragflow_derived.engine import CheckedEmbeddings
    from ragflow_derived.upstream.embedding_utils import EmbeddingUtils
    store = engine._scope(scope)
    mapping = {}
    for doc in corpus['documents']:
        store.check()
        rows = chunk_rows(engine, scope, doc)
        checked = CheckedEmbeddings(engine.embedding, scope)
        titles, texts = EmbeddingUtils.prepare_texts_for_embedding(rows)
        cv, _ = checked.encode(texts)
        tv, _ = checked.encode(titles)
        combined = EmbeddingUtils.combine_title_content_vectors(tv, cv)
        checked._check(combined, len(rows))
        EmbeddingUtils.attach_vectors(rows, combined)
        source = scope.source(doc['source'])
        content_digest = digest(json.dumps(rows, sort_keys=True))
        engine.backend.claim_source(scope, source, content_digest)
        engine.backend.replace(scope, source, rows)
        store.check()
        for chunk, row in zip(doc['chunks'], rows):
            mapping[row['id']] = {'original_chunk_id': chunk['id'], 'document_id': doc['id'],
                'order': chunk['order'], 'sha256': chunk['sha256']}
        print('REAL90_IMPORT ' + json.dumps({'document_id': doc['id'], 'chunks': len(rows)}), flush=True)
    return mapping


def inventory(engine, scope):
    from ragflow_derived.upstream.doc_store import OrderByExpr
    store = engine._scope(scope)
    result = store.search(['*'], [], {}, [], OrderByExpr(), 0, 10000, [scope.index], [scope.bot_id])
    hits = result['hits']['hits']
    require(result['hits']['total']['value'] == len(hits), 'INVENTORY_OVERFLOW')
    rows = sorted((h['_id'], h['_source']) for h in hits)
    require(all(len(row.get('q_384_vec', [])) == scope.dimension for _, row in rows), 'MISSING_VECTOR')
    return {'chunks': len(rows), 'sha256': digest(json.dumps(rows, sort_keys=True))}


def traced_backend(client, trace, scope, authorized):
    from ragflow_dev.runtime import TracedBackend
    from ragflow_derived.storage import ScopedStore
    class CompleteBackend(TracedBackend):
        def search(self, *args, **kwargs):
            result = super().search(*args, **kwargs)
            # Passive, complete candidate ledger in addition to the frozen
            # runtime's bounded 4096-event observer. Never changes return data.
            validator = ScopedStore(self, scope, authorized)
            validator.check()
            ready = self.ready_sources(scope)
            for hit in result.get('hits', {}).get('hits', []):
                row = hit['_source']
                validator.validate_row(row, row.get('artifact_role_kwd') if row.get('available_int') == 0 else None)
                require(row['source_version_kwd'] in ready, 'CANDIDATE_NOT_READY')
            trace[-1]['scope_verified'] = True
            trace[-1]['query_conditions'] = copy.deepcopy(args[2])
            trace[-1]['candidate_count'] = len(result.get('hits', {}).get('hits', []))
            return result
    return CompleteBackend(client, trace)


def emit(kind, value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=True).encode()
    encoded = base64.b64encode(gzip.compress(raw)).decode()
    pieces = [encoded[i:i+12000] for i in range(0, len(encoded), 12000)]
    for i, piece in enumerate(pieces):
        print('REAL90_ARTIFACT ' + json.dumps({'kind': kind, 'index': i, 'total': len(pieces),
            'sha256': digest(raw), 'data': piece}), flush=True)


def main():
    from ragflow_dev.config import Settings, PROFILE, DIMENSION
    from ragflow_dev.runtime import Runtime
    from ragflow_dev.chat import from_env
    from ragflow_derived.contracts import AuthorizedScope, SourceRef
    from ragflow_derived.engine import RagFlowDerivedEngine, EngineConfig
    from ragflow_derived.observation import observation
    require(os.environ.get('RAILWAY_PROJECT_ID') == PROJECT, 'WRONG_PROJECT')
    require(os.environ.get('RAGFLOW_DEV_REAL90_VALIDATION') == 'ONCE_FROZEN_HARDEST15', 'RUNNER_DISABLED')
    report = {'stage': 'preflight', 'questions': []}
    runtime = authority = None
    try:
        freeze = json.loads(FREEZE.read_text())
        verify_files(HERE.parents[1], freeze)
        spec, corpus, corpus_digest = load_inputs()
        report.update(freeze=freeze, selection_sha256=spec['selection_sha256'], corpus_sha256=corpus_digest,
            deployment=os.environ.get('RAILWAY_DEPLOYMENT_ID'), commit=os.environ.get('RAILWAY_GIT_COMMIT_SHA'),
            config=asdict(EngineConfig()))
        runtime = Runtime(Settings.from_env(), chat_model=NoProvider())
        before = {t: runtime.authority.read(t)['_source'] for t in ('a', 'b')}
        scope = AuthorizedScope(spec['organization'], spec['bot'], spec['generation'], PROFILE, DIMENSION,
            tuple(SourceRef(d['source'], d['id'], d['version']) for d in corpus['documents']))
        report['scope'] = asdict(scope)
        authority = Authority(runtime.client, scope, corpus_digest)
        def engine_for(trace, model):
            return RagFlowDerivedEngine(traced_backend(runtime.client, trace['backend'], scope, authority.authorized),
                runtime.models.embedding, still_authorized=authority.authorized, synonyms=runtime.synonyms,
                reranker=runtime.models.traced_reranker(trace['reranker']), chat_model=model)
        engine = engine_for({'backend': [], 'reranker': []}, NoProvider())
        report['chunk_mapping'] = import_corpus(engine, scope, corpus)
        require(engine.backend.ready_sources(scope) == {s.key for s in scope.sources}, 'SOURCES_NOT_READY')
        report['inventory_before'] = inventory(engine, scope)
        require(report['inventory_before']['chunks'] == len(report['chunk_mapping']), 'CORPUS_COUNT_MISMATCH')
        emit('preflight', report)
        for q in spec['questions']:
            result = dict(q, calls=[], parsed=[], dispatches=[], terminals=[], answer='', normal_return=False)
            trace = {'backend': [], 'reranker': []}
            model = from_env(PROJECT)
            require(model is not None, 'DEV_CALLBACK_MISSING')
            model.max_calls = 1 if q['mode'] == 'normal' else 20
            engine = engine_for(trace, AnswerObserver(model, result, model.max_calls))
            started = time.perf_counter()
            report['stage'] = q['id']
            print('REAL90_START ' + json.dumps({'id': q['id'], 'mode': q['mode']}), flush=True)
            with observation() as observed:
                try:
                    if q['mode'] == 'normal':
                        asyncio.run(normal_answer(engine, scope, q['question'], result))
                    else:
                        with dispatch_observation(result):
                            raw = asyncio.run(engine.research(scope, q['question'], thinking_mode='high', messages=q['history']))
                        result.update(raw, evidence=[evidence_json(e) for e in raw['evidence']])
                        result['mode'], result['normal_return'] = q['mode'], True
                except StopRun as exc:
                    result['failure'] = str(exc)
                except Exception as exc:
                    result['failure'] = type(exc).__name__
                    if hasattr(exc, 'code'):
                        result['failure_code'], result['failure_stage'] = exc.code, exc.stage
                        if exc.code in ('UNAUTHORIZED_SCOPE', 'PROVENANCE_FAILED'):
                            raise StopRun('SECURITY_OR_PROVENANCE_FAILURE') from None
                finally:
                    result.update(seconds=time.perf_counter()-started, provider_calls=model.calls,
                        provider_failures=model.failures, tokens=model.tokens, trace=dict(trace, observation=observed))
                    model.close()
                require(all(e['scope_verified'] for e in trace['backend']), 'CANDIDATE_SCOPE_FAILURE')
                result['scope_validation'] = 'PASS'
                result['complete_candidate_count'] = sum(e['candidate_count'] for e in trace['backend'])
            emit(q['id'], result)
            report['questions'].append({k: result.get(k) for k in ('id', 'mode', 'seconds', 'provider_calls',
                'provider_failures', 'normal_return', 'failure', 'scope_validation', 'complete_candidate_count')})
            print('REAL90_DONE ' + json.dumps(report['questions'][-1]), flush=True)
        report['inventory_after'] = inventory(engine, scope)
        require(report['inventory_before'] == report['inventory_after'], 'CORPUS_CHANGED_DURING_ANSWERS')
        report['existing_authority_unchanged'] = before == {t: runtime.authority.read(t)['_source'] for t in ('a', 'b')}
        require(report['existing_authority_unchanged'], 'EXISTING_AUTHORITY_CHANGED')
        verify_files(HERE.parents[1], freeze)
        report['frozen_files_unchanged'], report['stage'] = True, 'complete'
    except StopRun as exc:
        report['failure'] = str(exc)
    except Exception as exc:
        report['failure'] = type(exc).__name__
    finally:
        if authority:
            try:
                authority.finish()
                report['authority_closed'] = True
            except (Exception, StopRun):
                report['authority_closed'] = False
        if runtime:
            runtime.close()
        os.environ.pop('RAGFLOW_DEV_GEMINI_API_KEY', None)
        emit('final', report)
        print('REAL90_FINAL ' + json.dumps({'stage': report['stage'], 'failure': report.get('failure'),
            'questions': len(report['questions']), 'authority_closed': report.get('authority_closed')}), flush=True)


if __name__ == '__main__':
    logging.basicConfig(level=logging.ERROR)
    main()
