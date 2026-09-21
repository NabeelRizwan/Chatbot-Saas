"""Explicit upstream chat boundary and per-operation cache; no provider/config discovery."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import json
from .contracts import EngineError

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

    async def async_chat(self, system, history, gen_conf=None, **kwargs):
        self.check()
        try:
            result = await self.model.async_chat(system, deepcopy(history), gen_conf=deepcopy(gen_conf or {}), **kwargs)
        except EngineError:
            raise
        except Exception:
            raise EngineError("CHAT_MODEL_UNAVAILABLE", "callback") from None
        self.check()
        return result
