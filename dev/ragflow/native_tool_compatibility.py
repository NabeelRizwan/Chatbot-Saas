"""One-shot provider compatibility smoke, only in the isolated development project.

No corpus writes. No quality sets. One shared ten-attempt budget including text.
"""
import asyncio
import base64
import gzip
import hashlib
import json
import logging
import os
from pathlib import Path
import time
from types import SimpleNamespace

PROJECT = '068a5695-2cf6-4c7f-89fc-3d24a225e4a5'
MARKER = 'native-tool-compatibility-2026-09-22-v1'


def tool(name, parameters):
    return {'type': 'function', 'function': {'name': name, 'description': 'Synthetic compatibility tool.', 'parameters': parameters}}


def neutral_call(call):
    return {'id': call.id, 'type': 'function', 'function': vars(call.function).copy()}


async def minimal_smokes(model, scope, report):
    from ragflow_derived.model_runtime import model_operation, _cache
    zero = tool('get_test_value', {'type': 'object', 'properties': {}, 'required': []})
    parameter = tool('lookup_test_topic', {'type': 'object', 'properties': {'topic': {'type': 'string'}}, 'required': ['topic']})
    with model_operation(scope):
        report['stage'] = 'minimal_zero_arg'
        first = await model.async_completion([{'role': 'user', 'content': 'Call get_test_value.'}], tools=[zero])
        calls = first.choices[0].message.tool_calls
        assert len(calls) == 1 and calls[0].function.name == 'get_test_value' and json.loads(calls[0].function.arguments) == {}
        report['minimal_zero_arg'] = 'PASS'
    with model_operation(scope):
        report['stage'] = 'parameterized'
        messages = [{'role': 'user', 'content': 'Call lookup_test_topic with topic "calibration".'}]
        second = await model.async_completion(messages, tools=[parameter])
        message = second.choices[0].message
        calls = message.tool_calls
        assert len(calls) == 1 and calls[0].function.name == 'lookup_test_topic'
        assert json.loads(calls[0].function.arguments) == {'topic': 'calibration'}
        record = _cache.get()[2]['native_tool_transport']['calls'][calls[0].id]
        report['parameterized'] = 'PASS'
        report['call_id_preserved'] = record['provider_id'] is None or calls[0].id == record['provider_id']
        report['provider_id_present'] = record['provider_id'] is not None
        report['signature_parts_present'] = sum(bool(p.thought_signature) for p in record['content'].parts)
        messages.extend([{'role': 'assistant', 'content': message.content or '', 'tool_calls': [neutral_call(calls[0])]},
                         {'role': 'tool', 'tool_call_id': calls[0].id, 'name': 'lookup_test_topic', 'content': '{"value":"synthetic-ok"}'}])
        report['stage'] = 'function_response'
        third = await model.async_completion(messages, tools=[parameter])
        assert third.choices[0].message.content and not third.choices[0].message.tool_calls
        report['function_response'] = 'PASS'
        report['function_response_answer'] = third.choices[0].message.content


async def declaration_smoke(model, scope, report):
    from ragflow_derived.model_runtime import model_operation
    from ragflow_derived.upstream.advanced_rag.harness.action_session import _active_tool_specs
    from ragflow_dev.gemini35_tools import declarations_for
    specs = _active_tool_specs(SimpleNamespace(thinking_mode='medium', web_search=None))
    declarations_for(specs)
    report['actual_tool_names'] = [s['function']['name'] for s in specs]
    with model_operation(scope):
        report['stage'] = 'actual_declarations'
        value = await model.async_completion([{'role': 'user', 'content': 'Use retrieve to look up a synthetic calibration topic.'}], tools=specs)
        message = value.choices[0].message
        assert message.tool_calls and all(c.function.name in report['actual_tool_names'] for c in message.tool_calls)
        report['actual_declarations'] = 'PASS'
        report['declaration_calls_not_executed'] = [c.function.name for c in message.tool_calls]


class ObservedModel:
    """Observation wrapper only: never change messages, tools, results or limits."""
    def __init__(self, inner, events):
        self.inner, self.events = inner, events
        self.llm_name, self.max_length = inner.llm_name, inner.max_length

    async def async_chat(self, *args, **kwargs):
        started = time.perf_counter()
        try:
            return await self.inner.async_chat(*args, **kwargs)
        finally:
            self.events.append({'kind': 'text', 'seconds': time.perf_counter() - started, 'calls': self.inner.calls})

    async def async_completion(self, messages, **kwargs):
        started = time.perf_counter()
        value = await self.inner.async_completion(messages, **kwargs)
        self.events.append({'kind': 'native', 'seconds': time.perf_counter() - started,
            'calls': self.inner.calls, 'result_ids_sent': [m['tool_call_id'] for m in messages if m.get('role') == 'tool'],
            'returned': [{'id': c.id, 'name': c.function.name} for c in value.choices[0].message.tool_calls],
            'answer_present': bool(value.choices[0].message.content)})
        return value

    def close(self):
        self.inner.close()


def main():
    from elasticsearch import Elasticsearch, ConflictError
    from ragflow_dev.config import Settings
    from ragflow_dev.chat import from_env
    from ragflow_dev.authority import Authority, CONTROL_INDEX
    from ragflow_dev.runtime import Runtime
    from ragflow_dev.app import AdvancedQuery
    settings = Settings.from_env()
    assert settings.project_id == PROJECT
    assert os.environ.get('RAGFLOW_DEV_NATIVE_TOOL_VALIDATION') == 'ONCE_TEN_CALLS'
    freeze = json.loads((Path(__file__).parent / 'full_port_freeze.json').read_text())
    for filename, digest in freeze['file_hashes'].items():
        assert hashlib.sha256((Path(__file__).parent / filename).read_bytes()).hexdigest() == digest
    es = Elasticsearch(settings.es_url, request_timeout=20, max_retries=0, retry_on_timeout=False)
    model, runtime = None, None
    report = {'stage': 'preflight', 'provider_calls': 0, 'budget': 10, 'events': [], 'quality_sets': 'NOT RUN',
              'minimal_zero_arg': 'NOT RUN', 'parameterized': 'NOT RUN', 'function_response': 'NOT RUN',
              'actual_declarations': 'NOT RUN', 'mechanical': 'NOT RUN'}
    started = time.perf_counter()
    try:
        authority = Authority(es)
        inventory = {t: authority.read(t)['_source'] for t in ('a', 'b')}
        scope = Runtime.artifact_scope(authority.active_scope('a'), ['full-mechanical'])
        assert scope.source('full-mechanical').version == '1'
        try:
            es.create(index=CONTROL_INDEX, id=MARKER, document={'state': 'started', 'budget': 10}, refresh='wait_for')
        except ConflictError:
            print('NATIVE_COMPAT_ALREADY_ATTEMPTED_NO_CALLS', flush=True)
            return
        model = from_env(PROJECT)
        assert model is not None
        model.max_calls = 10
        observed = ObservedModel(model, report['events'])
        asyncio.run(minimal_smokes(observed, scope, report))
        asyncio.run(declaration_smoke(observed, scope, report))
        report['stage'] = 'mechanical'
        runtime = Runtime(settings, chat_model=observed)
        result = runtime.advanced('a', AdvancedQuery(query='How often does Beacon Laboratory calibrate sensors?',
            mode='agentic', thinking_mode='medium', artifact_sources=['full-mechanical'], trace=True))
        report['mechanical_result'] = result
        assert result['answer'] and result['evidence']
        assert all(e['source_id'] == 'full-mechanical' and e['version'] == '1' for e in result['evidence'])
        returned_ids = {c['id'] for e in report['events'][4:] for c in e.get('returned', [])}
        sent_ids = {c for e in report['events'][4:] for c in e.get('result_ids_sent', [])}
        report['mechanical_provider_tool_cycle'] = bool(returned_ids & sent_ids)
        assert report['mechanical_provider_tool_cycle'], 'NO_MODEL_SELECTED_TOOL_CYCLE'
        report['mechanical'] = 'PASS'
        report['stage'] = 'complete'
    except Exception as exc:
        # Never print raw exceptions, provider bodies, URLs, headers or secrets.
        from ragflow_dev.provider_diagnostics import safe_diagnostic
        report['failure'] = model.last_diagnostic if model and model.last_diagnostic else safe_diagnostic(exc, 'gemini-3.5-flash-lite', 'request')
        report[report['stage']] = 'FAIL'
    finally:
        report['provider_calls'] = model.calls if model else 0
        report['tokens'] = model.tokens if model else 0
        report['seconds'] = time.perf_counter() - started
        if 'inventory' in locals():
            report['source_authority_unchanged'] = inventory == {t: Authority(es).read(t)['_source'] for t in ('a', 'b')}
        if runtime:
            runtime.close()
        elif model:
            model.close()
        es.close()
        raw = json.dumps(report, sort_keys=True, ensure_ascii=True).encode()
        packed = base64.b64encode(gzip.compress(raw)).decode()
        print('NATIVE_COMPAT_SUMMARY ' + json.dumps({k: v for k, v in report.items() if k not in ('events', 'mechanical_result')}), flush=True)
        pieces = [packed[i:i+18000] for i in range(0, len(packed), 18000)]
        for i, piece in enumerate(pieces):
            print('NATIVE_COMPAT_ARTIFACT ' + json.dumps({'index': i, 'total': len(pieces), 'sha256': hashlib.sha256(raw).hexdigest(), 'data': piece}), flush=True)
        os.environ.pop('RAGFLOW_DEV_GEMINI_API_KEY', None)


if __name__ == '__main__':
    logging.basicConfig(level=logging.ERROR)
    main()
