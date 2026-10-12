import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from google.genai import types

from services.llama_rag.answer_contract import (
    AnswerContractStream, answer_messages, answer_schema, decode_answer,
    native_schema_supported,
)
from services.llama_rag.client import RetrievalError
from services.llama_rag.streaming import EvidenceStream
from services.providers.generation_input import (
    generation_input, current_input, gemini_contents, openai_messages,
    openai_output_options, admission_text,
)
from services.providers.gemini_provider import GeminiProvider
from services.providers.openai_provider import OpenAIProvider


def items():
    return [{'chunk': SimpleNamespace(metadata_json={'citation_id': n}),
             'document': SimpleNamespace(id=n)} for n in ('1', '2', '7')]


@pytest.mark.parametrize('structured', [False, True])
@pytest.mark.parametrize('normalize', [False, True])
@pytest.mark.parametrize('ascii_only', [False, True])
def test_every_stream_split_matches_final_without_metadata_leak(structured, normalize, ascii_only):
    answer = 'A "quoted" answer.\\\n\n- Café 🌍: 8–10 oz. [Source 1]\n- Other: 6–8 oz. [ID:7]'
    response = (json.dumps({'answer': answer, 'source_ids': ['1', '7']}, ensure_ascii=ascii_only)
                if structured else answer + '\n<source_refs>["1","7"]</source_refs>')
    final, selected, audit = decode_answer(response, items(), structured=structured, normalize=normalize)
    assert audit['selected_ids'] == ['1', '7']
    for split in range(len(response)+1):
        chunks = []
        delivery = EvidenceStream(chunks.append, lambda value: value, lambda: None)
        stream = AnswerContractStream(delivery.feed, structured=structured, normalize=normalize, items=items())
        stream.feed(response[:split])
        stream.feed(response[split:])
        shown = ''.join(chunks)
        assert final.startswith(shown)
        assert 'source_refs' not in shown and 'source_ids' not in shown
        delivery.finish(final)
        assert ''.join(chunks) == final
    chunks = []
    delivery = EvidenceStream(chunks.append, lambda value: value, lambda: None)
    stream = AnswerContractStream(delivery.feed, structured=structured, normalize=normalize, items=items())
    for char in response:
        stream.feed(char)
    assert final.startswith(''.join(chunks))
    delivery.finish(final)
    assert ''.join(chunks) == final


def test_sparse_context_ids_and_foreign_citations_do_not_select_neighbor():
    answer, selected, audit = decode_answer('Fact [Source 7]. Wrong [ID:9]. Ordinary [1].', items(), normalize=True)
    assert audit['selected_ids'] == ['7']
    assert audit['invalid_count'] == 0
    assert selected == [items()[2]]
    assert answer == 'Fact. Wrong [ID:9]. Ordinary [1].'


@pytest.mark.parametrize('raw', [
    '{"answer":"A","answer":"B","source_ids":[]}',
    '{"answer":"A","source_ids":[true]}',
    '{"answer":"A","source_ids":[],"extra":"hidden"}',
    '{"answer":"partial', '{"source_ids":[]}', '[]', 'null',
])
def test_malformed_native_output_never_returns_raw_json(raw):
    with pytest.raises(RetrievalError, match='invalid_answer_schema'):
        decode_answer(raw, items(), structured=True)


def test_empty_sources_are_valid_without_attaching_retrieved_pages():
    answer, selected, audit = decode_answer('{"answer":"Not confirmed.","source_ids":[]}', items(), structured=True)
    assert answer == 'Not confirmed.' and selected == [] and audit['status'] == 'valid'


def test_message_roles_keep_current_question_last_and_evidence_out_of_system():
    history = [{'role':'user','content':'Old question'}, {'role':'assistant','content':'Old answer'}]
    messages = answer_messages(history, 'Evidence\nCurrent question')
    with generation_input(messages, answer_schema(items())):
        output = openai_messages('serialized fallback', 'Trusted instructions')
        assert [m['role'] for m in output] == ['developer','user','assistant','user']
        assert output[0]['content'] == 'Trusted instructions'
        assert output[-1]['content'] == 'Evidence\nCurrent question'
        config = types.GenerateContentConfig(system_instruction='Trusted instructions')
        contents = gemini_contents('serialized fallback', config)
        assert [m.role for m in contents] == ['user','model','user']
        assert config.system_instruction == 'Trusted instructions'
        assert config.response_json_schema['properties']['source_ids']['items']['enum'] == ['1','2','7']
        assert config.response_mime_type == 'application/json'
        assert openai_output_options()['text']['format']['strict'] is True
        reservation = admission_text('serialized fallback')
        assert all(s in reservation for s in ['Old question','Old answer','Current question','source_ids'])
    assert current_input().messages == () and current_input().schema is None
    assert history == messages[:-1]


def test_native_options_are_isolated_between_tenants_and_nested_calls():
    barrier = Barrier(10)
    def run(index):
        with generation_input([{'role':'user','content':str(index)}], {'tenant':index}):
            barrier.wait(timeout=5)
            with generation_input():
                assert current_input().schema is None
            return current_input().messages, current_input().schema
    with ThreadPoolExecutor(10) as pool:
        rows = list(pool.map(run, range(10)))
    for i, (messages,schema) in enumerate(rows):
        assert messages == (('user',str(i)),) and schema == {'tenant':i}
    assert current_input().schema is None


def test_unknown_model_keeps_existing_answer_protocol():
    for provider,model in [('gemini','future-unknown'),('claude','anything'),('openai','gpt-3.5-turbo'),
                           ('openai','gpt-4o-2024-05-13'),('openai','gpt-4o-audio-preview'),
                           ('openai','gpt-4o-search-preview'),('openai','o3-deep-research')]:
        assert not native_schema_supported(SimpleNamespace(provider=provider,model_name=model))
    assert native_schema_supported(SimpleNamespace(provider='gemini',model_name='models/gemini-3.5-flash-lite'))
    assert native_schema_supported(SimpleNamespace(provider='openai',model_name='gpt-4.1-mini'))
    assert native_schema_supported(SimpleNamespace(provider='openai',model_name='gpt-4o-2024-08-06'))


@pytest.mark.parametrize('provider_class', [GeminiProvider, OpenAIProvider])
def test_real_provider_adapter_passes_contract_in_one_call(provider_class):
    provider = provider_class()
    client = Mock()
    provider._client = Mock(return_value=client)
    response = SimpleNamespace(text='{"answer":"A","source_ids":["1"]}',
        output_text='{"answer":"A","source_ids":["1"]}', usage=None, usage_metadata=None,
        sdk_http_response=None, candidates=[])
    client.models.generate_content.return_value = response
    client.responses.create.return_value = response
    with generation_input([{'role':'user','content':'actual'}], answer_schema(items())):
        result = provider.generate_with_metadata(api_key='synthetic', model_name='gemini-3.5-flash-lite'
            if provider_class is GeminiProvider else 'gpt-4.1', prompt='fallback', system_instruction='instructions')
    assert result.text == response.text
    if provider_class is GeminiProvider:
        client.models.generate_content.assert_called_once()
        assert client.models.generate_content.call_args.kwargs['contents'][0].parts[0].text == 'actual'
    else:
        client.responses.create.assert_called_once()
        assert client.responses.create.call_args.kwargs['text']['format']['type'] == 'json_schema'
