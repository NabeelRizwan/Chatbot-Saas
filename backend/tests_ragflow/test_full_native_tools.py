import asyncio
from types import SimpleNamespace
import pytest
from google.genai import types
from ragflow_dev.gemini35 import Gemini35Provider
from ragflow_dev.chat import DevGemini
from ragflow_derived.model_runtime import model_operation
from ragflow_derived.contracts import EngineError
from .fixtures import scope


class Client:
    def __init__(self):
        self.requests = []
        self.aio = SimpleNamespace(models=self)

    async def generate_content(self, **kwargs):
        self.requests.append(kwargs)
        part = (types.Part(function_call=types.FunctionCall(name='retrieve', args={'query': ['calibration']}),
                           thought_signature=b'opaque-test-signature') if len(self.requests) == 1
                else types.Part(text='Supported answer.'))
        return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role='model', parts=[part]))],
            usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=10, candidates_token_count=3, total_token_count=13))


def test_native_tool_roundtrip_preserves_schema_prompts_args_and_signature():
    client = Client()
    model = DevGemini(Gemini35Provider(client, 'gemini-3.5-flash-lite'))
    specs = [{'type': 'function', 'function': {'name': 'retrieve', 'description': 'Search stored evidence',
        'parameters': {'type': 'object', 'properties': {'query': {'type': 'array', 'items': {'type': 'string'}}}, 'required': ['query']}}}]
    history = [{'role': 'system', 'content': 'Unchanged upstream prompt.'}, {'role': 'user', 'content': 'Calibration?'}]
    async def run():
        with model_operation(scope()):
            first = await model.async_completion(history, tools=specs)
            call = first.choices[0].message.tool_calls[0]
            history.extend([{'role': 'assistant', 'content': '', 'tool_calls': [dict(id=call.id, type='function', function=vars(call.function))]},
                            {'role': 'tool', 'tool_call_id': call.id, 'content': 'Exact source passage.'}])
            second = await model.async_completion(history, tools=specs)
            assert second.choices[0].message.content == 'Supported answer.'
    asyncio.run(run())
    sent = client.requests[1]
    assert sent['config'].system_instruction == 'Unchanged upstream prompt.'
    assert sent['config'].automatic_function_calling.disable
    assert sent['config'].tools[0].function_declarations[0].parameters_json_schema == specs[0]['function']['parameters']
    assert sent['contents'][1].parts[0].thought_signature == b'opaque-test-signature'
    assert sent['contents'][2].parts[0].function_response.response == {'result': 'Exact source passage.'}
    assert model.calls == 2 and model.tokens == 26


def test_native_tools_require_operation_and_enforce_same_provider_budget():
    client = Client()
    model = DevGemini(Gemini35Provider(client, 'gemini-3.5-flash-lite'), max_calls=0)
    with pytest.raises(EngineError, match='UNAUTHORIZED_SCOPE'):
        asyncio.run(model.async_completion([]))
    with model_operation(scope()):
        with pytest.raises(EngineError, match='CHAT_MODEL_UNAVAILABLE'):
            asyncio.run(model.async_completion([]))
    assert not client.requests
