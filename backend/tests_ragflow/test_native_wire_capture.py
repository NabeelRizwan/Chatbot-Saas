"""Real upstream graph -> installed SDK -> mock HTTP; never a provider call."""
import asyncio
import json
import traceback
import httpx
from google import genai
from google.genai import types
from ragflow_dev.chat import DevGemini
from ragflow_dev.gemini35 import Gemini35Provider
from .fixtures import engine, scope
from .test_full_agentic import ResearchModel


def capture_medium_wire():
    captured = []
    async def transport(request):
        captured.append({'model': 'gemini-3.5-flash-lite', 'body': json.loads(request.content),
                         'stack': [f.name for f in traceback.extract_stack()
                                   if f.name in ('_llm_once_with_tools', '_acompletion', 'async_completion', 'native_completion')]})
        return httpx.Response(200, json={'candidates': [{'content': {'role': 'model', 'parts': [
            {'text': '<answer>{"answer":"Calibrate every seven days.","new_state":[]}</answer>'}]}}],
            'usageMetadata': {'totalTokenCount': 1}})
    client = genai.Client(api_key='offline-placeholder', vertexai=False,
        http_options=types.HttpOptions(httpx_async_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
                                      retry_options=types.HttpRetryOptions(attempts=1)))
    native = DevGemini(Gemini35Provider(client, 'gemini-3.5-flash-lite'))
    class Model(ResearchModel):
        async def async_completion(self, messages, **kwargs):
            return await native.async_completion(messages, **kwargs)
    e, s = engine(), scope()
    e.ingest(s, 'manual', 'Laboratory calibration is every seven days.', title='Laboratory')
    e.chat_model = Model()
    async def run():
        try:
            return await e.research(s, 'What is the laboratory calibration interval?', thinking_mode='medium')
        finally:
            await client.aio.aclose()
            client.close()
    result = asyncio.run(run())
    assert result['answer'] and captured
    return captured


def test_capture_medium_wire():
    captured = capture_medium_wire()
    body = captured[0]['body']
    assert len(body['tools'][0]['functionDeclarations']) == 6
    assert set(captured[0]['stack']) == {'_llm_once_with_tools', '_acompletion', 'async_completion', 'native_completion'}
    assert 'offline-placeholder' not in json.dumps(captured)
    model_parts = [p for c in body['contents'] if c['role'] == 'model' for p in c['parts'] if 'functionCall' in p]
    assert model_parts and all(p.get('thoughtSignature') for p in model_parts)
