from dataclasses import replace
from types import SimpleNamespace

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from retrieval_engine.adaptive_evidence import (
    anchors_without_primary_evidence, preserve_retrieved_anchor_spans,
    evidence_limits, ranking_projection, retain_source_and_detail,
    routing_hints, scoped_query,
)
from retrieval_engine.config import RetrievalConfig
from retrieval_engine.local_reranker import BatchedPredictor
from retrieval_engine.evidence_context import ContextBudgetExceeded, fit_evidence_context
from test_evidence_context import fixture, selected, tokens, assert_exact


def docs(*titles):
    return [{'source_id': str(i), 'title': title} for i, title in enumerate(titles)]


def test_list_routes_distinct_entities_without_comparison_keyword():
    hints = routing_hints('Which runs on batteries: Aurora Lantern, Summit Radio and Ridge Beacon?',
                          docs('Aurora Lantern', 'Summit Radio', 'Ridge Beacon'))
    assert set(hints.comparison_source_ids) == {'0', '1', '2'}


def test_single_family_variant_does_not_become_two_entities():
    hints = routing_hints('Is the green Alpine table large enough for four people?',
                          docs('Alpine table green', 'Alpine table white'))
    assert not hints.comparison_source_ids


def test_unique_model_aliases_allow_short_names_and_missing_accents():
    titles = docs('LÜMA portable torch', 'NOVA table lamp', 'SÖLAR floor light')
    hints = routing_hints('Which have replaceable batteries: luma, NOVA and SOLAR?', titles)
    assert hints.comparison_source_ids == ('0', '1', '2')
    from retrieval_engine.query_constraints import focused_query
    focus = focused_query('Compare LUMA and NOVA on battery life.', titles[0]['title'],
                          [titles[0]['title'], titles[1]['title']])
    assert 'NOVA' not in focus and 'battery life' in focus


def test_shared_model_alias_and_incidental_title_words_are_not_unique():
    titles = docs('NOVA lamp green', 'NOVA lamp white', 'LÜMA torch', 'Case for LÜMA')
    assert not routing_hints('Tell me about NOVA and LUMA.', titles).comparison_source_ids


def test_single_entity_material_question_does_not_trigger_document_discovery():
    hints = routing_hints('Which materials are used in Trail Lantern?',
                          docs('Trail Lantern', 'Summit Radio'))
    assert not hints.broad_discovery


def test_adaptive_limits_are_bounded_and_do_not_mutate_config():
    config = RetrievalConfig()
    assert evidence_limits(config, 0, False) == (64, 12)
    assert evidence_limits(config, 2, False) == (96, 16)
    assert evidence_limits(config, 0, True) == (64, 16)
    assert (config.rerank_candidates, config.evidence_top_k) == (64, 12)
    limited = replace(config, retriever_top_k=8, rerank_candidates=16, evidence_top_k=4)
    assert evidence_limits(limited, 4, False) == (16, 16)
    assert evidence_limits(replace(config, adaptive_evidence=False), 4, True) == (64, 12)


def test_ambiguous_focus_omits_only_redundant_title():
    titles = ['Alpine table green', 'Alpine table white']
    question = 'Do the green and white Alpine tables both seat four?'
    assert scoped_query(question, titles[0], titles, titles[0] + '. ' + question) == (question, True)
    question = 'Compare Aurora Lantern and Summit Radio on battery life.'
    focus = 'Aurora Lantern. on battery life.'
    assert scoped_query(question, 'Aurora Lantern', ['Aurora Lantern', 'Summit Radio'], focus) == (focus, False)


def test_rank_projection_does_not_mutate_source_or_metadata():
    original = NodeWithScore(node=TextNode(text='document_title: Device\nsection: Voltage\n220 V',
                             metadata={'source_id': 'a', 'title': 'Device'}), score=1)
    projected = ranking_projection([original], True)[0]
    assert projected.node.text == 'section: Voltage\n220 V'
    assert original.node.text.startswith('document_title:')
    assert projected.node.node_id == original.node.node_id
    assert projected.node.metadata == original.node.metadata


def test_primary_descriptions_and_details_remain_scored_original_nodes():
    ranked = [NodeWithScore(node=TextNode(id_=str(i), text=f'Fact {i}',
               metadata={'source_id': str(i // 2)}), score=9-i) for i in range(6)]
    kept = retain_source_and_detail(ranked, list(reversed(ranked)), {'0': ['0'], '1': ['2']}, 4)
    assert [r.node.node_id for r in kept] == ['0', '2', '1', '3']
    assert all(r in ranked for r in kept)
    assert not retain_source_and_detail(ranked, ranked, {'0': ['fabricated']}, 0)


def test_description_reservation_preserves_existing_source_span_and_neighbors():
    def node(node_id, source, start):
        return NodeWithScore(node=TextNode(id_=node_id, text='Voltage: 12 V',
            start_char_idx=start, end_char_idx=start+13,
            metadata={'source_id':source,'evidence_role':'PRIMARY'}),score=2)
    first=node('first','device',100)
    duplicate=node('later','device',500)
    anchor=node('anchor','device',800)
    other=node('other','different-device',100)
    result=preserve_retrieved_anchor_spans([first,duplicate],[anchor,other])
    assert result[0] is first
    assert result[0].node.start_char_idx==100
    assert result[1] is other
    assert anchor.node.start_char_idx==800


def test_comparison_reservations_only_fill_missing_primary_subjects():
    selected=[NodeWithScore(node=TextNode(text='Verified detail',metadata={
        'source_id':'catalogue','subject_source_id':'device-a','evidence_role':'PRIMARY'})),
        NodeWithScore(node=TextNode(text='Review opinion',metadata={
        'source_id':'device-b','evidence_role':'REVIEW'}))]
    anchors={'device-a':['a'], 'device-b':['b']}
    assert anchors_without_primary_evidence(selected,anchors)=={'device-b':['b']}
    assert anchors=={'device-a':['a'], 'device-b':['b']}


def test_budget_fallback_keeps_whole_cores_and_reports_omissions():
    documents, mapping, nodes = fixture(['First complete fact.', ' '.join(['long'] * 200), 'Last complete fact.'])
    result = fit_evidence_context(selected(*nodes), mapping, documents, tokens, 110, 3)
    assert nodes[1].node_id in result['audit']['omitted_core_node_ids']
    assert nodes[0].node_id in result['audit']['selected_core_node_ids']
    assert nodes[2].node_id in result['audit']['selected_core_node_ids']
    assert result['context_tokens'] <= 110
    assert_exact(result, documents)


def test_budget_fallback_does_not_swallow_invalid_provenance():
    documents, mapping, nodes = fixture(['One fact.'])
    nodes[0].start_char_idx = 1000
    with pytest.raises(ValueError):
        fit_evidence_context(selected(*nodes), mapping, documents, tokens, 1, 1)


def test_unusable_budget_is_explicit():
    documents, mapping, nodes = fixture(['One fact.'])
    with pytest.raises(ContextBudgetExceeded):
        fit_evidence_context(selected(*nodes), mapping, documents, tokens, 1, 1)


def test_batch_adapter_delegates_without_changing_pairs_or_scores():
    calls = []
    model = SimpleNamespace(tokenizer=lambda *a, **kw: {'input_ids': [[1, 2]]},
                            predict=lambda pairs, **kw: calls.append((pairs, kw)) or [2.7])
    adapter = BatchedPredictor(model, 4)
    pairs = [('question', 'passage')]
    assert adapter.predict(pairs) == [2.7]
    assert calls == [(pairs, {'batch_size': 4, 'show_progress_bar': False})]


def test_batch_adapter_rejects_truncation_before_inference():
    model = SimpleNamespace(tokenizer=lambda *a, **kw: {'input_ids': [list(range(513))]},
                            predict=lambda *a, **kw: pytest.fail('Inference must not run'))
    with pytest.raises(ValueError, match='truncated'):
        BatchedPredictor(model, 4).predict([('question', 'passage')])
