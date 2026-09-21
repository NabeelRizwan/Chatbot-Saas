import asyncio
import pytest
from ragflow_derived.contracts import EngineError
from ragflow_derived.upstream.runtime import native_tokenizer
from .fixtures import TokenizerDouble
from .test_full_artifacts import compilation_fixture


@pytest.fixture(autouse=True)
def offline_tokenizer(monkeypatch):
    monkeypatch.setattr(native_tokenizer, '_instance', TokenizerDouble())


def test_raptor_uses_one_joint_ranking_with_originals_and_summaries():
    e, s = compilation_fixture()
    asyncio.run(e.compile(s, kind='raptor'))
    result = asyncio.run(e.retrieve_mode(s, 'laboratory calibration equipment', mode='raptor'))
    assert result['selected_order'] and result['evidence'] and result['generated_artifacts']
    assert any(len(call[1]) == 2 for call in e.artifact_io.calls)
    assert all(not ev.metadata['generated'] for ev in result['evidence'])


def test_real_document_structure_navigation_executes_compiled_graph():
    e, s = compilation_fixture()
    asyncio.run(e.compile(s, kind='structure'))
    result = asyncio.run(e.retrieve_mode(s, 'laboratory calibration', mode='navigation', document_id='doc-a'))
    assert result['navigation']['doc_ids'] == ['doc-a']
    assert result['navigation']['entities'] > 0
    assert result['generated_artifacts'] and result['evidence']


@pytest.mark.parametrize('mode,kind', [('raptor', 'raptor'), ('navigation', 'structure'), ('graph', 'graph')])
def test_modes_reject_foreign_document_before_search(mode, kind):
    e, s = compilation_fixture()
    with pytest.raises(EngineError, match='UNAUTHORIZED_SCOPE'):
        asyncio.run(e.retrieve_mode(s, 'calibration', mode=mode, document_ids=['foreign']))
    assert not e.artifact_io.calls


@pytest.mark.parametrize('mode', ['raptor', 'navigation', 'graph'])
def test_uncompiled_mode_fails_explicitly_instead_of_falling_back(mode):
    e, s = compilation_fixture()
    with pytest.raises(EngineError, match='MODE_UNAVAILABLE'):
        asyncio.run(e.retrieve_mode(s, 'calibration', mode=mode))
