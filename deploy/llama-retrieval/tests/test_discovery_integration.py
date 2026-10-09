"""Routing/budget tests use fixed results and no learned model inference."""
from dataclasses import replace
from types import SimpleNamespace
import re

import pytest
from llama_index.core.schema import IndexNode, NodeWithScore, TextNode

from retrieval_engine.config import RetrievalConfig
from retrieval_engine.retrieval import LocalRetrievalEngine, _merge_discovered_candidates, _wants_document_discovery


def tokens(text):
    return re.findall(r'\w+|[^\w\s]', text)


def item(index, source='global'):
    return NodeWithScore(node=TextNode(id_=f'{source}-{index}', text=f'Original fact {index} for {source}.',
        metadata={'source_id': source, 'subject_source_id': source, 'title': source}, embedding=[1.0, 0.0]), score=1.0)


def test_discovery_budget_preserves48_global_and_roundrobins16_details():
    wide = [item(i) for i in range(100)]
    groups = {source: [item(i, source) for i in range(12)] for source in ('a', 'b', 'c', 'd')}
    chosen, audit = _merge_discovered_candidates(wide, groups, 64, 16)
    assert [n.node.node_id for n in chosen[:48]] == [n.node.node_id for n in wide[:48]]
    assert [n.node.metadata['source_id'] for n in chosen[48:]] == ['a', 'b', 'c', 'd'] * 4
    assert len(chosen) == 64 and audit['discovery_slots_used'] == 16


def test_discovery_overlap_and_empty_routes_use_global_fallback():
    wide = [item(i) for i in range(64)]
    for groups in ({}, {'global': wide[:4]}):
        chosen, audit = _merge_discovered_candidates(wide, groups, 64, 16)
        assert [n.node.node_id for n in chosen] == [n.node.node_id for n in wide]
        assert audit['discovery_slots_used'] == 0
    groups = {'a': [item(1, 'a')], 'b': [item(2, 'b')]}
    chosen, audit = _merge_discovered_candidates(wide, groups, 64, 16)
    assert len(chosen) == 64 and audit['discovery_slots_used'] == 2


@pytest.mark.parametrize('question,broad,expected', [
    ('What does this company sell?', False, True),
    ('Which services do they offer?', False, True),
    ('Show me the catalogue.', False, True),
    ('Give a website overview.', False, True),
    ('Which options support outdoor use?', True, False),
    ('How much does this device weigh?', False, False),
])
def test_discovery_trigger_is_generic_and_opt_in(question, broad, expected):
    assert _wants_document_discovery(question, broad) is expected


def test_discovery_configuration_is_bounded_and_fingerprinted():
    base = RetrievalConfig()
    assert base.document_discovery_slots == 16
    other = replace(base, document_discovery_slots=0)
    assert LocalRetrievalEngine(base).pipeline_provenance() != LocalRetrievalEngine(other).pipeline_provenance()
    for value in (-1, 17, True, 2.5):
        with pytest.raises(ValueError, match='discovery'):
            replace(base, document_discovery_slots=value)


class Tokenizer:
    def encode(self, text, **kwargs):
        return tokens(text)

    def __call__(self, query, passage, **kwargs):
        return {'input_ids': tokens(query + passage) + [0, 0, 0]}


class FixedRetriever:
    def __init__(self, results, *, initialize_embedding=False):
        self.results, self.calls = results, []
        self.initialize_embedding = initialize_embedding

    def retrieve(self, bundle):
        self.calls.append((bundle, bundle.embedding))
        if self.initialize_embedding:
            bundle.embedding = [1.0, 0.0]
        return self.results


def engine_fixture(slots):
    engine = LocalRetrievalEngine(RetrievalConfig(document_discovery_slots=slots, evidence_top_k=4))
    engine._state = 'ready'
    engine._tokenizer = Tokenizer()
    engine._embedding_tokenizer = SimpleNamespace(encode=lambda text: SimpleNamespace(ids=tokens(text)))
    engine._context_tokenizer = SimpleNamespace(encode=lambda text, **kwargs: tokens(text))
    engine._reranker = SimpleNamespace(postprocess_nodes=lambda candidates, query_bundle: [
        NodeWithScore(node=c.node, score=float(len(candidates)-i)) for i, c in enumerate(candidates)])
    all_groups = {'global': [item(i) for i in range(64)], **{
        source: [item(i, source) for i in range(8)] for source in ('a', 'b', 'c', 'd')}}
    for source, items in all_groups.items():
        text = '\n\n'.join(n.node.text for n in items)
        engine._documents[source] = {'id': source, 'source_id': source, 'title': source,
                                      'url': f'https://example.org/{source}', 'text': text}
        cursor = 0
        for n in items:
            n.node.start_char_idx, n.node.end_char_idx = cursor, cursor + len(n.node.text)
            n.node.metadata['url'] = engine._documents[source]['url']
            n.node.metadata['subject_title'] = source
            cursor = n.node.end_char_idx + 2
            engine._source_nodes[n.node.node_id] = n.node
            engine._model_nodes[n.node.node_id] = n.node
    engine._fusion = FixedRetriever(all_groups['global'], initialize_embedding=True)
    engine._scoped = {source: FixedRetriever(items) for source, items in all_groups.items() if source != 'global'}
    engine._discovery = FixedRetriever([NodeWithScore(node=IndexNode(id_='summary-'+source, index_id=source,
        text='SUMMARY MUST NEVER BECOME EVIDENCE', metadata={'source_id': source, 'discovery_only': True}))
        for source in ('a', 'b', 'c', 'd')])
    engine._manifest = {'corpus_sha256': 'synthetic-test-corpus', 'index_id': 'synthetic-test-index'}
    return engine


def test_full_retrieve_reuses_query_embedding_and_never_reranks_summary():
    engine = engine_fixture(16)
    result = engine.retrieve('What does this company sell?')
    assert result['audit']['scored_pairs'] == 64
    assert result['audit']['document_discovery']['source_ids'] == ['a', 'b', 'c', 'd']
    assert result['audit']['document_discovery']['embedding_reused']
    query = engine._fusion.calls[0][0]
    assert engine._discovery.calls[0][0] is query
    assert all(r.calls[0][0] is query and r.calls[0][1] == [1.0, 0.0] for r in engine._scoped.values())
    origins = [c['candidate_origin'] for c in result['audit']['candidates']]
    assert origins.count('global') == 48
    assert sum(origin.startswith('document_discovery:') for origin in origins) == 16
    assert all(not c['node_id'].startswith('summary-') for c in result['audit']['candidates'])
    assert 'SUMMARY MUST NEVER' not in result['context']


def test_disabled_discovery_calls_no_extra_retriever_and_keeps64_global():
    engine = engine_fixture(0)
    result = engine.retrieve('What does this company sell?')
    assert result['audit']['scored_pairs'] == 64
    assert not engine._discovery.calls
    assert not result['audit']['document_discovery']['enabled']
    assert all(c['candidate_origin'] == 'global' for c in result['audit']['candidates'])


class FixedPrimaryLane:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def retrieve(self, bundle, question):
        self.calls.append((bundle, question, bundle.embedding))
        return self.results, {'enabled': True, 'returned': len(self.results),
                              'generative_provider_calls': 0}


def primary_routing_fixture(discovery_slots=0):
    engine = engine_fixture(discovery_slots)
    titles = {'global': 'Everyday Equipment', 'a': 'Trail Lantern',
              'b': 'Camp Torch', 'c': 'Water Flask', 'd': 'Travel Bottle'}
    for source, title in titles.items():
        engine._documents[source]['title'] = title
    for node in engine._source_nodes.values():
        title = titles[node.metadata['source_id']]
        node.metadata.update(title=title, subject_title=title)
    primary = [*engine._scoped['c'].results, *engine._scoped['d'].results]
    for candidate in primary:
        candidate.node.metadata['evidence_role'] = 'PRIMARY'
    engine._primary = {source: FixedPrimaryLane(primary) for source in titles}
    return engine


@pytest.mark.parametrize('question', [
    'What is Trail Lantern made from?',
    'How many batteries does Trail Lantern use?',
    'What types of bulbs does Trail Lantern use?',
    'Which materials are used in Trail Lantern?',
    'What is the voltage range of Trail Lantern?',
])
def test_precise_questions_keep_global_pool_without_querying_primary(question):
    engine = primary_routing_fixture(16)
    result = engine.retrieve(question)
    assert all(not lane.calls for lane in engine._primary.values())
    assert not engine._discovery.calls
    assert not result['audit']['primary_candidate_lane']
    assert result['audit']['scored_pairs'] == 64
    assert [row['node_id'] for row in result['audit']['candidates']] == [
        candidate.node.node_id for candidate in engine._fusion.results]


@pytest.mark.parametrize('question', [
    'Compare Trail Lantern and Camp Torch for outdoor use.',
    'Which option should I choose between Trail Lantern and Camp Torch?',
    'Compare the types of bulbs in Trail Lantern and Camp Torch.',
])
def test_named_comparisons_query_only_normal_subject_lanes(question):
    engine = primary_routing_fixture(16)
    result = engine.retrieve(question)
    assert set(result['audit']['query_hints']['comparison_source_ids']) == {'a', 'b'}
    assert all(not lane.calls for lane in engine._primary.values())
    assert not engine._discovery.calls
    assert not result['audit']['primary_candidate_lane']
    assert set(result['audit']['scoped_queries']) == {'a/0', 'b/1'}
    assert len(engine._scoped['a'].calls) == len(engine._scoped['b'].calls) == 1
    assert not engine._scoped['c'].calls and not engine._scoped['d'].calls
    assert 0 < result['audit']['scored_pairs'] <= 64
    assert {row['source_id'] for row in result['audit']['candidates']} == {'a', 'b'}


@pytest.mark.parametrize('discovery_slots', [0, 16])
@pytest.mark.parametrize('question', [
    'What does this company sell?',
    'Show me the catalogue.',
])
def test_catalogue_queries_use_primary_within_shared_pair_budget(question, discovery_slots):
    engine = primary_routing_fixture(discovery_slots)
    result = engine.retrieve(question)
    assert len(engine._primary['global'].calls) == 1
    assert all(not lane.calls for source, lane in engine._primary.items() if source != 'global')
    bundle, original_question, embedding = engine._primary['global'].calls[0]
    assert bundle is engine._fusion.calls[0][0]
    assert original_question == question and embedding == [1.0, 0.0]
    primary = result['audit']['primary_candidate_lane']['global']['merge']
    assert primary['primary_lane_slots'] == 16
    assert result['audit']['scored_pairs'] == result['audit']['unique_candidates'] == 64
    origins = [row['candidate_origin'] for row in result['audit']['candidates']]
    assert 0 < origins.count('primary') <= 16
    assert sum(origin.startswith('document_discovery:') for origin in origins) == discovery_slots
    assert 'SUMMARY MUST NEVER' not in result['context']


def test_broad_options_with_exclusion_keep_primary_but_filter_rejected_subject():
    engine = primary_routing_fixture()
    result = engine.retrieve('Can you suggest portable options? No travel bottles for me.')
    assert result['audit']['query_hints']['excluded_title_terms']
    assert len(engine._primary['global'].calls) == 1
    assert result['audit']['scored_pairs'] == 64
    primary_rows = [row for row in result['audit']['candidates'] if row['candidate_origin'] == 'primary']
    assert primary_rows and {row['source_id'] for row in primary_rows} == {'c'}
    assert all(row['subject_source_id'] != 'd' for row in result['audit']['candidates'])


def test_discovery_persistence_roundtrip_uses_mock_embeddings_only(tmp_path, monkeypatch):
    from llama_index.core.embeddings import MockEmbedding
    from llama_index.core.llms import MockLLM
    from llama_index.core.schema import Document, QueryBundle
    from retrieval_engine.document_nodes import build_nodes

    doc = Document(id_='record-a', text='# Product Description\nThis ceramic light has a replaceable battery for portable outdoor use.',
                   metadata={'source_id': 'a', 'title': 'Portable light', 'url': 'https://example.org/a'})
    raw = build_nodes([doc], tokens, 128, 12)

    def prepared():
        engine = LocalRetrievalEngine(RetrievalConfig(document_discovery_slots=16))
        engine._embedding = MockEmbedding(embed_dim=8)
        engine._tokenizer = Tokenizer()
        engine._embedding_tokenizer = SimpleNamespace(encode=lambda text: SimpleNamespace(ids=tokens(text)))
        engine._source_nodes = {n.node_id: n for n in raw}
        engine._manifest = {'index_id': 'parent', 'corpus_sha256': 'fixture'}
        engine._pipeline_artifacts = {'embedding_file_sha256': 'mock', 'packages': {}}
        return engine

    first = prepared()
    first._build_or_load_discovery([doc], tmp_path, MockLLM())
    assert first._discovery_manifest['summary_count'] == 1
    assert list(tmp_path.glob('discovery/*/manifest.json'))
    monkeypatch.setattr(MockEmbedding, 'get_text_embedding_batch', lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError('Persisted summaries must not be re-embedded.')))
    loaded = prepared()
    loaded._build_or_load_discovery([doc], tmp_path, MockLLM())
    results = loaded._discovery.retrieve(QueryBundle('portable light', embedding=[0.1] * 8))
    assert results and isinstance(results[0].node, IndexNode)
    assert results[0].node.index_id == 'a'
    assert loaded._discovery_manifest == first._discovery_manifest
