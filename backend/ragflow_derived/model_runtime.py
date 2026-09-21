"""Explicit upstream chat boundary and per-operation cache; no provider/config discovery."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import json
import time
from .contracts import EngineError
from .observation import record

_cache = ContextVar("ragflow_scoped_model_cache", default=None)


@contextmanager
def model_operation(scope):
    # A fresh cache, including exact authorized sources/versions, cannot leak
    # across requests, tenants or a changed source inventory.
    token = _cache.set((scope.key, tuple(s.key for s in scope.sources), {}))
    try:
        yield
    finally:
        _cache.reset(token)


def _key(model, system, history, config):
    return hashlib.sha256(json.dumps([model, system, history, config], sort_keys=True).encode()).hexdigest()


def get_llm_cache(model, system, history, config):
    state = _cache.get()
    return state[2].get(_key(model, system, history, config)) if state else None


def set_llm_cache(model, system, response, history, config):
    state = _cache.get()
    if state is not None:
        state[2][_key(model, system, history, config)] = response


class AuthorizedChatModel:
    """Connect upstream async_chat to an operator-installed callback, never model text scope."""
    def __init__(self, model, check):
        if model is None or not callable(getattr(model, "async_chat", None)):
            raise EngineError("CHAT_MODEL_UNAVAILABLE", "explicit model callback required")
        self.model, self.check = model, check
        self.max_length, self.llm_name = model.max_length, model.llm_name
        self.mdl = _ProviderView(self)

    def clone(self):
        # No provider/tenant discovery. Request-local callback state is retained.
        return AuthorizedChatModel(self.model, self.check)

    def _failed(self, exc):
        # Upstream may catch model errors for optional fallbacks. Explicitly
        # configured modes must not report health/success after provider failure.
        from .full_runtime import _operation
        op = _operation.get()
        if op is not None:
            op.fatal = exc
        raise exc from None

    async def async_completion(self, messages, tools=None, temperature=0.3, timeout=60):
        import asyncio
        self.check()
        callback = getattr(self.model, 'async_completion', None)
        if not callable(callback):
            raise EngineError('CHAT_MODEL_UNAVAILABLE', 'native tool completion required')
        started = time.perf_counter()
        try:
            async with asyncio.timeout(timeout):
                result = await callback(deepcopy(messages), tools=deepcopy(tools),
                                        temperature=temperature, timeout=timeout)
            self.check()
            return result
        except EngineError as exc:
            self._failed(exc)
        except Exception:
            self._failed(EngineError('CHAT_MODEL_UNAVAILABLE', 'native tool callback'))
        finally:
            record('model_callback', model=self.llm_name, component='native_tools',
                   milliseconds=(time.perf_counter() - started) * 1000)

    async def async_chat_streamly_delta(self, system, history, gen_conf=None, **kwargs):
        self.check()
        callback = getattr(self.model, 'async_chat_streamly_delta', None)
        if not callable(callback):
            # Transport may buffer, but the graph still executes the same
            # upstream synthesis prompt. This is not a retrieval fallback.
            yield await self.async_chat(system, history, gen_conf, **kwargs)
            return
        try:
            async for delta in callback(system, deepcopy(history), deepcopy(gen_conf or {}), **kwargs):
                self.check()
                yield delta
        except EngineError as exc:
            self._failed(exc)
        except Exception:
            self._failed(EngineError('CHAT_MODEL_UNAVAILABLE', 'stream callback'))

    async def async_chat(self, system, history, gen_conf=None, **kwargs):
        self.check()
        started = time.perf_counter()
        outcome = "failed"
        try:
            result = await self.model.async_chat(system, deepcopy(history), gen_conf=deepcopy(gen_conf or {}), **kwargs)
            outcome = "returned"
        except EngineError as exc:
            self._failed(exc)
        except Exception:
            self._failed(EngineError("CHAT_MODEL_UNAVAILABLE", "callback"))
        finally:
            record("model_callback", model=self.llm_name, outcome=outcome,
                   milliseconds=(time.perf_counter() - started) * 1000)
        self.check()
        return result


class _ProviderView:
    """Upstream Base-style tuple return over the same authorized bundle callback."""
    def __init__(self, bundle):
        self.bundle = bundle
        self.max_length, self.llm_name = bundle.max_length, bundle.llm_name

    @property
    def last_usage(self):
        return getattr(self.bundle.model, 'last_usage', None)

    async def async_chat(self, system, history, gen_conf=None, **kwargs):
        result = await self.bundle.async_chat(system, history, gen_conf, **kwargs)
        return result, (self.last_usage or {}).get('total_tokens', 0)

    async def async_completion(self, messages, **kwargs):
        return await self.bundle.async_completion(messages, **kwargs)
