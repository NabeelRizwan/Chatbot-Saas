"""General citation-release controls; synthetic data only, no provider calls."""
import copy
import json
from types import SimpleNamespace

import pytest

from services.rag2 import citation_registry as registry_module
from services.rag2 import source_map_answer as contract


def packet(answer='The workshop opens at 08:45.', text=None, cid='manual:Q-8'):
    text = text or 'The workshop opens at 08:45. Capacity is 16 visitors.'
    item = {'chunk': SimpleNamespace(content=text, metadata_json={'citation_id': cid})}
    fact = {'subject': 'Workshop', 'field': 'hours', 'text': 'Opening time.', 'quote': text}
    payload = {'answer': answer, 'source_ids': [cid],
               'source_map': [{'source_id': cid, 'relevant_facts': [fact]}]}
    return text, [item], payload


def decode(context, items, payload):
    frozen = copy.deepcopy(payload)
    raw = json.dumps(payload, ensure_ascii=False)
    answer, selected, audit = contract.validated_answer(raw, context, items)
    assert answer == payload['answer'] and payload == frozen
    return selected, audit


@pytest.mark.parametrize('answer', [
    'Type `[Source 72]` literally.',
    'Type ``a `[Source 72]` example`` literally.',
    '```json\n{"example": "[Source 72]"}\n```',
    '~~~text\n<source_refs>private example</source_refs>\n~~~',
    'Example:\n\n    [Source 72]\n\nContinue here.',
    'Example:\r\n\r\n\t[Source_72]\r\n\r\nContinue here.',
    '>     [ID:72]\n',
    '> ```text\n> [Source 72]\n> ```',
    '- Example:\n\n      [Source 72]\n',
    '```text\n[Source 72]',  # CommonMark permits an unclosed fenced block.
    'A [`[Source 72]`](https://example.test/reference) code label.',
    'Keep `<span data-citation="72">` as an example.',
    'Line\u2028separator, then `[Source 72]`.',
    '```text\n[Source 72]\n```\u2028[Source 73]',  # U+2028 does not close a CommonMark fence line.
])
def test_actual_markdown_code_is_not_a_leaked_private_marker(answer):
    context, items, payload = packet(answer)
    selected, audit = decode(context, items, payload)
    assert selected == items and audit['fatal_errors'] == []


@pytest.mark.parametrize('answer', [
    'The time is 08:45 [Source 72].',
    'The time is 08:45 [Source_72].',
    'The time is 08:45 [ID:72].',
    'Before <source_refs>["72"]</source_refs> after.',
    '<span data-citation="72">reference</span>',
    'Unmatched `[Source 72] backtick.',
    r'Escaped \`[Source 72]\` is ordinary text.',
    r'Escaped \[Source 72\] still displays a source marker.',
    '```text\n[Source 72]\n```\nOutside [Source 73].',
    'Paragraph\n    [Source 72]',  # Indent cannot interrupt a paragraph.
    '[Source 72](https://example.test/reference)',
    '[Source 72][manual]\n\n[manual]: https://example.test/reference',
    '[manual](https://example.test/[Source_72])',
    '[manual](https://example.test/ "[Source 72]")',
    '![Source 72](https://example.test/picture.png)',
    '![`[Source 72]`](https://example.test/picture.png)',
    '[Source 72]: https://example.test/reference',
    'Read &#91;Source 72&#93;.',
    'Read [**Source** 72].',
    '<pre>[Source 72]</pre>',
])
def test_non_code_markers_stay_blocked_without_rewriting_the_answer(answer):
    context, items, payload = packet(answer)
    _, audit = decode(context, items, payload)
    assert audit['fatal_errors'] == ['answer:raw_source_marker']


@pytest.mark.parametrize('text, quote, accepted', [
    ('Café panels are ready.', 'Cafe\u0301 panels are ready.', True),
    ('Cafe\u0301 panels are ready.', 'Cafe', False),
    ('नाम: **किरण**।', 'नाम: किरण।', True),
    ('किताब', 'कि', False),
    ('الاسم **عَلَم**', 'الاسم عَلَم', True),
    ('区域：苏州市。', '苏州市', True),
    ('Badge 👨\u200d👧 available.', '👨\u200d👧', True),
    ('Badge 👨\u200d👧 available.', '👨', False),
    ('Value −4.2 mm.', '4.2 mm', False),
    ('Load 150 kg.', '15', False),
    ('3. Open the hatch.', '8. Open the hatch.', False),
    ('Use [portal](https://example.test/right).', 'Use [portal](https://other.test/wrong).', False),
    ('Use [portal](https://example.test/right).', 'Use portal.', True),
    ('Do **not** freeze.', 'Do not freeze.', True),
    ('Do **not** freeze.', 'Do freeze.', False),
    ('Type `count * 2 + 1`.', 'count * 2 + 1', True),
    ('Type `count * 2 + 1`.', 'count + 2 + 1', False),
])
def test_literal_quote_provenance_preserves_factual_characters(text, quote, accepted):
    context, items, payload = packet(text=text)
    payload['source_map'][0]['relevant_facts'][0]['quote'] = quote
    selected, audit = decode(context, items, payload)
    assert bool(selected) is accepted
    assert not audit['fatal_errors']


def test_good_quote_survives_bad_companion_without_certifying_that_companion():
    context, items, payload = packet()
    payload['source_map'][0]['relevant_facts'] = [
        {'subject': 'Workshop', 'field': 'opening', 'text': '08:45.',
         'quote': 'The workshop opens at 08:45.'},
        {'subject': 'Workshop', 'field': 'capacity', 'text': '18 visitors.',
         'quote': 'Capacity is 18 visitors.'},
    ]
    selected, audit = decode(context, items, payload)
    assert selected == items
    assert audit['verified_fact_paths'] == ['source_map[0].relevant_facts[0]']
    assert 'source_map[0].relevant_facts[1].quote:not_in_own_source' in audit['validation_errors']


def test_authentic_long_quote_is_diagnostic_and_never_truncates_the_answer():
    passage = ' '.join('instruction' + str(i) for i in range(85)) + '.'
    context, items, payload = packet(text=passage, answer=passage)
    selected, audit = decode(context, items, payload)
    assert selected == items and not audit['validation_errors']
    assert audit['diagnostics'] == ['source_map[0].relevant_facts[0].quote:over_60_words_but_provenance_checked']


def test_literal_source_identity_wins_and_underscore_alias_collisions_do_not_guess():
    available = {cid: {'text': 'Evidence ' + cid} for cid in ('1', '_1', 'source_1')}
    registry = registry_module.CitationRegistry(available, '')
    assert registry.resolve('source_1') == 'source_1'
    assert registry.resolve('[Source_1]') is None
    assert registry.resolve('1') == '1' and registry.resolve('_1') == '_1'


def test_optional_markdown_budget_never_disables_exact_or_whitespace_evidence(monkeypatch):
    monkeypatch.setattr(registry_module, 'MAX_MARKDOWN_SOURCE_CHARS', 20)
    text = 'Very long **workshop** instructions remain complete.'
    registry = registry_module.CitationRegistry({'r': {'text': text}}, text)
    assert registry.quote_match('r', 'Very long workshop instructions') is None
    assert registry.quote_match('r', text) == 'exact'
    assert registry.quote_match('r', text.replace(' ', '\u00a0')) == 'nfc_whitespace'
    assert registry.diagnostics == [{'source_id': 'r', 'code': 'markdown_projection_budget_exceeded'}]


def test_projection_caches_are_per_request_and_each_source_is_parsed_once(monkeypatch):
    original = registry_module.visible_markdown
    parsed = []
    def tracked(text):
        parsed.append(text)
        return original(text)
    monkeypatch.setattr(registry_module, 'visible_markdown', tracked)
    text = 'The **Alder** panel is **blue**.'
    first = registry_module.CitationRegistry({'r': {'text': text}}, text)
    assert first.quote_match('r', 'The Alder panel')
    assert first.quote_match('r', 'panel is blue.')
    assert parsed == [text]
    second = registry_module.CitationRegistry({'r': {'text': 'The **Birch** panel is **red**.'}}, '')
    assert second.quote_match('r', 'The Alder panel') is None
    assert len(parsed) == 2


def test_deep_json_is_rejected_as_invalid_json_instead_of_raising_recursion_error():
    raw = '[' * 5000 + '0' + ']' * 5000
    answer, selected, audit = contract.validated_answer(raw, '', [])
    assert answer == '' and selected == [] and audit['fatal_errors'] == ['invalid_json']
