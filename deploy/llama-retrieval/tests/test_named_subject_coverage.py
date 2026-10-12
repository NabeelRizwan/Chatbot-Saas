"""Complete explicit source recognition before allocating bounded search slots."""
from dataclasses import replace

import pytest

from retrieval_engine.adaptive_evidence import routing_hints, evidence_limits
from retrieval_engine.config import RetrievalConfig
from retrieval_engine.query_constraints import focused_query
from test_discovery_integration import engine_fixture, FixedRetriever


TITLES = ['LÜMA portable torch', 'NOVA desk light', 'ASTRAL camping light',
          'CELESTIAL wall light', 'FOCAL reading light', 'ZENITH floor light']


def test_long_names_do_not_hide_short_or_accent_folded_unique_names():
    docs = [{'source_id': str(i), 'title': title} for i, title in enumerate(TITLES)]
    question = 'Which need batteries: ASTRAL, CELESTIAL, FOCAL, ZENITH, LUMA and NOVA?'
    hints = routing_hints(question, docs)
    assert set(hints.comparison_source_ids) == set(map(str, range(6)))
    assert evidence_limits(RetrievalConfig(), len(hints.comparison_source_ids), False) == (96, 16)


def test_property_first_comparison_keeps_property_and_resolves_all_names():
    question = 'Compare the cleaning directions for LUMA, NOVA, ASTRAL and CELESTIAL.'
    focus = focused_query(question, TITLES[0], TITLES[:4])
    assert 'cleaning directions' in focus
    assert all(name not in focus for name in ['NOVA', 'ASTRAL', 'CELESTIAL'])
    assert focus.startswith(TITLES[0] + '. ')


def test_many_literal_names_share_existing_pair_and_context_limits():
    engine = engine_fixture(0)
    base_nodes = engine._scoped['a'].results
    for source in ['e', 'f']:
        document = dict(engine._documents['a'], id=source, source_id=source, url=f'https://example.org/{source}')
        engine._documents[source] = document
        copied = []
        for original in base_nodes:
            item = original.model_copy(deep=True)
            item.node.id_ = source + '-' + original.node.node_id
            item.node.metadata.update(source_id=source, subject_source_id=source, url=document['url'])
            engine._source_nodes[item.node.node_id] = item.node
            engine._model_nodes[item.node.node_id] = item.node
            copied.append(item)
        engine._scoped[source] = FixedRetriever(copied)
    for source, title in zip(['a', 'b', 'c', 'd', 'e', 'f'], TITLES):
        engine._documents[source]['title'] = title
        for item in engine._scoped[source].results:
            item.node.metadata.update(title=title, subject_title=title)
    result = engine.retrieve('Compare battery requirements for LUMA, NOVA, ASTRAL, CELESTIAL, FOCAL and ZENITH.')
    assert set(result['audit']['query_hints']['comparison_source_ids']) == {'a', 'b', 'c', 'd', 'e', 'f'}
    assert result['audit']['scored_pairs'] <= 96
    assert result['audit']['core_limit'] == 16
    assert result['context_tokens'] <= engine.config.context_token_budget
    assert {e['source_id'] for e in result['evidence']} == {'a', 'b', 'c', 'd', 'e', 'f'}
    assert result['audit']['generative_provider_calls'] == 0


def test_over_cap_never_silently_routes_a_partial_list():
    docs = [{'source_id': str(i), 'title': title} for i, title in enumerate(TITLES)]
    question = 'Compare LUMA, NOVA, ASTRAL, CELESTIAL, FOCAL and ZENITH.'
    assert not routing_hints(question, docs, max_subjects=4).comparison_source_ids


@pytest.mark.parametrize('value', [1, 9, True, 4.5])
def test_comparison_ceiling_is_explicit_and_bounded(value):
    with pytest.raises(ValueError, match='Comparison subjects'):
        replace(RetrievalConfig(), max_comparison_subjects=value)
