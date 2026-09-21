"""One authorized eight-call follow-up; existing fixture and runtime stay frozen."""
import asyncio
import copy
import hashlib
from importlib.metadata import version
import inspect
import json
import logging
import os
from pathlib import Path
import re
import time
import model_selected_dispatch as prior

MARKER = 'model-selected-dispatch-terminal-2026-09-22-v2'
FREEZE = Path(__file__).with_name('dispatch_terminal_freeze.json')


def verify_files(root, freeze):
    for name, digest in freeze['file_hashes'].items():
        prior.require(hashlib.sha256((root / name).read_bytes()).hexdigest() == digest,
                      'FROZEN_SOURCE_HASH_MISMATCH')
    prior.require(prior.QUESTION.encode() == freeze['question'].encode(), 'QUESTION_BYTES_CHANGED')
    prior.require(hashlib.sha256(prior.FIXTURE.read_text(encoding='utf-8').encode()).hexdigest()
                  == freeze['fixture_sha256'], 'FIXTURE_HASH_CHANGED')
    prior.require(version('google-genai') == '1.55.0', 'SDK_VERSION_CHANGED')


def verify_originals(rows, freeze):
    # Scores/excerpts are not source identity. Compare complete original records
    # saved by the six-call run, including exact bytes, IDs, metadata and hashes.
    expected = {e['chunk_id']: e for e in freeze['original_evidence']}
    actual = {e['chunk_id']: e for e in rows}
    prior.require(len(actual) == len(rows) and actual == expected, 'ORIGINAL_FIXTURE_RECORDS_CHANGED')


def stored_digest(runtime, scope):
    """Read-only, exactly scoped seven-row inventory including existing vectors."""
    from ragflow_derived.storage import ScopedStore
    from ragflow_derived.upstream.doc_store import OrderByExpr
    store = ScopedStore(runtime.backend, scope, lambda s: runtime.authority.authorized('a', s))
    result = store.search(['*'], [], {}, [], OrderByExpr(), 0, 8, [scope.index], [scope.bot_id])
    hits = result['hits']['hits']
    prior.require(result['hits']['total']['value'] == 7 and len(hits) == 7, 'FIXTURE_ROW_COUNT_CHANGED')
    rows = sorted((h['_id'], h['_source']) for h in hits)
    prior.require(all(len(row.get('q_384_vec', [])) == 384 for _, row in rows), 'FIXTURE_VECTOR_INVENTORY_CHANGED')
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def workflow_snapshot():
    """Names and explicit non-secret graph fields only; never dump frame locals."""
    result = {'upstream_frames': [], 'graph_state': {}}
    frame = inspect.currentframe().f_back
    try:
        while frame:
            name = frame.f_code.co_filename.replace('\\', '/')
            if '/ragflow_derived/upstream/advanced_rag/' in name:
                result['upstream_frames'].append({'file': Path(name).name,
                    'function': frame.f_code.co_name, 'line': frame.f_lineno})
                state = frame.f_locals.get('state')
                if isinstance(state, dict):
                    for key in ('draft', 'slot_draft', 'verdict', 'unresolved_slots',
                                'search_rounds', 'current_queries', 'collected_answer'):
                        if key in state and key not in result['graph_state']:
                            result['graph_state'][key] = copy.deepcopy(state[key])
                    table = state.get('slot_table')
                    if table is not None and callable(getattr(table, 'render_slots', None)):
                        result['graph_state']['slots'] = table.render_slots()
            frame = frame.f_back
    finally:
        del frame
    return result


class EightCallObservation(prior.ObservedModel):
    """Same forwarding/stop rules. Only callback ceiling changes from six to eight."""
    def __init__(self, inner, report):
        super().__init__(inner, report)
        self.started_calls = 0

    def save_observation(self):
        from ragflow_derived.observation import _current
        current = _current.get()
        if current is not None:
            self.report['last_live_observation'] = copy.deepcopy(current)

    def gate(self):
        prior.require(not self.stopped, 'RUN_ALREADY_STOPPED')
        if self.inner.calls >= 8:
            self.report['ceiling_stop'] = workflow_snapshot()
            self.save_observation()
            raise prior.StopRun('EIGHT_CALL_CEILING')

    async def invoke(self, kind, method, *args, **kwargs):
        self.gate()
        self.started_calls += 1
        event = {'ordinal': self.started_calls, 'kind': kind,
                 'entry': workflow_snapshot()}
        self.report.setdefault('ordered_calls', []).append(event)
        try:
            result = await super().invoke(kind, method, *args, **kwargs)
            event['completed'] = True
            if kind == 'text':
                event['text'] = result
            else:
                msg = result.choices[0].message
                event['content'] = msg.content
                event['selected'] = [{'id': c.id, 'name': c.function.name,
                    'args': json.loads(c.function.arguments)} for c in msg.tool_calls or []]
            return result
        finally:
            self.save_observation()


def validate_terminal(report, scope, freeze):
    """Outer graph return/final citations, not an inner session's XML tag choice."""
    result = report['result']
    prior.require(report.get('normal_graph_return') is True, 'NO_NORMAL_GRAPH_RETURN')
    prior.require(report.get('initial_answer_present') is False, 'INITIAL_ANSWER_LEAK')
    prior.scope_check(result['evidence'], scope)
    originals = {r['chunk_id']: r for r in freeze['original_evidence']}
    for e in result['evidence']:
        original = originals.get(e['chunk_id'])
        prior.require(original and all(e[k] == v for k, v in original.items()), 'FINAL_ORIGINAL_PROVENANCE_CHANGED')
    obs = result['trace']['observation']
    candidates = [e for e in obs['events'] if e['kind'] == 'authorized_candidate']
    prior.require(candidates and obs['dropped_events'] == 0, 'CANDIDATE_TRACE_MISSING')
    for e in candidates:
        r = originals.get(e['chunk_id'])
        prior.require(r and e['organization_id'] == scope.organization_id and e['bot_id'] == scope.bot_id
            and e['scope_key'] == scope.key and e['generation'] == scope.generation
            and e['source_id'] == r['source_id'] and e['document_id'] == r['document_id']
            and str(e['version']) == r['version'] and e['text_sha256'] == r['text_sha256']
            and e['ready_verified'] and e['text_hash_verified'], 'CANDIDATE_SCOPE_FAILURE')
    selected = [c for a in report['actions'] for c in a['returned']]
    parsed = [c for group in report['parsed'] for c in group]
    prior.require(selected and all(any(p['id'] == c['id'] and p['name'] == c['name'] for p in parsed)
                                  for c in selected), 'MODEL_SELECTION_NOT_PARSED')
    dispatches = [d for d in report['dispatches'] if d['caller'] == '_tool_node']
    prior.require(any(d['evidence_ids'] and prior.contains_fact(d['payload']) for d in dispatches),
                  'ACTUAL_TOOL_DID_NOT_RETURN_FACT')
    roundtrips = [r for a in report['actions'] for r in a['roundtrips']]
    prior.require(any(r['paired'] and r['complete_provider_content_preserved'] and r['response_contains_fact']
                      for r in roundtrips), 'MISSING_FUNCTION_RESPONSE_CONTINUATION')
    prior.require(prior.contains_fact(result['answer']), 'FINAL_ANSWER_MISSING_FACT')
    cites = {int(n) for n in re.findall(r'\[ID:(\d+)\]', result['answer'])}
    answer_ids = {r['chunk_id'] for r in result['evidence'] if prior.contains_fact(r['text'])}
    prior.require(any(c['upstream_id'] in cites and c['chunk_id'] in answer_ids and not c['generated']
                      for c in result['citation_pool']), 'FINAL_CITATION_NOT_ANSWER_SOURCE')
    report['authorized_candidate_count'] = len(candidates)
    report['acceptance'] = 'PASS'


def main():
    from ragflow_dev.config import Settings
    from ragflow_dev.runtime import Runtime
    from ragflow_dev.app import AdvancedQuery
    from ragflow_dev.authority import CONTROL_INDEX
    from ragflow_dev.chat import from_env
    settings = Settings.from_env()
    prior.require(settings.project_id == prior.PROJECT, 'WRONG_PROJECT')
    prior.require(os.environ.get('RAGFLOW_DEV_TERMINAL_VALIDATION') == 'ONCE_EIGHT_CALLS', 'RUNNER_DISABLED')
    report = {'stage': 'integrity_preflight', 'acceptance': 'FAIL', 'events': [], 'actions': [],
        'parsed': [], 'dispatches': [], 'terminals': [], 'question': prior.QUESTION,
        'budget': 8, 'quality_sets': 'NOT RUN', 'new_execution_identity': MARKER}
    runtime = model = None
    started = time.perf_counter()
    try:
        freeze = json.loads(FREEZE.read_text(encoding='utf-8'))
        verify_files(Path(__file__).resolve().parents[2], freeze)
        report['frozen_files_verified'] = len(freeze['file_hashes'])
        report['previous_result_sha256'] = freeze['previous_result_sha256']
        runtime = Runtime(settings, chat_model=prior.NoProvider())
        before = {t: runtime.authority.read(t)['_source'] for t in ('a', 'b')}
        prior_marker = runtime.client.get(index=CONTROL_INDEX, id=prior.MARKER)['_source']
        prior.require(prior_marker == {'state': 'started', 'budget': 6, 'source': prior.SOURCE}, 'PRIOR_MARKER_CHANGED')
        scope = runtime.artifact_scope(runtime.authority.active_scope('a'), [prior.SOURCE])
        identity = {'organization': scope.organization_id, 'bot': scope.bot_id, 'generation': scope.generation,
            'source': prior.SOURCE, 'document': scope.source(prior.SOURCE).document_id,
            'version': scope.source(prior.SOURCE).version, 'scope_key': scope.key}
        prior.require(identity == freeze['source'], 'FIXTURE_IDENTITY_CHANGED')
        report['source'] = identity
        before_rows = stored_digest(runtime, scope)
        report['stored_rows_vectors_sha256_before'] = before_rows
        # New CREATE-only identity; the prior marker is not changed or deleted.
        runtime.client.create(index=CONTROL_INDEX, id=MARKER,
            document={'state': 'started', 'budget': 8, 'source': prior.SOURCE}, refresh='wait_for')
        probes = []
        for direction in (prior.QUESTION, 'emergency battery handoff release phrase', 'Northbridge Equipment Manual'):
            probe = asyncio.run(prior.prefix_probe(runtime, scope, direction))
            prior.scope_check(probe['evidence'], scope)
            prior.require(probe['evidence_ids'] and not prior.contains_fact(probe), 'PREFLIGHT_NAVIGATION_ANSWER_LEAK_OR_EMPTY')
            probes.append(probe)
        report['preflight_prefixes'] = probes
        reachable = asyncio.run(prior.prefix_probe(runtime, scope, prior.QUESTION, fetch=True))
        prior.scope_check(reachable['evidence'], scope)
        verify_originals(reachable['evidence'], freeze)
        prior.require(prior.contains_fact(reachable['messages']), 'UNDERLYING_TOOL_CANNOT_REACH_FACT')
        report['preflight_underlying'] = reachable
        report['preflight'] = 'PASS_BEFORE_ANY_GEMINI_CALL'
        model = from_env(prior.PROJECT)
        prior.require(model is not None, 'DEV_CALLBACK_MISSING')
        model.max_calls = 8
        runtime.chat_model = EightCallObservation(model, report)
        report['stage'] = 'one_medium_graph'
        with prior.dispatch_observation(report):
            report['result'] = runtime.advanced('a', AdvancedQuery(query=prior.QUESTION, mode='agentic',
                thinking_mode='medium', artifact_sources=[prior.SOURCE], trace=True))
        report['normal_graph_return'] = True
        validate_terminal(report, scope, freeze)
        report['stage'] = 'complete'
    except prior.StopRun as exc:
        report['failure'] = str(exc)
    except Exception as exc:
        report['failure'] = type(exc).__name__
    finally:
        report['provider_calls'] = model.calls if model else 0
        report['provider_failures'] = model.failures if model else 0
        report['tokens'] = model.tokens if model else 0
        report['seconds'] = time.perf_counter() - started
        if runtime:
            try:
                report['all_source_authority_unchanged'] = before == {t: runtime.authority.read(t)['_source'] for t in ('a', 'b')}
                report['prior_marker_unchanged'] = runtime.client.get(index=CONTROL_INDEX, id=prior.MARKER)['_source'] == prior_marker
                if 'before_rows' in locals():
                    report['stored_rows_vectors_sha256_after'] = stored_digest(runtime, scope)
                    report['fixture_rows_vectors_unchanged'] = report['stored_rows_vectors_sha256_after'] == before_rows
                prior.require(report['all_source_authority_unchanged'] and report['prior_marker_unchanged']
                    and report.get('fixture_rows_vectors_unchanged'), 'FINAL_PRESERVATION_CHECK_FAILED')
            except (Exception, prior.StopRun):
                report['acceptance'], report['preservation_failure'] = 'FAIL', 'FINAL_PRESERVATION_CHECK_FAILED'
            runtime.close()
        elif model:
            model.close()
        os.environ.pop('RAGFLOW_DEV_GEMINI_API_KEY', None)
        prior.emit(report)


if __name__ == '__main__':
    logging.basicConfig(level=logging.ERROR)
    main()
