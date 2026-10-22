"""
LLM Router
==========
Dispatches generation requests to the correct provider.

Key resolution order:
1. bot.provider_api_key       → BYOK (Fernet-encrypted at rest)
2. platform credential profile → Admin-managed encrypted key assigned to this bot
Unassigned/disabled platform bots fail closed; no environment-key fallback.

Usage metrics are updated after every successful generation.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextvars import ContextVar, copy_context
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from time import perf_counter
import time
import os
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, Event, Lock
from types import SimpleNamespace

from database.models import Bot
from services.observability_service import observe_latency
from services.providers.base_provider import ProviderError, ProviderErrorKind, GenerationStreamEvent, generation_deadline
from services.providers.base_provider import auxiliary_budget, ProviderFeedback
from services.providers.gemini_provider import GeminiProvider
from services.providers.openai_provider import OpenAIProvider
from services.providers.claude_provider import ClaudeProvider
from services.providers.grok_provider import GrokProvider
from utils.secret_redaction import redact_secrets
from services import provider_capacity, provider_quotas
from services.providers.generation_input import admission_text, current_input

verification_mode: ContextVar[bool] = ContextVar('verification_mode', default=False)


@dataclass(frozen=True)
class _GenerationStreamOptions:
    on_delta: object
    cancel_event: Event | None = None


_GENERATION_STREAM: ContextVar[_GenerationStreamOptions | None] = ContextVar('generation_stream', default=None)


def get_generation_stream_sink():
    options = _GENERATION_STREAM.get()
    return options.on_delta if options else None


@contextmanager
def generation_stream_context(on_delta=None, cancel_event=None):
    """Opt in for this request only; a nested None sink restores buffering."""
    if on_delta is not None and not callable(on_delta):
        raise TypeError('Generation stream sink must be callable')
    parent = _GENERATION_STREAM.get()
    if cancel_event is None and parent is not None:
        cancel_event = parent.cancel_event
    options = _GenerationStreamOptions(on_delta, cancel_event) if on_delta is not None else None
    token = _GENERATION_STREAM.set(options)
    try:
        yield
    finally:
        _GENERATION_STREAM.reset(token)


def _check_stream_cancelled(options):
    if options is not None and options.cancel_event is not None and options.cancel_event.is_set():
        raise ProviderError('AI answer was cancelled.', status_code=499, kind=ProviderErrorKind.INVALID_REQUEST)


_ACTIVE_PROVIDER_LEASE: ContextVar[object | None] = ContextVar('active_provider_lease', default=None)


def _capacity_error(error):
    category = str(error)
    if category == 'provider_capacity_daily_quota_exhausted':
        return ProviderError('The configured daily AI quota is exhausted.', status_code=429,
                             kind=ProviderErrorKind.QUOTA_EXHAUSTED,
                             feedback=ProviderFeedback(quota_category='daily_quota'))
    kind = (ProviderErrorKind.INVALID_REQUEST if category in {'provider_capacity_cancelled',
            'provider_capacity_request_exceeds_quota', 'provider_capacity_configuration_invalid'} else
            ProviderErrorKind.TIMEOUT if category == 'provider_capacity_deadline_exceeded' else
            ProviderErrorKind.UNAVAILABLE)
    status = (499 if category == 'provider_capacity_cancelled' else 400 if kind == ProviderErrorKind.INVALID_REQUEST
              else 504 if kind == ProviderErrorKind.TIMEOUT else 503)
    return ProviderError('AI request capacity is temporarily unavailable.', status_code=status, kind=kind)


@contextmanager
def _provider_admission(provider_name, model_name, api_key, org_id, reservation=None, on_admission=None):
    """Acquisition waits separately from the provider's generation budget."""
    try:
        with provider_capacity.provider_capacity_guard(provider_name, model_name, api_key, org_id,
                reservation=reservation, on_admission=on_admission, defer_dispatch=True) as lease:
            token = _ACTIVE_PROVIDER_LEASE.set(lease)
            try:
                yield
            finally:
                _ACTIVE_PROVIDER_LEASE.reset(token)
    except provider_capacity.ProviderCapacityError as exc:
        raise _capacity_error(exc) from exc


@contextmanager
def _provider_attempt(provider_name, model_name, api_key, org_id):
    """Check the attempt-owned lease and record provider cooldowns in its scope."""
    options = _GENERATION_STREAM.get()
    _check_stream_cancelled(options)
    lease = _ACTIVE_PROVIDER_LEASE.get()
    try:
        if lease is not None:
            lease.check()
            lease.dispatched = True
        yield lease
        if lease is not None:
            lease.check()
    except provider_capacity.ProviderCapacityError as exc:
        raise _capacity_error(exc) from exc
    except ProviderError as exc:
        if lease is not None:
            lease.observe(feedback=getattr(exc, 'feedback', None))
        if exc.retry_after_seconds:
            try:
                provider_capacity.record_provider_cooldown(provider_name, model_name, api_key,
                    exc.retry_after_seconds, org_id=org_id)
            except provider_capacity.ProviderCapacityError:
                # Preserve this failure; the next admission fails closed.
                pass
        raise


def _admission_options(provider_name, model_name, api_key, org_id, prompt='', system_instruction=None,
                       output_limit=None, on_admission=None):
    if not provider_capacity.enabled():
        return {}
    try:
        reservation = provider_quotas.estimate_tokens(admission_text(prompt), system_instruction, output_limit)
    except (TypeError, ValueError):
        raise _capacity_error(provider_capacity.ProviderCapacityError('provider_capacity_configuration_invalid')) from None
    return dict(skip_legacy_guard=True,
                attempt_admission=lambda: _provider_admission(provider_name, model_name, api_key, org_id,
                                                              reservation, on_admission),
                remaining_budget=provider_capacity.provider_capacity_remaining)


class LLMRouterError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


PROVIDERS = {
    "gemini": GeminiProvider(),
    "openai": OpenAIProvider(),
    "claude": ClaudeProvider(),
    "grok": GrokProvider(),
}

def _generation_model(bot: Bot) -> str | None:
    """Only a missing Gemini model uses the default; explicit choices win."""
    model = getattr(bot, "model_name", None)
    if not model and (bot.provider or "").lower().strip() == "gemini":
        return "models/gemini-3.5-flash-lite"
    return model


def _resolve_api_key(bot: Bot) -> tuple[str, bool]:
    """
    Resolve which API key to use for this bot.

    Returns:
        (api_key, is_platform_key)  — is_platform_key=True when using pool key
    """
    # Priority 1: BYOK — decrypt only at the provider-call boundary.
    if bot.provider_api_key and bot.provider_api_key.strip():
        from services.bot_secret_service import decrypt_bot_provider_key
        try:
            plaintext = decrypt_bot_provider_key(bot.provider_api_key)
        except Exception as exc:
            raise LLMRouterError(
                "The bot's custom provider credential is unavailable. Re-save or migrate the key.",
                status_code=400,
            ) from exc
        if plaintext:
            return plaintext, False

    # Priority 2: Platform-managed encrypted key allocated to this bot
    from database.connection import SessionLocal
    from services.platform_key_service import get_decrypted_key_for_bot
    with SessionLocal() as db:
        plaintext = get_decrypted_key_for_bot(db, bot.id, expected_provider=bot.provider)
        if plaintext:
            return plaintext, True

    raise LLMRouterError(
        "AI service is unavailable for this bot. Please contact the administrator or configure your own provider key.",
        status_code=503,
    )


_LAST_GENERATION_METADATA: ContextVar[dict[str, object]] = ContextVar(
    "last_generation_metadata",
    default={},
)


def get_last_generation_metadata() -> dict[str, object]:
    return dict(_LAST_GENERATION_METADATA.get())


def _track_usage(bot_id: int, tokens: int | None) -> None:
    """Increment platform key usage metrics asynchronously (best-effort)."""
    try:
        from database.connection import SessionLocal
        from services.platform_key_service import increment_usage
        with SessionLocal() as db:
            increment_usage(db, bot_id, tokens=int(tokens or 0))
    except Exception:
        pass  # Non-critical — never raise from here


from services.llm_client import CentralizedLLMError, execute_with_resilience


_auxiliary_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="rag-auxiliary")
_auxiliary_slots = BoundedSemaphore(4)
_queued_auxiliary_pool = ThreadPoolExecutor(max_workers=20, thread_name_prefix="queued-rag-auxiliary")
_queued_auxiliary_slots = BoundedSemaphore(20)
_LAST_AUXILIARY_METADATA: ContextVar[dict] = ContextVar('last_auxiliary_metadata', default={})
AUXILIARY_SETUP_TIMEOUT = 5.0
AUXILIARY_CLEANUP_TIMEOUT = 5.0


class AuxiliaryDeadlineExceeded(TimeoutError):
    def __init__(self, stage):
        self.stage = stage
        super().__init__(f'Auxiliary {stage} deadline exceeded')


def get_last_auxiliary_metadata():
    return dict(_LAST_AUXILIARY_METADATA.get())


def _acquire_auxiliary_slot():
    queued = provider_capacity.enabled()
    if not queued:
        if not _auxiliary_slots.acquire(blocking=False):
            raise LLMRouterError('Auxiliary model unavailable', 503)
        return _auxiliary_pool, _auxiliary_slots, False
    try:
        remaining = provider_capacity.provider_capacity_remaining()
        deadline = time.monotonic() + (remaining if remaining is not None else 60.0)
        cancel = provider_capacity.provider_capacity_cancel_event()
        while True:
            if cancel is not None and cancel.is_set():
                raise LLMRouterError('Auxiliary request cancelled', 499)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LLMRouterError('Auxiliary request capacity wait expired', 504)
            if _queued_auxiliary_slots.acquire(timeout=min(.1, remaining)):
                return _queued_auxiliary_pool, _queued_auxiliary_slots, True
    except provider_capacity.ProviderCapacityError as exc:
        raise LLMRouterError('Auxiliary request capacity unavailable', 503) from exc


def generate_auxiliary(bot: Bot, prompt: str, system_instruction: str, *, timeout=5.0, tokens=768,
                       json_mode=True, use_auxiliary_model=True):
    """One bounded planning/review attempt through the bot's existing provider.

    Queued chat workers wait for bounded planning capacity; the normal path keeps
    its existing immediate admission. A timed-out transport keeps its slot until
    it exits, so it cannot accumulate unbounded orphan requests. No fallback.
    ORM objects and database sessions never enter the executor.
    """
    started_at = perf_counter()
    _LAST_AUXILIARY_METADATA.set({})
    provider_name = (bot.provider or "").lower()
    provider = PROVIDERS.get(provider_name)
    if provider is None:
        raise LLMRouterError("Auxiliary model unavailable", 503)
    auxiliary_pool, auxiliary_slots, queued_mode = _acquire_auxiliary_slot()
    try:
        model = (os.getenv(f"RAG_AUX_MODEL_{provider_name.upper()}") if use_auxiliary_model else None) or _generation_model(bot)
        bot_id, org_id = bot.id, bot.organization_id
        # Scalar snapshot only: key resolution owns a fresh session in the worker.
        identity = SimpleNamespace(id=bot_id, provider=provider_name,
                                   provider_api_key=getattr(bot, 'provider_api_key', None))
        inference_started, inference_done, abandoned, setup_completed = Event(), Event(), Event(), Event()
        lock = Lock()
        state = dict(key_resolution_ms=0.0, concurrency_acquisition_ms=0.0,
                     provider_ms=0.0, usage_accounting_ms=0.0, cleanup_ms=0.0,
                     queue_ms=0.0, total_ms=0.0, provider_status='not_started',
                     timeout_stage=None, cleanup_pending=False, cleanup_error=None, usage_error=None,
                     setup_budget_ms=AUXILIARY_SETUP_TIMEOUT*1000,
                     provider_budget_ms=timeout*1000, cleanup_budget_ms=AUXILIARY_CLEANUP_TIMEOUT*1000)
        state.update(max_output_tokens=tokens, finish_reason=None, input_tokens=None, output_tokens=None)
        result_holder, errors = [], []
        provider_started_at = [None]
        setup_deadline = perf_counter() + AUXILIARY_SETUP_TIMEOUT

        def mark(name, start):
            with lock:
                state[name] = round((perf_counter()-start)*1000, 3)

        def check_setup():
            if abandoned.is_set() or perf_counter() >= setup_deadline:
                raise AuxiliaryDeadlineExceeded('setup')

        def call():
            token = auxiliary_budget.set({"timeout": timeout, "tokens": tokens,
                                          **({'json_mode': False} if not json_mode else {})})
            platform = False
            try:
                mark('queue_ms', started_at)
                key_start = perf_counter()
                try:
                    api_key, platform = _resolve_api_key(identity)
                finally:
                    mark('key_resolution_ms', key_start)
                check_setup()
                setup_completed.set()
                guard_start = perf_counter()
                def attempt():
                    with _provider_attempt(provider_name, model, api_key, org_id) as lease:
                        mark('concurrency_acquisition_ms', guard_start)
                        if queued_mode:
                            if abandoned.is_set():
                                raise AuxiliaryDeadlineExceeded('admission')
                        else:
                            check_setup()
                        provider_started_at[0] = perf_counter()
                        state['provider_status'] = 'running'
                        inference_started.set()
                        try:
                            result = provider.generate_with_metadata(
                                api_key=api_key, model_name=model, prompt=prompt,
                                system_instruction=system_instruction, temperature=0.0,
                            )
                            if lease is not None:
                                lease.observe(usage=result.usage, feedback=getattr(result, 'feedback', None))
                            state['finish_reason'] = getattr(result, 'finish_reason', None)
                            state['input_tokens'] = getattr(result.usage, 'input_tokens', None)
                            state['output_tokens'] = getattr(result.usage, 'output_tokens', None)
                            if not result.text or not result.text.strip():
                                raise ValueError('Empty auxiliary provider response')
                            result_holder.append(result)
                            state['provider_status'] = 'success'
                            return result.text
                        except Exception as exc:
                            errors.append(exc)
                            state['provider_status'] = 'error'
                            raise
                        finally:
                            mark('provider_ms', provider_started_at[0])
                            inference_done.set()
                try:
                    return execute_with_resilience(attempt, provider_name, model, org_id=org_id, max_retries=0,
                        **_admission_options(provider_name, model, api_key, org_id, prompt,
                                             system_instruction, tokens,
                                             lambda data: state.update(admission=data)),
                        generation_timeout_seconds=current_input().generation_timeout_seconds,
                        on_event=lambda event: state.setdefault('attempt_events', []).append(event))
                finally:
                    if provider_started_at[0] is not None:
                        with lock:
                            state['cleanup_ms'] = round(max(0, (perf_counter()-provider_started_at[0])*1000-state['provider_ms']),3)
                    else:
                        mark('concurrency_acquisition_ms', guard_start)
            except Exception as exc:
                if isinstance(exc, AuxiliaryDeadlineExceeded):
                    state['timeout_stage'] = exc.stage
                if not errors:
                    errors.append(exc)
                if result_holder:
                    state['cleanup_error'] = type(exc).__name__
                raise
            finally:
                # Usage is still tracked once, including a late successful
                # response. It is not charged against the inference deadline.
                if platform and result_holder:
                    usage_start = perf_counter()
                    try:
                        usage = result_holder[0].usage
                        _track_usage(bot_id, usage.total_tokens if usage else None)
                    except Exception as exc:
                        state['usage_error'] = type(exc).__name__
                    finally:
                        mark('usage_accounting_ms', usage_start)
                auxiliary_budget.reset(token)
                mark('total_ms', started_at)
                inference_started.set()  # Wake callers on a setup refusal too.
                inference_done.set()
                setup_completed.set()
        future = auxiliary_pool.submit(copy_context().run, call)
    except Exception:
        auxiliary_slots.release()
        raise
    def finished(_):
        # Completion metrics include work that outlived a bounded caller wait.
        # Only stage durations are emitted; no identity, prompt or secret.
        auxiliary_slots.release()
        observe_latency('auxiliary.completed_total_ms', int(state['total_ms']))
        observe_latency('auxiliary.completed_usage_ms', int(state['usage_accounting_ms']))
        observe_latency('auxiliary.completed_cleanup_ms', int(state['cleanup_ms']))
    future.add_done_callback(finished)
    try:
        if queued_mode and not setup_completed.wait(max(0, setup_deadline-perf_counter())):
            abandoned.set()
            state['timeout_stage'] = 'setup'
            raise AuxiliaryDeadlineExceeded('setup')
        start_wait = max(0, setup_deadline-perf_counter())
        if queued_mode:
            try:
                remaining = provider_capacity.provider_capacity_remaining()
                start_wait = remaining if remaining is not None else 60.0
            except provider_capacity.ProviderCapacityError as exc:
                abandoned.set()
                raise LLMRouterError('Auxiliary request capacity unavailable', 503) from exc
        if not inference_started.wait(start_wait):
            abandoned.set()
            stage = 'admission' if queued_mode else 'setup'
            state['timeout_stage'] = stage
            raise AuxiliaryDeadlineExceeded(stage)
        if provider_started_at[0] is None:
            raise errors[0] if errors else AuxiliaryDeadlineExceeded('setup')
        provider_deadline = provider_started_at[0] + timeout
        if not inference_done.wait(max(0, provider_deadline-perf_counter())) or state['provider_ms'] > timeout*1000:
            abandoned.set()
            state['timeout_stage'] = 'provider'
            raise AuxiliaryDeadlineExceeded('provider')
        if errors and not result_holder:
            raise errors[0]
        # Separate bounded post-call wait. Slow accounting cannot turn a valid
        # model response into a provider failure. The worker keeps its slot and
        # ownership until cleanup really finishes, even if the caller moves on.
        try:
            future.result(timeout=AUXILIARY_CLEANUP_TIMEOUT)
        except TimeoutError:
            state['cleanup_pending'] = True
        except Exception as exc:
            state['cleanup_error'] = type(exc).__name__
        return result_holder[0].text
    finally:
        with lock:
            snapshot = dict(state, caller_wall_ms=round((perf_counter()-started_at)*1000,3))
        _LAST_AUXILIARY_METADATA.set(snapshot)
        for name in ('key_resolution_ms','concurrency_acquisition_ms','provider_ms','usage_accounting_ms','cleanup_ms','caller_wall_ms'):
            observe_latency('auxiliary.'+name, int(snapshot[name]))


def generate(
    bot: Bot,
    prompt: str,
    system_instruction: str | None = None,
    temperature_override: float | None = None,
) -> str:
    """
    Dispatch generation to the provider configured on the bot via centralized resilient client.
    """
    if verification_mode.get():
        return generate_auxiliary(bot, prompt, system_instruction or '',
                                  json_mode=False, use_auxiliary_model=False)
    _LAST_GENERATION_METADATA.set({})
    provider_name = (bot.provider or "").lower().strip()
    provider = PROVIDERS.get(provider_name)

    if not provider:
        raise LLMRouterError(
            f"Unsupported provider '{bot.provider}'. Supported providers: {', '.join(sorted(PROVIDERS))}.",
            status_code=400,
        )

    api_key, is_platform_key = _resolve_api_key(bot)
    model_name = _generation_model(bot)

    capabilities = bot.capabilities or {}
    temperature = temperature_override if temperature_override is not None else float(capabilities.get("temperature", 0.7))

    stream_options = _GENERATION_STREAM.get()
    progressive = stream_options is not None and provider_name in {'gemini', 'openai'}
    published = False
    execution_started = perf_counter()
    events, admissions = [], []
    _LAST_GENERATION_METADATA.set({'provider': provider_name, 'model': model_name})

    def record_event(event):
        if len(events) < 32:
            events.append(dict(event))

    def record_admission(data):
        if len(admissions) < 8:
            admissions.append(data)

    def _call_primary() -> str:
        nonlocal published
        started_at = perf_counter()
        with _provider_attempt(provider_name, model_name or 'default', api_key, bot.organization_id) as lease:
            if progressive:
                iterator = provider.generate_stream_with_metadata(
                    api_key=api_key, model_name=model_name, prompt=prompt,
                    system_instruction=system_instruction, temperature=temperature)
                parts, result = [], None
                try:
                    for event in iterator:
                        _check_stream_cancelled(stream_options)
                        if lease is not None:
                            lease.check()
                        deadline = generation_deadline.get()
                        if deadline is not None and time.monotonic() >= deadline:
                            raise ProviderError('AI answer stream exceeded its generation budget.', status_code=504,
                                                kind=ProviderErrorKind.TIMEOUT)
                        if not isinstance(event, GenerationStreamEvent) or result is not None:
                            raise ProviderError('Invalid AI answer stream.', status_code=502,
                                                kind=ProviderErrorKind.INVALID_REQUEST)
                        if event.delta:
                            parts.append(event.delta)
                            # Mark before invoking the sink: even a failed callback
                            # may have published text and must never be replayed.
                            published = True
                            stream_options.on_delta(event.delta)
                        if event.result is not None:
                            result = event.result
                finally:
                    if callable(getattr(iterator, 'close', None)):
                        iterator.close()
                if result is None or ''.join(parts) != result.text:
                    raise ProviderError('AI answer stream did not finish consistently.', status_code=502,
                                        kind=ProviderErrorKind.INVALID_REQUEST)
            else:
                result = provider.generate_with_metadata(
                    api_key=api_key, model_name=model_name, prompt=prompt,
                    system_instruction=system_instruction, temperature=temperature)
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            observe_latency('provider.stream_ms' if progressive else 'provider.generate_ms', elapsed_ms)
            usage = result.usage
            if lease is not None:
                lease.observe(usage=usage, feedback=getattr(result, 'feedback', None))
            _LAST_GENERATION_METADATA.set({
                'provider': result.provider, 'model': result.model, 'latency_ms': elapsed_ms,
                'input_tokens': usage.input_tokens if usage else None,
                'output_tokens': usage.output_tokens if usage else None,
                'total_tokens': usage.total_tokens if usage else None,
                **({'streamed': True, 'finish_reason': result.finish_reason} if progressive else {}),
            })
            if is_platform_key:
                _track_usage(bot.id, usage.total_tokens if usage else None)
            return result.text

    try:
        return execute_with_resilience(
            generate_fn=_call_primary,
            provider_name=provider_name,
            model_name=model_name or "default",
            org_id=bot.organization_id,
            **_admission_options(provider_name, model_name or 'default', api_key, bot.organization_id,
                prompt, system_instruction, getattr(provider, 'default_output_token_limit', None), record_admission),
            on_event=record_event,
            generation_timeout_seconds=current_input().generation_timeout_seconds,
            can_retry=lambda: not published and not (stream_options and stream_options.cancel_event
                                                     and stream_options.cancel_event.is_set()),
        )
    except CentralizedLLMError as c_exc:
        raise LLMRouterError(
            redact_secrets(c_exc.message, known_secrets=(api_key,)),
            status_code=c_exc.status_code,
        ) from c_exc
    except ProviderError as exc:
        raise LLMRouterError(
            redact_secrets(exc.message, known_secrets=(api_key,)),
            status_code=exc.status_code,
        ) from exc
    finally:
        metadata = dict(_LAST_GENERATION_METADATA.get() or {})
        metadata.update(execution_ms=round((perf_counter()-execution_started)*1000, 3),
                        attempt_events=events, admissions=admissions,
                        retry_count=max(0, sum(e.get('event') == 'attempt_finished' and
                                              e.get('provider_started', False) for e in events)-1))
        _LAST_GENERATION_METADATA.set(metadata)



def generate_stream(
    bot: Bot,
    prompt: str,
    system_instruction: str | None = None,
    temperature_override: float | None = None,
) -> Iterator[str]:
    """Streaming variant of generate(). Yields chunks as they arrive."""
    provider_name = (bot.provider or "").lower().strip()
    provider = PROVIDERS.get(provider_name)

    if not provider:
        raise LLMRouterError(
            f"Unsupported provider '{bot.provider}'. Supported providers: {', '.join(sorted(PROVIDERS))}.",
            status_code=400,
        )

    api_key, is_platform_key = _resolve_api_key(bot)
    model_name = _generation_model(bot)

    # Extract temperature from capabilities (default to 0.7)
    capabilities = bot.capabilities or {}
    temperature = temperature_override if temperature_override is not None else float(capabilities.get("temperature", 0.7))

    started_at = perf_counter()
    admissions = []
    _LAST_GENERATION_METADATA.set({'provider': provider_name, 'model': model_name})
    try:
        options = _admission_options(provider_name, model_name or 'default', api_key, bot.organization_id,
            prompt, system_instruction, getattr(provider, 'default_output_token_limit', None), admissions.append)
        admission = options['attempt_admission']() if options else nullcontext()
        with admission, _provider_attempt(provider_name, model_name or 'default', api_key, bot.organization_id) as lease:
            iterator = provider.generate_stream(api_key=api_key, model_name=model_name, prompt=prompt,
                system_instruction=system_instruction, temperature=temperature)
            try:
                for chunk in iterator:
                    if lease is not None:
                        lease.check()
                    provider_capacity.provider_capacity_remaining()
                    yield chunk
            finally:
                if callable(getattr(iterator, 'close', None)):
                    iterator.close()

        elapsed_ms = int((perf_counter() - started_at) * 1000)
        observe_latency("provider.stream_ms", elapsed_ms)

        # Update usage metrics after full stream
        _LAST_GENERATION_METADATA.set(
            {
                "provider": provider_name,
                "model": model_name,
                "latency_ms": elapsed_ms,
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
            }
        )
        if is_platform_key:
            # Count the request, but do not fabricate token usage when a stream
            # does not expose a final usage record.
            _track_usage(bot.id, None)

    except ProviderError as exc:
        _LAST_GENERATION_METADATA.set({'provider': provider_name, 'model': model_name,
            'error_kind': exc.kind.value, 'status_code': exc.status_code,
            'retry_after_seconds': exc.retry_after_seconds})
        raise LLMRouterError(
            redact_secrets(exc.message, known_secrets=(api_key,)),
            status_code=exc.status_code,
        ) from exc
    finally:
        metadata = dict(_LAST_GENERATION_METADATA.get() or {})
        metadata.update(execution_ms=round((perf_counter()-started_at)*1000,3), admissions=admissions)
        _LAST_GENERATION_METADATA.set(metadata)
