"""Frozen, one-shot full-port development validation. Never a startup hook.

Run only inside the exact new Railway project. Secrets stay in its environment.
Evaluation expectations are consumed only AFTER a response; never by the engine.
"""
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from native_acceptance import Client, QUESTIONS, verify_pack
from expanded_acceptance import emit_expanded, validate_trace_observations

REPORT = {'mechanical': [], 'quality': [], 'security': [], 'provider_calls': 0,
          'old90_run': False, 'custom_quality_heuristics': 0}
URL = 'https://ragflow-dev-backend-production.up.railway.app'
ROOT = Path(__file__).resolve().parent
MECHANICAL = (
    '# Calibration Bureau\n\n'
    'The Calibration Bureau operates Beacon Laboratory. Beacon Laboratory calibrates sensors every seven days.\n\n'
    'Inspector Calder works for the Calibration Bureau. Calder reviews the calibration records every month.\n\n'
    'Before inspecting a sensor, disconnect its power cable and verify that the status lamp is dark.\n\n'
    'The laboratory maintains reference weights in a locked cabinet. Only trained inspectors may remove them.\n\n'
    'Record the sensor serial number and inspection date. Keep the signed record for two years.\n\n'
    'A damaged sensor is quarantined in a labelled box until the Calibration Bureau authorizes a repair.'
)


class BoundedClient(Client):
    def __init__(self, url, maximum_seconds=7200):
        if url != URL:
            raise RuntimeError('EXACT_DEVELOPMENT_TARGET_REQUIRED')
        super().__init__(url)
        self.deadline = time.monotonic() + maximum_seconds

    def call(self, method, path, data=None, tenant='a', expected=200):
        if method != 'GET' and time.monotonic() >= self.deadline:
            raise RuntimeError('VALIDATION_DEADLINE_EXCEEDED')
        headers = {'Content-Type': 'application/json'}
        if tenant:
            variable = {'a': 'RAGFLOW_DEV_TOKEN_A', 'b': 'RAGFLOW_DEV_TOKEN_B',
                        'admin': 'RAGFLOW_DEV_ADMIN_TOKEN'}[tenant]
            headers['Authorization'] = 'Bearer ' + os.environ[variable]
        request = Request(self.url + path, method=method, headers=headers,
                          data=json.dumps(data).encode() if data is not None else None)
        print('FULL_PORT_STEP ' + json.dumps({'method': method, 'path': path,
              'mode': (data or {}).get('mode'), 'kind': (data or {}).get('kind')}), flush=True)
        try:
            with urlopen(request, timeout=960) as response:
                code, raw = response.status, response.read()
        except HTTPError as exc:
            code, raw = exc.code, exc.read()
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            REPORT['http_failure'] = {'status': code, 'path': path, 'non_json': True}
            raise RuntimeError('NON_JSON_HTTP_RESPONSE') from None
        if code != expected:
            REPORT['http_failure'] = {'status': code, 'expected': expected,
                'error': result.get('error'), 'stage': result.get('stage'), 'path': path}
            raise RuntimeError('HTTP_FAILURE')
        return result


def normalize(value):
    return ' '.join(value.casefold().split())


def score(result, expected):
    evidence = result.get('evidence', [])
    sources = {e['source_id'] for e in evidence}
    text = normalize('\n'.join(e['text'] for e in evidence))
    return {'required_source_hits': sorted(set(expected['required_sources']) & sources),
            'required_source_count': len(expected['required_sources']),
            'support_hits': [fragment for fragment in expected['required_text'] if normalize(fragment) in text],
            'support_count': len(expected['required_text'])}


def validate_advanced(result, tenant, permitted_sources):
    from ragflow_derived.contracts import AuthorizedScope, SourceRef
    from ragflow_dev.config import PROFILE, DIMENSION
    scope = AuthorizedScope('synthetic-org-' + tenant, 'synthetic-bot-' + tenant, 'native-v1',
        PROFILE, DIMENSION, tuple(SourceRef(sid, entry['document_id'], str(entry['version']))
        for sid, entry in permitted_sources.items() if entry['state'] == 'ready'))
    for row in result['evidence']:
        assert row['generated'] is False and row['source_id'] in permitted_sources
        ref = scope.source(row['source_id'])
        assert row['scope_key'] == scope.key and row['document_id'] == ref.document_id
        assert row['version'] == str(permitted_sources[row['source_id']]['version'])
        assert hashlib.sha256(row['text'].encode()).hexdigest() == row['text_sha256']
        assert row['generation'] == 'native-v1'
    for row in result.get('generated_artifacts', []):
        assert row['generated'] and row['source_chunk_ids']
        assert row['organization_id'] == 'synthetic-org-' + tenant
        assert row['bot_id'] == 'synthetic-bot-' + tenant
        assert row['generation'] == 'native-v1'
        assert row['scope_key'] == scope.key
        assert {s['source_id'] for s in row['support_sources']} <= permitted_sources.keys()
        for source in row['support_sources']:
            assert SourceRef(**source) == scope.source(source['source_id'])
    observation = result.get('trace', {}).get('observation')
    if observation:
        assert observation['dropped_events'] == 0
        for event in observation['events']:
            if event['kind'] == 'authorized_candidate':
                assert event['organization_id'] == 'synthetic-org-' + tenant
                assert event['bot_id'] == 'synthetic-bot-' + tenant
                assert event['source_id'] in permitted_sources
                assert event['scope_key'] == scope.key
                assert str(event['version']) == scope.source(event['source_id']).version
                assert event['ready_verified'] and event['text_hash_verified']


def validate_saved_originals(es, report):
    """Read-only revalidation, not retrieval, reranking or another quality run."""
    from ragflow_dev.authority import Authority
    from ragflow_derived.storage import ScopedStore, ElasticsearchBackend
    authority = Authority(es)
    scope = authority.active_scope('a')
    store = ScopedStore(ElasticsearchBackend(es), scope, lambda candidate: authority.authorized('a', candidate))
    rows = {}
    for item in report['mechanical'] + report['quality']:
        result = item.get('result', {})
        observation = (result.get('trace') or {}).get('observation') or result.get('observation') or {}
        for event in observation.get('events', []):
            if event['kind'] == 'authorized_candidate':
                rows[event['chunk_id']] = event.get('auxiliary')
    ready = store.backend.ready_sources(scope)
    store.check()
    if rows:
        for entry in es.mget(index=scope.index, ids=sorted(rows))['docs']:
            assert entry.get('found')
            store.validate_row(entry['_source'], rows[entry['_id']])
            assert entry['_source']['source_version_kwd'] in ready
    store.check()
    report['saved_candidate_revalidation'] = {'original_candidates': len(rows), 'result': 'PASS'}


def main():
    from elasticsearch import Elasticsearch
    from ragflow_dev.config import Settings
    from ragflow_dev.authority import CONTROL_INDEX
    settings = Settings.from_env()
    assert settings.project_id == '068a5695-2cf6-4c7f-89fc-3d24a225e4a5'
    if os.environ.get('RAGFLOW_DEV_FULL_VALIDATION') != 'ONCE_AFTER_FULL_FREEZE':
        raise RuntimeError('EXPLICIT_FULL_FREEZE_GATE_REQUIRED')
    freeze = json.loads((ROOT / 'full_port_freeze.json').read_text())
    for filename, expected_hash in freeze['file_hashes'].items():
        assert hashlib.sha256((ROOT / filename).read_bytes()).hexdigest() == expected_hash
    c = json.loads((ROOT / 'generic_holdout_c.json').read_text())
    b = json.loads((ROOT / 'generic_holdout_b.json').read_text())
    REPORT['freeze'] = freeze
    REPORT['deployment_commit'] = os.environ.get('RAILWAY_GIT_COMMIT_SHA')
    started = time.perf_counter()
    client = BoundedClient(URL, freeze['maximum_seconds'])
    REPORT['health_before'] = client.call('GET', '/ragflow-dev/health', tenant=None)
    assert REPORT['health_before']['upstream_components']['full_software_ready']
    before_calls = REPORT['health_before']['upstream_components']['chat_calls']
    # Durable CREATE-only marker prevents accidental execution/retry, including
    # a process restart. No credentials, prompts or customer data are stored here.
    es = Elasticsearch(settings.es_url, request_timeout=20, max_retries=0)
    run_id = 'full_port_validation_' + hashlib.sha256(json.dumps(freeze, sort_keys=True).encode()).hexdigest()
    es.create(index=CONTROL_INDEX, id=run_id, document={'state': 'started', 'kind': 'full_port_once'}, refresh='wait_for')
    try:
        inventories = {t: client.call('GET', '/ragflow-dev/sources', tenant=t) for t in ['a', 'b']}
        REPORT['starting_inventory'] = inventories
        additions = ['full-mechanical'] + [d['source_id'] for d in c['documents']]
        for t, inv in inventories.items():
            assert inv['organization'] == 'synthetic-org-' + t
            assert not set(additions) & inv['sources'].keys()
            assert len(inv['sources']) + len(additions) <= 30
        for t in ['a', 'b']:
            client.call('POST', '/ragflow-dev/ingest', {'source_id': 'full-mechanical', 'expected_version': 0,
                'content': MECHANICAL, 'kind': 'md', 'title': 'Calibration Bureau',
                'url': 'https://example.test/' + t + '/full-mechanical',
                'child_delimiters': ['\n'], 'generate_toc': True}, tenant=t)
        inventory = client.call('GET', '/ragflow-dev/sources')['sources']
        mechanical_docs = ['doc-full-mechanical']
        q = 'How often does Beacon Laboratory calibrate sensors?'
        result = client.call('POST', '/ragflow-dev/retrieve', {'query': q, 'document_ids': mechanical_docs,
                           'options': {'toc_enhance': True}, 'trace': True})
        verify_pack(result, 'a'); validate_trace_observations(result, 'a')
        assert result['evidence']
        REPORT['mechanical'].append({'mode': 'normal_parent_toc', 'result': result})
        for kind in ['structure', 'raptor', 'graph']:
            compiled = client.call('POST', '/ragflow-dev/compile', {'kind': kind,
                'artifact_sources': ['full-mechanical'], 'source_versions': {'full-mechanical': 1}, 'generation': 'native-v1'})
            REPORT['mechanical'].append({'compiled': kind, 'result': compiled})
        for mode in ['navigation', 'raptor', 'graph', 'agentic']:
            body = {'mode': mode, 'query': q, 'artifact_sources': ['full-mechanical'], 'trace': True}
            if mode == 'agentic': body['thinking_mode'] = 'medium'
            result = client.call('POST', '/ragflow-dev/advanced', body)
            validate_advanced(result, 'a', {'full-mechanical': inventory['full-mechanical']})
            assert result['evidence']
            if mode == 'agentic': assert result['answer']
            REPORT['mechanical'].append({'mode': mode, 'result': result})
        # No quality run on top of an unresolved mode/ownership failure.
        for mode in ['navigation', 'raptor', 'graph', 'agentic']:
            client.call('POST', '/ragflow-dev/advanced', {'mode': mode, 'query': 'calibration',
                'document_ids': ['foreign-document']}, expected=403)
            REPORT['security'].append({'mode': mode, 'foreign_document': 'PASS'})
        emit_expanded(REPORT, 'full_port_mechanical_checkpoint')
        for t in ['a', 'b']:
            for doc in c['documents']:
                client.call('POST', '/ragflow-dev/ingest', dict(doc, expected_version=0, child_delimiters=['\n'],
                    url='https://example.test/' + t + '/' + doc['source_id']), tenant=t)
        cids = [d['source_id'] for d in c['documents']]
        for kind in ['structure', 'raptor', 'graph']:
            compiled = client.call('POST', '/ragflow-dev/compile', {'kind': kind, 'artifact_sources': cids,
                'source_versions': {sid: 1 for sid in cids}, 'generation': 'native-v1'})
            REPORT['mechanical'].append({'holdout_artifacts': kind, 'result': compiled})
        # The frozen normal comparison is the unchanged ordinary mode; no keyword
        # or advanced preparation is silently enabled for particular questions.
        old_docs = ['doc-' + x for x in ['library', 'museum', 'workshop', 'transit', 'garden', 'cafe',
                                       'fitness', 'study', 'kayak', 'recycling', 'delivery', 'membership']]
        all_sets = []
        for i, (category, question, target) in enumerate(QUESTIONS):
            required = [target] if target else freeze['same8_required_sources'][category]
            all_sets.append(('SAME8', str(i + 1), question, old_docs,
                             {'required_sources': required, 'required_text': []},
                             'agentic' if category in freeze['same8_agentic_categories'] else None))
        for i, question in enumerate(b['questions']):
            all_sets.append(('HOLDOUT_B', str(i + 1), question['question'],
                ['doc-' + d['source_id'] for d in b['documents']], question,
                'agentic' if question['category'] in freeze['holdout_b_agentic_categories'] else None))
        for question in c['questions']:
            all_sets.append(('HOLDOUT_C', question['id'], question['query'], ['doc-' + sid for sid in cids],
                {'required_sources': question['required_sources'], 'required_text': question['support']},
                question['advanced_mode']))
        inventory = client.call('GET', '/ragflow-dev/sources')['sources']
        for dataset, qid, question, docs, expected, advanced in all_sets:
            result = client.call('POST', '/ragflow-dev/retrieve', {'query': question, 'document_ids': docs, 'trace': True})
            verify_pack(result, 'a'); validate_trace_observations(result, 'a')
            REPORT['quality'].append({'dataset': dataset, 'id': qid, 'mode': 'normal', 'query': question,
                                      'score': score(result, expected), 'result': result})
            if advanced:
                body = {'mode': advanced, 'query': question, 'document_ids': docs,
                        'thinking_mode': 'high', 'trace': True}
                if dataset == 'HOLDOUT_C' and advanced != 'agentic': body['artifact_sources'] = cids
                result = client.call('POST', '/ragflow-dev/advanced', body)
                validate_advanced(result, 'a', inventory)
                REPORT['quality'].append({'dataset': dataset, 'id': qid, 'mode': advanced, 'query': question,
                                          'score': score(result, expected), 'result': result})
            emit_expanded(REPORT, 'full_port_quality_checkpoint_' + dataset + '_' + qid)
        validate_saved_originals(es, REPORT)
        REPORT['completed'] = True
        es.update(index=CONTROL_INDEX, id=run_id, doc={'state': 'completed'}, refresh='wait_for')
    finally:
        es.close()
        REPORT['elapsed_seconds'] = time.perf_counter() - started
        REPORT['health_after'] = client.call('GET', '/ragflow-dev/health', tenant=None)
        REPORT['provider_calls'] = REPORT['health_after']['upstream_components']['chat_calls'] - before_calls
        REPORT['final_inventory'] = {t: client.call('GET', '/ragflow-dev/sources', tenant=t) for t in ['a', 'b']}
        for tenant in REPORT.get('starting_inventory', {}):
            assert all(REPORT['final_inventory'][tenant]['sources'][sid] == entry
                       for sid, entry in REPORT['starting_inventory'][tenant]['sources'].items())


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        import traceback
        REPORT['failure'] = {'type': type(exc).__name__, 'frames': [
            {'file': Path(f.filename).name, 'line': f.lineno} for f in traceback.extract_tb(exc.__traceback__)]}
        emit_expanded(REPORT, 'full_port_partial')
        raise SystemExit(1) from None
    else:
        emit_expanded(REPORT, 'full_port')
    finally:
        for name in ['RAGFLOW_DEV_TOKEN_A', 'RAGFLOW_DEV_TOKEN_B', 'RAGFLOW_DEV_ADMIN_TOKEN', 'RAGFLOW_DEV_GEMINI_API_KEY']:
            os.environ.pop(name, None)
