"""Two new synthetic answer attempts; unchanged engine, graph and prompts.

No evaluation answers or quality assertions belong in this execution harness.
Only a new exact-scope test authority, safety ceilings and passive observations.
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
from types import SimpleNamespace

from model_selected_dispatch import StopRun, require, NoProvider, dispatch_observation
from dispatch_terminal_completion import workflow_snapshot

PROJECT = '068a5695-2cf6-4c7f-89fc-3d24a225e4a5'
MARKER = 'answer-quality-two-new-questions-2026-09-22-v1'
FIXTURE = Path(__file__).with_name('answer_quality_fixture.json')
FREEZE = Path(__file__).with_name('answer_quality_freeze.json')


def verify_files(root, freeze):
    for name, digest in freeze['file_hashes'].items():
        require(hashlib.sha256((root / name).read_bytes()).hexdigest() == digest,
                'FROZEN_FILE_CHANGED')


class ExactTestAuthority:
    """Test-only server-issued identity; never accepts caller/model scope data."""
    def __init__(self, client, scope, fixture_digest):
        from ragflow_dev.authority import CONTROL_INDEX
        self.client, self.scope, self.index = client, scope, CONTROL_INDEX
        self.record = {'state': 'active', 'scope': asdict(scope), 'fixture_sha256': fixture_digest}
        # JSON round-trip gives the same list representation ES returns.
        self.record = json.loads(json.dumps(self.record))
        require(not client.indices.exists(index=scope.index), 'NEW_TEST_INDEX_ALREADY_EXISTS')
        client.create(index=self.index, id=MARKER, document=self.record, refresh='wait_for')

    def authorized(self, scope):
        if scope != self.scope:
            return False
        return self.client.get(index=self.index, id=MARKER)['_source'] == self.record

    def finish(self):
        record = self.client.get(index=self.index, id=MARKER)
        require(record['_source'] == self.record, 'TEST_AUTHORITY_CHANGED')
        self.client.index(index=self.index, id=MARKER,
            document=dict(self.record, state='completed_no_rerun'),
            if_seq_no=record['_seq_no'], if_primary_term=record['_primary_term'], refresh='wait_for')


class AnswerObserver:
    """Forward identical calls/results. Do not require or inject a tool choice."""
    def __init__(self, inner, report, ceiling):
        self.inner, self.report, self.ceiling = inner, report, ceiling
        self.llm_name, self.max_length = inner.llm_name, inner.max_length
        self.started = 0
        self.stopped = False

    @property
    def last_usage(self):
        return self.inner.last_usage

    def snapshot_evidence(self):
        from ragflow_derived.full_runtime import _operation
        from ragflow_derived.advanced import exact_evidence
        op = _operation.get()
        if op is not None and op.tools is not None:
            chunks = op.tools.kbinfos.get('chunks', [])
            self.report['last_gathered_evidence'] = [evidence_json(exact_evidence(op, c)) for c in chunks]

    async def invoke(self, kind, method, *args, **kwargs):
        require(not self.stopped, 'RUN_ALREADY_STOPPED')
        if self.started >= self.ceiling:
            self.report['ceiling_stop'] = workflow_snapshot()
            self.snapshot_evidence()
            self.stopped = True
            raise StopRun('QUESTION_CALL_CEILING')
        # No await between checking and reserving: concurrent graph slots cannot
        # exceed this question's ceiling. Other questions have separate counters.
        self.started += 1
        event = {'ordinal': self.started, 'kind': kind, 'entry': workflow_snapshot()}
        self.report['calls'].append(event)
        if kind == 'text':
            event['system'] = args[0]
            event['history'] = copy.deepcopy(args[1])
        else:
            # Explicit message fields only. Never inspect provider transport
            # cache or serialize opaque Gemini Content/signature objects.
            event['messages'] = [{k: copy.deepcopy(m[k]) for k in
                ('role', 'content', 'tool_calls', 'tool_call_id', 'name') if k in m} for m in args[0]]
            event['tool_names'] = [t['function']['name'] for t in kwargs.get('tools') or []]
        started = time.perf_counter()
        try:
            result = await method(*args, **kwargs)
            if kind == 'text':
                event['output'] = result
            else:
                message = result.choices[0].message
                event['output'] = message.content
                event['selected'] = [{'id': c.id, 'name': c.function.name,
                    'arguments': json.loads(c.function.arguments)} for c in message.tool_calls or []]
            return result
        except Exception as exc:
            self.stopped = True
            event['failure_class'] = type(exc).__name__
            raise StopRun('PROVIDER_FAILURE_NO_RETRY') from None
        finally:
            event['seconds'] = time.perf_counter() - started
            self.snapshot_evidence()

    async def async_chat(self, *args, **kwargs):
        return await self.invoke('text', self.inner.async_chat, *args, **kwargs)

    async def async_completion(self, *args, **kwargs):
        return await self.invoke('native', self.inner.async_completion, *args, **kwargs)


def evidence_json(e):
    return dict(e.citation(), text=e.text, scope_key=e.scope_key, generation=e.generation,
        similarity=e.similarity, lexical_similarity=e.lexical_similarity,
        vector_or_model_similarity=e.vector_similarity, metadata=dict(e.metadata))


def validate_observation(observed, scope):
    require(observed['dropped_events'] == 0, 'TRACE_OVERFLOW')
    candidates = [e for e in observed['events'] if e['kind'] == 'authorized_candidate']
    for event in candidates:
        ref = scope.source(event['source_id'])
        require(event['organization_id'] == scope.organization_id and event['bot_id'] == scope.bot_id
            and event['scope_key'] == scope.key and event['generation'] == scope.generation
            and event['document_id'] == ref.document_id and event['version'] == ref.version
            and event['source_version_key'] == ref.key
            and event['ready_verified'] and event['text_hash_verified'], 'CANDIDATE_SCOPE_FAILURE')
    return len(candidates)


async def normal_answer(engine, scope, question, result):
    """Normal retrieval + context + existing synthesis helper, NO agent graph."""
    from ragflow_derived.model_runtime import AuthorizedChatModel, model_operation
    from ragflow_derived.upstream.advanced_rag.agentic_rag_graph import _compose_answer_from_evidence
    evidence = await engine.retrieve(scope, question)  # unchanged default top_k/options
    pack = engine.build_context(scope, evidence)
    result['retrieved'] = [evidence_json(e) for e in evidence]
    result['context'] = pack['context']
    result['evidence'] = [evidence_json(e) for e in pack['evidence']]
    chunks = [{'chunk_id': e.chunk_id, 'content_with_weight': e.text, 'docnm_kwd': e.title,
        'url': e.url, 'similarity': e.similarity} for e in pack['evidence']]
    queue = asyncio.Queue()
    store = engine._scope(scope)
    with model_operation(scope):
        tools = SimpleNamespace(chat_mdl=AuthorizedChatModel(engine.chat_model, store.check),
                                user_defined_prompts={}, system_prompt='', empty_response='')
        # Reuse the already-frozen final synthesis and citation prompts unchanged.
        # No formalization, fanout, navigation, action session or SCA executes.
        await _compose_answer_from_evidence({'question': question,
            'kbinfos': {'chunks': chunks, 'doc_aggs': []}}, tools, queue, {'temperature': 0.3})
    result['answer'] = ''.join(queue.get_nowait() for _ in range(queue.qsize()))
    result['normal_return'] = True
    store.check()


def inventory(engine, scope):
    from ragflow_derived.upstream.doc_store import OrderByExpr
    store = engine._scope(scope)
    result = store.search(['*'], [], {}, [], OrderByExpr(), 0, 1000, [scope.index], [scope.bot_id])
    hits = result['hits']['hits']
    require(result['hits']['total']['value'] == len(hits), 'INVENTORY_OVERFLOW')
    rows = sorted((h['_id'], h['_source']) for h in hits)
    require(all(len(row.get('q_384_vec', [])) == scope.dimension for _, row in rows), 'MISSING_VECTOR')
    return {'chunks': len(rows), 'sha256': hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()}


def emit(report):
    raw = json.dumps(report, sort_keys=True, ensure_ascii=True).encode()
    encoded = base64.b64encode(gzip.compress(raw)).decode()
    pieces = [encoded[i:i+12000] for i in range(0, len(encoded), 12000)]
    print('ANSWER_SUMMARY ' + json.dumps({'stage': report['stage'], 'failure': report.get('failure'),
        'questions': {k: {'calls': v.get('provider_calls'), 'normal_return': v.get('normal_return'),
            'failure': v.get('failure')} for k, v in report['questions'].items()}}), flush=True)
    for i, data in enumerate(pieces):
        print('ANSWER_ARTIFACT ' + json.dumps({'index': i, 'total': len(pieces),
            'sha256': hashlib.sha256(raw).hexdigest(), 'data': data}), flush=True)


def main():
    from ragflow_dev.config import Settings, PROFILE, DIMENSION
    from ragflow_dev.runtime import Runtime, TracedBackend
    from ragflow_dev.chat import from_env
    from ragflow_derived.contracts import AuthorizedScope, SourceRef
    from ragflow_derived.engine import RagFlowDerivedEngine
    from ragflow_derived.observation import observation
    settings = Settings.from_env()
    require(settings.project_id == PROJECT, 'WRONG_PROJECT')
    require(os.environ.get('RAGFLOW_DEV_ANSWER_VALIDATION') == 'ONCE_TWO_NEW_QUESTIONS', 'RUNNER_DISABLED')
    report = {'stage': 'preflight', 'questions': {}, 'other_quality_sets': 'NOT RUN'}
    runtime = authority = None
    try:
        freeze = json.loads(FREEZE.read_text(encoding='utf-8'))
        verify_files(Path(__file__).resolve().parents[2], freeze)
        report['freeze'] = freeze
        report['deployment'] = os.environ.get('RAILWAY_DEPLOYMENT_ID')
        report['commit'] = os.environ.get('RAILWAY_GIT_COMMIT_SHA')
        fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))
        runtime = Runtime(settings, chat_model=NoProvider())
        before = {t: runtime.authority.read(t)['_source'] for t in ('a', 'b')}
        scope = AuthorizedScope(fixture['organization'], fixture['bot'], fixture['generation'], PROFILE,
            DIMENSION, tuple(SourceRef(d['source'], 'doc-' + d['source'], '1') for d in fixture['documents']))
        report['scope'] = asdict(scope)
        authority = ExactTestAuthority(runtime.client, scope, hashlib.sha256(FIXTURE.read_bytes()).hexdigest())
        def engine_for(trace, model):
            return RagFlowDerivedEngine(TracedBackend(runtime.client, trace['backend']), runtime.models.embedding,
                still_authorized=authority.authorized, synonyms=runtime.synonyms,
                reranker=runtime.models.traced_reranker(trace['reranker']), chat_model=model)
        engine = engine_for({'backend': [], 'reranker': []}, NoProvider())
        report['ingestion'] = [engine.ingest(scope, d['source'], d['content'], kind='md', title=d['title'])
                               for d in fixture['documents']]
        require(engine.backend.ready_sources(scope) == {s.key for s in scope.sources}, 'SOURCES_NOT_READY')
        report['inventory_before'] = inventory(engine, scope)
        for mode, question in fixture['questions'].items():
            result = {'mode': mode, 'question': question, 'calls': [], 'parsed': [], 'dispatches': [],
                      'terminals': [], 'answer': '', 'normal_return': False}
            report['questions'][mode] = result
            trace = {'backend': [], 'reranker': []}
            model = from_env(PROJECT)
            require(model is not None, 'DEV_CALLBACK_MISSING')
            model.max_calls = 1 if mode == 'normal' else 20
            observed_model = AnswerObserver(model, result, model.max_calls)
            engine = engine_for(trace, observed_model)
            started = time.perf_counter()
            report['stage'] = mode
            with observation() as observed:
                try:
                    if mode == 'normal':
                        asyncio.run(normal_answer(engine, scope, question, result))
                    else:
                        with dispatch_observation(result):
                            raw = asyncio.run(engine.research(scope, question, thinking_mode='high'))
                        result.update(raw, evidence=[evidence_json(e) for e in raw['evidence']])
                        result['mode'] = 'agentic_high'
                        result['normal_return'] = True
                except StopRun as exc:
                    result['failure'] = str(exc)
                except Exception as exc:
                    result['failure'] = type(exc).__name__
                    if hasattr(exc, 'code'):
                        result['failure_code'], result['failure_stage'] = exc.code, exc.stage
                        if exc.code in ('UNAUTHORIZED_SCOPE', 'PROVENANCE_FAILED'):
                            raise StopRun('SECURITY_OR_PROVENANCE_FAILURE') from None
                finally:
                    result['seconds'] = time.perf_counter() - started
                    result['provider_calls'] = model.calls
                    result['provider_failures'] = model.failures
                    result['tokens'] = model.tokens
                    result['trace'] = dict(trace, observation=observed)
                    model.close()
                result['authorized_candidates'] = validate_observation(observed, scope)
                result['scope_validation'] = 'PASS'
            # Quality scoring occurs only after the job. Failure is not retried.
        report['inventory_after'] = inventory(engine, scope)
        require(report['inventory_before'] == report['inventory_after'], 'CORPUS_CHANGED_DURING_ANSWERS')
        report['existing_authority_unchanged'] = before == {t: runtime.authority.read(t)['_source'] for t in ('a', 'b')}
        require(report['existing_authority_unchanged'], 'EXISTING_AUTHORITY_CHANGED')
        verify_files(Path(__file__).resolve().parents[2], freeze)
        report['frozen_files_unchanged'] = True
        report['stage'] = 'complete'
    except StopRun as exc:
        report['failure'] = str(exc)
    except Exception as exc:
        report['failure'] = type(exc).__name__
    finally:
        if authority:
            try:
                authority.finish()
                report['new_test_authority_closed'] = True
            except (Exception, StopRun):
                report['new_test_authority_closed'] = False
        if runtime:
            runtime.close()
        os.environ.pop('RAGFLOW_DEV_GEMINI_API_KEY', None)
        emit(report)


if __name__ == '__main__':
    logging.basicConfig(level=logging.ERROR)
    main()
