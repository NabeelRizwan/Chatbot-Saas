import copy
import re

import pytest
from llama_index.core.schema import NodeRelationship, NodeWithScore, TextNode

from retrieval_engine.config import RetrievalConfig
from retrieval_engine.evidence_context import build_evidence_context

RetrievalConfig().apply_runtime_environment()


def tokens(text):
    return re.findall(r"\w+|[^\w\s]", text)


def fixture(parts, source="a", gap="\n\n"):
    text = gap.join(parts)
    document = {"text": text, "title": f"Source {source}", "url": f"https://example.org/{source}"}
    nodes, cursor = [], 0
    for index, part in enumerate(parts):
        node = TextNode(id_=f"{source}-{index}", text=part, start_char_idx=cursor, end_char_idx=cursor + len(part),
                        metadata={"source_id": source, "title": document["title"], "url": document["url"], "section": f"Part {index}"})
        nodes.append(node)
        cursor += len(part) + len(gap)
    for index, node in enumerate(nodes):
        if index:
            node.relationships[NodeRelationship.PREVIOUS] = nodes[index - 1].as_related_node_info()
        if index + 1 < len(nodes):
            node.relationships[NodeRelationship.NEXT] = nodes[index + 1].as_related_node_info()
    return {source: document}, {node.node_id: node for node in nodes}, nodes


def selected(*nodes):
    # Deliberately use cleaned model text; only IDs may determine source evidence.
    result = []
    for index, node in enumerate(nodes):
        model = node.model_copy(deep=True)
        model.text = "MODEL INPUT, NOT A SOURCE QUOTE"
        result.append(NodeWithScore(node=model, score=10 - index))
    return result


def test_merged_role_boundaries_keep_exact_spans_without_prompt_token_cost():
    docs, mapping, nodes = fixture(['## Specifications\nThe chair is 70 cm wide.',
                                   '## Customer Reviews\nI measured it as 72 cm.'])
    for node, role in zip(nodes, ['PRIMARY', 'REVIEW']):
        node.metadata.update(evidence_role=role, evidence_role_basis='heading:' + node.text.splitlines()[0][3:])
    result = build_evidence_context(selected(nodes[0]), mapping, docs, tokens, 400, 1)
    item = result['evidence'][0]
    assert item['text'] == docs['a']['text']
    assert item['evidence_roles'] == ['PRIMARY', 'REVIEW']
    assert item['evidence_role_spans'] == [
        {'node_id': n.node_id, 'start_char': n.start_char_idx, 'end_char': n.end_char_idx,
         'evidence_role': n.metadata['evidence_role'], 'evidence_role_basis': n.metadata['evidence_role_basis']}
        for n in nodes]
    expected = ('[Source 1] Source a\nSection: Part 0\nStructural evidence roles: PRIMARY, REVIEW\n'
                'URL: https://example.org/a\n' + docs['a']['text'])
    assert result['context'] == expected
    assert result['context_tokens'] == len(tokens(expected))


def test_role_trace_for_clipped_neighbor_records_only_included_source_span():
    docs, mapping, nodes = fixture(['A preceding fact. ' * 40, 'The selected fact.'])
    nodes[0].metadata.update(evidence_role='REVIEW', evidence_role_basis='heading:Customer Reviews')
    result = build_evidence_context(selected(nodes[1]), mapping, docs, tokens, 400, 1, max_neighbor_tokens=20)
    item = result['evidence'][0]
    for span in item['evidence_role_spans']:
        assert item['start_char'] <= span['start_char'] < span['end_char'] <= item['end_char']
    review_span = next(span for span in item['evidence_role_spans'] if span['evidence_role'] == 'REVIEW')
    assert review_span['start_char'] > nodes[0].start_char_idx
    assert review_span['end_char'] <= nodes[0].end_char_idx


def assert_exact(result, documents):
    for item in result["evidence"]:
        source = documents[item["source_id"]]
        assert item["text"] == source["text"][item["start_char"]:item["end_char"]]
        assert item["url"] == source["url"]
        assert "MODEL INPUT" not in item["text"]


def table_fixture():
    header = "| Model | Voltage (V) | Current (A) |\n| --- | --- | --- |\n"
    docs, mapping, nodes = fixture([header.rstrip(), "| R100 | 150 | 1 |", "| R200 | 220 | 2 |"], gap="\n")
    for node in nodes:
        node.metadata.update({"table_header": header, "table_header_start_char_idx": 0,
                              "table_header_end_char_idx": len(header), "table_start_char_idx": 0,
                              "table_end_char_idx": len(docs["a"]["text"])})
    return docs, mapping, nodes, header


def test_table_header_is_separately_verified_and_budgeted_for_late_rows():
    docs, mapping, nodes, header = table_fixture()
    result = build_evidence_context(selected(nodes[2]), mapping, docs, tokens, 400, 1, expand_neighbors=False)
    assert_exact(result, docs)
    item = result["evidence"][0]
    assert item["text"] == nodes[2].text and header not in item["text"]
    assert header.rstrip() in result["context"]
    reference = item["table_headers"][0]
    assert reference["text"] == docs["a"]["text"][reference["start_char"]:reference["end_char"]]
    assert reference["included_in_context"]
    assert reference["source_id"] == "a" and reference["url"] == docs["a"]["url"]
    assert result["context_tokens"] == len(tokens(result["context"]))
    with pytest.raises(ValueError, match="no comparison source"):
        build_evidence_context(selected(nodes[2]), mapping, docs, tokens, result["context_tokens"] - 1, 1,
                               expand_neighbors=False)


def test_merged_table_header_already_present_is_not_duplicated():
    docs, mapping, nodes, header = table_fixture()
    result = build_evidence_context(selected(*nodes), mapping, docs, tokens, 400, 3, expand_neighbors=False)
    assert_exact(result, docs)
    assert len(result["evidence"]) == 1
    assert result["context"].count(header.rstrip()) == 1
    assert result["evidence"][0]["table_headers"] == [{"start_char": 0, "end_char": len(header), "text": header,
            "source_id": "a", "url": docs["a"]["url"], "included_in_context": False}]
    header_only = build_evidence_context(selected(nodes[0]), mapping, docs, tokens, 400, 1, expand_neighbors=False)
    assert header_only["context"].count(header.rstrip()) == 1
    assert not header_only["evidence"][0]["table_headers"][0]["included_in_context"]


@pytest.mark.parametrize("damage", ["text", "start", "end", "foreign_table"])
def test_forged_table_header_provenance_is_rejected(damage):
    docs, mapping, nodes, header = table_fixture()
    if damage == "text":
        nodes[2].metadata["table_header"] = header.replace("Voltage", "Temperature")
    elif damage == "start":
        nodes[2].metadata["table_header_start_char_idx"] = 2
    elif damage == "end":
        nodes[2].metadata["table_header_end_char_idx"] += 1
    else:
        nodes[2].metadata["table_end_char_idx"] = nodes[1].end_char_idx
    with pytest.raises(ValueError, match="Table header"):
        build_evidence_context(selected(nodes[2]), mapping, docs, tokens, 400, 1, expand_neighbors=False)


def test_table_header_merge_after_neighbor_expansion_avoids_duplicate_labels():
    docs, mapping, nodes, header = table_fixture()
    result = build_evidence_context(selected(nodes[2]), mapping, docs, tokens, 400, 1, max_neighbor_tokens=128)
    assert_exact(result, docs)
    assert result["context"].count(header.rstrip()) == 1
    assert not result["evidence"][0]["table_headers"][0]["included_in_context"]


def test_real_table_parser_nodes_keep_headers_through_context_selection():
    from llama_index.core.schema import Document
    from retrieval_engine.document_nodes import build_nodes

    text = "# Specifications\n| Model | Voltage (V) | Current (A) |\n| --- | --- | --- |\n"
    text += "\n".join(f"| R{i:03d} | {i + 100} | 1 |" for i in range(70))
    doc = Document(id_="a", text=text, metadata={"source_id": "a", "title": "Device specifications",
                                                "url": "https://example.org/a"})
    nodes = build_nodes([doc], tokens, 128, 12)
    node = next(n for n in nodes if "R050" in n.text)
    result = build_evidence_context(selected(node), {n.node_id: n for n in nodes}, {"a": doc}, tokens, 300, 1)
    assert result["context_tokens"] <= 300
    assert "Voltage (V)" in result["context"] and "| R050 | 150 | 1 |" in result["context"]
    assert result["evidence"][0]["text"] == text[result["evidence"][0]["start_char"]:result["evidence"][0]["end_char"]]


def test_neighbor_restores_label_and_document_order_with_exact_unicode_offsets():
    docs, mapping, nodes = fixture(["Months 1–2 🐈", "## Start\nCafé and 茶 begin here.", "Months 3–4", "## Continue\nKeep using it.", "Unrelated end."])
    before = copy.deepcopy(mapping)
    result = build_evidence_context(selected(nodes[3], nodes[1]), mapping, docs, tokens, 400, 2)
    assert_exact(result, docs)
    assert "Months 1–2" in result["context"]
    assert result["context"].index("Months 1–2") < result["context"].index("Months 3–4")
    assert len(result["evidence"]) == 1
    assert set(result["evidence"][0]["core_node_ids"]) == {nodes[1].node_id, nodes[3].node_id}
    assert mapping == before


def test_core_spans_reserved_before_optional_neighbor_of_high_ranked_source():
    docs_a, map_a, a = fixture(["Long optional details. " * 70, "Fact A."], "a")
    docs_b, map_b, b = fixture(["Fact B."], "b")
    docs, mapping = {**docs_a, **docs_b}, {**map_a, **map_b}
    cores = build_evidence_context(selected(a[1], b[0]), mapping, docs, tokens, 1000, 2, expand_neighbors=False)
    result = build_evidence_context(selected(a[1], b[0]), mapping, docs, tokens, cores["context_tokens"], 2)
    assert_exact(result, docs)
    assert {e["source_id"] for e in result["evidence"]} == {"a", "b"}
    assert result["context_tokens"] <= cores["context_tokens"]
    assert not result["audit"]["accepted_neighbors"]


def test_insufficient_core_budget_raises_instead_of_silently_dropping_source():
    docs, mapping, nodes = fixture(["A useful fact.", "A second useful fact."])
    with pytest.raises(ValueError, match="no comparison source"):
        build_evidence_context(selected(*nodes), mapping, docs, tokens, 5, 2)


def test_source_priority_retained_but_spans_sorted_within_source():
    da, ma, a = fixture(["A first.", "A middle.", "A last."], "a")
    db, mb, b = fixture(["B first."], "b")
    result = build_evidence_context(selected(a[2], b[0], a[0]), {**ma, **mb}, {**da, **db}, tokens, 400, 3, expand_neighbors=False)
    assert [item["source_id"] for item in result["evidence"]] == ["a", "a", "b"]
    assert result["evidence"][0]["start_char"] < result["evidence"][1]["start_char"]
    assert "A middle" not in result["context"]


def test_long_neighbor_is_clipped_to_nearest_official_sentence_chunk():
    parts = ["Far away content. " * 100 + "Important preceding label.", "## Current\nCurrent fact.", "Next sentence. " * 100]
    docs, mapping, nodes = fixture(parts)
    result = build_evidence_context(selected(nodes[1]), mapping, docs, tokens, 400, 1, max_neighbor_tokens=32)
    assert_exact(result, docs)
    assert "Important preceding label" in result["context"]
    assert len(result["context"]) < len(docs["a"]["text"]) / 3
    assert len(result["audit"]["accepted_neighbors"]) == 2
    for addition in result["audit"]["accepted_neighbors"]:
        fragment = docs["a"]["text"][addition["start_char"]:addition["end_char"]]
        assert len(tokens(fragment)) <= 32


def test_expansion_is_one_hop_not_recursive():
    docs, mapping, nodes = fixture(["Never included zero.", "Immediate previous.", "Selected core.", "Immediate next.", "Never included four."])
    result = build_evidence_context(selected(nodes[2]), mapping, docs, tokens, 1000, 1, neighbor_hops=1)
    assert "Immediate previous" in result["context"] and "Immediate next" in result["context"]
    assert "Never included" not in result["context"]


def test_cross_source_and_missing_relationships_rejected_without_losing_core():
    da, ma, a = fixture(["Source A fact."], "a")
    db, mb, b = fixture(["Source B fact."], "b")
    a[0].relationships[NodeRelationship.NEXT] = b[0].as_related_node_info()
    ghost = TextNode(id_="missing", text="Missing")
    a[0].relationships[NodeRelationship.PREVIOUS] = ghost.as_related_node_info()
    result = build_evidence_context(selected(a[0]), {**ma, **mb}, {**da, **db}, tokens, 400, 1)
    assert "Source A fact" in result["context"] and "Source B fact" not in result["context"]
    assert {entry["reason"] for entry in result["audit"]["rejected_neighbors"]} == {"different_source", "missing_source_node"}


def test_corrupt_core_source_offsets_fail_loudly():
    docs, mapping, nodes = fixture(["Fact."])
    nodes[0].end_char_idx -= 1
    with pytest.raises(ValueError, match="slice"):
        build_evidence_context(selected(nodes[0]), mapping, docs, tokens, 400, 1)


def test_duplicate_selection_and_crlf_whitespace_merge():
    docs, mapping, nodes = fixture(["First € fact.", "Second 日本 fact."], gap="\r\n\r\n")
    result = build_evidence_context(selected(nodes[0], nodes[0], nodes[1]), mapping, docs, tokens, 400, 2, expand_neighbors=False)
    assert_exact(result, docs)
    assert len(result["evidence"]) == 1
    assert result["evidence"][0]["text"] == docs["a"]["text"]


def test_overlapping_selected_nodes_merged_without_duplicate_text():
    docs, mapping, nodes = fixture(["Alpha beta gamma delta epsilon."])
    text = docs["a"]["text"]
    left = nodes[0].model_copy(deep=True)
    left.id_, left.end_char_idx, left.text = "left", 16, text[:16]
    right = nodes[0].model_copy(deep=True)
    right.id_, right.start_char_idx, right.text = "right", 11, text[11:]
    result = build_evidence_context(selected(left, right), {"left":left, "right":right}, docs, tokens, 400, 2, expand_neighbors=False)
    assert result["evidence"][0]["text"] == text
    assert_exact(result, docs)


def test_explicit_selected_limit_and_empty_input():
    docs, mapping, nodes = fixture(["One fact.", "Two facts."])
    with pytest.raises(ValueError, match="declared maximum"):
        build_evidence_context(selected(*nodes), mapping, docs, tokens, 400, 1)
    result = build_evidence_context([], {}, {}, tokens, 400, 0)
    assert result["context"] == "" and result["evidence"] == []


def test_already_selected_neighbors_are_not_counted_as_new_context():
    docs, mapping, nodes = fixture(["First fact.", "Second fact."])
    result = build_evidence_context(selected(*nodes), mapping, docs, tokens, 400, 2)
    assert not result["audit"]["accepted_neighbors"]
    assert result["evidence"][0]["expanded_node_ids"] == []


def test_duplicate_selected_nodes_preserve_first_score():
    docs, mapping, nodes = fixture(["A fact."])
    items = [NodeWithScore(node=nodes[0], score=9), NodeWithScore(node=nodes[0], score=1)]
    result = build_evidence_context(items, mapping, docs, tokens, 400, 1)
    assert result["evidence"][0]["score"] == 9


def test_three_hops_reaches_nearby_sections_but_not_the_whole_document():
    docs, mapping, nodes = fixture([f"Distinct paragraph {index}." for index in range(11)])
    result = build_evidence_context(selected(nodes[5]), mapping, docs, tokens, 1000, 1)
    assert_exact(result, docs)
    assert result["audit"]["neighbor_hops"] == 3
    for index in range(2, 9):
        assert f"Distinct paragraph {index}." in result["context"]
    for index in (0, 1, 9, 10):
        assert f"Distinct paragraph {index}." not in result["context"]
    assert [item["distance"] for item in result["audit"]["accepted_neighbors"]] == [1,1,2,2,3,3]


def test_distance_first_expansion_gives_other_core_immediate_context_before_second_hop():
    da, ma, a = fixture([f"A paragraph {index}." for index in range(7)], "a")
    db, mb, b = fixture([f"B paragraph {index}." for index in range(7)], "b")
    result = build_evidence_context(selected(a[3], b[3]), {**ma, **mb}, {**da, **db}, tokens, 1000, 2)
    accepted = result["audit"]["accepted_neighbors"]
    assert [(item["core_node_id"], item["direction"], item["distance"]) for item in accepted[:4]] == [
        (a[3].node_id, "previous", 1), (a[3].node_id, "next", 1),
        (b[3].node_id, "previous", 1), (b[3].node_id, "next", 1),
    ]
    assert [item["distance"] for item in accepted] == sorted(item["distance"] for item in accepted)


def test_clipped_long_neighbor_does_not_allow_jumping_to_farther_text():
    docs, mapping, nodes = fixture([
        "Farther previous must stay absent.",
        "Long preceding text. " * 70 + "Nearest preceding sentence.",
        "Selected central fact.",
        "Nearest following sentence. " + "Long following text. " * 70,
        "Farther next must stay absent.",
    ])
    result = build_evidence_context(selected(nodes[2]), mapping, docs, tokens, 1000, 1, max_neighbor_tokens=24)
    assert_exact(result, docs)
    assert "Nearest preceding sentence" in result["context"]
    assert "Nearest following sentence" in result["context"]
    assert "Farther previous" not in result["context"] and "Farther next" not in result["context"]
    assert any(item["reason"] == "noncontiguous_fragment" for item in result["audit"]["rejected_neighbors"])


def test_invalid_second_hop_cannot_cross_sources_or_reach_missing_third_hop():
    da, ma, a = fixture(["Core fact.", "Valid immediate context."], "a")
    db, mb, b = fixture(["Foreign context."], "b")
    a[1].relationships[NodeRelationship.NEXT] = b[0].as_related_node_info()
    result = build_evidence_context(selected(a[0]), {**ma, **mb}, {**da, **db}, tokens, 1000, 1)
    assert_exact(result, {**da, **db})
    assert "Valid immediate context" in result["context"] and "Foreign" not in result["context"]
    rejected = result["audit"]["rejected_neighbors"]
    assert any(item["reason"] == "different_source" and item["distance"] == 2 for item in rejected)
    missing = TextNode(id_="absent", text="absent")
    a[1].relationships[NodeRelationship.NEXT] = missing.as_related_node_info()
    result = build_evidence_context(selected(a[0]), ma, da, tokens, 1000, 1)
    assert any(item["reason"] == "missing_source_node" and item["distance"] == 2
               for item in result["audit"]["rejected_neighbors"])


def test_three_hops_preserves_all_cores_under_tight_budget():
    da, ma, a = fixture([f"A contextual paragraph {i}. " * 15 for i in range(7)], "a")
    db, mb, b = fixture([f"B contextual paragraph {i}. " * 15 for i in range(7)], "b")
    docs, mapping = {**da, **db}, {**ma, **mb}
    core_only = build_evidence_context(selected(a[3], b[3]), mapping, docs, tokens, 1000, 2, neighbor_hops=0)
    budget = core_only["context_tokens"] + 128
    result = build_evidence_context(selected(a[3], b[3]), mapping, docs, tokens, budget, 2)
    assert result["context_tokens"] <= budget
    assert {node_id for item in result["evidence"] for node_id in item["core_node_ids"]} == {a[3].node_id,b[3].node_id}
    assert {item["source_id"] for item in result["evidence"]} == {"a","b"}


@pytest.mark.parametrize("hops", [-1, 4, 1.5, True])
def test_reject_unbounded_or_noninteger_hop_count(hops):
    with pytest.raises(ValueError, match="Neighbor hops"):
        build_evidence_context([], {}, {}, tokens, 400, 0, neighbor_hops=hops)


def subject_fixture():
    docs, mapping, nodes = fixture([
        "Alpha primary fact.", "Beta card fact.", "Beta continuation fact.",
        "Gamma card fact.", "Alpha closing fact.",
    ], "a")
    docs.update({
        "b": {"title": "Beta Product", "text": "Separate Beta page.", "url": "https://example.org/b"},
        "c": {"title": "Gamma Product", "text": "Separate Gamma page.", "url": "https://example.org/c"},
    })
    for node, subject_id in zip(nodes, ("a", "b", "b", "c", "a")):
        node.metadata.update(subject_source_id=subject_id, subject_title=docs[subject_id]["title"])
    return docs, mapping, nodes


def test_same_page_cross_subject_neighbors_do_not_enter_primary_context():
    docs, mapping, nodes = subject_fixture()
    result = build_evidence_context(selected(nodes[0]), mapping, docs, tokens, 1000, 1)
    assert_exact(result, docs)
    assert "Alpha primary" in result["context"]
    assert "Beta card" not in result["context"] and "Gamma" not in result["context"]
    assert any(item["reason"] == "different_subject" for item in result["audit"]["rejected_neighbors"])
    assert result["evidence"][0]["subject_source_id"] == "a"


def test_cross_sell_core_expands_only_its_own_subject_and_displays_both_attributions():
    docs, mapping, nodes = subject_fixture()
    result = build_evidence_context(selected(nodes[1]), mapping, docs, tokens, 1000, 1)
    assert_exact(result, docs)
    assert "Beta card" in result["context"] and "Beta continuation" in result["context"]
    assert "Alpha primary" not in result["context"] and "Gamma card" not in result["context"]
    evidence = result["evidence"][0]
    assert evidence["source_id"] == "a" and evidence["title"] == "Source a"
    assert evidence["subject_source_id"] == "b" and evidence["subject_title"] == "Beta Product"
    assert evidence["url"] == docs["a"]["url"]
    assert "[Source 1] Source a\nSubject: Beta Product\n" in result["context"]
    assert any(item["reason"] == "different_subject" and item["distance"] == 2
               for item in result["audit"]["rejected_neighbors"])


def test_adjacent_selected_different_subjects_do_not_merge_or_drop_core_spans():
    docs, mapping, nodes = subject_fixture()
    result = build_evidence_context(selected(nodes[0], nodes[1], nodes[4]), mapping, docs, tokens, 1000, 3)
    assert_exact(result, docs)
    assert len(result["evidence"]) == 3
    assert [item["subject_source_id"] for item in result["evidence"]] == ["a", "b", "a"]
    assert {core for item in result["evidence"] for core in item["core_node_ids"]} == {
        nodes[0].node_id, nodes[1].node_id, nodes[4].node_id,
    }
    assert "Gamma card" not in result["context"]


def test_absent_subject_metadata_defaults_to_same_source_subject():
    docs, mapping, nodes = fixture(["First fact.", "Second fact."])
    nodes[1].metadata.update(subject_source_id="a", subject_title="Source a")
    result = build_evidence_context(selected(nodes[0]), mapping, docs, tokens, 400, 1)
    assert result["evidence"][0]["text"] == docs["a"]["text"]
    assert result["evidence"][0]["subject_source_id"] == "a"
    assert "Subject:" not in result["context"]
