"""One-shot mechanical fixture/observation job, not an application policy.

Normal upstream ingestion, prefix, tools and full medium graph; no forced calls.
All wrappers forward the identical request/result objects. Safety aborts use a
BaseException so upstream optional Exception fallbacks cannot retry a failed run.
"""
import asyncio
import base64
import copy
from contextlib import contextmanager
import gzip
import hashlib
import inspect
import json
import logging
import os
from pathlib import Path
import re
import time

PROJECT = '068a5695-2cf6-4c7f-89fc-3d24a225e4a5'
SOURCE = 'mechanical-dispatch-northbridge-v1'
MARKER = 'model-selected-dispatch-2026-09-22-v1'
QUESTION = 'What release phrase does the Northbridge Equipment Manual require for an emergency battery handoff?'
FACT = 'copper orchard at dusk'
FIXTURE = Path(__file__).with_name('model_selected_fixture.jsonl')


class StopRun(BaseException):
    pass


def require(condition, reason):
    if not condition:
        raise StopRun(reason)


def contains_fact(value):
    return FACT in json.dumps(value, ensure_ascii=True, default=str).lower()


class NoProvider:
    llm_name = 'preflight-no-provider'
    max_length = 32768

    async def async_chat(self, *args, **kwargs):
        raise StopRun('PREFLIGHT_ATTEMPTED_MODEL_ACCESS')

    async def async_completion(self, *args, **kwargs):
        raise StopRun('PREFLIGHT_ATTEMPTED_MODEL_ACCESS')

    def close(self):
        pass


async def prefix_probe(runtime, scope, direction, *, fetch=False):
    """Real storage and exact upstream tools, separate request-local caches."""
    from ragflow_derived.advanced import operation_for, exact_evidence
    from ragflow_derived.engine import CheckedEmbeddings
    from ragflow_derived.full_runtime import full_operation
    from ragflow_derived.model_runtime import model_operation, AuthorizedChatModel
    from ragflow_derived.upstream.advanced_rag.agentic_rag import RAGTools
    from ragflow_derived.upstream.advanced_rag.harness.action_session import run_nav_prefix, execute_tool
    engine = runtime.engine('a')
    op = operation_for(engine, scope)
    with full_operation(op), model_operation(scope):
        tools = RAGTools([scope.key], AuthorizedChatModel(NoProvider(), op.check),
            CheckedEmbeddings(engine.embedding, scope), kbs=op.catalog.knowledgebases(),
            doc_scope=[s.document_id for s in scope.sources], thinking_mode='medium',
            original_user_question=QUESTION, similarity_threshold=engine.config.similarity_threshold,
            vector_similarity_weight=engine.config.vector_weight, top_n=12,
            rerank_candidates_count=engine.config.candidates, top_k=engine.config.knn_top_k)
        op.tools = tools
        if fetch:
            result = await execute_tool(tools, 'list_chunks', {'doc_id': scope.source(SOURCE).document_id})
            messages, ids, outcomes = result.payload, result.evidence_ids, []
        else:
            messages, ids, outcomes, _ = await run_nav_prefix(tools, direction, 180)
        evidence = [exact_evidence(op, c) for c in tools.kbinfos.get('chunks', [])]
        op.check()
        return {'direction': direction, 'messages': messages, 'evidence_ids': ids,
                'outcomes': outcomes, 'evidence': [dict(e.citation(), text=e.text,
                    scope_key=e.scope_key, generation=e.generation) for e in evidence]}


def scope_check(rows, scope):
    for row in rows:
        ref = scope.source(row['source_id'])
        require(row['source_id'] == SOURCE and row['document_id'] == ref.document_id,
                'SOURCE_OR_DOCUMENT_MISMATCH')
        require(row['version'] == ref.version and row['generation'] == scope.generation
                and row['scope_key'] == scope.key, 'SCOPE_VERSION_MISMATCH')
        require(hashlib.sha256(row['text'].encode()).hexdigest() == row['text_sha256'],
                'SOURCE_HASH_MISMATCH')


class ObservedModel:
    def __init__(self, inner, report):
        self.inner, self.report = inner, report
        self.llm_name, self.max_length = inner.llm_name, inner.max_length
        self.stopped = False
        self.native_count = 0

    @property
    def last_usage(self):
        return self.inner.last_usage

    def gate(self):
        require(not self.stopped, 'RUN_ALREADY_STOPPED')
        require(self.inner.calls < 6, 'SIX_CALL_CEILING')

    async def invoke(self, kind, method, *args, **kwargs):
        self.gate()
        started = time.perf_counter()
        try:
            result = await method(*args, **kwargs)
        except Exception as exc:
            self.stopped = True
            self.report['provider_failure_class'] = type(exc).__name__
            raise StopRun('PROVIDER_FAILURE_NO_RETRY') from None
        self.report['events'].append({'kind': kind, 'call': self.inner.calls,
                                     'seconds': time.perf_counter() - started})
        return result

    async def async_chat(self, *args, **kwargs):
        # Before action evidence exists, no harness-supplied answer may appear.
        if not self.native_count:
            require(not contains_fact((args, kwargs)), 'ANSWER_IN_PRE_ACTION_PROMPT')
        return await self.invoke('text', self.inner.async_chat, *args, **kwargs)

    async def async_completion(self, messages, **kwargs):
        from ragflow_derived.model_runtime import _cache
        from ragflow_dev.gemini35_tools import history_contents
        self.gate()
        first = self.native_count == 0
        if first:
            self.report['initial_action_messages'] = copy.deepcopy(messages)
            self.report['initial_answer_present'] = contains_fact(messages)
            require(not self.report['initial_answer_present'], 'ANSWER_LEAKED_IN_ACTUAL_ACTION_CONTEXT')
        self.native_count += 1
        state = _cache.get()[2].get('native_tool_transport', {})
        # Build a disposable COPY using the frozen pure wire encoder. Never
        # replace/mutate the state or messages sent by the actual adapter.
        names = {t['function']['name'] for t in kwargs.get('tools', [])}
        _, contents = history_contents(messages, copy.deepcopy(state), names)
        records = state.get('calls', {})
        roundtrips = []
        for message in messages:
            cid = message.get('tool_call_id')
            if message.get('role') != 'tool' or cid not in records:
                continue
            record = records[cid]
            paired = any(p.function_response and p.function_response.name == record['name']
                         and p.function_response.id == record['provider_id']
                         and p.function_response.response == {'result': message['content']}
                         for c in contents for p in c.parts)
            preserved = any(c == record['content'] for c in contents)
            require(paired and preserved, 'WIRE_PAIR_OR_METADATA_MISMATCH')
            roundtrips.append({'id': cid, 'name': record['name'], 'paired': paired,
                'complete_provider_content_preserved': preserved,
                'provider_id_present': record['provider_id'] is not None,
                'signed_parts_present': any(bool(p.thought_signature) for p in record['content'].parts),
                'response_contains_fact': contains_fact(message['content'])})
        result = await self.invoke('native', self.inner.async_completion, messages, **kwargs)
        calls = result.choices[0].message.tool_calls or []
        self.report['actions'].append({'sequence': self.native_count, 'call': self.inner.calls,
            'roundtrips': roundtrips, 'returned': [{'id': c.id, 'name': c.function.name,
                'args': json.loads(c.function.arguments)} for c in calls],
            'content': result.choices[0].message.content})
        if first and not calls:
            self.stopped = True
            raise StopRun('NO_MODEL_SELECTED_TOOL_STOPPED')
        return result

    def close(self):
        self.inner.close()


@contextmanager
def dispatch_observation(report):
    """Isolated process wrappers; compiled graph still invokes original nodes."""
    from ragflow_derived.upstream.advanced_rag.harness import action_session as action
    parse, execute, terminal = action._parse_tool_calls, action.execute_tool, action._parse_terminal

    def parsed(message):
        result = parse(message)
        report['parsed'].append(copy.deepcopy(result))
        return result

    async def dispatched(tools, name, args):
        caller = inspect.currentframe().f_back.f_code.co_name
        result = await execute(tools, name, args)
        report['dispatches'].append({'caller': caller, 'name': name, 'args': copy.deepcopy(args),
            'status': result.status, 'reason': result.reason,
            'evidence_ids': list(result.evidence_ids), 'payload': copy.deepcopy(result.payload)})
        return result

    def ended(content, state):
        result = terminal(content, state)
        report['terminals'].append({'type': result[2], 'answer': result[1]})
        return result

    action._parse_tool_calls, action.execute_tool, action._parse_terminal = parsed, dispatched, ended
    try:
        yield
    finally:
        action._parse_tool_calls, action.execute_tool, action._parse_terminal = parse, execute, terminal


def acceptance(report, scope):
    result = report['result']
    scope_check(result['evidence'], scope)
    observation = result['trace']['observation']
    require(observation['dropped_events'] == 0, 'TRACE_OVERFLOW')
    candidates = [e for e in observation['events'] if e['kind'] == 'authorized_candidate']
    require(bool(candidates), 'NO_REAL_CANDIDATE_TRACE')
    for e in candidates:
        require(e['organization_id'] == scope.organization_id and e['bot_id'] == scope.bot_id
                and e['source_id'] == SOURCE and e['scope_key'] == scope.key
                and e['generation'] == scope.generation
                and e['document_id'] == scope.source(SOURCE).document_id
                and str(e['version']) == scope.source(SOURCE).version
                and e['ready_verified'] and e['text_hash_verified'], 'CANDIDATE_SCOPE_FAILURE')
    selected = [c for a in report['actions'] for c in a['returned']]
    recognized = [c for group in report['parsed'] for c in group]
    dispatches = [d for d in report['dispatches'] if d['caller'] == '_tool_node']
    roundtrips = [r for a in report['actions'] for r in a['roundtrips']]
    require(selected and all(any(c['id'] == p['id'] for p in recognized) for c in selected), 'TOOL_NOT_PARSED')
    require(any(d['evidence_ids'] and contains_fact(d['payload']) for d in dispatches), 'REAL_DISPATCH_MISSING_FACT')
    require(any(r['paired'] and r['complete_provider_content_preserved'] and r['response_contains_fact']
                for r in roundtrips), 'NO_GROUNDED_FUNCTION_RESPONSE_ROUNDTRIP')
    require(any(t['type'] == 'answer' and contains_fact(t['answer']) for t in report['terminals']), 'NO_GROUNDED_TERMINAL')
    require(contains_fact(result['answer']), 'FINAL_ANSWER_MISSING_FACT')
    cited = {int(n) for n in re.findall(r'\[ID:(\d+)\]', result['answer'])}
    answer_ids = {e['chunk_id'] for e in result['evidence'] if contains_fact(e['text'])}
    require(any(c['upstream_id'] in cited and c['chunk_id'] in answer_ids and not c['generated']
                for c in result['citation_pool']), 'FINAL_CITATION_NOT_ANSWER_SOURCE')
    report['authorized_candidate_count'] = len(candidates)
    report['acceptance'] = 'PASS'


def emit(report):
    raw = json.dumps(report, sort_keys=True, ensure_ascii=True, default=str).encode()
    packed = base64.b64encode(gzip.compress(raw)).decode()
    print('DISPATCH_SUMMARY ' + json.dumps({k: report[k] for k in
        ('stage', 'acceptance', 'failure', 'provider_calls', 'provider_failures', 'seconds') if k in report}), flush=True)
    pieces = [packed[i:i+16000] for i in range(0, len(packed), 16000)]
    for i, piece in enumerate(pieces):
        print('DISPATCH_ARTIFACT ' + json.dumps({'index': i, 'total': len(pieces),
            'sha256': hashlib.sha256(raw).hexdigest(), 'data': piece}), flush=True)


def main():
    from ragflow_dev.config import Settings
    from ragflow_dev.runtime import Runtime
    from ragflow_dev.app import Ingest, AdvancedQuery
    from ragflow_dev.authority import CONTROL_INDEX
    from ragflow_dev.chat import from_env
    settings = Settings.from_env()
    require(settings.project_id == PROJECT, 'WRONG_PROJECT')
    require(os.environ.get('RAGFLOW_DEV_DISPATCH_VALIDATION') == 'ONCE_SIX_CALLS', 'RUNNER_DISABLED')
    report = {'stage': 'preflight', 'acceptance': 'FAIL', 'events': [], 'actions': [], 'parsed': [],
              'dispatches': [], 'terminals': [], 'question': QUESTION, 'budget': 6, 'quality_sets': 'NOT RUN'}
    started = time.perf_counter()
    runtime = model = None
    try:
        runtime = Runtime(settings, chat_model=NoProvider())
        before = {t: runtime.authority.read(t)['_source'] for t in ('a', 'b')}
        require(SOURCE not in before['a']['sources'] and SOURCE not in before['b']['sources'], 'FIXTURE_ALREADY_EXISTS_NO_RETRY')
        # CREATE-only marker before new synthetic ingestion, no overwritten data.
        runtime.client.create(index=CONTROL_INDEX, id=MARKER,
            document={'state': 'started', 'budget': 6, 'source': SOURCE}, refresh='wait_for')
        content = FIXTURE.read_text(encoding='utf-8')
        report['fixture_sha256'] = hashlib.sha256(content.encode()).hexdigest()
        report['ingestion'] = runtime.ingest('a', Ingest(source_id=SOURCE, expected_version=0,
            kind='jsonl', title='Northbridge Equipment Manual', content=content))
        scope = runtime.artifact_scope(runtime.authority.active_scope('a'), [SOURCE])
        report['source'] = {'organization': scope.organization_id, 'bot': scope.bot_id,
            'generation': scope.generation, 'source': SOURCE, 'document': scope.source(SOURCE).document_id,
            'version': scope.source(SOURCE).version, 'scope_key': scope.key}
        probes = []
        for direction in (QUESTION, 'emergency battery handoff release phrase', 'Northbridge Equipment Manual'):
            probe = asyncio.run(prefix_probe(runtime, scope, direction))
            scope_check(probe['evidence'], scope)
            require(probe['evidence_ids'] and not contains_fact(probe), 'PREFLIGHT_NAVIGATION_ANSWER_LEAK_OR_EMPTY')
            probes.append(probe)
        report['preflight_prefixes'] = probes
        reachable = asyncio.run(prefix_probe(runtime, scope, QUESTION, fetch=True))
        scope_check(reachable['evidence'], scope)
        require(contains_fact(reachable['messages']), 'UNDERLYING_TOOL_CANNOT_REACH_FACT')
        report['preflight_underlying'] = reachable
        report['preflight'] = 'PASS_BEFORE_ANY_GEMINI_CALL'
        # Separate engine/op/caches in Runtime.advanced; preflight evidence is
        # NEVER inserted into the live graph, model prompts or model state.
        model = from_env(PROJECT)
        require(model is not None, 'DEV_CALLBACK_MISSING')
        model.max_calls = 6
        runtime.chat_model = ObservedModel(model, report)
        report['stage'] = 'one_medium_graph'
        with dispatch_observation(report):
            report['result'] = runtime.advanced('a', AdvancedQuery(query=QUESTION, mode='agentic',
                thinking_mode='medium', artifact_sources=[SOURCE], trace=True))
        acceptance(report, scope)
        report['stage'] = 'complete'
    except StopRun as exc:
        report['failure'] = str(exc)  # Only our static, non-secret reason codes.
    except Exception as exc:
        report['failure'] = type(exc).__name__  # No exception text or provider payload.
    finally:
        report['provider_calls'] = model.calls if model else 0
        report['provider_failures'] = model.failures if model else 0
        report['tokens'] = model.tokens if model else 0
        report['seconds'] = time.perf_counter() - started
        if runtime:
            try:
                after = {t: runtime.authority.read(t)['_source'] for t in ('a', 'b')}
                after['a']['sources'].pop(SOURCE, None)
                report['other_source_authority_unchanged'] = after == before
                if not report['other_source_authority_unchanged']:
                    report['acceptance'], report['failure'] = 'FAIL', 'OTHER_SOURCE_AUTHORITY_CHANGED'
            except Exception:
                report['acceptance'], report['failure'] = 'FAIL', 'FINAL_PRESERVATION_CHECK_FAILED'
            runtime.close()
        elif model:
            model.close()
        os.environ.pop('RAGFLOW_DEV_GEMINI_API_KEY', None)
        emit(report)


if __name__ == '__main__':
    logging.basicConfig(level=logging.ERROR)
    main()
