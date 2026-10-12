"""Provenance and structure checks for the official-parser source adapter."""

import json
import re

import pytest
from llama_index.core.schema import Document, MetadataMode, NodeRelationship, TextNode

from retrieval_engine.config import RetrievalConfig
from retrieval_engine.document_nodes import build_nodes, model_text, has_textual_evidence

RetrievalConfig().apply_runtime_environment()


def tokenize(text):
    return re.findall(r"\w+|[^\w\s]", text)


def document(text, id_="doc", title="A source"):
    return Document(id_=id_, text=text, metadata={"source_id": id_, "title": title, "url": "https://example.org/"})


def assert_provenance(doc, nodes):
    for node in nodes:
        assert doc.text[node.start_char_idx:node.end_char_idx] == node.text
        assert node.source_node.node_id == doc.id_
        assert len(tokenize(node.get_content(metadata_mode=MetadataMode.EMBED))) <= 128


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("separator", [" ", "\t", "  "])
def test_unicode_duplicate_heading_offsets(newline, separator):
    text = newline.join([
        "#" + separator + "Résumé 🐈", "", "##" + separator + "问答",
        "Same answer. Café costs €8.", "", "##" + separator + "问答",
        "Same answer. Café costs €8.", "", "### Shipping", "日本 ships tomorrow.",
    ])
    doc = document(text)
    nodes = build_nodes([doc], tokenize, 128, 12)
    assert_provenance(doc, nodes)
    duplicates = [node for node in nodes if "Same answer" in node.text]
    assert len(duplicates) == 2
    assert duplicates[0].start_char_idx < duplicates[1].start_char_idx
    assert duplicates[0].node_id != duplicates[1].node_id
    assert all("问答" in node.metadata["section"] for node in duplicates)


def test_faq_and_review_binding_remain_together():
    text = """# Device
## Can I use it outdoors?
Yes, but keep it dry and below 30°C.

## Mild flavour
I mix this powder into my morning drink.

[View Product](https://example.org/products/green-powder)

## Other feedback
A different review.
"""
    doc = document(text)
    nodes = build_nodes([doc], tokenize, 128, 12)
    assert_provenance(doc, nodes)
    faq = next(node for node in nodes if "Can I" in node.text)
    assert "below 30°C" in faq.text
    review = next(node for node in nodes if "morning drink" in node.text)
    assert "products/green-powder" in review.text
    assert "products/green-powder" in model_text(review)
    assert "different review" not in review.text


def test_tables_links_and_code_are_not_rewritten_in_evidence():
    doc = document("""# Specifications
| Item | Count |
| --- | --- |
| Café | 12 |
| 茶 | 3 |

[Manual](https://example.org/manual?a=1&b=2)

```python
# this is code, not a heading
value = 'é'
```
""")
    nodes = build_nodes([doc], tokenize, 128, 12)
    assert_provenance(doc, nodes)
    assert any("| 茶 | 3 |" in node.text for node in nodes)
    assert any("# this is code" in node.text for node in nodes)
    assert all("# this is code" not in node.metadata["section"] for node in nodes)


def test_tilde_code_fence_falls_back_without_false_section_metadata():
    doc = document("# Outside\n~~~text\n# Not a section\n~~~\nFinal fact.")
    nodes = build_nodes([doc], tokenize, 128, 12)
    assert_provenance(doc, nodes)
    assert len(nodes) == 1
    assert nodes[0].metadata["node_parser"] == "sentence_fallback"
    assert nodes[0].metadata["section"] == ""
    assert "Not a section" in nodes[0].text


def test_long_section_overlaps_without_forging_offsets():
    text = "# Long document\n## Instructions\n" + "\n\n".join(
        f"Step {index}: Keep the item dry. Always disconnect the power first."
        for index in range(30)
    )
    doc = document(text)
    nodes = build_nodes([doc], tokenize, 128, 16)
    assert_provenance(doc, nodes)
    assert len(nodes) > 3
    assert all(node.metadata["section"] == "Instructions" for node in nodes[1:])
    starts = [node.start_char_idx for node in nodes]
    assert starts == sorted(set(starts))
    assert any(a.end_char_idx > b.start_char_idx for a, b in zip(nodes, nodes[1:]))


def test_model_view_removes_image_urls_but_preserves_facts_and_destinations():
    node = TextNode(text="""![Ingredient chart](https://cdn.test/huge-image.png?width=2048)

[View Product](https://shop.test/products/device)
[View Product](https://shop.test/products/device)

Do not exceed 2 servings. Payment is due in 30 days.
Do not exceed 2 servings. Payment is due in 30 days.
""")
    original = node.text
    view = model_text(node)
    assert "Ingredient chart" in view
    assert "huge-image" not in view
    assert view.count("https://shop.test/products/device") == 1
    assert view.count("Payment is due in 30 days") == 2
    assert node.text == original


def test_separate_reviews_keep_each_product_footer_even_when_destination_repeats():
    link = "[View Product](https://shop.test/products/device)"
    node = TextNode(text=f"First reviewer liked it.\n\n{link}\n\nSecond reviewer disliked it.\n\n{link}")
    view = model_text(node)
    assert view.count("https://shop.test/products/device") == 2


def test_source_metadata_unmodified_and_visible_metadata_bounded():
    doc = document("# " + "Heading " * 90 + "\nA useful answer.", title="Title " * 90)
    before = doc.model_dump()
    nodes = build_nodes([doc], tokenize, 128, 8)
    assert_provenance(doc, nodes)
    assert doc.model_dump() == before
    assert all(node.metadata["title"] == doc.metadata["title"] for node in nodes)
    assert all(len(tokenize(node.metadata["document_title"])) <= 12 for node in nodes)
    assert all(len(tokenize(node.metadata["section"])) <= 12 for node in nodes)


def test_deterministic_ids_and_relationships_do_not_cross_documents():
    docs = [document("# Same\nIdentical text.\n## End\nMore text.", id_=str(index)) for index in range(2)]
    first = build_nodes(docs, tokenize, 128, 8)
    second = build_nodes(docs, tokenize, 128, 8)
    assert [node.id_ for node in first] == [node.id_ for node in second]
    assert len({node.id_ for node in first}) == len(first)
    assert NodeRelationship.NEXT not in first[1].relationships
    assert NodeRelationship.PREVIOUS not in first[2].relationships
    roundtrip = TextNode.from_dict(json.loads(first[0].json()))
    assert roundtrip.text == first[0].text
    assert roundtrip.start_char_idx == first[0].start_char_idx


def test_reject_duplicate_document_ids():
    with pytest.raises(ValueError, match="unique"):
        build_nodes([document("A"), document("B")], tokenize, 128, 8)


@pytest.mark.parametrize('action', ['Add to wishlist', 'ADD TO WISH LIST', 'Add to cart', 'Remove from basket'])
def test_product_photo_and_matching_action_are_not_index_evidence(action):
    text = ('[![Portable Device](https://cdn.example.org/photo.jpg)]'
            '(https://example.org/products/device)\n\n'
            f'[{action} Portable Device](https://example.org/#)')
    node = TextNode(text=text, metadata={'title': 'Unrelated host page'})
    before = node.model_dump()
    assert not has_textual_evidence(node)
    assert node.model_dump() == before


@pytest.mark.parametrize('text', [
    '![Rated output: 12 V, 2 A](https://example.org/chart.png)',
    '![Each serving contains 250 mg.](https://example.org/label.png)',
    '![Dimensions 12 cm x 8 cm](https://example.org/dimensions.png)',
    '[Warranty lasts 2 years](https://example.org/warranty)',
    '[Add to cart. Ships in 2 days.](https://example.org/cart)',
    '[Add to wishlist Device costs $12](https://example.org/#)',
    'Read more about the 30-day return policy.',
    '12 reviews', '$9.50', 'Gluten free', '2 capsules',
    '材料：再生アルミニウム',
])
def test_navigation_filter_retains_short_facts_and_factual_alt_text(text):
    assert has_textual_evidence(TextNode(text=text))


def test_navigation_filter_keeps_review_with_its_product_link():
    text = ('I used it daily and found the handle comfortable.\n\n'
            '[View Product](https://example.org/products/device)\n\nLoading...')
    node = TextNode(text=text)
    assert has_textual_evidence(node)
    assert 'https://example.org/products/device' in model_text(node)


def test_generic_customer_image_control_is_not_a_factual_sentence():
    node = TextNode(text='![Customer-uploaded image. Click to see more details.](https://example.org/photo.jpg)')
    assert not has_textual_evidence(node)


def test_closed_card_following_photo_stays_in_raw_nodes_but_is_not_indexed():
    text = ('# Host\n\n## [Device](https://example.org/products/device)\n\n'
            'The ceramic casing resists scratches during everyday use.\n\n'
            '[View product](https://example.org/products/device)\n\n'
            '[![Other Device](https://cdn.example.org/other.jpg)]'
            '(https://example.org/products/other)\n\n'
            '[Add to wishlist Other Device](https://example.org/#)\n\n'
            '## [Other Device](https://example.org/products/other)\n\n'
            'This version has a replaceable battery and a steel enclosure.')
    doc = document(text)
    nodes = build_nodes([doc], tokenize, 128, 12)
    assert_provenance(doc, nodes)
    leading = next(n for n in nodes if 'Add to wishlist' in n.text)
    assert not has_textual_evidence(leading)
    assert 'other.jpg' in leading.text and leading.metadata['subject_source_id'] == 'doc'
    assert any(has_textual_evidence(n) and 'steel enclosure' in n.text for n in nodes)
    # Every original non-whitespace character still belongs to a raw node.
    covered = {i for n in nodes for i in range(n.start_char_idx, n.end_char_idx)}
    assert all(i in covered for i, char in enumerate(doc.text) if not char.isspace())


def test_empty_documents_and_invalid_limits():
    assert build_nodes([document(" \n ")], tokenize, 128, 8) == []
    with pytest.raises(ValueError):
        build_nodes([document("A")], tokenize, 128, 128)


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_plain_labels_separate_checkout_from_descriptions_and_instructions(newline):
    text = newline.join([
        "# Everyday Device", "", "Choose an option", "", "$49.00", "", "Visa", "", "Digital Wallet", "",
        "Technical Description", "",
        "The device uses a ceramic housing and a replaceable rechargeable battery designed for everyday indoor use.", "",
        "Use & Care", "",
        "Connect the included cable and charge the device fully before use. Keep the charging socket dry.", "",
        "Dimensions", "", "- Width: 12 cm", "- Height: 8 cm", "",
    ])
    doc = document(text)
    nodes = build_nodes([doc], tokenize, 128, 12)
    assert_provenance(doc, nodes)
    description = next(node for node in nodes if "ceramic housing" in node.text)
    directions = next(node for node in nodes if "Connect the included cable" in node.text)
    assert "Technical Description" in description.text and description.metadata["section"] == "Technical Description"
    assert "Visa" not in description.text and "$49.00" not in description.text
    assert "Use & Care" in directions.text and directions.metadata["section"] == "Use & Care"
    assert "ceramic housing" not in directions.text
    assert any("Width: 12 cm" in node.text and "Height: 8 cm" in node.text for node in nodes)
    for node in nodes:
        if node.next_node:
            following = next(item for item in nodes if item.node_id == node.next_node.node_id)
            assert following.start_char_idx > node.start_char_idx


def test_wrapped_headings_and_bold_faq_preserve_literal_source_and_local_topic():
    doc = document("""# Catalog
**## Device Materials**

**The housing uses recycled aluminium with silicone seals around the charging socket.**

**### Frequently Asked Questions**

**Which battery sizes can I use?**

**This device takes either an AA or AAA rechargeable battery when fitted with the included adapter.**

**How should it be stored?**

**Keep the device indoors away from direct sunlight and remove the battery before long term storage.**
""")
    nodes = build_nodes([doc], tokenize, 128, 12)
    assert_provenance(doc, nodes)
    battery = next(node for node in nodes if "included adapter" in node.text)
    assert battery.metadata["section"] == "Which battery sizes can I use?"
    assert "**Which battery sizes can I use?**" in battery.text
    assert "recycled aluminium" not in battery.text and "long term storage" not in battery.text
    materials = next(node for node in nodes if "recycled aluminium" in node.text)
    assert materials.metadata["section"] == "Device Materials"
    assert "**## Device Materials**" in materials.text


def test_standalone_short_sentences_and_reference_links_are_not_promoted():
    doc = document("""# Customer story
I like it.

It works well

After a month of normal use, the battery still lasts a full day of travel.

[View Product](https://example.org/device)
""")
    nodes = build_nodes([doc], tokenize, 128, 12)
    assert_provenance(doc, nodes)
    assert len(nodes) == 1
    assert "It works well" in nodes[0].text and "View Product" in nodes[0].text


def test_list_to_prose_boundary_does_not_drop_list_or_following_fact():
    doc = document("""# Policies
- Card payment
- Mobile payment
- Cash on collection

The warranty lasts for two years and covers manufacturing defects under normal indoor use.
""")
    nodes = build_nodes([doc], tokenize, 128, 12)
    assert_provenance(doc, nodes)
    prose = next(node for node in nodes if "warranty lasts" in node.text)
    assert "Card payment" not in prose.text
    assert any("Card payment" in node.text and "Cash on collection" in node.text for node in nodes)


def test_pseudo_headings_in_code_and_nested_lists_are_not_promoted():
    doc = document("""# Examples
```markdown
**## This is literal code**
```

- **## Nested list text**
- A second item.
""")
    nodes = build_nodes([doc], tokenize, 128, 12)
    assert_provenance(doc, nodes)
    assert len(nodes) == 1
    assert nodes[0].metadata["section"] == "Examples"


def test_single_wrapped_heading_gets_local_metadata():
    doc = document("**## Charging Instructions**\n\nUse the supplied cable to charge the battery fully before its first use.")
    nodes = build_nodes([doc], tokenize, 128, 12)
    assert len(nodes) == 1
    assert nodes[0].metadata["section"] == "Charging Instructions"
    assert_provenance(doc, nodes)


def subject_document(source_id, title, text, url):
    return Document(id_=f"record-{source_id}", text=text,
                    metadata={"source_id": source_id, "title": title, "url": url})


def test_known_linked_heading_subject_uses_target_identity_but_keeps_source_provenance():
    base_url = "https://shop.example/products/a"
    a = subject_document("a", "Alpha Device", """# [Alpha Device](https://shop.example/products/a#top)
Alpha has an aluminium housing and a rechargeable battery for everyday travel.

### [Beta Device](https://shop.example/products/b#details)
Beta has a ceramic housing and a removable battery for indoor use.

Technical Description

This additional explanation belongs to the linked card and describes its replaceable silicone seal.

### Use Instructions
Charge Alpha with its supplied cable before taking it outside for the first time.
""", base_url)
    b = subject_document("b", "Beta Device", "# Beta Device\nA separate product document.",
                         "https://shop.example/products/b")
    c = subject_document("c", "Gamma Device", "# Gamma Device\nAnother separate product document.",
                         "https://shop.example/products/c")
    before = [doc.model_dump() for doc in (a, b, c)]
    nodes = build_nodes([a, b, c], tokenize, 128, 12)
    by_source = [node for node in nodes if node.metadata["source_id"] == "a"]
    assert_provenance(a, by_source)
    beta = next(node for node in by_source if "ceramic housing" in node.text)
    assert beta.metadata["subject_source_id"] == "b"
    assert beta.metadata["subject_title"] == "Beta Device"
    assert beta.metadata["document_title"] == "Beta Device"
    assert beta.metadata["title"] == "Alpha Device" and beta.metadata["url"] == base_url
    assert "https://shop.example/products/b#details" in beta.text
    assert "document_title: Beta Device" in model_text(beta)
    assert next(node for node in by_source if "replaceable silicone seal" in node.text).metadata["subject_source_id"] == "b"
    for phrase in ("Alpha has", "Charge Alpha"):
        assert next(node for node in by_source if phrase in node.text).metadata["subject_source_id"] == "a"
    assert all("subject_source_id" in node.metadata and "subject_title" in node.metadata for node in nodes)
    assert [doc.model_dump() for doc in (a, b, c)] == before


@pytest.mark.parametrize("destination, expected", [
    ("HTTPS://SHOP.EXAMPLE:443/products/b#top", "b"),
    ("/products/b#details", "b"),
    ("b?tracking=2", "linked:"),
    ("https://shop.example/products/%62", "b"),
    ("https://shop.example/products/B", "linked:"),
    ("https://shop.example/products%2Fb", "linked:"),
    ("https://elsewhere.example/products/b", "a"),
    ("http://shop.example/products/b", "a"),
    ("https://shop.example:444/products/b", "a"),
    ("https://user@shop.example/products/b", "a"),
])
def test_heading_url_matching_is_normalized_but_conservative(destination, expected):
    a = subject_document("a", "Alpha", f"### [Linked device]({destination})\nA useful fact belongs to this card.",
                         "https://shop.example/products/a")
    b = subject_document("b", "Beta", "A separate fact.", "https://shop.example/products/b")
    nodes = build_nodes([a, b], tokenize, 128, 8)
    actual = nodes[0].metadata["subject_source_id"]
    assert actual.startswith("linked:") if expected == "linked:" else actual == expected
    assert_provenance(a, [node for node in nodes if node.metadata["source_id"] == "a"])


@pytest.mark.parametrize("heading", [
    "## References",
    "## Research about [Beta](https://shop.example/products/b)",
    "## [Beta](https://shop.example/products/b) and [Gamma](https://shop.example/products/c)",
    "## [Unknown](https://external.example/products/b)",
    "## [![Device](https://images.example/pic.png)](https://shop.example/products/b)",
])
def test_body_links_references_and_ambiguous_headings_do_not_reroute(heading):
    a = subject_document("a", "Alpha", heading + "\nA useful source fact is explained here.\n\n"
                         "[View Product](https://shop.example/products/b)\n\n"
                         "See [Beta](https://shop.example/products/b) for a related example.",
                         "https://shop.example/products/a")
    b = subject_document("b", "Beta", "A separate fact.", "https://shop.example/products/b")
    c = subject_document("c", "Gamma", "Another fact.", "https://shop.example/products/c")
    nodes = build_nodes([a, b, c], tokenize, 128, 8)
    own = [node for node in nodes if node.metadata["source_id"] == "a"]
    assert all(node.metadata["subject_source_id"] == "a" for node in own)
    assert_provenance(a, own)


@pytest.mark.parametrize("heading", [
    "## [**Beta Device**](https://shop.example/products/b)",
    "**## [Beta Device](https://shop.example/products/b)**",
    "## [Beta Device][beta]\n\n[beta]: https://shop.example/products/b",
    "[Beta Device](https://shop.example/products/b)\n----------------",
    "## [" + "A long descriptive label " * 10 + "](https://shop.example/products/b)",
])
def test_full_heading_link_is_resolved_before_bounded_metadata(heading):
    a = subject_document("a", "Alpha", heading + "\n\nThe ceramic shell is suitable for ordinary indoor use.",
                         "https://shop.example/products/a")
    b = subject_document("b", "Beta Device", "A separate fact.", "https://shop.example/products/b")
    nodes = build_nodes([a, b], tokenize, 128, 8)
    card = next(node for node in nodes if "ceramic shell" in node.text)
    assert card.metadata["subject_source_id"] == "b"
    assert card.metadata["document_title"] == "Beta Device"
    assert len(tokenize(card.metadata["section"])) <= 12
    assert_provenance(a, [node for node in nodes if node.metadata["source_id"] == "a"])


@pytest.mark.parametrize("query,expected", [("", "linked:"), ("?id=2", "b"), ("?id=3", "c"), ("?id=4", "linked:")])
def test_query_identity_wins_and_ambiguous_queryless_urls_do_not_choose_arbitrary_subject(query, expected):
    a = subject_document("a", "Alpha", f"## [Other](https://shop.example/view{query})\nA useful source fact.",
                         "https://shop.example/products/a")
    b = subject_document("b", "Beta", "One record.", "https://shop.example/view?id=2")
    c = subject_document("c", "Gamma", "A distinct record.", "https://shop.example/view?id=3")
    nodes = build_nodes([a, b, c], tokenize, 128, 8)
    actual = nodes[0].metadata["subject_source_id"]
    assert actual.startswith("linked:") if expected == "linked:" else actual == expected


def test_linked_headings_inside_fenced_code_are_not_subject_declarations():
    a = subject_document("a", "Alpha", "# Examples\n```markdown\n## [Beta](https://shop.example/products/b)\n```\nA literal example.",
                         "https://shop.example/products/a")
    b = subject_document("b", "Beta", "A separate fact.", "https://shop.example/products/b")
    nodes = build_nodes([a, b], tokenize, 128, 8)
    assert all(node.metadata["subject_source_id"] == "a" for node in nodes if node.metadata["source_id"] == "a")


@pytest.mark.parametrize("wrapped", [False, True])
def test_nested_subject_inherits_and_resets_at_sibling_and_ancestor(wrapped):
    heading = lambda level, label: f"**{'#' * level} {label}**" if wrapped else f"{'#' * level} {label}"
    a = subject_document("a", "Main Device", "\n\n".join([
        heading(1, "Main Device"), "The main product is red.",
        heading(2, "[Accessory](https://shop.example/item?id=2) ceramic accessory"), "The accessory is blue.",
        heading(3, "Dimensions"), "Accessory width: 18 cm.",
        heading(4, "Weight"), "Accessory weight: 45 g.",
        heading(2, "Dimensions"), "Main width: 30 cm.",
        heading(1, "Another section"), "Main weight: 150 g.",
    ]), "https://shop.example/item?id=1")
    b = subject_document("b", "Accessory", "The actual accessory page.", "https://shop.example/item?id=2")
    nodes = build_nodes([a, b], tokenize, 128, 12)
    own = [n for n in nodes if n.metadata["source_id"] == "a"]
    assert_provenance(a, own)
    for phrase in ("accessory is blue", "Accessory width", "Accessory weight"):
        assert next(n for n in own if phrase in n.text).metadata["subject_source_id"] == "b"
    for phrase in ("Main width", "Main weight", "main product is red"):
        assert next(n for n in own if phrase in n.text).metadata["subject_source_id"] == "a"


def test_single_known_query_variant_does_not_steal_uncrawled_variant():
    a = subject_document("a", "Catalog", "## [Different device](/item?id=200)\nA different item costs 45 euros.",
                         "https://shop.example/catalog")
    b = subject_document("b", "Device 100", "One item.", "https://shop.example/item?id=100")
    node = build_nodes([a, b], tokenize, 128, 8)[0]
    assert node.metadata["subject_source_id"].startswith("linked:")
    assert node.metadata["subject_title"] == "Different device"
    assert node.metadata["subject_url"] == "https://shop.example/item?id=200"
    assert node.metadata["source_id"] == "a"


def test_uncrawled_same_origin_subject_is_stable_across_hosts_and_distinct_queries():
    docs = [subject_document(str(index), f"Catalog {index}",
            f"## [Shared item](/item?id={variant}#details) descriptive tail\nA card fact.\n\n### Dimensions\nWidth 18 cm.",
            f"https://shop.example/catalog/{index}") for index, variant in enumerate((200, 200, 300))]
    nodes = build_nodes(docs, tokenize, 128, 8)
    by_source = {str(index): [n for n in nodes if n.metadata["source_id"] == str(index)] for index in range(3)}
    first = by_source["0"][0].metadata["subject_source_id"]
    assert first.startswith("linked:")
    assert all(n.metadata["subject_source_id"] == first for index in ("0", "1") for n in by_source[index])
    assert by_source["2"][0].metadata["subject_source_id"] != first
    assert all(n.metadata["document_title"] == "Shared item" for n in nodes)


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_table_rows_keep_exact_source_and_late_rows_receive_column_headers(newline):
    header = "| Model | Operating voltage (V) | Maximum current (A) |"
    lines = ["# Specifications", header, "| --- | --- | --- |"]
    lines.extend(f"| R{index:03d} | {index + 100} | 1 |" for index in range(70))
    doc = document(newline.join(lines))
    nodes = build_nodes([doc], tokenize, 128, 12)
    assert_provenance(doc, nodes)
    row_node = next(n for n in nodes if "R050" in n.text)
    assert header in model_text(row_node)
    assert "150" in row_node.text
    table_nodes = [n for n in nodes if "table_header" in n.metadata]
    assert len(table_nodes) > 3
    assert not any(n.metadata["table_row_fragmented"] for n in table_nodes)
    for node in table_nodes:
        meta = node.metadata
        assert doc.text[meta["table_header_start_char_idx"]:meta["table_header_end_char_idx"]] == meta["table_header"]
        for line in node.text.splitlines():
            assert line.startswith("|") and line.endswith("|")
        assert len(tokenize(model_text(node))) <= 128
    for line in lines[3:]:
        assert sum(line in node.text for node in table_nodes) == 1


def test_oversized_table_row_uses_upstream_fallback_and_is_flagged():
    doc = document("# Specifications\n| Name | Description |\n| --- | --- |\n| Long | "
                   + "A long factual description contains several ordinary words. " * 50 + "|\n| Short | 3 W |")
    nodes = build_nodes([doc], tokenize, 128, 12)
    assert_provenance(doc, nodes)
    table = [node for node in nodes if "table_header" in node.metadata]
    assert any(node.metadata["table_row_fragmented"] for node in table)
    assert any("| Short | 3 W |" in node.text for node in table)
    covered = [False] * len(doc.text)
    for node in nodes:
        covered[node.start_char_idx:node.end_char_idx] = [True] * len(node.text)
    assert all(covered[i] or character.isspace() for i, character in enumerate(doc.text))


def test_table_escape_links_unicode_and_duplicate_rows_remain_exact():
    doc = document("# Data\n| Item | Value |\n| --- | --- |\n| Café \\| 茶 | [Manual](/a?b=2) |\n"
                   + "| Same | 10 mm |\n" * 35)
    nodes = build_nodes([doc], tokenize, 128, 12)
    assert_provenance(doc, nodes)
    assert any("Café \\| 茶" in n.text for n in nodes)
    assert sum(n.text.count("| Same | 10 mm |") for n in nodes) == 35


@pytest.mark.parametrize("heading,body,expected", [
    ("Customer Reviews", "The device uses four batteries.", "REVIEW"),
    ("Review Policy", "Only verified purchases can be reviewed.", "POLICY"),
    ("Frequently Asked Questions", "Can I review this product? Yes, after a purchase.", "FAQ"),
    ("Product Description", "The ceramic housing is 18 cm wide.", "PRIMARY"),
    ("A personal story", "My review says this product works well.", "UNKNOWN"),
    ("Specifications in customer reviews", "The item weighs 2 kg.", "REVIEW"),
    ("Thousands of customer reviews across our products", "The device works well.", "REVIEW"),
    ("A selection of testimonials", "The device works well.", "REVIEW"),
    ("How many customer reviews are there?", "There are 52.", "UNKNOWN"),
    ("FAQ: Customer reviews", "You may review your purchase.", "FAQ"),
    ("Our customer reviews policy", "Only verified purchases can be reviewed.", "POLICY"),
    ("Clinical review", "A clinician checked the product information.", "UNKNOWN"),
])
def test_evidence_roles_are_structural_and_do_not_classify_body_mentions(heading, body, expected):
    node = build_nodes([document(f"# {heading}\n{body}")], tokenize, 128, 8)[0]
    assert node.metadata["evidence_role"] == expected
    assert node.metadata["evidence_role_basis"].startswith("heading:") if expected != "UNKNOWN" else True


def test_review_ancestry_does_not_turn_nested_specs_into_primary_evidence():
    nodes = build_nodes([document("# Customer Reviews\n## Specifications\nI measured the width as 18 cm.")], tokenize, 128, 8)
    assert all(n.metadata["evidence_role"] == "REVIEW" for n in nodes)
    nested_faq = build_nodes([document("# Customer Reviews\n## FAQ\nWas the device easy to use? The reviewer says yes.")], tokenize, 128, 8)
    assert all(n.metadata["evidence_role"] == "REVIEW" for n in nested_faq)


def test_linked_reference_subheading_does_not_declare_a_product_subject():
    a = subject_document("a", "Main Device", "# Main Device\n## References\n"
                         "### [Study](/paper?id=2) scientific discussion\nA study about materials.",
                         "https://shop.example/item?id=1")
    nodes = build_nodes([a], tokenize, 128, 8)
    assert all(n.metadata["subject_source_id"] == "a" for n in nodes)


def test_table_header_too_wide_is_explicitly_flagged_but_raw_header_not_lost():
    header = "| " + " | ".join(f"Column {i} with a descriptive name" for i in range(18)) + " |"
    delimiter = "| " + " | ".join("---" for _ in range(18)) + " |"
    row = "| " + " | ".join(str(i) for i in range(18)) + " |"
    doc = document("# Specifications\n" + "\n".join((header, delimiter, row)))
    nodes = build_nodes([doc], tokenize, 128, 8)
    assert_provenance(doc, nodes)
    tables = [n for n in nodes if "table_header" in n.metadata]
    assert tables and all(n.metadata["table_header_truncated"] for n in tables)
    assert all(header in n.metadata["table_header"] for n in tables)
    covered = set()
    for node in nodes:
        covered.update(range(node.start_char_idx, node.end_char_idx))
    assert all(i in covered or c.isspace() for i, c in enumerate(doc.text))


def test_declared_source_role_requires_explicit_metadata_not_title_guessing():
    plain = document("A user measured this item as 12 cm wide.", title="Customer Reviews")
    explicit = document("A user measured this item as 12 cm wide.", id_="explicit")
    explicit.metadata["source_role"] = "REVIEW"
    nodes = build_nodes([plain, explicit], tokenize, 128, 8)
    assert nodes[0].metadata["evidence_role"] == "UNKNOWN"
    assert nodes[1].metadata["evidence_role"] == "REVIEW"
    assert nodes[1].metadata["evidence_role_basis"] == "metadata:source_role"


@pytest.mark.parametrize('role,heading,expected', [
    ('REVIEW', 'Specifications', 'REVIEW'),
    ('REVIEW', 'FAQ', 'REVIEW'),
    ('POLICY', 'Materials', 'POLICY'),
    ('FAQ', 'Dimensions', 'FAQ'),
    ('PRIMARY', 'Customer Reviews', 'REVIEW'),
    ('POLICY', 'Customer Reviews', 'REVIEW'),
    ('UNKNOWN', 'Specifications', 'PRIMARY'),
])
def test_explicit_source_context_cannot_be_elevated_by_technical_subheading(role, heading, expected):
    doc = document(f'# {heading}\nThe item is 12 cm wide and covered for one year.')
    doc.metadata['source_role'] = role
    nodes = build_nodes([doc], tokenize, 128, 8)
    assert all(node.metadata['evidence_role'] == expected for node in nodes)
    assert_provenance(doc, nodes)


def test_sibling_official_sections_do_not_inherit_closed_review_subtree():
    doc = document('# Device\n## Customer Reviews\n### Specifications\nI measured 12 cm.\n'
                   '## Product Details\nThe official width is 14 cm.\n'
                   '## FAQ\nA different published direction says 13 cm.')
    nodes = build_nodes([doc], tokenize, 128, 8)
    assert next(n for n in nodes if 'I measured' in n.text).metadata['evidence_role'] == 'REVIEW'
    assert next(n for n in nodes if 'official width' in n.text).metadata['evidence_role'] == 'PRIMARY'
    assert next(n for n in nodes if 'different published' in n.text).metadata['evidence_role'] == 'FAQ'
    assert_provenance(doc, nodes)


@pytest.mark.parametrize('closing_label', ['View product', 'VIEW PRODUCT', 'View productView product', 'View Product View Product'])
@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_explicit_card_closing_link_restores_origin_for_unheaded_following_content(closing_label, newline):
    text = newline.join(['# Main Device', '', '## Related items', '',
        '### [Accessory](/item?id=2)', '', 'The accessory uses a detachable mains cable and a ceramic case.', '',
        '#### Dimensions', '', 'Accessory width: 18 cm.', '',
        f'[{closing_label}](/item?id=2#details)', '',
        'Who reviews the main device?', '',
        'Independent specialists review the main device and publish their comments without compensation.', '',
        'The main device includes a rechargeable battery for convenient portable use.'])
    doc = subject_document('a', 'Main Device', text, 'https://shop.example/item?id=1')
    other = subject_document('b', 'Accessory', 'A separate accessory page.', 'https://shop.example/item?id=2')
    nodes = build_nodes([doc, other], tokenize, 128, 12)
    own = [n for n in nodes if n.metadata['source_id'] == 'a']
    assert_provenance(doc, own)
    assert next(n for n in own if 'Accessory width' in n.text).metadata['subject_source_id'] == 'b'
    for phrase in ('Independent specialists', 'rechargeable battery'):
        selected = next(n for n in own if phrase in n.text)
        assert selected.metadata['subject_source_id'] == 'a'
        assert selected.metadata['document_title'] == 'Main Device'
        assert 'Accessory' not in selected.metadata['section']
    covered = set()
    for node in own:
        covered.update(range(node.start_char_idx, node.end_char_idx))
    assert all(i in covered or c.isspace() for i, c in enumerate(doc.text))


def test_closing_card_keeps_distinct_following_images_out_of_repeated_card_model_view():
    docs = [subject_document(str(i), f'Host {i}', '# Host\n\n### [Shared accessory](/shared)\n\n'
            'The accessory has a ceramic body and supports everyday indoor use.\n\n'
            '[View productView product](/shared)\n\n'
            f'![Next item {i}](https://images.example/different-{i}.png)\n\n'
            'A following sentence belongs to the original host page and its main product.',
            f'https://shop.example/host/{i}') for i in range(2)]
    nodes = build_nodes(docs, tokenize, 128, 12)
    cards = [n for n in nodes if 'accessory has a ceramic' in n.text]
    assert len(cards) == 2 and model_text(cards[0]) == model_text(cards[1])
    assert all('Next item' not in n.text for n in cards)
    for i, doc in enumerate(docs):
        own = [n for n in nodes if n.metadata['source_id'] == str(i)]
        assert_provenance(doc, own)
        following = next(n for n in own if 'following sentence' in n.text)
        assert following.metadata['subject_source_id'] == str(i)


@pytest.mark.parametrize('control', [
    '[View product](/item?id=3)',
    'See [View product](/item?id=2) for specifications.',
    '[View product](/item?id=2) and compare the listed facts.',
    '[Read more](/item?id=2)',
])
def test_nonmatching_or_nonstandalone_links_do_not_close_linked_heading_scope(control):
    doc = subject_document('a', 'Main', '## [Other](/item?id=2)\nA card description.\n\n' + control
            + '\n\n### Dimensions\nThe accessory width is 18 cm.', 'https://shop.example/item?id=1')
    nodes = build_nodes([doc], tokenize, 128, 12)
    width = next(n for n in nodes if 'accessory width' in n.text)
    assert width.metadata['subject_source_id'].startswith('linked:')
    assert width.metadata['subject_url'] == 'https://shop.example/item?id=2'


def test_closing_card_at_end_without_newline_has_exact_offsets():
    doc = subject_document('a', 'Main', '### [Other](/item?id=2)\nA different item costs 12 euros.\n\n[View product](/item?id=2)',
                           'https://shop.example/item?id=1')
    nodes = build_nodes([doc], tokenize, 128, 12)
    assert_provenance(doc, nodes)
    assert any('[View product]' in n.text for n in nodes)
