"""Exercise the actual pinned LangGraph/tool runtime with provider doubles only."""
import asyncio
import json
from types import SimpleNamespace
import pytest
from ragflow_derived.advanced import operation_for
from ragflow_derived.contracts import EngineError
from ragflow_derived.full_runtime import full_operation, RequestTools, scoped_documents
from ragflow_derived.model_runtime import AuthorizedChatModel
from ragflow_derived.upstream.advanced_rag.agentic_rag import RAGTools
from .fixtures import engine, scope


class ResearchModel:
    max_length = 8192
    llm_name = 'offline-provider-double'

    def __init__(self):
        self.prompts, self.native_calls = [], []

    async def async_chat(self, system, history, gen_conf=None, **kwargs):
        self.prompts.append((system, history))
        if 'FOUR' in system and 'entity' in system:
            return json.dumps({'entity': ['laboratory'], 'aliases': [], 'fact_type': ['calibration'], 'qualifiers': []})
        if 'first_queries' in system:
            return json.dumps({'slots': [{'id': 0, 'type': 'fact', 'clues': ['calibration']}],
                               'first_queries': ['laboratory calibration']})
        if 'fan' in system.lower() and 'JSON' in system:
            return json.dumps({'fanouts': ['laboratory calibration', 'laboratory intervals']})
        if 'is_sufficient' in system:
            return json.dumps({'is_sufficient': True, 'confidence': 1, 'contradictions': [],
                               'reasoning': 'The supplied fixture supports the fact.', 'claims': []})
        return 'Calibrate laboratory equipment every seven days. [ID:0]'

    async def async_completion(self, messages, **kwargs):
        self.native_calls.append((messages, kwargs))
        if len(self.native_calls) == 1:
            message = SimpleNamespace(content='', tool_calls=[SimpleNamespace(
                id='fixture-search', type='function', function=SimpleNamespace(
                    name='retrieve', arguments=json.dumps({'query': ['laboratory calibration']})))])
            return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)
        message = SimpleNamespace(content='<answer>{"answer":"Calibrate every seven days.","new_state":[]}</answer>',
                                  tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)


def test_actual_low_graph_runs_search_synthesis_and_exact_citations():
    e, s = engine(), scope()
    e.ingest(s, 'manual', 'Laboratory calibration is every seven days.', title='Laboratory')
    e.chat_model = ResearchModel()
    result = asyncio.run(e.research(s, 'What is the laboratory calibration interval?', thinking_mode='low'))
    assert result['answer']
    assert result['mode'] == 'low'
    assert result['evidence'] and result['evidence'][0].source_id == 'manual'
    assert result['evidence'][0].text == '\nLaboratory calibration is every seven days.'
    assert e.backend.calls and e.chat_model.prompts
    assert any('Citation' in system or 'citation' in system for system, _ in e.chat_model.prompts)


def test_actual_medium_graph_executes_native_research_and_review():
    e, s = engine(), scope()
    e.ingest(s, 'manual', 'Laboratory calibration is every seven days.', title='Laboratory')
    e.chat_model = ResearchModel()
    result = asyncio.run(e.research(s, 'What is the laboratory calibration interval?', thinking_mode='medium'))
    assert result['answer'] and 'internal error' not in result['answer']
    assert result['evidence']
    assert e.chat_model.native_calls
    assert any('is_sufficient' in system for system, _ in e.chat_model.prompts)


@pytest.mark.parametrize('mode', ['high', 'ultra'])
def test_actual_fanout_executor_runs_with_upstream_stopping_policy(mode):
    e, s = engine(), scope()
    e.ingest(s, 'manual', 'Laboratory calibration is every seven days.', title='Laboratory')
    e.chat_model = ResearchModel()
    result = asyncio.run(e.research(s, 'What is the laboratory calibration interval?', thinking_mode=mode))
    assert result['answer'] and 'internal error' not in result['answer']
    assert result['evidence'] and e.chat_model.native_calls
    assert any('first_queries' in system for system, _ in e.chat_model.prompts)


@pytest.mark.parametrize('mode', ['invalid', 'naive', 'HIGH', ''])
def test_mode_never_silently_degrades(mode):
    with pytest.raises(EngineError, match='MODE_UNAVAILABLE'):
        asyncio.run(engine().research(scope(), 'A fact?', thinking_mode=mode))


def test_provider_tuple_and_bundle_string_share_one_authorized_callback():
    calls = []
    model = AuthorizedChatModel(ResearchModel(), lambda: calls.append(True))
    assert isinstance(asyncio.run(model.async_chat('text', [])), str)
    text, usage = asyncio.run(model.mdl.async_chat('text', []))
    assert isinstance(text, str) and usage == 0 and len(calls) >= 4


def test_navigation_binding_is_context_local_across_interleaved_tenants():
    refs = RequestTools()
    async def scenario():
        a = scope()
        b = scope(org='other')
        ready = asyncio.Event()
        async def first():
            op = operation_for(engine(), a)
            with full_operation(op):
                tools = SimpleNamespace(tenant_ids=[a.key], kb_ids=[a.bot_id])
                refs['tools'] = tools
                await ready.wait()
                assert refs.get('tools') is tools
        async def second():
            op = operation_for(engine(), b)
            with full_operation(op):
                tools = SimpleNamespace(tenant_ids=[b.key], kb_ids=[b.bot_id])
                refs['tools'] = tools
                ready.set()
                await asyncio.sleep(0)
                assert refs.get('tools') is tools
        await asyncio.gather(first(), second())
    asyncio.run(scenario())
    with pytest.raises(EngineError, match='UNAUTHORIZED_SCOPE'):
        refs.get('tools')


@pytest.mark.parametrize('identifier', ['foreign-document', 'foreign-node', 'old-version-node'])
def test_model_identifiers_cannot_widen_scope_even_when_error_is_swallowed(identifier):
    op = operation_for(engine(), scope())
    with pytest.raises(EngineError, match='UNAUTHORIZED_SCOPE'):
        with full_operation(op):
            try:
                scoped_documents([identifier])
            except EngineError:
                pass


def test_backend_scope_failure_remains_fatal_after_upstream_style_catch():
    from ragflow_derived.upstream.doc_store import OrderByExpr
    op = operation_for(engine(), scope())
    with pytest.raises(EngineError, match='UNAUTHORIZED_SCOPE'):
        with full_operation(op):
            try:
                op.store.search([], [], {}, [], OrderByExpr(), 0, 1, ['ragflow_foreign'], [op.scope.bot_id])
            except EngineError:
                pass
