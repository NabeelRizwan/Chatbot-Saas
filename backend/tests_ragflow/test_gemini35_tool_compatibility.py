"""Provider wire tests. Socket access is blocked by the suite fixture."""
import asyncio
import copy
import json
import pytest
import httpx
from google import genai
from google.genai import types
from ragflow_dev.gemini35 import Gemini35Provider
from ragflow_dev.gemini35_tools import declarations_for, history_contents, parse_native_response, CLIENT_HISTORY_SIGNATURE
from ragflow_derived.upstream.advanced_rag.harness.action_session import _TOOL_MAP


def spec(name='lookup', parameters=None):
    return {'type': 'function', 'function': {'name': name, 'description': 'Synthetic tool.', 'parameters':
        parameters if parameters is not None else {'type': 'object', 'properties': {}, 'required': []}}}


def response(parts):
    return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role='model', parts=parts))])


def history(calls, content=''):
    return [{'role': 'user', 'content': 'Synthetic.'}, {'role': 'assistant', 'content': content, 'tool_calls': [
        {'id': c.id, 'type': 'function', 'function': vars(c.function)} for c in calls]}]


@pytest.mark.parametrize('parameters', [None, {'type': 'object', 'properties': {'topic': {'type': 'string'}}, 'required': ['topic']}])
def test_canonical_schemas_roundtrip_without_mutation(parameters):
    source = spec(parameters=parameters)
    before = copy.deepcopy(source)
    assert declarations_for([source])[0].parameters_json_schema == source['function']['parameters']
    assert source == before


@pytest.mark.parametrize('name', list(_TOOL_MAP))
def test_every_real_upstream_schema_is_identity_conversion(name):
    source = copy.deepcopy(_TOOL_MAP[name])
    converted = declarations_for([source])[0]
    assert converted.name == source['function']['name']
    assert converted.description == source['function']['description']
    assert converted.parameters_json_schema == source['function']['parameters']
    assert source == _TOOL_MAP[name]


@pytest.mark.parametrize('parameters', [
    {'type': 'string'}, {'type': 'object', 'required': ['missing']},
    {'type': 'object', 'properties': {'bad-name': {'type': 'string'}}},
    {'type': 'object', 'properties': {'x': {'type': 'array'}}},
    {'type': 'object', 'properties': {'x': {'type': 'array', 'items': [{'type': 'string'}]}}},
    {'type': 'object', 'properties': {'x': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 3, 'maxItems': 1}}},
    {'type': 'object', 'properties': {'x': {'type': 'string', 'enum': []}}},
    {'type': 'object', 'properties': {'x': {'type': ['string', 'null']}}},
    *[{'type': 'object', keyword: {}} for keyword in ('$ref', 'oneOf', 'anyOf', 'allOf', 'additionalProperties', 'default', 'format', 'title')],
])
def test_unvalidated_or_invalid_schema_fails_without_silently_stripping(parameters):
    with pytest.raises(ValueError):
        declarations_for([spec(parameters=parameters)])


@pytest.mark.parametrize('name', ['', 'bad name', 'x' * 129])
def test_invalid_function_name(name):
    with pytest.raises(ValueError):
        declarations_for([spec(name)])


def test_duplicate_names_rejected():
    with pytest.raises(ValueError):
        declarations_for([spec(), spec()])


def test_parallel_ids_full_parts_signatures_and_response_names_are_preserved():
    parts = [types.Part(text='private thought', thought=True, thought_signature=b'text-signature'),
        types.Part(function_call=types.FunctionCall(id='provider-one', name='lookup', args={'topic': 'a'}), thought_signature=b'call-signature'),
        types.Part(text='Checking both.'),
        types.Part(function_call=types.FunctionCall(id='provider-two', name='lookup', args={'topic': 'b'})),
        types.Part(text='', thought_signature=b'last-signature')]
    state = {}
    parsed = parse_native_response(response(parts), state, {'lookup'})
    calls = parsed.choices[0].message.tool_calls
    assert [c.id for c in calls] == ['provider-one', 'provider-two']
    assert parsed.choices[0].message.content == 'Checking both.'
    messages = history(calls, 'Checking both.') + [
        {'role': 'tool', 'tool_call_id': c.id, 'name': 'lookup', 'content': str(i)} for i, c in enumerate(calls)]
    before = copy.deepcopy(messages)
    _, contents = history_contents(messages, state, {'lookup'})
    assert contents[1].parts == parts
    results = [p.function_response for p in contents[2].parts]
    assert [p.id for p in results] == ['provider-one', 'provider-two']
    assert all(p.name == 'lookup' for p in results)
    assert messages == before
    assert 'private thought' not in parsed.choices[0].message.content


def test_missing_provider_id_gets_internal_id_only_and_signature_never_replaced():
    state = {}
    parts = [types.Part(function_call=types.FunctionCall(name='lookup', args={}), thought_signature=b'provider')]
    call = parse_native_response(response(parts), state, {'lookup'}).choices[0].message.tool_calls[0]
    messages = history([call]) + [{'role': 'tool', 'tool_call_id': call.id, 'content': 'x'}]
    _, contents = history_contents(messages, state, {'lookup'})
    assert call.id.startswith('call_')
    assert contents[1].parts == parts
    assert contents[2].parts[0].function_response.id is None


def test_upstream_synthetic_history_gets_documented_marker_not_fake_provider_signature():
    messages = [{'role': 'user', 'content': 'x'}, {'role': 'assistant', 'content': '', 'tool_calls': [
        {'id': 'local-first', 'function': {'name': 'lookup', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'local-first', 'content': 'unchanged exact result'}]
    _, contents = history_contents(messages, {}, {'lookup'})
    assert contents[1].parts[0].thought_signature == CLIENT_HISTORY_SIGNATURE
    assert contents[1].parts[0].function_call.id == contents[2].parts[0].function_response.id == 'local-first'
    assert contents[2].parts[0].function_response.response == {'result': 'unchanged exact result'}


def test_non_call_part_metadata_survives_neutral_history():
    state = {}
    parts = [types.Part(text='visible'), types.Part(text='', thought_signature=b'last')]
    parse_native_response(response(parts), state, {'lookup'})
    _, contents = history_contents([{'role': 'assistant', 'content': 'visible'}, {'role': 'user', 'content': 'Next.'}], state, {'lookup'})
    assert contents[0].parts == parts


@pytest.mark.parametrize('mutation', ['foreign-id', 'wrong-name', 'missing', 'duplicate', 'args', 'reorder', 'text'])
def test_invalid_tool_context_rejected_before_request(mutation):
    state = {}
    calls = parse_native_response(response([types.Part(function_call=types.FunctionCall(id=cid, name='lookup', args={}))
        for cid in ('p1', 'p2')]), state, {'lookup'}).choices[0].message.tool_calls
    messages = history(calls) + [{'role': 'tool', 'tool_call_id': c.id, 'content': 'x'} for c in calls]
    if mutation == 'foreign-id': messages[2]['tool_call_id'] = 'foreign'
    if mutation == 'wrong-name': messages[2]['name'] = 'foreign'
    if mutation == 'missing': messages.pop()
    if mutation == 'duplicate': messages.append(copy.deepcopy(messages[-1]))
    if mutation == 'args': messages[1]['tool_calls'][0]['function']['arguments'] = '{"changed":true}'
    if mutation == 'reorder': messages[1]['tool_calls'].reverse()
    if mutation == 'text': messages[1]['content'] = 'changed'
    with pytest.raises(ValueError):
        history_contents(messages, state, {'lookup'})


def test_foreign_tool_rejected_before_dispatch_and_state_not_poisoned():
    state = {}
    with pytest.raises(ValueError, match='UNKNOWN_PROVIDER_TOOL'):
        parse_native_response(response([types.Part(function_call=types.FunctionCall(name='foreign', args={}))]), state, {'lookup'})
    assert state == {}


def test_installed_sdk_serializes_ids_signatures_and_canonical_schemas_without_network(caplog):
    bodies = []
    async def mock(request):
        bodies.append(json.loads(request.content))  # Never capture headers.
        parts = ([{'functionCall': {'id': 'native-provider-id', 'name': 'lookup', 'args': {}}, 'thoughtSignature': 'b3BhcXVl'}]
                 if len(bodies) == 1 else [{'text': 'Done.'}])
        return httpx.Response(200, json={'candidates': [{'content': {'role': 'model', 'parts': parts}}]})
    async def run():
        client = genai.Client(api_key='private-placeholder-never-log', vertexai=False,
            http_options=types.HttpOptions(httpx_async_client=httpx.AsyncClient(transport=httpx.MockTransport(mock))))
        try:
            p, state = Gemini35Provider(client, 'gemini-3.5-flash-lite'), {}
            first = await p.native_completion([{'role': 'user', 'content': 'Call lookup.'}], [spec()], state)
            c = first.choices[0].message.tool_calls[0]
            await p.native_completion(history([c]) + [{'role': 'tool', 'tool_call_id': c.id, 'content': '42'}], [spec()], state)
        finally:
            await client.aio.aclose()
            client.close()
    asyncio.run(run())
    assert bodies[1]['contents'][1]['parts'][0]['functionCall']['id'] == 'native-provider-id'
    assert bodies[1]['contents'][1]['parts'][0]['thoughtSignature'] == 'b3BhcXVl'
    assert bodies[1]['contents'][2]['parts'][0]['functionResponse']['id'] == 'native-provider-id'
    assert 'private-placeholder-never-log' not in caplog.text + json.dumps(bodies)
