"""No live calls: safety and forwarding of the two-new-question harness."""
import asyncio
import copy
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

from .fixtures import scope
from .test_model_selected_dispatch_job import WireClient, tools
from ragflow_dev.chat import DevGemini
from ragflow_dev.gemini35 import Gemini35Provider
from ragflow_derived.model_runtime import model_operation

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'dev/ragflow'))
try:
    spec = importlib.util.spec_from_file_location('answer_quality_job', ROOT / 'dev/ragflow/answer_quality_once.py')
    job = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(job)
finally:
    sys.path.pop(0)


def test_runtime_freeze_and_new_fixture_are_exact():
    freeze = json.loads(job.FREEZE.read_text())
    job.verify_files(ROOT, freeze)
    assert freeze['source_commit'] == '05ceb975125a4706ff97852e78377934c8531666'
    fixture = json.loads(job.FIXTURE.read_text())
    assert len(fixture['documents']) == 6
    assert len({d['source'] for d in fixture['documents']}) == 6
    assert fixture['organization'] == 'synthetic-answer-test-org'
    assert fixture['bot'] == 'synthetic-answer-test-bot'
    assert fixture['generation'] == 'answer-test-v1'
    for d in fixture['documents']:
        assert set(d) == {'source', 'title', 'content'}
        assert all(q not in d['content'] for q in fixture['questions'].values())


class FakeAuthorityClient:
    def __init__(self):
        self.indices = SimpleNamespace(exists=lambda **kw: False)
        self.documents = {}
    def create(self, *, index, id, document, **kw):
        if id in self.documents:
            raise RuntimeError('conflict')
        self.documents[id] = copy.deepcopy(document)
    def get(self, **kw):
        return {'_source': copy.deepcopy(self.documents[kw['id']]), '_seq_no': 1, '_primary_term': 1}
    def index(self, **kw):
        assert kw['if_seq_no'] == kw['if_primary_term'] == 1
        self.documents[kw['id']] = copy.deepcopy(kw['document'])


@pytest.mark.parametrize('change', ['org', 'bot', 'generation', 'version', 'sources', 'revoke'])
def test_exact_new_test_authority_fails_closed(change):
    client, s = FakeAuthorityClient(), scope()
    auth = job.ExactTestAuthority(client, s, 'fixture')
    assert auth.authorized(s)
    if change == 'revoke':
        client.documents[job.MARKER]['state'] = 'revoked'
        other = s
    elif change == 'sources':
        other = replace(s, sources=())
    elif change == 'version':
        other = replace(s, sources=(replace(s.sources[0], version='2'),))
    else:
        other = replace(s, **{{'org': 'organization_id', 'bot': 'bot_id'}.get(change, change): 'foreign'})
    assert not auth.authorized(other)


def test_one_shot_marker_and_finish_prevent_rerun():
    client, s = FakeAuthorityClient(), scope()
    auth = job.ExactTestAuthority(client, s, 'fixture')
    auth.finish()
    assert not auth.authorized(s)
    with pytest.raises(RuntimeError, match='conflict'):
        job.ExactTestAuthority(client, s, 'fixture')


def test_existing_index_is_never_reused():
    client = FakeAuthorityClient()
    client.indices.exists = lambda **kw: True
    with pytest.raises(job.StopRun, match='NEW_TEST_INDEX_ALREADY_EXISTS'):
        job.ExactTestAuthority(client, scope(), 'fixture')
    assert not client.documents


def test_twenty_calls_then_refuse_21_even_concurrently():
    class Text:
        llm_name, max_length, calls = 'offline', 32768, 0
        async def async_chat(self, *args, **kw):
            self.calls += 1
            await asyncio.sleep(0)
            return 'unchanged'
    inner, report = Text(), {'calls': []}
    observer = job.AnswerObserver(inner, report, 20)
    async def run():
        results = await asyncio.gather(*(observer.async_chat('s', []) for _ in range(20)))
        assert results == ['unchanged'] * 20
        with pytest.raises(job.StopRun, match='QUESTION_CALL_CEILING'):
            await observer.async_chat('s', [])
    asyncio.run(run())
    assert inner.calls == observer.started == 20


def test_native_forwarding_identical_and_no_opaque_trace():
    async def run(observe):
        client = WireClient()
        inner = DevGemini(Gemini35Provider(client, 'gemini-3.5-flash-lite'))
        report = {'calls': []}
        mdl = job.AnswerObserver(inner, report, 20) if observe else inner
        with model_operation(scope()):
            first = await mdl.async_completion([{'role': 'user', 'content': 'offline fixture'}], tools=tools())
            c = first.choices[0].message.tool_calls[0]
            history = [{'role': 'user', 'content': 'offline fixture'}, {'role': 'assistant', 'content': '',
                'tool_calls': [{'id': c.id, 'type': 'function', 'function': vars(c.function)}]},
                {'role': 'tool', 'tool_call_id': c.id, 'content': 'offline evidence'}]
            before = copy.deepcopy(history)
            second = await mdl.async_completion(history, tools=tools())
            assert history == before
        return client.requests, second, report
    plain, pa, _ = asyncio.run(run(False))
    traced, ta, report = asyncio.run(run(True))
    assert plain == traced and pa == ta
    assert 'opaque-offline-signature' not in json.dumps(report)


def test_natural_terminal_without_tool_is_allowed():
    client = WireClient(terminal_first=True)
    mdl = DevGemini(Gemini35Provider(client, 'gemini-3.5-flash-lite'))
    observer = job.AnswerObserver(mdl, {'calls': []}, 20)
    async def run():
        with model_operation(scope()):
            return await observer.async_completion([{'role': 'user', 'content': 'offline'}], tools=tools())
    result = asyncio.run(run())
    assert result.choices[0].message.content
    assert not observer.stopped


def test_provider_failure_is_not_retried():
    client = WireClient(failure=True)
    mdl = DevGemini(Gemini35Provider(client, 'gemini-3.5-flash-lite'))
    observer = job.AnswerObserver(mdl, {'calls': []}, 20)
    async def run():
        with model_operation(scope()):
            with pytest.raises(job.StopRun, match='PROVIDER_FAILURE_NO_RETRY'):
                await observer.async_completion([{'role': 'user', 'content': 'offline'}], tools=tools())
            with pytest.raises(job.StopRun, match='RUN_ALREADY_STOPPED'):
                await observer.async_completion([], tools=tools())
    asyncio.run(run())
    assert mdl.calls == 1


def test_no_manual_decomposition_or_expected_answers_in_harness():
    text = Path(job.__file__).read_text()
    assert text.count('engine.research(') == text.count('engine.retrieve(') == 1
    assert "thinking_mode='high'" in text
    assert 'document_ids=' not in text
    for value in ('28 credits', '90 minutes', '18 hours', '7:00 PM', 'Harborview', 'Orion'):
        assert value not in text
    assert '_compose_answer_from_evidence' in text


def test_normal_uses_frozen_composer_not_agent_graph(monkeypatch):
    from ragflow_derived.upstream.advanced_rag import agentic_rag_graph as graph
    # The actual composer is exercised elsewhere; here prove the entry sequence,
    # the default retrieve call and absence of model answer seeding.
    events = []
    class Engine:
        chat_model = SimpleNamespace(async_chat=lambda: None, max_length=32768, llm_name='offline')
        async def retrieve(self, s, q):
            events.append(('retrieve', q))
            return []
        def build_context(self, s, e):
            return {'context': '', 'evidence': []}
        def _scope(self, s):
            return SimpleNamespace(check=lambda: None)
    async def composer(state, tools, queue, config):
        events.append(('compose', state))
        queue.put_nowait('offline answer')
    monkeypatch.setattr(graph, '_compose_answer_from_evidence', composer)
    result = {}
    asyncio.run(job.normal_answer(Engine(), scope(), 'offline', result))
    assert [e[0] for e in events] == ['retrieve', 'compose']
    assert set(events[1][1]) == {'question', 'kbinfos'}
    assert result['answer'] == 'offline answer'
