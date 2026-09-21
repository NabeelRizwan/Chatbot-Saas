"""Terminal follow-up harness only; all network is denied by the suite fixture."""
import asyncio
import base64
import copy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import pytest
from ragflow_derived.model_runtime import model_operation
from ragflow_dev.chat import DevGemini
from ragflow_dev.gemini35 import Gemini35Provider
from .fixtures import scope
from .test_model_selected_dispatch_job import WireClient, tools, report

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'dev/ragflow'))
try:
    spec = importlib.util.spec_from_file_location('terminal_completion_job', ROOT / 'dev/ragflow/dispatch_terminal_completion.py')
    job = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(job)
finally:
    sys.path.pop(0)


def test_integrity_manifest_is_exactly_the_preserved_six_call_artifact():
    freeze = json.loads(job.FREEZE.read_text(encoding='utf-8'))
    artifact = json.loads((ROOT / 'docs/RAGFLOW_MODEL_SELECTED_DISPATCH_LIVE_RESULTS.json').read_text())
    raw = gzip.decompress(base64.b64decode(''.join(p['data'] for p in artifact['parts'])))
    old = json.loads(raw)
    assert hashlib.sha256(raw).hexdigest() == freeze['previous_result_sha256']
    assert job.prior.QUESTION.encode() == old['question'].encode() == freeze['question'].encode()
    assert freeze['original_evidence'] == old['preflight_underlying']['evidence']
    assert freeze['source'] == old['source']
    assert hashlib.sha256(job.prior.FIXTURE.read_text(encoding='utf-8').encode()).hexdigest() == freeze['fixture_sha256']


def test_all_runtime_file_hashes_are_the_prior_committed_run():
    freeze = json.loads(job.FREEZE.read_text(encoding='utf-8'))
    assert len(freeze['file_hashes']) == 192
    for name, digest in freeze['file_hashes'].items():
        blob = subprocess.check_output(['git', 'show', freeze['source_commit'] + ':' + name], cwd=ROOT)
        assert hashlib.sha256(blob).hexdigest() == digest


@pytest.mark.parametrize('change', ['text', 'version', 'document_id', 'duplicate', 'missing'])
def test_original_record_mismatch_is_fail_closed(change):
    freeze = json.loads(job.FREEZE.read_text(encoding='utf-8'))
    rows = copy.deepcopy(freeze['original_evidence'])
    if change == 'duplicate':
        rows.append(copy.deepcopy(rows[0]))
    elif change == 'missing':
        rows.pop()
    else:
        rows[0][change] += 'changed'
    with pytest.raises(job.prior.StopRun, match='ORIGINAL_FIXTURE_RECORDS_CHANGED'):
        job.verify_originals(rows, freeze)


def test_runtime_hash_mismatch_fails_before_model_construction(tmp_path):
    (tmp_path / 'source.py').write_text('altered')
    with pytest.raises(job.prior.StopRun, match='FROZEN_SOURCE_HASH_MISMATCH'):
        job.verify_files(tmp_path, {'file_hashes': {'source.py': '0' * 64}})


def test_eight_call_ceiling_allows_two_more_then_refuses_ninth():
    class Text:
        llm_name, max_length, calls, last_usage = 'offline', 32768, 0, {}
        async def async_chat(self, *args, **kwargs):
            self.calls += 1
            return 'unchanged output'
    inner, r = Text(), report()
    observed = job.EightCallObservation(inner, r)
    async def run():
        for _ in range(8):
            assert await observed.async_chat('system', []) == 'unchanged output'
        with pytest.raises(job.prior.StopRun, match='EIGHT_CALL_CEILING'):
            await observed.async_chat('system', [])
    asyncio.run(run())
    assert inner.calls == 8
    assert [e['ordinal'] for e in r['ordered_calls']] == list(range(1, 9))
    assert 'ceiling_stop' in r


@pytest.mark.parametrize('failure,terminal_first,reason', [
    (True, False, 'PROVIDER_FAILURE_NO_RETRY'),
    (False, True, 'NO_MODEL_SELECTED_TOOL_STOPPED')])
def test_previous_fail_stop_behavior_remains(failure, terminal_first, reason):
    client = WireClient(failure=failure, terminal_first=terminal_first)
    inner = DevGemini(Gemini35Provider(client, 'gemini-3.5-flash-lite'), max_calls=8)
    observed = job.EightCallObservation(inner, report())
    async def run():
        with model_operation(scope()):
            with pytest.raises(job.prior.StopRun, match=reason):
                await observed.async_completion([{'role': 'user', 'content': job.prior.QUESTION}], tools=tools())
            with pytest.raises(job.prior.StopRun, match='RUN_ALREADY_STOPPED'):
                await observed.async_completion([], tools=tools())
    asyncio.run(run())
    assert inner.calls == len(client.requests) == 1


def test_observation_does_not_change_native_requests_results_or_metadata():
    async def run(observed):
        client = WireClient()
        inner = DevGemini(Gemini35Provider(client, 'gemini-3.5-flash-lite'), max_calls=8)
        r = report()
        model = job.EightCallObservation(inner, r) if observed else inner
        messages = [{'role': 'user', 'content': job.prior.QUESTION}]
        with model_operation(scope()):
            first = await model.async_completion(messages, tools=tools())
            call = first.choices[0].message.tool_calls[0]
            messages += [{'role': 'assistant', 'content': '', 'tool_calls': [{'id': call.id,
                'type': 'function', 'function': vars(call.function)}]},
                {'role': 'tool', 'tool_call_id': call.id, 'content': job.prior.FACT}]
            original = copy.deepcopy(messages)
            second = await model.async_completion(messages, tools=tools())
            assert messages == original
        return client.requests, second, r
    plain, plain_answer, _ = asyncio.run(run(False))
    observed, observed_answer, r = asyncio.run(run(True))
    assert plain == observed and plain_answer == observed_answer
    assert r['actions'][1]['roundtrips'][0]['complete_provider_content_preserved']
    assert [e['ordinal'] for e in r['ordered_calls']] == [1, 2]
    assert 'opaque-offline-signature' not in json.dumps(r)


def test_no_reingestion_or_fixture_writes_and_only_one_graph_entry():
    text = Path(job.__file__).read_text()
    assert 'runtime.ingest(' not in text and 'runtime.delete(' not in text
    assert 'model.max_calls = 8' in text
    assert text.count('runtime.advanced(') == 1
    assert job.MARKER != job.prior.MARKER
    assert 'tool_config' not in text and 'function_calling_config' not in text
    assert 'runtime.client.create(index=CONTROL_INDEX, id=MARKER' in text


@pytest.mark.parametrize('kind', ['text', 'native'])
def test_initial_answer_leak_guard_is_inherited(kind):
    model = job.EightCallObservation(SimpleNamespace(llm_name='offline', max_length=32768, calls=0), report())
    async def run():
        if kind == 'text':
            await model.async_chat('system', [{'role': 'user', 'content': job.prior.FACT}])
        else:
            await model.async_completion([{'role': 'user', 'content': job.prior.FACT}], tools=tools())
    with pytest.raises(job.prior.StopRun, match='ANSWER_'):
        asyncio.run(run())
