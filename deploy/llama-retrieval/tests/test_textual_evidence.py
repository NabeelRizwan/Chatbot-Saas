from llama_index.core.schema import TextNode
from retrieval_engine.document_nodes import has_textual_evidence, build_nodes


def test_image_and_heading_only_fragments_are_not_factual_passages():
    for text in ('## Catalog', '![](https://example.com/logo.png)',
                 '## Brand\n\n![Brand](https://example.com/a.png)', 'Loading...\n\nShow More'):
        assert not has_textual_evidence(TextNode(text=text))


def test_brief_facts_and_numbers_are_preserved():
    for text in ('$33.00', 'Gluten free', '2 capsules', '204 reviews',
                 '![Parts](https://example.com/a.png)\n\nDisconnect power first.'):
        assert has_textual_evidence(TextNode(text=text))


def test_model_topic_keeps_leaf_not_repeated_marketing_headline():
    from llama_index.core.schema import Document
    doc = Document(id_='one', text='# Catalog saves time for every customer\n\n## Returns\nReturns take 7 days.',
                   metadata={'title':'Catalog'})
    nodes = build_nodes([doc],lambda text:text.split(),128,16)
    assert nodes[-1].metadata['section']=='Returns'
