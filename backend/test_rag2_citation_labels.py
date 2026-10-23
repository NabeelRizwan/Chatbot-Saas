"""Offline decoder regressions: exact label aliases never invent provenance."""
import copy
import json
from types import SimpleNamespace

import pytest

from services.rag2 import source_map_answer as contract


def packet(ids=('1', '2')):
    items = [{'chunk': SimpleNamespace(
        content=f'Product {index} must stay dry and upright.', metadata_json={'citation_id': cid})}
        for index, cid in enumerate(ids)]
    context = '\n\n'.join(item['chunk'].content for item in items)
    payload = {'answer': '  Café 🌍.\r\nKeep both products dry.\n\nFinal line.  ',
        'source_ids': list(ids), 'source_map': [
            {'source_id': cid, 'relevant_facts': [
                {'subject': f'Product {index}', 'field': 'storage', 'text': 'Keep dry and upright.',
                 'quote': items[index]['chunk'].content}]}
            for index, cid in enumerate(ids)]}
    return context, items, payload


def decode(context, items, payload):
    answer, sources, audit = contract.validated_answer(
        json.dumps(payload, ensure_ascii=False), context, items)
    assert answer.encode('utf-8') == payload['answer'].encode('utf-8')
    return sources, audit


@pytest.mark.parametrize('selected', ['Source1', 'Source 1', '[Source 1]', 'source 1', ' SOURCE 1 ', '[Source1]', 'Source_1'])
@pytest.mark.parametrize('mapped', ['Source1', 'Source 1', '[Source 1]', 'Source  1', 'Source_1'])
def test_known_label_spellings_resolve_independently_without_rewriting_payload(selected, mapped):
    context, items, payload = packet()
    payload['source_ids'] = [selected, '2']
    payload['source_map'][0]['source_id'] = mapped
    before = copy.deepcopy(payload)
    sources, audit = decode(context, items, payload)
    assert sources == items
    assert sources[0] is items[0] and sources[1] is items[1]
    assert audit['attached_ids'] == ['1', '2'] and audit['validation_errors'] == []
    assert audit['selected_ids'] == payload['source_ids']
    assert payload == before
    result = contract.decode_response(json.dumps(payload), context, items)
    assert result['source_map'] == before['source_map']


@pytest.mark.parametrize('foreign', [
    'Source 999', '[Source 999]', 'Source01', 'Source ١',
    'Source 1 extra', '[Source 1, Source 2]', 1, None, ['1'], {'id': '1'},
])
def test_unrecognized_or_foreign_labels_never_guess(foreign):
    context, items, payload = packet()
    payload['source_ids'] = [foreign, '2']
    sources, audit = decode(context, items, payload)
    assert sources == [items[1]]
    assert audit['validation_errors'] == ['source_ids[0]:unknown_source_id']
    assert audit['fatal_errors'] == []


def test_partial_map_retains_missing_record_diagnostics_and_never_cites_omitted_map_source():
    context, items, payload = packet(('1', '2', '3'))
    payload['source_map'] = [payload['source_map'][0], payload['source_map'][2]]
    payload['source_map'][0]['source_id'] = '[Source 1]'
    payload['source_ids'] = ['Source 1', 'Source 2']
    sources, audit = decode(context, items, payload)
    assert sources == [items[0]]  # Mapped source 3 was not cited; source 2 lacks a map record.
    assert 'source_map:wrong_record_count' in audit['validation_errors']
    assert 'source_map:missing_source:2' in audit['validation_errors']
    assert audit['fatal_errors'] == []


@pytest.mark.parametrize('aliases', [ ['1', 'Source 1'], ['Source1', '[Source 1]'], ['1', '1'] ])
def test_duplicate_top_level_aliases_attach_once_and_are_still_audited(aliases):
    context, items, payload = packet()
    payload['source_ids'] = aliases
    sources, audit = decode(context, items, payload)
    assert sources == [items[0]]
    assert audit['validation_errors'] == ['source_ids:duplicate_source_id:1']


@pytest.mark.parametrize('duplicate', ['1', 'Source1', '[Source 1]'])
def test_duplicate_map_records_cannot_choose_a_winning_provenance(duplicate):
    context, items, payload = packet()
    second = copy.deepcopy(payload['source_map'][0])
    second['source_id'] = duplicate
    payload['source_map'].append(second)
    sources, audit = decode(context, items, payload)
    assert sources == [items[1]]
    assert 'source_map[2].source_id:duplicate' in audit['validation_errors']
    assert audit['fatal_errors'] == []


@pytest.mark.parametrize('literal', ['Source1', 'Source 1', '[Source 1]'])
def test_exact_known_id_wins_but_ambiguous_nonexact_alias_is_withheld(literal):
    context, items, payload = packet(('1', literal))
    sources, audit = decode(context, items, payload)
    assert sources == items and audit['validation_errors'] == []
    alias = next(value for value in ('Source1', 'Source 1', '[Source 1]') if value != literal)
    payload['source_ids'] = [alias]
    sources, audit = decode(context, items, payload)
    assert sources == [] and audit['validation_errors'] == ['source_ids[0]:unknown_source_id']


def test_known_literal_source_label_without_numeric_target_remains_valid():
    context, items, payload = packet(('Source 1',))
    sources, audit = decode(context, items, payload)
    assert sources == items and audit['validation_errors'] == []


@pytest.mark.parametrize('literal', ['Source1', 'Source 1', '[Source 1]'])
def test_ambiguous_map_label_cannot_borrow_an_exact_numeric_citation(literal):
    context, items, payload = packet(('1', literal))
    payload['source_map'][0]['source_id'] = next(
        value for value in ('Source1', 'Source 1', '[Source 1]') if value != literal)
    sources, audit = decode(context, items, payload)
    assert sources == [items[1]]
    assert 'source_map[0].source_id:unknown' in audit['validation_errors']
    assert 'source_map:missing_source:1' in audit['validation_errors']


@pytest.mark.parametrize('bad_first', [False, True])
def test_duplicate_record_with_one_valid_quote_is_withheld_regardless_of_order(bad_first):
    context, items, payload = packet()
    duplicate = copy.deepcopy(payload['source_map'][0])
    duplicate['source_id'] = 'Source 1'
    duplicate['relevant_facts'][0]['quote'] = 'Invented evidence.'
    payload['source_map'].insert(0 if bad_first else 1, duplicate)
    sources, audit = decode(context, items, payload)
    assert sources == [items[1]]
    assert 'source_ids:missing_valid_source_quote:1' in audit['validation_errors']


@pytest.mark.parametrize('mutation', [
    lambda p: p['source_map'][0].update(relevant_facts=[]),
    lambda p: p['source_map'][0].update(relevant_facts=None),
    lambda p: p['source_map'][0].update(relevant_facts={}),
    lambda p: p['source_map'][0].update(relevant_facts=[None]),
    lambda p: p['source_map'][0].update(extra='unexpected'),
    lambda p: p['source_map'][0]['relevant_facts'][0].update(quote='Invented evidence.'),
    lambda p: p['source_map'][0]['relevant_facts'][0].update(quote='Product 1 must stay dry and upright.'),
    lambda p: p['source_map'][0]['relevant_facts'][0].update(quote=None),
    lambda p: p['source_map'][0]['relevant_facts'][0].update(quote=''),
    lambda p: p['source_map'][0]['relevant_facts'][0].update(quote=' '),
    lambda p: p['source_map'][0]['relevant_facts'][0].update(subject=''),
    lambda p: p['source_map'][0]['relevant_facts'][0].pop('field'),
    lambda p: p['source_map'][0]['relevant_facts'][0].update(extra='unexpected'),
])
def test_missing_or_malformed_own_source_provenance_withholds_only_that_citation(mutation):
    context, items, payload = packet()
    mutation(payload)
    sources, audit = decode(context, items, payload)
    assert sources == [items[1]] and audit['attached_ids'] == ['2']
    assert audit['fatal_errors'] == []


def test_duplicate_fact_is_audited_without_erasing_the_independently_valid_fact():
    context, items, payload = packet()
    payload['source_map'][0]['relevant_facts'].append(
        copy.deepcopy(payload['source_map'][0]['relevant_facts'][0]))
    sources, audit = decode(context, items, payload)
    assert sources == items
    assert 'source_map[0].relevant_facts[1]:duplicate_fact' in audit['validation_errors']
    assert 'source_map[0].relevant_facts[0]' in audit['verified_fact_paths']
    assert 'source_map[0].relevant_facts[1]' not in audit['verified_fact_paths']


def test_overlong_authentic_own_source_quote_remains_valid_with_a_diagnostic():
    context, items, payload = packet()
    long_quote = ' '.join(f'word{i}' for i in range(61))
    items[0]['chunk'].content = long_quote
    context = long_quote + '\n' + items[1]['chunk'].content
    payload['source_map'][0]['relevant_facts'][0]['quote'] = long_quote
    sources, audit = decode(context, items, payload)
    assert sources == items and audit['validation_errors'] == []
    assert 'source_map[0].relevant_facts[0].quote:over_60_words_but_provenance_checked' in audit['diagnostics']


@pytest.mark.parametrize('invalid_map', [None, {}, 'not a map'])
def test_invalid_map_cannot_attach_top_level_ids(invalid_map):
    context, items, payload = packet()
    payload['source_map'] = invalid_map
    sources, audit = decode(context, items, payload)
    assert sources == [] and audit['validation_errors'] == ['source_map:array_required']
    assert audit['fatal_errors'] == []


def test_map_evidence_does_not_invent_top_level_citations_or_sort_the_selected_order():
    context, items, payload = packet()
    payload['source_ids'] = ['Source 2', '[Source 1]']
    sources, audit = decode(context, items, payload)
    assert sources == items[::-1] and audit['validation_errors'] == []
    payload['source_ids'] = []
    sources, audit = decode(context, items, payload)
    assert sources == [] and audit['validation_errors'] == []


def test_duplicate_scoped_evidence_ids_remain_fatal_before_model_output_is_read():
    context, items, payload = packet(('1', '1'))
    with pytest.raises(contract.RetrievalError, match='source_map_citation_ids_invalid'):
        decode(context, items, payload)


@pytest.mark.parametrize('raw, expected', [
    ('{"source_map":', ['invalid_json']),
    ('[]', ['response_not_object']),
    ('{"answer":"first","answer":"last","source_map":[],"source_ids":[]}',
     ['duplicate_json_key:answer']),
    ('{"answer":null,"source_map":[],"source_ids":[]}', ['answer:string_required']),
    ('{"answer":" ","source_map":[],"source_ids":[]}', ['answer:nonempty_string_required']),
    ('{"answer":"Text [Source 1]","source_map":[],"source_ids":[]}', ['answer:raw_source_marker']),
    ('{"answer":"Text","source_map":[],"source_ids":null}', ['source_ids:array_required']),
    ('{"answer":"Text","source_map":[]}', ['response:missing_key:source_ids', 'source_ids:array_required']),
    ('{"answer":"Text","source_map":[],"source_ids":[],"extra":1}', ['response:unexpected_key:extra']),
])
def test_fatal_error_classification_remains_exact(raw, expected):
    context, items, _ = packet()
    _, _, audit = contract.validated_answer(raw, context, items)
    assert audit['fatal_errors'] == expected


@pytest.mark.parametrize('raw', [None, 'x' * 2_000_001], ids=['not_text', 'over_size_limit'])
def test_response_type_and_size_limits_remain_fatal(raw):
    context, items, _ = packet()
    with pytest.raises(contract.RetrievalError, match='source_map_response_invalid_or_too_large'):
        contract.validated_answer(raw, context, items)
