import copy
import re

import pytest
from llama_index.core.base.base_retriever import BaseRetriever
from llama_index.core.retrievers import RecursiveRetriever
from llama_index.core.schema import Document, IndexNode, MetadataMode, NodeWithScore, TextNode

from retrieval_engine.config import RetrievalConfig
from retrieval_engine.document_discovery import build_discovery_nodes, ranked_source_ids, source_scope_filters
from retrieval_engine.document_nodes import build_nodes

RetrievalConfig().apply_runtime_environment()


def tokens(text):
    return re.findall(r"\w+|[^\w\s]", text)


def document(source_id, text, title="A generic page"):
    return Document(id_="record-" + source_id, text=text,
                    metadata={"source_id": source_id, "title": title, "url": "https://example.org/?id=" + source_id})


def summaries(documents, **kwargs):
    raw = build_nodes(documents, tokens, 128, 12)
    return build_discovery_nodes(documents, raw, tokens, **kwargs), raw


def assert_exact(summary, document):
    assert summary.index_id == document.metadata['source_id']
    assert summary.metadata['answer_evidence'] is False
    assert summary.start_char_idx is None and summary.end_char_idx is None
    assert len(tokens(summary.get_content(metadata_mode=MetadataMode.EMBED))) <= summary.metadata['max_summary_tokens']
    for witness in summary.metadata['discovery_witnesses']:
        assert witness['text'] == document.text[witness['start_char']:witness['end_char']]
        assert witness['text'] in summary.text
    title = summary.metadata['title_provenance']
    assert title['text'] == document.metadata['title'][title['start_char']:title['end_char']]


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_extracts_exact_title_headings_description_and_preserves_unicode(newline):
    text = newline.join(['# Résumé 茶', '', '## Product Description', '',
        'The ceramic device uses a rechargeable battery and produces 150 lumens.', '',
        '## Dimensions', '', 'The device measures 12 cm across and weighs 400 grams.', '',
        '## Customer Reviews', '', 'Best device ever; this made my whole week much better.'])
    doc = document('a', text, 'Résumé 茶 device')
    before = doc.model_dump()
    result, raw = summaries([doc])
    assert len(result) == 1
    assert_exact(result[0], doc)
    assert '150 lumens' in result[0].text
    assert 'Best device ever' not in result[0].text
    assert 'Customer Reviews' not in result[0].text
    assert result[0].metadata['description_basis'] == 'PRIMARY'
    assert doc.model_dump() == before


def test_foreign_cross_sell_is_not_host_summary_and_unknown_keeps_lead_prose():
    a = document('a', '# Catalog\nA catalog of portable lights with rechargeable batteries and replaceable covers.\n\n'
                 '## [Other device](https://example.org/?id=b)\nThe other device has a purple metal housing and a mains cable.\n\n'
                 '### Dimensions\nThe other device weighs three kilograms and needs a large shelf.', 'Catalog')
    b = document('b', '# Device B\nThe separate device page contains original specifications for the second item.', 'Device B')
    result, raw = summaries([a, b])
    assert 'rechargeable batteries' in result[0].text
    assert 'purple' not in result[0].text and 'three kilograms' not in result[0].text
    assert result[0].metadata['description_basis'] == 'UNKNOWN_LEAD'
    assert_exact(result[0], a)


def test_long_review_section_cannot_dominate_summary_even_when_late_description():
    doc = document('a', '# Device\n## Customer Reviews\n' + 'This is the best item I have ever owned. ' * 500
                   + '\n\n## Product Description\nThe actual device includes a ceramic housing and a rechargeable battery rated for ten hours.')
    result, raw = summaries([doc], max_tokens=100, max_description_tokens=50)
    assert 'ceramic housing' in result[0].text
    assert 'best item' not in result[0].text
    assert_exact(result[0], doc)


def test_empty_unknown_and_title_only_fallbacks_are_explicit():
    empty = document('empty', ' \n ')
    plain = document('plain', 'This service handles file uploads and converts office documents into searchable text.')
    review = document('review', '# Customer Reviews\nI found this device easy to carry and pleasant to use.', 'Review collection')
    result, raw = summaries([empty, plain, review])
    assert [item.index_id for item in result] == ['plain', 'review']
    assert result[0].metadata['description_basis'] == 'UNKNOWN_LEAD'
    assert result[1].metadata['description_basis'] == 'NONE'
    assert result[1].text == 'Title: Review collection'
    assert result[1].metadata['discovery_witnesses'] == []
    assert ranked_source_ids([], ['plain'], max_sources=3) == []


def test_budgets_long_title_duplicate_headings_and_determinism():
    doc = document('a', '# A page\n' + '\n\n'.join('## Repeated heading\nThe corresponding paragraph has useful factual details about this service.' for _ in range(30)),
                   'Long original descriptive title ' * 100)
    first, raw = summaries([doc], max_tokens=96, max_description_tokens=35, max_headings=3)
    before = copy.deepcopy(raw)
    second = build_discovery_nodes([doc], {n.node_id: n for n in raw}, tokens, max_tokens=96,
                                   max_description_tokens=35, max_headings=3)
    assert first[0].model_dump() == second[0].model_dump()
    assert raw == before
    assert first[0].text.count('Heading: ## Repeated heading') == 1
    assert_exact(first[0], doc)


def test_unknown_external_links_do_not_become_summary_fact_content():
    doc = document('a', '# Manual\n[Support Center](https://outside.example/support)\n\n'
                   '![A giant unsupported infographic](https://images.example/a.png)\n\n'
                   'The manual explains device charging and maintenance in clear numbered sections.')
    result, raw = summaries([doc])
    assert 'outside.example' not in result[0].text
    assert 'infographic' not in result[0].text
    assert 'charging and maintenance' in result[0].text


def test_non_whitespace_language_keeps_exact_unknown_prose():
    doc = document('zh', '# 使用说明\n这款便携式设备采用可充电电池和陶瓷外壳，每次充电后可以连续使用十小时。', '便携设备使用说明')
    result, raw = summaries([doc])
    assert '可以连续使用十小时' in result[0].text
    assert result[0].metadata['description_basis'] == 'UNKNOWN_LEAD'
    assert_exact(result[0], doc)


def test_ranked_routes_are_ordered_deduplicated_bounded_and_not_fabricated():
    docs = [document(str(i), 'This page has useful source text for checking routing and retrieval.') for i in range(3)]
    nodes, _ = summaries(docs)
    ranked = [NodeWithScore(node=nodes[2], score=0.1), NodeWithScore(node=nodes[2], score=5),
              NodeWithScore(node=nodes[0], score=4), NodeWithScore(node=nodes[1], score=3)]
    assert ranked_source_ids(ranked, ['0', '1', '2'], max_sources=2) == ['2', '0']
    assert ranked_source_ids(ranked, ['0', '1'], max_sources=2) == ['0', '1']
    assert ranked_source_ids(ranked, ['0'], max_sources=0) == []
    with pytest.raises(ValueError):
        ranked_source_ids([NodeWithScore(node=TextNode(text='fake source'))], ['0'], max_sources=1)
    forged = nodes[0].model_copy(deep=True); forged.index_id = '2'
    with pytest.raises(ValueError):
        ranked_source_ids([NodeWithScore(node=forged)], ['0', '2'], max_sources=1)


def test_official_metadata_filters_require_source_and_subject():
    filters = source_scope_filters('source-with-query-id')
    assert filters.condition.value == 'and'
    assert [(f.key, f.value, f.operator.value) for f in filters.filters] == [
        ('source_id', 'source-with-query-id', '=='), ('subject_source_id', 'source-with-query-id', '==')]


class FixedRetriever(BaseRetriever):
    def __init__(self, results):
        super().__init__()
        self.results, self.queries = results, []

    def _retrieve(self, query_bundle):
        self.queries.append(query_bundle.query_str)
        return self.results


def test_official_recursive_retriever_follows_index_routes_without_summary_answers():
    docs = [document(str(i), f'Original source {i} contains the actual detailed information for the question.') for i in range(2)]
    index_nodes, raw = summaries(docs)
    root = FixedRetriever([NodeWithScore(node=n, score=0.5) for n in index_nodes])
    details = {d.metadata['source_id']: FixedRetriever([NodeWithScore(node=next(n for n in raw if n.metadata['source_id'] == d.metadata['source_id']), score=1.0)]) for d in docs}
    recursive = RecursiveRetriever(root_id='root', retriever_dict={'root': root, **details})
    results = recursive.retrieve('Which sources contain the details?')
    assert {item.node.node_id for item in results} == {node.node_id for node in raw}
    assert all(not isinstance(item.node, IndexNode) for item in results)
    assert all(child.queries == ['Which sources contain the details?'] for child in details.values())


def test_source_provenance_and_duplicate_ids_fail_closed():
    doc = document('a', 'This page has useful content for an integrity validation fixture.')
    raw = build_nodes([doc], tokens, 128, 12)
    raw[0].text += ' fabricated'
    with pytest.raises(ValueError, match='provenance'):
        build_discovery_nodes([doc], raw, tokens)
    with pytest.raises(ValueError, match='unique'):
        build_discovery_nodes([doc, doc], [], tokens)
    with pytest.raises(ValueError, match='at least'):
        build_discovery_nodes([doc], [], tokens, max_tokens=32)
