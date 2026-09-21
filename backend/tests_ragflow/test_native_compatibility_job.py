"""Offline stop gates and budget for the one-shot development smoke."""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest
from google.genai import types
from ragflow_dev.chat import DevGemini
from ragflow_dev.gemini35 import Gemini35Provider
from .fixtures import scope

spec = importlib.util.spec_from_file_location('native_compatibility_job', Path(__file__).resolve().parents[2] / 'dev/ragflow/native_tool_compatibility.py')
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)


class Client:
    def __init__(self, failure=None):
        self.aio = SimpleNamespace(models=self)
        self.calls = 0
        self.failure = failure

    async def generate_content(self, **kwargs):
        self.calls += 1
        if self.calls == self.failure:
            raise ValueError('OFFLINE_FAILURE')
        names = [d.name for d in kwargs['config'].tools[0].function_declarations]
        if self.calls == 3:
            parts = [types.Part(text='synthetic-ok')]
        else:
            name = names[0]
            args = {'topic': 'calibration'} if name == 'lookup_test_topic' else ({'query': ['synthetic']} if name == 'retrieve' else {})
            parts = [types.Part(function_call=types.FunctionCall(id='call-' + str(self.calls), name=name, args=args), thought_signature=b'fixture')]
        return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role='model', parts=parts))])


@pytest.mark.parametrize('failure', [1, 2, 3, 4, None])
def test_ordered_smokes_stop_without_retry(failure):
    client = Client(failure)
    model = DevGemini(Gemini35Provider(client, 'gemini-3.5-flash-lite'), max_calls=10)
    report = {}
    async def run():
        await job.minimal_smokes(model, scope(), report)
        await job.declaration_smoke(model, scope(), report)
    if failure:
        with pytest.raises(Exception):
            asyncio.run(run())
        assert client.calls == model.calls == failure
    else:
        asyncio.run(run())
        assert model.calls == client.calls == 4
        assert report['actual_declarations'] == 'PASS'
        assert len(report['actual_tool_names']) == 6


def test_job_imports_real_request_contract_and_uses_frozen_question():
    from ragflow_dev.app import AdvancedQuery
    value = AdvancedQuery(mode='agentic', query='How often does Beacon Laboratory calibrate sensors?', artifact_sources=['full-mechanical'])
    assert value.thinking_mode == 'medium'
    text = Path(job.__file__).read_text()
    assert 'model.max_calls = 10' in text
    assert 'es.create(index=CONTROL_INDEX, id=MARKER' in text
    assert 'runtime.ingest' not in text
