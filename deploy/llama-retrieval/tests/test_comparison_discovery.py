"""Incomplete comparison names route softly through bounded source discovery."""
from dataclasses import replace

import pytest

from retrieval_engine.adaptive_evidence import routing_hints
from llama_index.core.schema import NodeWithScore, TextNode

from retrieval_engine.query_constraints import comparison_needs_discovery, comparison_discovery_sources, query_hints
from test_discovery_integration import engine_fixture


CASES = [
    ('Precision Machined Travel Mug', 'Precision Travel Mug Insulated',
     'How do the cleaning directions for plain Travel Mug and Travel Mug Insulated compare?'),
    ('Business Hosted Starter Plan', 'Business Starter Plan Annual',
     'Compare Starter Plan and Starter Plan Annual on fees and cancellation.'),
    ('Harbor Courtyard Standard Suite', 'Harbor Courtyard Suite Balcony',
     'What is the difference between plain Courtyard Suite and Courtyard Suite Balcony for amenities?'),
]


def documents(first, second):
    return [{'source_id': 'a', 'title': first}, {'source_id': 'b', 'title': second},
            {'source_id': 'c', 'title': 'Shipping Policy'},
            {'source_id': 'd', 'title': 'Outdoor Lantern'}]


@pytest.mark.parametrize('builder', [query_hints, routing_hints])
@pytest.mark.parametrize('first,second,question', CASES)
def test_partial_comparisons_request_discovery_without_inventing_hard_scopes(builder, first, second, question):
    docs = documents(first, second)
    hints = builder(question, docs)
    assert not hints.comparison_source_ids
    assert hints.retrieval_query == question
    assert comparison_needs_discovery(question, docs, hints)


@pytest.mark.parametrize('builder', [query_hints, routing_hints])
def test_fully_resolved_comparison_keeps_existing_subject_scopes(builder):
    docs = documents('Precision Machined Travel Mug', 'Precision Travel Mug Insulated')
    question = 'Compare Precision Machined Travel Mug and Precision Travel Mug Insulated on cleaning.'
    hints = builder(question, docs)
    assert set(hints.comparison_source_ids) == {'a', 'b'}
    assert not comparison_needs_discovery(question, docs, hints)


@pytest.mark.parametrize('question', [
    'Can I store Travel Mug Insulated in the fridge or at room temperature?',
    'Should I use Travel Mug Insulated before or after food?',
    'Does Travel Mug Insulated hold more than 2 cups?',
    'Can I use Travel Mug Insulated with both hot and cold drinks?',
    'Which materials are used in Precision Travel Mug Insulated?',
    'Compare handling fees and cancellation terms.',
    'Compare Unlisted Thing and Unknown Device.',
])
@pytest.mark.parametrize('builder', [query_hints, routing_hints])
def test_ordinary_properties_and_unverified_subjects_do_not_enable_comparison_discovery(question, builder):
    docs = documents('Precision Machined Travel Mug', 'Precision Travel Mug Insulated')
    assert not comparison_needs_discovery(question, docs, builder(question, docs))


def test_excluded_title_is_not_a_positive_comparison_witness():
    docs = documents('Precision Machined Travel Mug', 'Precision Travel Mug Insulated')
    question = 'Compare Unlisted Thing and Unknown Device. Exclude Precision Travel Mug Insulated.'
    hints = routing_hints(question, docs)
    assert hints.excluded_title_terms
    assert not comparison_needs_discovery(question, docs, hints)


def test_discovered_pages_need_original_name_phrases_not_just_semantic_neighbours():
    docs = documents(CASES[0][0], CASES[0][1])
    hints = query_hints(CASES[0][2], docs)
    assert comparison_discovery_sources(docs, hints, ['c', 'b', 'd', 'a', 'b']) == ['b', 'a']
    assert not hints.comparison_source_ids


def test_one_candidate_or_large_ambiguous_family_does_not_guess_second_item():
    docs = documents(CASES[0][0], CASES[0][1])
    hints = query_hints(CASES[0][2], docs)
    assert comparison_discovery_sources(docs, hints, ['c', 'a', 'd']) == []
    docs = [{'source_id': str(i), 'title': f'Travel Mug Series {i}'} for i in range(5)]
    hints = query_hints('Compare Travel Mug with an unknown product.', docs)
    assert comparison_discovery_sources(docs, hints, [str(i) for i in range(5)]) == []


@pytest.mark.parametrize('first,second,question', [
    ('Router Pro 100', 'Router Pro 200', 'Compare Router Pro 200 and Unlisted Device.'),
    ('Precision Machined Travel Mug', 'Precision Travel Mug Insulated',
     'Compare Travel Mug Insulated and Unlisted Device.'),
])
def test_short_phrase_inside_one_named_variant_cannot_reserve_a_sibling_page(first, second, question):
    docs = documents(first, second)
    hints = routing_hints(question, docs)
    assert not hints.comparison_source_ids
    assert comparison_discovery_sources(docs, hints, ['b', 'a', 'c', 'd']) == []


def test_separate_shared_phrase_preserves_candidate_uncertainty_without_picking_a_model():
    docs = documents('Router Pro 100', 'Router Pro 200')
    question = 'Compare Router Pro and Router Pro 200 on installation.'
    hints = routing_hints(question, docs)
    assert not hints.comparison_source_ids
    assert comparison_discovery_sources(docs, hints, ['b', 'a', 'c', 'd']) == ['b', 'a']


def partial_engine(*, adaptive=True, slots=16):
    engine = engine_fixture(slots)
    engine.config = replace(engine.config, adaptive_evidence=adaptive)
    titles = {'global': 'General Information', 'a': CASES[0][0], 'b': CASES[0][1],
              'c': 'Shipping Policy', 'd': 'Outdoor Lantern'}
    for source, doc in engine._documents.items():
        doc['title'] = titles[source]
    for node in engine._source_nodes.values():
        node.metadata.update(title=titles[node.metadata['source_id']],
                             subject_title=titles[node.metadata['source_id']])
    # Global relevance favors one side. Discovery finds the other original page.
    engine._fusion.results = [*engine._scoped['b'].results, *engine._fusion.results[:56]]
    engine._discovery.results = engine._discovery.results[:2]
    engine._targeted_discovery = engine._discovery if adaptive else None
    return engine


@pytest.mark.parametrize('adaptive', [False, True])
def test_partial_comparison_keeps_both_original_sources_within_the_pair_budget(adaptive):
    engine = partial_engine(adaptive=adaptive)
    result = engine.retrieve(CASES[0][2])
    audit = result['audit']
    assert not audit['query_hints']['comparison_source_ids']
    assert audit['query_hints']['comparison_discovery']
    assert audit['document_discovery']['enabled']
    assert audit['document_discovery']['embedding_reused']
    assert set(audit['document_discovery']['source_ids']) == {'a', 'b'}
    assert audit['scored_pairs'] <= 64
    assert audit['document_ranking_pairs'] <= 2
    assert audit['generative_provider_calls'] == 0
    assert {'a', 'b'} <= {row['source_id'] for row in audit['candidates']}
    assert {'a', 'b'} <= {row['source_id'] for row in result['evidence']}
    assert 'SUMMARY MUST NEVER' not in result['context']
    assert audit['document_discovery']['reserved_global_slots'] >= 32
    assert not audit['scoped_queries']


def test_disabled_discovery_preserves_original_global_only_path():
    engine = partial_engine(slots=0)
    result = engine.retrieve(CASES[0][2])
    assert not engine._discovery.calls
    assert not result['audit']['document_discovery']['enabled']
    assert result['audit']['scored_pairs'] == 64
    assert all(row['candidate_origin'] == 'global' for row in result['audit']['candidates'])


def test_partial_comparison_reaches_deeper_conflicting_details_without_unrelated_page_reservations():
    engine = partial_engine()
    engine._fusion.results = engine_fixture(16)._fusion.results
    engine._discovery.results.extend(engine_fixture(16)._discovery.results[2:])
    facts = [f'General information about item a, paragraph {i}.' for i in range(20)]
    facts[1] = 'Clean the item once daily.'
    facts[9] = 'Clean the item twice daily.'
    source = engine._documents['a']
    source['text'] = '\n\n'.join(facts)
    nodes, cursor = [], 0
    for i, fact in enumerate(facts):
        node = TextNode(id_=f'a-detail-{i}', text=fact, embedding=[1.0, 0.0],
            start_char_idx=cursor, end_char_idx=cursor + len(fact),
            metadata={'source_id': 'a', 'subject_source_id': 'a', 'title': source['title'],
                      'subject_title': source['title'], 'url': source['url']})
        cursor += len(fact) + 2
        engine._source_nodes[node.node_id] = engine._model_nodes[node.node_id] = node
        nodes.append(NodeWithScore(node=node, score=1.0))
    engine._scoped['a'].results = nodes

    def rerank(candidates, query_bundle):
        def score(item):
            if item.node.metadata['source_id'] == 'a' and not item.node.metadata.get('discovery_only'):
                return {facts[0]: 9.8, facts[1]: 9.0, facts[2]: 8.8, facts[9]: 8.5}.get(item.node.text, 1.0)
            return 10.0
        return sorted([NodeWithScore(node=c.node, score=score(c)) for c in candidates],
                      key=lambda item: -item.score)
    engine._reranker.postprocess_nodes = rerank
    result = engine.retrieve(CASES[0][2])
    audit = result['audit']
    assert set(audit['document_discovery']['source_ids']) == {'a', 'b'}
    assert audit['document_discovery']['detail_candidates']['a'][9] == 'a-detail-9'
    assert 'a-detail-9' in {c['node_id'] for c in audit['candidates']}
    assert facts[1] in result['context'] and facts[9] in result['context']
    assert not ({'c', 'd'} & {e['source_id'] for e in result['evidence']})
    assert audit['document_discovery']['context_policy'] == 'balanced_candidate_sources'
    assert any(e['source_id'] == 'global' for e in result['evidence'])
    assert audit['scored_pairs'] <= 64
    assert audit['generative_provider_calls'] == 0
