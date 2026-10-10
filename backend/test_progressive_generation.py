"""Offline contracts for optional provider streaming and shared capacity ownership."""
from contextlib import contextmanager, nullcontext
from threading import Event, Barrier, BoundedSemaphore
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import httpx
from google.genai import types
from openai import APITimeoutError

from services import llm_router as router
from services.providers.base_provider import (GenerationResult, GenerationStreamEvent, ProviderError,
    ProviderErrorKind, ProviderUsage, generation_deadline)
from services.providers.gemini_provider import GeminiProvider
from services.providers.openai_provider import OpenAIProvider


class ProgressiveRouterTests(TestCase):
    def setUp(self):
        self.bot = SimpleNamespace(id=3, organization_id=8, provider='gemini', model_name='configured-model',
                                   capabilities={'temperature': .37})
        self.provider = Mock()
        self.result = GenerationResult('First\nSecond', 'gemini', 'configured-model', ProviderUsage(12, 4), 'STOP')
        self.provider.generate_with_metadata.return_value = self.result
        self.events = [GenerationStreamEvent(delta='First\n'), GenerationStreamEvent(delta='Second'),
                       GenerationStreamEvent(result=self.result)]
        self.provider.generate_stream_with_metadata.side_effect = lambda **kw: iter(self.events)
        self.held = False
        self.lease = Mock()

        @contextmanager
        def guard(*args, **kwargs):
            self.held = True
            try:
                yield self.lease
            finally:
                self.held = False

        patches = [patch.dict(router.PROVIDERS, {'gemini': self.provider, 'claude': self.provider}),
                   patch.object(router, '_resolve_api_key', return_value=('synthetic-key', True)),
                   patch.object(router, '_track_usage'),
                   patch('services.llm_client.distributed_concurrency_guard', return_value=nullcontext(True)),
                   patch('services.llm_client.global_circuit_breaker'),
                   patch('services.llm_client.time.sleep'),
                   patch('services.provider_capacity.enabled', return_value=True),
                   patch('services.provider_capacity.provider_capacity_guard', side_effect=guard)]
        started = []
        for item in patches:
            started.append(item.start())
            self.addCleanup(item.stop)
        self.usage = started[2]
        self.breaker = started[4]
        self.breaker.is_allowed.return_value = True
        self.sleep = started[5]
        self.guard = started[-1]

    def test_normal_generation_stays_buffered_with_identical_arguments(self):
        self.assertEqual(router.generate(self.bot, 'prompt', 'instructions'), self.result.text)
        self.provider.generate_stream_with_metadata.assert_not_called()
        self.provider.generate_with_metadata.assert_called_once_with(api_key='synthetic-key',
            model_name='configured-model', prompt='prompt', system_instruction='instructions', temperature=.37)
        self.usage.assert_called_once_with(3, 16)

    def test_progressive_keeps_permit_until_final_usage_and_emits_original_text(self):
        chunks = []
        def emit(text):
            self.assertTrue(self.held)
            self.assertIsNotNone(generation_deadline.get())
            chunks.append(text)
        with router.generation_stream_context(emit):
            response = router.generate(self.bot, 'prompt', 'instructions')
        self.assertEqual(chunks, ['First\n', 'Second'])
        self.assertEqual(response, self.result.text)
        self.assertFalse(self.held)
        self.provider.generate_with_metadata.assert_not_called()
        self.usage.assert_called_once_with(3, 16)
        self.assertEqual(router.get_last_generation_metadata()['total_tokens'], 16)
        self.assertTrue(router.get_last_generation_metadata()['streamed'])
        self.assertIsNone(generation_deadline.get())
        self.assertIsNone(router.get_generation_stream_sink())

    def test_nested_none_context_disables_and_restores_streaming(self):
        sink = Mock()
        with router.generation_stream_context(sink):
            self.assertIs(router.get_generation_stream_sink(), sink)
            with router.generation_stream_context():
                self.assertIsNone(router.get_generation_stream_sink())
                router.generate(self.bot, 'question')
            self.assertIs(router.get_generation_stream_sink(), sink)
        sink.assert_not_called()

    def test_other_provider_uses_buffered_fallback(self):
        self.bot.provider = 'claude'
        sink = Mock()
        with router.generation_stream_context(sink):
            router.generate(self.bot, 'question')
        sink.assert_not_called()
        self.provider.generate_with_metadata.assert_called_once()
        self.provider.generate_stream_with_metadata.assert_not_called()

    def test_failure_before_any_delta_can_retry_same_selected_model(self):
        self.provider.generate_stream_with_metadata.side_effect = [
            ProviderError('Unavailable', status_code=503, kind=ProviderErrorKind.TEMPORARY), iter(self.events)]
        sink = Mock()
        with router.generation_stream_context(sink):
            self.assertEqual(router.generate(self.bot, 'question'), self.result.text)
        self.assertEqual(self.provider.generate_stream_with_metadata.call_count, 2)
        self.assertEqual(self.guard.call_count, 2)
        self.usage.assert_called_once_with(3, 16)
        self.sleep.assert_called_once()

    def test_failure_after_delta_never_replays_and_closes_iterator(self):
        closed = Event()
        def broken(**kwargs):
            try:
                yield GenerationStreamEvent(delta='Already shown')
                raise ProviderError('Unavailable', status_code=503, kind=ProviderErrorKind.TEMPORARY)
            finally:
                closed.set()
        self.provider.generate_stream_with_metadata.side_effect = broken
        sink = Mock()
        with router.generation_stream_context(sink), self.assertRaises(router.LLMRouterError):
            router.generate(self.bot, 'question')
        self.provider.generate_stream_with_metadata.assert_called_once()
        sink.assert_called_once_with('Already shown')
        self.sleep.assert_not_called()
        self.usage.assert_not_called()
        self.assertTrue(closed.is_set())
        self.assertFalse(self.held)

    def test_sink_failure_never_replays_potentially_published_text(self):
        sink = Mock(side_effect=ProviderError('Unavailable', status_code=503, kind=ProviderErrorKind.TEMPORARY))
        with router.generation_stream_context(sink), self.assertRaises(router.LLMRouterError):
            router.generate(self.bot, 'question')
        sink.assert_called_once()
        self.provider.generate_stream_with_metadata.assert_called_once()
        self.assertFalse(self.held)

    def test_cancel_stops_publication_and_releases_ownership(self):
        cancel = Event()
        sink = Mock(side_effect=lambda text: cancel.set())
        with router.generation_stream_context(sink, cancel), self.assertRaises(router.LLMRouterError):
            router.generate(self.bot, 'question')
        sink.assert_called_once_with('First\n')
        self.provider.generate_stream_with_metadata.assert_called_once()
        self.sleep.assert_not_called()
        self.assertFalse(self.held)

    def test_already_cancelled_request_does_not_call_provider(self):
        cancel = Event()
        cancel.set()
        with router.generation_stream_context(Mock(), cancel), self.assertRaises(router.LLMRouterError):
            router.generate(self.bot, 'question')
        self.provider.generate_stream_with_metadata.assert_not_called()

    def test_missing_or_inconsistent_terminal_result_fails(self):
        for events in ([GenerationStreamEvent(delta='Partial')],
                       [GenerationStreamEvent(delta='Different'), GenerationStreamEvent(result=self.result)]):
            with self.subTest(events=events):
                self.provider.generate_stream_with_metadata.side_effect = lambda **kw: iter(events)
                with router.generation_stream_context(Mock()), self.assertRaises(router.LLMRouterError):
                    router.generate(self.bot, 'question')
        self.usage.assert_not_called()

    def test_provider_retry_hint_is_recorded_for_the_correct_credential_scope(self):
        self.provider.generate_with_metadata.side_effect = ProviderError('Rate limited', status_code=429,
            kind=ProviderErrorKind.RATE_LIMIT, retry_after_seconds=120)
        with patch('services.provider_capacity.record_provider_cooldown') as cooldown:
            with self.assertRaises(router.LLMRouterError):
                router.generate(self.bot, 'question')
        cooldown.assert_called_once_with('gemini', 'configured-model', 'synthetic-key', 120, org_id=8)


class ProviderMetadataStreamTests(TestCase):
    def setUp(self):
        self.arguments = dict(api_key='synthetic-key', model_name='configured-model', prompt='question',
                              system_instruction='instructions', temperature=.37)

    def test_gemini_emits_only_answer_text_and_latest_cumulative_usage(self):
        provider = GeminiProvider()
        client = Mock()
        provider._client = Mock(return_value=client)
        responses = [types.GenerateContentResponse(candidates=[types.Candidate(
            content=types.Content(parts=[types.Part(text='private reasoning', thought=True), types.Part(text='First')]))],
            usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=10, candidates_token_count=1)),
            types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(parts=[types.Part(text=' second')]),
                finish_reason=types.FinishReason.STOP)],
                usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=10, candidates_token_count=3))]
        closed = Event()
        def events():
            try:
                yield from responses
            finally:
                closed.set()
        client.models.generate_content_stream.return_value = events()
        with patch('services.providers.base_provider.time.monotonic', return_value=100):
            token = generation_deadline.set(112)
            try:
                events = list(provider.generate_stream_with_metadata(**self.arguments))
            finally:
                generation_deadline.reset(token)
        self.assertEqual([e.delta for e in events if e.delta], ['First', ' second'])
        self.assertEqual(events[-1].result.text, 'First second')
        self.assertEqual(events[-1].result.usage.total_tokens, 13)
        config = client.models.generate_content_stream.call_args.kwargs['config']
        self.assertEqual(config.http_options.timeout, 12000)
        self.assertEqual((config.temperature, config.system_instruction), (.37, 'instructions'))
        self.assertTrue(closed.is_set())

    def test_gemini_missing_finish_or_blocked_completion_is_not_success(self):
        provider = GeminiProvider()
        client = Mock()
        provider._client = Mock(return_value=client)
        for reason in (None, types.FinishReason.SAFETY, types.FinishReason.MAX_TOKENS):
            client.models.generate_content_stream.return_value = iter([SimpleNamespace(
                text='Partial', candidates=[SimpleNamespace(finish_reason=reason)])])
            with self.subTest(reason=reason), self.assertRaises(ProviderError):
                list(provider.generate_stream_with_metadata(**self.arguments))

    def test_openai_requires_completion_uses_final_usage_and_closes(self):
        provider = OpenAIProvider()
        client = Mock()
        provider._client = Mock(return_value=client)
        final = SimpleNamespace(output_text='A\nB', status='completed', usage=SimpleNamespace(input_tokens=10, output_tokens=3))
        class Stream:
            def __iter__(self):
                yield SimpleNamespace(type='response.reasoning_text.delta', delta='private reasoning')
                yield SimpleNamespace(type='response.output_text.delta', delta='A\n')
                yield SimpleNamespace(type='response.output_text.delta', delta='B')
                yield SimpleNamespace(type='response.completed')
            def get_final_response(self):
                return final
        closed = Event()
        @contextmanager
        def stream_context():
            try:
                yield Stream()
            finally:
                closed.set()
        client.responses.stream.return_value = stream_context()
        with patch('services.providers.base_provider.time.monotonic', return_value=100):
            token = generation_deadline.set(112)
            try:
                events = list(provider.generate_stream_with_metadata(**self.arguments))
            finally:
                generation_deadline.reset(token)
        self.assertEqual([e.delta for e in events if e.delta], ['A\n', 'B'])
        self.assertEqual(events[-1].result.usage.total_tokens, 13)
        kwargs = client.responses.stream.call_args.kwargs
        self.assertEqual(kwargs['timeout'], 12)
        self.assertEqual(kwargs['input'], [{'role': 'developer', 'content': 'instructions'}, {'role': 'user', 'content': 'question'}])
        self.assertEqual(kwargs['temperature'], .37)
        self.assertTrue(closed.is_set())

    def test_openai_explicit_error_missing_terminal_or_timeout_never_succeeds(self):
        provider = OpenAIProvider()
        client = Mock()
        provider._client = Mock(return_value=client)
        for name in ('response.failed', 'response.incomplete', 'error', None):
            events = [SimpleNamespace(type=name)] if name else []
            client.responses.stream.return_value = nullcontext(iter(events))
            with self.subTest(name=name), self.assertRaises(ProviderError):
                list(provider.generate_stream_with_metadata(**self.arguments))
        def timeout():
            yield SimpleNamespace(type='response.output_text.delta', delta='First')
            raise APITimeoutError(request=httpx.Request('POST', 'https://example.invalid'))
        client.responses.stream.return_value = nullcontext(timeout())
        stream = provider.generate_stream_with_metadata(**self.arguments)
        self.assertEqual(next(stream).delta, 'First')
        with self.assertRaises(ProviderError) as error:
            next(stream)
        self.assertEqual(error.exception.kind, ProviderErrorKind.TIMEOUT)


class QueuedAuxiliaryTests(TestCase):
    def setUp(self):
        self.bot = SimpleNamespace(id=3, organization_id=8, provider='gemini', model_name='configured-model',
                                   capabilities={}, provider_api_key=None)
        self.provider = Mock()
        patches = [patch.dict(router.PROVIDERS, {'gemini': self.provider}),
                   patch.object(router, '_resolve_api_key', return_value=('synthetic-key', False)),
                   patch('services.provider_capacity.enabled', return_value=True),
                   patch('services.llm_client.global_circuit_breaker')]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_ten_planners_run_without_the_old_four_slot_refusal(self):
        all_started = Barrier(10)
        def reply(**kwargs):
            all_started.wait(timeout=3)
            return GenerationResult('resolved question', 'gemini', 'configured-model', ProviderUsage(2, 1))
        self.provider.generate_with_metadata.side_effect = reply
        with patch('services.provider_capacity.provider_capacity_guard', side_effect=lambda *args: nullcontext(None)):
            with ThreadPoolExecutor(max_workers=10) as callers:
                results = list(callers.map(lambda _: router.generate_auxiliary(
                    self.bot, 'question', 'instructions', timeout=4), range(10)))
        self.assertEqual(results, ['resolved question'] * 10)
        self.assertEqual(self.provider.generate_with_metadata.call_count, 10)

    def test_late_auxiliary_transport_keeps_its_slot_and_permit_until_it_finishes(self):
        started, release, ownership_closed = Event(), Event(), Event()
        slots = BoundedSemaphore(1)
        @contextmanager
        def guard(*args):
            try:
                yield None
            finally:
                ownership_closed.set()
        def reply(**kwargs):
            started.set()
            release.wait(timeout=3)
            return GenerationResult('late answer', 'gemini', 'configured-model', ProviderUsage(2, 1))
        self.provider.generate_with_metadata.side_effect = reply
        with patch.object(router, '_queued_auxiliary_slots', slots), patch(
                'services.provider_capacity.provider_capacity_guard', side_effect=guard):
            try:
                with self.assertRaises(router.AuxiliaryDeadlineExceeded):
                    router.generate_auxiliary(self.bot, 'question', 'instructions', timeout=.02)
                self.assertTrue(started.is_set())
                self.assertFalse(ownership_closed.is_set())
                self.assertFalse(slots.acquire(blocking=False))
            finally:
                release.set()
            self.assertTrue(ownership_closed.wait(timeout=3))
            self.assertTrue(slots.acquire(timeout=3))
            slots.release()
