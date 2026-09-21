"""Offline mechanical-runner checks. Suite fixture blocks all socket access."""
import asyncio
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from google.genai import types
from ragflow_dev.chat import DevGemini
from ragflow_dev.gemini35 import Gemini35Provider
from ragflow_derived.model_runtime import model_operation
from ragflow_derived.parsing import parse
from .fixtures import scope, engine, TokenizerDouble
from .test_full_agentic import ResearchModel

spec = importlib.util.spec_from_file_location('dispatch_job', Path(__file__).resolve().parents[2] / 'dev/ragflow/model_selected_dispatch.py')
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)


def report():
    return {'events': [], 'actions': [], 'parsed': [], 'dispatches': [], 'terminals': []}


def test_normal_jsonl_parser_separates_index_from_answer():
    pieces = parse(job.FIXTURE.read_text(), 'jsonl', chunk_tokens=512, tokenizer=TokenizerDouble())
    assert len(pieces) == 7
    assert all(job.FACT not in p['text'] for p in pieces[:-1])
    assert job.FACT in pieces[-1]['text'] and 'RB742' in pieces[-1]['text']
    assert 'RB742' in pieces[0]['text']
    assert all(len(p['text']) < 1200 for p in pieces)


@pytest.mark.parametrize('method', ['async_chat', 'async_completion'])
def test_preflight_cannot_access_a_provider(method):
    with pytest.raises(job.StopRun, match='PREFLIGHT_ATTEMPTED_MODEL_ACCESS'):
        asyncio.run(getattr(job.NoProvider(), method)([]))


class WireClient:
    def __init__(self, *, failure=False, terminal_first=False):
        self.aio = SimpleNamespace(models=self)
        self.requests = []
        self.failure, self.terminal_first = failure, terminal_first

    async def generate_content(self, **kwargs):
        self.requests.append(kwargs)
        if self.failure:
            raise ValueError('offline failure')
        if len(self.requests) == 1 and not self.terminal_first:
            parts = [types.Part(function_call=types.FunctionCall(id='provider-id', name='list_chunks',
                args={'doc_id': 'doc-test'}), thought_signature=b'opaque-offline-signature')]
        else:
            parts = [types.Part(text='<answer>{"answer":"copper orchard at dusk","new_state":[]}</answer>')]
        return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role='model', parts=parts))])


def tools():
    from ragflow_derived.upstream.advanced_rag.harness.action_session import _TOOL_MAP
    return [copy.deepcopy(_TOOL_MAP['list_chunks'])]


def test_native_forwarding_pairing_and_metadata_are_observational():
    async def run(observed):
        client = WireClient()
        inner = DevGemini(Gemini35Provider(client, 'gemini-3.5-flash-lite'), max_calls=6)
        r = report()
        model = job.ObservedModel(inner, r) if observed else inner
        messages = [{'role': 'user', 'content': job.QUESTION}]
        original = copy.deepcopy(messages)
        with model_operation(scope()):
            first = await model.async_completion(messages, tools=tools())
            assert messages == original
            call = first.choices[0].message.tool_calls[0]
            messages += [{'role': 'assistant', 'content': '', 'tool_calls': [
                {'id': call.id, 'type': 'function', 'function': vars(call.function)}]},
                {'role': 'tool', 'tool_call_id': call.id, 'content': '{"value":"copper orchard at dusk"}'}]
            original = copy.deepcopy(messages)
            second = await model.async_completion(messages, tools=tools())
            assert messages == original
        return client.requests, second, r
    plain, plain_answer, _ = asyncio.run(run(False))
    observed, observed_answer, r = asyncio.run(run(True))
    assert plain == observed
    assert plain_answer == observed_answer
    assert r['actions'][1]['roundtrips'][0]['complete_provider_content_preserved']
    assert r['actions'][1]['roundtrips'][0]['provider_id_present']
    assert r['actions'][1]['roundtrips'][0]['signed_parts_present']
    assert 'opaque-offline-signature' not in json.dumps(r)


@pytest.mark.parametrize('terminal_first,failure,reason', [
    (True, False, 'NO_MODEL_SELECTED_TOOL_STOPPED'),
    (False, True, 'PROVIDER_FAILURE_NO_RETRY')])
def test_first_failure_or_no_selection_cannot_retry(terminal_first, failure, reason):
    client = WireClient(failure=failure, terminal_first=terminal_first)
    inner = DevGemini(Gemini35Provider(client, 'gemini-3.5-flash-lite'), max_calls=6)
    model = job.ObservedModel(inner, report())
    async def run():
        with model_operation(scope()):
            with pytest.raises(job.StopRun, match=reason):
                await model.async_completion([{'role': 'user', 'content': job.QUESTION}], tools=tools())
            with pytest.raises(job.StopRun, match='RUN_ALREADY_STOPPED'):
                await model.async_completion([{'role': 'user', 'content': job.QUESTION}], tools=tools())
    asyncio.run(run())
    assert len(client.requests) == inner.calls == 1


@pytest.mark.parametrize('kind', ['native', 'text'])
def test_answer_leak_stops_before_any_provider_call(kind):
    inner = SimpleNamespace(llm_name='offline', max_length=32768, calls=0)
    observed = job.ObservedModel(inner, report())
    async def run():
        if kind == 'native':
            await observed.async_completion([{'role': 'user', 'content': job.FACT}], tools=tools())
        else:
            await observed.async_chat('system', [{'role': 'user', 'content': job.FACT}])
    with pytest.raises(job.StopRun, match='ANSWER_'):
        asyncio.run(run())
    assert inner.calls == 0


def test_six_call_ceiling_prevents_seventh_transport_request():
    inner = SimpleNamespace(llm_name='offline', max_length=32768, calls=6)
    observed = job.ObservedModel(inner, report())
    with pytest.raises(job.StopRun, match='SIX_CALL_CEILING'):
        asyncio.run(observed.async_completion([], tools=tools()))


def test_real_graph_dispatch_observation_preserves_answers_evidence_and_restores_functions():
    from ragflow_derived.upstream.advanced_rag.harness import action_session as action
    originals = action._parse_tool_calls, action.execute_tool, action._parse_terminal
    def run(record=False):
        e, s = engine(), scope()
        e.ingest(s, 'manual', 'Laboratory calibration is every seven days.', title='Laboratory')
        e.chat_model = ResearchModel()
        r = report()
        if record:
            with job.dispatch_observation(r):
                value = asyncio.run(e.research(s, 'What is the laboratory calibration interval?', thinking_mode='medium'))
        else:
            value = asyncio.run(e.research(s, 'What is the laboratory calibration interval?', thinking_mode='medium'))
        return value, r
    plain, _ = run()
    observed, r = run(True)
    for key in ('answer', 'evidence', 'citation_pool', 'verdict', 'mode'):
        assert plain[key] == observed[key]
    assert r['parsed'] and any(d['caller'] == '_tool_node' for d in r['dispatches'])
    assert originals == (action._parse_tool_calls, action.execute_tool, action._parse_terminal)


def test_observation_restored_on_fail_closed_abort():
    from ragflow_derived.upstream.advanced_rag.harness import action_session as action
    original = action.execute_tool
    with pytest.raises(job.StopRun):
        with job.dispatch_observation(report()):
            raise job.StopRun('offline abort')
    assert action.execute_tool is original


def test_only_new_source_normal_ingestion_and_one_full_graph_in_job():
    text = Path(job.__file__).read_text()
    assert text.count('runtime.advanced(') == 1
    assert 'expected_version=0' in text
    assert 'model.max_calls = 6' in text
    assert "es.create(" not in text  # Only runtime's scoped DEV connection.
    assert 'runtime.client.create(index=CONTROL_INDEX, id=MARKER' in text
    assert 'tool_config' not in text and 'function_calling_config' not in text
