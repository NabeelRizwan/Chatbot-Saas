"""Offline provenance, provider transport and live-answer boundary checks."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

import pytest
from google.genai import types

# Reuse only the existing isolated SQLite test setup, never application data.
import test_llama_rag as support
from services.rag2 import answer, knowledge, planned_client, search_planning, source_map_answer as contract
from services.llm_router import generation_stream_context, get_generation_stream_sink
from services.observability_service import ChatTrace
from services.providers.base_provider import ProviderError
from services.providers.gemini_provider import GeminiProvider
from services.providers.generation_input import generation_input, current_input, gemini_contents


def evidence():
    texts = ['Store Alpha upright in a dry place.', 'Keep the Beta cap closed.']
    items = [{'chunk': SimpleNamespace(content=text, metadata_json={'citation_id': str(i + 1)})}
             for i, text in enumerate(texts)]
    return '\n\n'.join(texts), items


def reply():
    return {'source_map': [
        {'source_id': '1', 'relevant_facts': [{'subject': 'Alpha', 'field': 'storage',
            'text': 'Store upright in a dry place.', 'quote': 'Store Alpha upright in a dry place.'}]},
        {'source_id': '2', 'relevant_facts': [{'subject': 'Beta', 'field': 'storage',
            'text': 'Keep the cap closed.', 'quote': 'Keep the Beta cap closed.'}]},
    ], 'answer': 'Store Alpha upright in a dry place. Keep the Beta cap closed.', 'source_ids': ['1', '2']}


def test_valid_answer_preserves_all_prose_and_scoped_source_objects():
    context, items = evidence()
    payload = reply()
    payload['answer'] = '  Café 🌍.\n\n' + payload['answer'] + '\nLast sentence.\n'
    result = contract.decode_response(json.dumps(payload), context, items)
    assert result['validation_errors'] == []
    assert result['answer'] == payload['answer']
    assert result['source_map'] == payload['source_map']
    assert result['sources'][0] is items[0] and result['sources'][1] is items[1]


@pytest.mark.parametrize('mutation, expected', [
    (lambda p: p['source_map'].pop(), 'source_map:missing_source:2'),
    (lambda p: p['source_map'][1].update(source_id='1'), 'source_map[1].source_id:duplicate'),
    (lambda p: p['source_map'][1].update(source_id='999'), 'source_map[1].source_id:unknown'),
    (lambda p: p['source_map'][0]['relevant_facts'][0].update(quote='Keep the Beta cap closed.'),
     'source_map[0].relevant_facts[0].quote:not_in_own_source'),
    (lambda p: p['source_map'][0]['relevant_facts'][0].update(quote='Invented evidence.'),
     'source_map[0].relevant_facts[0].quote:not_in_context'),
    (lambda p: p.update(source_ids=['999']), 'source_ids[0]:unknown_source_id'),
    (lambda p: p.update(source_ids=['1', '1']), 'source_ids:duplicate_source_id:1'),
    (lambda p: p.update(answer='First. <source_refs>["1"]</source_refs> Last.'), 'answer:raw_source_marker'),
])
def test_local_validation_rejects_bad_provenance_without_silent_repair(mutation, expected):
    context, items = evidence()
    payload = reply()
    mutation(payload)
    result = contract.decode_response(json.dumps(payload), context, items)
    assert expected in result['validation_errors']
    assert result['answer'] == payload['answer']


@pytest.mark.parametrize('raw, expected', [
    ('{"source_map":', 'invalid_json'),
    ('{"source_map":[],"answer":"first","answer":"last","source_ids":[]}', 'duplicate_json_key:answer'),
    ('{"source_map":[],"answer":NaN,"source_ids":[]}', 'invalid_json'),
])
def test_partial_duplicate_and_non_json_outputs_are_flagged(raw, expected):
    context, items = evidence()
    assert expected in contract.decode_response(raw, context, items)['validation_errors']


def test_irrelevant_sources_still_require_records_but_do_not_become_citations():
    context, items = evidence()
    payload = reply()
    payload['source_map'][0]['relevant_facts'] = []
    payload['source_ids'] = ['2']
    payload['answer'] = 'Keep the Beta cap closed.'
    result = contract.decode_response(json.dumps(payload), context, items)
    assert result['validation_errors'] == [] and result['sources'] == [items[1]]


def test_unrecognized_citations_are_audited_and_never_attached_or_guessed():
    context, items = evidence()
    payload = reply()
    payload['source_ids'] = ['Source 1', '2', '999']
    answer_text, selected, audit = contract.validated_answer(json.dumps(payload), context, items)
    assert answer_text == payload['answer'] and selected == [items[1]]
    assert audit['attached_ids'] == ['2'] and len(audit['validation_errors']) == 2
    assert audit['fatal_errors'] == []


def test_schema_relaxes_only_transport_constraints_and_has_no_visible_template():
    schema = contract.response_schema()
    assert list(schema['properties']) == ['source_map', 'answer', 'source_ids']
    mapping = schema['properties']['source_map']
    assert 'minItems' not in mapping and 'maxItems' not in mapping
    assert mapping['items']['properties']['source_id'] == {'type': 'string'}
    assert schema['properties']['source_ids']['items'] == {'type': 'string'}
    assert schema['properties']['answer'] == {'type': 'string'}


def test_more_than_64_sources_do_not_drop_citations_or_truncate_answer():
    items = [{'chunk': SimpleNamespace(content=f'Fact {i}.', metadata_json={'citation_id': str(i)})}
             for i in range(70)]
    context = '\n'.join(item['chunk'].content for item in items)
    payload = {'source_map': [{'source_id': str(i), 'relevant_facts': []} for i in range(70)],
               'answer': 'The complete answer ends here.', 'source_ids': [str(i) for i in range(70)]}
    result = contract.decode_response(json.dumps(payload), context, items)
    assert result['validation_errors'] == [] and len(result['sources']) == 70
    assert result['answer'].endswith('ends here.')


@pytest.mark.parametrize('provider, model, active', [
    ('gemini', 'gemini-3.5-flash-lite', True), ('gemini', 'models/gemini-3.5-flash-lite', True),
    ('gemini', None, True), ('gemini', 'gemini-2.5-flash', False), ('openai', 'gpt-4.1', False),
])
def test_method_is_explicit_and_uses_only_tested_model(provider, model, active):
    bot = SimpleNamespace(provider=provider, model_name=model)
    with patch.dict('os.environ', {'LLAMA_ANSWER_METHOD': contract.METHOD}):
        assert contract.selected(bot) is active
    with patch.dict('os.environ', {'LLAMA_ANSWER_METHOD': 'existing'}):
        assert contract.selected(bot) is active  # Organisation pipeline, never a global toggle.


def test_medium_thinking_and_schema_are_request_scoped_and_preserve_full_input():
    barrier = Barrier(4)
    def run(index):
        with generation_input(schema=contract.response_schema(), thinking_level='medium', require_complete=True):
            barrier.wait(timeout=5)
            config = types.GenerateContentConfig(temperature=.55, system_instruction=f'Business {index}')
            full = 'Full evidence\n' + ('distinct material ' * 10000)
            assert gemini_contents(full, config) is full
            assert config.thinking_config.thinking_level == types.ThinkingLevel.MEDIUM
            assert config.temperature == .55 and config.system_instruction == f'Business {index}'
            with generation_input():
                assert current_input().thinking_level is None and not current_input().require_complete
            assert current_input().thinking_level == 'medium'
        assert current_input().thinking_level is None and current_input().schema is None
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(run, range(4)))


@pytest.mark.parametrize('reason, valid', [(types.FinishReason.STOP, True), (types.FinishReason.MAX_TOKENS, False), (None, False)])
def test_provider_rejects_truncated_source_maps_even_when_text_is_valid_json(reason, valid):
    provider = GeminiProvider()
    client = Mock()
    provider._client = Mock(return_value=client)
    response = SimpleNamespace(text=json.dumps(reply()), usage_metadata=None, sdk_http_response=None,
                               candidates=[SimpleNamespace(finish_reason=reason)])
    client.models.generate_content.return_value = response
    with generation_input(schema=contract.response_schema(), thinking_level='medium', require_complete=True):
        kwargs = dict(api_key='synthetic', model_name='gemini-3.5-flash-lite', prompt='All evidence',
                      system_instruction='Customer prompt', temperature=.6)
        if valid:
            assert provider.generate_with_metadata(**kwargs).text == response.text
        else:
            with pytest.raises(ProviderError, match='did not complete'):
                provider.generate_with_metadata(**kwargs)
    sent = client.models.generate_content.call_args.kwargs
    assert sent['contents'] == 'All evidence'
    assert sent['config'].thinking_config.thinking_level == types.ThinkingLevel.MEDIUM
    assert sent['config'].temperature == .6 and sent['config'].system_instruction == 'Customer prompt'
    assert sent['config'].max_output_tokens is None


class SourceMapIntegrationTests(unittest.TestCase):
    def setUp(self):
        support.KnowledgeTests.setUp(self)
        self.client.mutate = lambda result: result.update(
            pipeline='rag2_improved', pipeline_build_revision='rag2-voyage-v1')
        for target, value in [(knowledge, 'RetrievalClient')]:
            patched = patch.object(target, value, return_value=self.client)
            patched.start(); self.addCleanup(patched.stop)
        planned = patch.object(planned_client, 'retrieve_planned',
            side_effect=lambda client, scope, docs, question, queries: self.client.retrieve(scope, docs, question))
        planned.start(); self.addCleanup(planned.stop)
        planner = patch.object(search_planning, 'generate_auxiliary', return_value='{"queries":["desk width"]}')
        planner.start(); self.addCleanup(planner.stop)
    tearDown = support.KnowledgeTests.tearDown

    def exercise(self, *, invalid=False, malformed=False, model='gemini-3.5-flash-lite', on_generate=None):
        self.bot.model_name = model
        self.bot.system_prompt = 'Customer business instructions.'
        self.bot.tone = 'friendly'
        self.bot.capabilities = {'temperature': .55}
        self.db.commit()
        trace = ChatTrace(self.bot.id, 'internal')
        deltas, observed = [], {}
        payload = {'source_map': [{'source_id': '1', 'relevant_facts': [
            {'subject': 'Desk', 'field': 'width', 'text': '120 cm wide', 'quote': 'The desk is 120 cm wide.'}]}],
            'answer': 'The desk is 120 cm wide.\n\nComplete final paragraph.', 'source_ids': ['1']}
        if invalid:
            payload['source_map'][0]['relevant_facts'][0]['quote'] = 'Unsupported invented width.'
        def generate(**kwargs):
            observed.update(kwargs)
            observed['contract'] = current_input()
            raw = json.dumps(payload) if model == 'gemini-3.5-flash-lite' else 'Existing answer.\n<source_refs>["1"]</source_refs>'
            if malformed:
                raw = raw[:-5]
            sink = get_generation_stream_sink()
            if sink:
                for char in raw:
                    sink(char)
            observed['during_generation'] = ''.join(deltas)
            if on_generate:
                on_generate()
            return raw
        with patch.dict('os.environ', {'LLAMA_ANSWER_METHOD': contract.METHOD,
                                      'LLAMA_ANSWER_NATIVE_MESSAGES': '1',
                                      'LLAMA_ANSWER_NORMALIZE_CITATIONS': '1'}), \
             patch.object(answer, 'generate', side_effect=generate), \
             patch.object(answer, 'resolve', return_value=SimpleNamespace(action='search', question='How wide is the desk?')), \
             generation_stream_context(deltas.append):
            result = answer.answer_question(self.db, self.bot, 'How wide is the desk?', trace=trace)
        return result, trace, observed, deltas, payload

    def test_integration_retains_customer_bot_full_context_and_only_publishes_validated_answer(self):
        result, trace, sent, deltas, payload = self.exercise()
        assert result[0] == payload['answer'] and ''.join(deltas) == payload['answer']
        assert sent['during_generation'] == ''
        assert result[1][0]['document_id'] == self.doc.id
        assert sent['bot'] is self.bot
        assert self.doc.raw_text in sent['prompt']
        assert sent['contract'].thinking_level == 'medium' and sent['contract'].require_complete
        assert sent['contract'].transport_timeout_seconds == 150
        assert sent['contract'].generation_timeout_seconds == 150
        assert sent['contract'].messages == ()
        assert sent['system_instruction'] == answer._answer_system_instruction(self.bot, structured=True) + '\n\n' + contract.SOURCE_MAP_INSTRUCTION
        assert 'Customer business instructions.' in sent['system_instruction']
        assert trace.diagnostics['source_attribution']['status'] == 'valid'
        assert current_input().thinking_level is None

    def test_malformed_response_publishes_neither_json_nor_provisional_answer(self):
        result, trace, sent, deltas, payload = self.exercise(malformed=True)
        assert result == (answer.TEMPORARY_SERVICE_REPLY, [], [])
        assert deltas == []
        assert trace.diagnostics['source_attribution']['status'] == 'invalid'
        assert trace.retrieval.terminal_response_category == 'temporary_service_failure'

    def test_map_audit_errors_preserve_tested_prose_delivery_with_visible_citations(self):
        result, trace, sent, deltas, payload = self.exercise(invalid=True)
        assert result[0] == payload['answer'] and ''.join(deltas) == payload['answer']
        assert sent['during_generation'] == ''
        assert result[1][0]['document_id'] == self.doc.id
        assert trace.diagnostics['source_attribution']['validation_errors']
        assert trace.diagnostics['source_attribution']['fatal_errors'] == []

    def test_other_customer_models_keep_existing_path(self):
        result, trace, sent, deltas, payload = self.exercise(model='configured-model')
        assert result[0] == 'Existing answer.'
        assert trace.diagnostics['answer_contract']['answer_method'] == 'existing'
        assert sent['contract'].thinking_level is None and not sent['contract'].require_complete
        assert contract.SOURCE_MAP_INSTRUCTION not in sent['system_instruction']

    def test_planned_large_context_is_preserved_by_improved_method(self):
        from services.rag2 import planned_client, search_planning, knowledge
        text = self.doc.raw_text + '\n' + ('Additional distinct source material is retained.\n' * 2000)
        self.doc.raw_text = text
        self.doc.content_hash = support.hashlib.sha256(text.encode()).hexdigest()
        self.db.commit()
        observed_queries = []
        def retrieve(client, scope, records, question, queries):
            observed_queries.extend(queries)
            return self.client.retrieve(scope, records, question)
        with patch.dict('os.environ', {'LLAMA_SEARCH_PLANNING': 'true'}), \
             patch.object(search_planning, 'generate_auxiliary', return_value='{"queries":["desk width"]}'), \
             patch.object(planned_client, 'retrieve_planned', side_effect=retrieve):
            result, trace, sent, deltas, payload = self.exercise()
        assert observed_queries == ['desk width']
        assert knowledge.count_tokens(text) > 4000 and text in sent['prompt']
        assert result[0] == payload['answer'] and ''.join(deltas) == payload['answer']
        assert sent['contract'].thinking_level == 'medium'

    def test_revoked_source_authority_cannot_release_buffered_answer(self):
        def revoke():
            self.doc.status = 'staging'
            self.db.commit()
        result, trace, sent, deltas, payload = self.exercise(on_generate=revoke)
        assert result == (answer.TEMPORARY_SERVICE_REPLY, [], []) and deltas == []
        assert trace.diagnostics['retrieval_failure']['category'] == 'knowledge_authority_changed'
