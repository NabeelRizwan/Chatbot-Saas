"""Scoped marker cleanup must preserve prose, links and streamed answer prefixes."""

import json
from types import SimpleNamespace

import pytest

from services.llama_rag.answer_contract import AnswerContractStream, decode_answer
from services.llama_rag.streaming import EvidenceStream


def evidence():
    return [{'document': SimpleNamespace(id=100 + int(value)),
             'chunk': SimpleNamespace(metadata_json={'citation_id': value})}
            for value in ('1', '7', '8')]


@pytest.mark.parametrize('marker', [
    '[Source 1, Source 8]', '[Source 1, 8]', '[ID:1, ID:8]',
    '[source 1, SOURCE 8]', '[Source 1, ID:8]', '[Source 1, 8, 1]',
    '[Source_1, Source_8]', '[Source_1, ID:8]',
    '[Source 1][Source 8]', '[ID:1][ID:8]', '[Source_1][Source_8]',
])
def test_grouped_markers_use_scoped_passage_ids_without_changing_facts(marker):
    raw = 'Both products use 8 to 10 ounces ' + marker + '.'
    answer, selected, audit = decode_answer(raw, evidence(), normalize=True)
    assert answer == 'Both products use 8 to 10 ounces.'
    assert selected == [evidence()[0], evidence()[2]]
    assert audit['selected_ids'] == ['1', '8']
    assert audit['metadata_status'] == 'missing'
    assert audit['inline_markers_removed'] == 1


@pytest.mark.parametrize('text', [
    'An ordinary [1, 8] list.', 'Read [Sources of income].',
    'Unknown [Source 900].', 'Mixed [Source 1, Source 900].',
    'Not a range parser [Source 1-8].', 'Not canonical [Source 01].',
    'Not a document ID [Source 101].', 'Incomplete [Source 1,',
    r'Escaped \[Source 1].', 'Code `[Source 1, Source 8]` stays.',
    '```text\n[Source 1]\n```', '~~~text\n[Source 8]\n~~~',
    'Quoted "[Source 1]" text.', 'Nested [[Source 1]].',
    'Quoted “[Source 1]” text.', 'Quoted ‘[Source 1]’ text.',
    'Quoted «[Source 1]» text.', 'Quoted 「[Source 1]」 text.',
    'Example:\n\n    [Source 1]\n\nContinue.',
    'Example:\r\n\r\n\t[Source 1]\r\n\r\nContinue.',
    '>     [Source 1]\n',
    'Use <code>[Source 1]</code> literally.',
    'Read <a href="https://example.test">[Source 1]</a> literally.',
    'Use <code><code>[Source 1]</code> [Source 8]</code> literally.',
    '<pre class="sample">[Source 1]</pre>',
    'Read [label [Source 1]](https://example.test/info).',
    'Read [Source 1](https://example.test/info).',
    'Read [Source 1][Source 8].\n\n[Source 8]: https://example.test/info',
    '[Source 1]: https://example.test/info',
    'Read [Source 1][Source 8](https://example.test/info).',
    'Unknown [Source 1][Source 900].', 'Quoted “[Source 1][Source 8]”.',
    'Nested [[Source 1][Source 8]].', 'Code `[Source_1][Source_8]` stays.',
    'Quoted 「[Source_1][Source_8]」.', 'Unknown [Source_900].',
    'Read [Source_1].\n\n[Source_1]: https://example.test/manual',
    'Read ![Source_1].\n\n[Source_1]: https://example.test/manual',
    'URL <https://example.test/[Source_1][Source_8]>.',
    'URL https://example.test/[Source_1][Source_8].',
    'Read (https://example.test/[Source_1][Source_8]).',
    'URL https://example.test/file?label=[Source_1].',
    'Read [manual](https://example.test/[Source_1][Source_8]).',
    'Read ![manual](https://example.test/[Source_1][Source_8]).',
    '[ref]: https://example.test/[Source_1][Source_8]\n\nRead [ref].',
])
def test_ambiguous_unknown_and_literal_markup_is_preserved(text):
    answer, selected, audit = decode_answer(text, evidence(), normalize=True)
    assert answer == text
    assert selected == []
    assert audit['inline_markers_removed'] == 0


def test_valid_private_selection_survives_unknown_inline_group():
    raw = 'Fact [Source 1, Source 900].\n<source_refs>["7"]</source_refs>'
    answer, selected, audit = decode_answer(raw, evidence(), normalize=True)
    assert answer == 'Fact [Source 1, Source 900].'
    assert audit['selected_ids'] == ['7']
    assert selected == [evidence()[1]]


def test_normalization_preserves_invalid_private_reference_diagnostics():
    raw = 'Fact [Source 8].\n<source_refs>["7", "900"]</source_refs>'
    answer, selected, audit = decode_answer(raw, evidence(), normalize=True)
    assert answer == 'Fact.'
    assert selected == [evidence()[1], evidence()[2]]
    assert audit['status'] == audit['metadata_status'] == 'invalid_ids'
    assert audit['invalid_count'] == 1


def test_explicit_inline_and_private_references_deduplicate_without_broadening_to_all_evidence():
    raw = 'Fact [Source 8, Source 1].\n<source_refs>["8"]</source_refs>'
    _, selected, audit = decode_answer(raw, evidence(), normalize=True)
    assert audit['selected_ids'] == ['8', '1']
    assert selected == [evidence()[2], evidence()[0]]


@pytest.mark.parametrize('structured', [False, True])
@pytest.mark.parametrize('answer', [
    'Both use 8 to 10 ounces [Source 1, Source 8].\n\nSecond paragraph.',
    'Both use 8 to 10 ounces [Source 1, 8]',
    'First [Source 1] then second [Source 8].',
    'First [Source 1]word.\n\nSecond paragraph.',
    'Fact [ID:1, ID:8].', 'Unknown [Source 1, Source 900].',
    'Incomplete [Source 1, Source ',
    'Code `[Source 1]` and fact [Source 8].',
    '```\n[Source 1]\n```\n\nFact [Source 8].',
    'Read [Source 1](https://example.test/a). Then [Source 8].',
    'Read [Source 1][Source 8].',
    'Fact [Source_1][Source_8]. More facts.',
    'Fact [Source_1]. More facts.',
    'Read [Source 1][Source 8].\n\n[Source 8]: https://example.test/info',
    '[Source 8]: https://example.test/info\n\nRead [Source 1][Source 8].',
    'Read [Source 1][Source 8](https://example.test/info).',
    'Unknown [Source 1][Source 900]. More facts.',
    'Quoted “[Source 1][Source 8]”. More facts.',
    'Read [Source_1].\n\n[Source_1]: https://example.test/manual',
    'Read ![Source_1].\n\n[Source_1]: https://example.test/manual',
    'URL <https://example.test/[Source_1][Source_8]>.',
    'URL https://example.test/[Source_1][Source_8]. More text.',
    'Read (https://example.test/[Source_1][Source_8]). More text.',
    'URL https://example.test/file?label=[Source_1]. More text.',
    'Read [manual](https://example.test/[Source_1][Source_8]).',
    'Read ![manual](https://example.test/[Source_1][Source_8]).',
    '[ref]: https://example.test/[Source_1][Source_8]\n\nRead [ref].',
    'Read [label [Source 1]](https://example.test/info). Then [Source 8].',
    'Quoted “[Source 1]” text. Fact [Source 8].',
    'Quoted 「[Source 1]」 text. Fact [Source 8].',
    'Example:\n\n    [Source 1]\n\nFact [Source 8].',
    'Use <code>[Source 1]</code> literally. Fact [Source 8].',
    'Fact [Source ' + ', '.join(['1'] * 65) + '].',
    'Literal [1] and [Sources of income].',
])
def test_every_chunk_boundary_finishes_with_exact_normalized_answer(structured, answer):
    raw = (json.dumps({'answer': answer, 'source_ids': ['1', '8']}) if structured
           else answer + '\n<source_refs>["1", "8"]</source_refs>')
    final, _, _ = decode_answer(raw, evidence(), structured=structured, normalize=True)
    for chunks in ([raw[:i], raw[i:]] for i in range(len(raw) + 1)):
        delivered = []
        delivery = EvidenceStream(delivered.append, lambda value: value, lambda: None)
        stream = AnswerContractStream(delivery.feed, structured=structured,
                                      normalize=True, items=evidence())
        for chunk in chunks:
            stream.feed(chunk)
        delivery.finish(final)
        assert ''.join(delivered) == final
    delivered = []
    stream = AnswerContractStream(delivered.append, structured=structured,
                                  normalize=True, items=evidence())
    for char in raw:
        stream.feed(char)
    assert final.startswith(''.join(delivered))
    assert 'source_refs' not in ''.join(delivered)


def test_normalization_off_preserves_existing_protocol_exactly():
    raw = 'Both use 8 to 10 ounces [Source 1, Source 8].\n<source_refs>["8"]</source_refs>'
    answer, selected, audit = decode_answer(raw, evidence(), normalize=False)
    assert answer == 'Both use 8 to 10 ounces [Source 1, Source 8].'
    assert selected == [evidence()[2]]
    assert audit == {'status': 'valid', 'available_count': 3, 'selected_ids': ['8'],
                     'invalid_count': 0, 'structured_output': False}


@pytest.mark.parametrize('reference', ['Source 8', 'source 8', 'Source_8', 'ID:8'])
def test_commonmark_reference_definitions_preserve_actual_labelled_links(reference):
    answer = f'Read [Source 1][{reference}].\n\n[{reference.upper()}]: https://example.test/info'
    final, selected, audit = decode_answer(answer, evidence(), normalize=True)
    assert final == answer
    assert selected == [] and audit['inline_markers_removed'] == 0


@pytest.mark.parametrize('marker', ['Source 1', 'Source_1', 'ID:1'])
@pytest.mark.parametrize('prefix', ['', '!'])
def test_shortcut_and_image_references_are_preserved_with_late_definitions(marker, prefix):
    answer = f'Read {prefix}[{marker}].\n\n[{marker.upper()}]: https://example.test/info'
    final, selected, audit = decode_answer(answer, evidence(), normalize=True)
    assert final == answer
    assert selected == [] and audit['inline_markers_removed'] == 0


def test_ambiguous_chain_holds_only_suffix_until_final_answer():
    delivered = []
    stream = AnswerContractStream(delivered.append, normalize=True, items=evidence())
    stream.feed('Useful first sentence. Fact [Source 1][Source 8]. More facts.')
    assert ''.join(delivered) == 'Useful first sentence. Fact'


@pytest.mark.parametrize('answer,expected', [
    ('Read https://example.test/manual [Source_1].', 'Read https://example.test/manual.'),
    ('Read (https://example.test/manual).[Source_1]', 'Read (https://example.test/manual).'),
    ('Read https://example.test/manual; [Source_1]', 'Read https://example.test/manual;'),
])
def test_citations_after_plain_url_boundaries_still_normalize(answer, expected):
    final, _, audit = decode_answer(answer, evidence(), normalize=True)
    assert final == expected and audit['selected_ids'] == ['1']
    test_every_chunk_boundary_finishes_with_exact_normalized_answer(False, answer)
    test_every_chunk_boundary_finishes_with_exact_normalized_answer(True, answer)


@pytest.mark.parametrize('count', [65, 800])
def test_adjacent_chain_bounds_are_shared_in_stream_and_final(count):
    answer = 'Fact ' + '[Source 1]' * count + '.'
    final, selected, _ = decode_answer(answer, evidence(), normalize=True)
    assert final == answer and selected == []
    for split in {0, 20, 649, len(answer) - 1, len(answer)}:
        delivered = []
        delivery = EvidenceStream(delivered.append, lambda value: value, lambda: None)
        stream = AnswerContractStream(delivery.feed, normalize=True, items=evidence())
        stream.feed(answer[:split])
        stream.feed(answer[split:])
        delivery.finish(final)
        assert ''.join(delivered) == answer


def test_oversized_or_unscoped_groups_are_not_normalized():
    raw = 'Fact [Source ' + ', '.join(str(n) for n in range(1, 66)) + '].'
    assert decode_answer(raw, evidence(), normalize=True)[0] == raw
    assert decode_answer('Fact [Source 1].', [], normalize=True)[0] == 'Fact [Source 1].'


@pytest.mark.parametrize('answer', [
    'Fact [Source ' + ', '.join(['1'] * 65) + '].',
    'Fact [Source 1' + ' ' * 4096 + '].',
])
@pytest.mark.parametrize('structured', [False, True])
def test_marker_bounds_apply_before_deduplication_in_stream_and_final(answer, structured):
    raw = (json.dumps({'answer': answer, 'source_ids': []}) if structured else answer)
    final, selected, audit = decode_answer(raw, evidence(), structured=structured, normalize=True)
    assert final == answer and selected == []
    for split in {0, len(raw), len(raw) - 2, len(raw) - 3, len(raw) // 2}:
        delivered = []
        delivery = EvidenceStream(delivered.append, lambda value: value, lambda: None)
        stream = AnswerContractStream(delivery.feed, structured=structured,
                                      normalize=True, items=evidence())
        stream.feed(raw[:split])
        stream.feed(raw[split:])
        delivery.finish(final)
        assert ''.join(delivered) == answer


@pytest.mark.parametrize('marker', [
    '<span class="citation" data-citation="1"></span>',
    "<span data-citation='1, 8' class='citation'></span>",
    '<SPAN CLASS="citation" DATA-CITATION="1,8,1"></SPAN>',
    '<span class=citation data-citation=1></span>',
])
def test_empty_html_citation_spans_use_only_exact_scoped_ids(marker):
    answer, selected, audit = decode_answer('Fact.' + marker, evidence(), normalize=True)
    assert answer == 'Fact.'
    assert audit['selected_ids'] == (['1'] if '8' not in marker else ['1', '8'])
    assert audit['inline_markers_removed'] == 1


@pytest.mark.parametrize('text', [
    'Unknown <span class="citation" data-citation="99"></span>.',
    'Mixed <span class="citation" data-citation="1,99"></span>.',
    'Extra <span class="citation" data-citation="1" title="literal"></span>.',
    'Duplicate <span class="citation" data-citation="1" data-citation="8"></span>.',
    'Other <span class="citation sample" data-citation="1"></span>.',
    'Content <span class="citation" data-citation="1">literal</span>.',
    'Self-closing <span class="citation" data-citation="1"/>.',
    'Code `<span class="citation" data-citation="1"></span>`.',
    'Example:\n\n    <span class="citation" data-citation="1"></span>',
    'Quoted “<span class="citation" data-citation="1"></span>”.',
    'Quoted 「<span class="citation" data-citation="1"></span>」.',
    'Read [<span class="citation" data-citation="1"></span>](https://example.test).',
    'Read <a href="https://example.test"><span class="citation" data-citation="1"></span></a>.',
    'Use <code><span class="citation" data-citation="1"></span></code>.',
    'Malformed <span class="citation" data-citation="01"></span>.',
    'Literal <span class="citation" data-citation="1, 8"></span with typo>.',
])
def test_html_citation_lookalikes_and_literal_examples_remain_unchanged(text):
    answer, selected, audit = decode_answer(text, evidence(), normalize=True)
    assert answer == text
    assert selected == []
    assert audit['inline_markers_removed'] == 0


@pytest.mark.parametrize('structured', [False, True])
@pytest.mark.parametrize('answer', [
    'Fact.<span class="citation" data-citation="1, 8"></span> More.',
    'Fact.<span data-citation="1" class="citation"></span>',
    'Literal <span class="citation" data-citation="1">content</span>.',
    'Unknown <span class="citation" data-citation="99"></span>.',
    'Quoted “<span class="citation" data-citation="1"></span>”.',
    'Use `<span class="citation" data-citation="1"></span>` literally.',
    '<span class="citation" data-citation="1"></span> after.',
    '<span class="citation" data-citation="1"></span>\n\nAfter.',
    'Fact.<span class="citation" data-citation="' + ','.join(['1'] * 65) + '"></span>.',
])
def test_html_citation_spans_preserve_stream_prefixes_at_every_split(structured, answer):
    test_every_chunk_boundary_finishes_with_exact_normalized_answer(structured, answer)


@pytest.mark.parametrize('structured', [False, True])
def test_html_citation_length_bound_is_identical_for_stream_and_final(structured):
    answer = 'Fact.<span class="citation"' + ' ' * 4096 + 'data-citation="1"></span>.'
    raw = json.dumps({'answer': answer, 'source_ids': []}) if structured else answer
    final, selected, _ = decode_answer(raw, evidence(), structured=structured, normalize=True)
    assert final == answer and selected == []
    for split in {len(raw) // 2, len(raw) - 1, len(raw) - 9}:
        delivered = []
        delivery = EvidenceStream(delivered.append, lambda value: value, lambda: None)
        stream = AnswerContractStream(delivery.feed, structured=structured, normalize=True, items=evidence())
        stream.feed(raw[:split])
        stream.feed(raw[split:])
        delivery.finish(final)
        assert ''.join(delivered) == final
