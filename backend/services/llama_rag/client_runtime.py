"""Process-owned HTTP connections and bounded retrieval request lifetimes."""
import atexit
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import os
import threading
import time

import httpx


class RetrievalError(RuntimeError):
    """A safe category; never expose credentials or upstream response bodies."""

    def __init__(self, category, *, retryable=False):
        super().__init__(category)
        self.retryable = retryable


def enabled(name):
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes"}


def setting(name, default, minimum, maximum, *, integer=False):
    try:
        value = int(os.getenv(name, str(default))) if integer else float(os.getenv(name, str(default)))
        if minimum <= value <= maximum:
            return value
    except (TypeError, ValueError):
        pass
    raise RetrievalError("retrieval_configuration_invalid")


@dataclass(frozen=True)
class RequestLifetime:
    deadline: float
    cancel_event: threading.Event | None = None

    def remaining(self):
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise RetrievalError("retrieval_cancelled")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise RetrievalError("retrieval_deadline_exceeded")
        return remaining


_LIFETIME = ContextVar("llama_retrieval_lifetime", default=None)
_LAST_RETRIEVAL_METADATA = ContextVar("last_retrieval_metadata", default=None)


def record_retrieval_metadata(*, cache_hit, client_elapsed_ms):
    _LAST_RETRIEVAL_METADATA.set({'cache_hit': bool(cache_hit), 'client_elapsed_ms': client_elapsed_ms})


def get_last_retrieval_metadata():
    return dict(_LAST_RETRIEVAL_METADATA.get() or {'cache_hit': False, 'client_elapsed_ms': 0.0})


@contextmanager
def retrieval_request_context(*, timeout=420, cancel_event=None):
    """An outer chat deadline/cancel event can cover queueing and all HTTP calls.

    Cancellation is cooperative between socket operations. Each socket operation
    also has a bounded HTTPX timeout; closing a browser alone is not a signal.
    """
    parent = _LIFETIME.get()
    deadline = time.monotonic() + min(float(timeout), 420)
    if parent is not None:
        deadline = min(deadline, parent.deadline)
        cancel_event = parent.cancel_event or cancel_event
    lifetime = RequestLifetime(deadline, cancel_event)
    token = _LIFETIME.set(lifetime)
    try:
        lifetime.remaining()
        yield lifetime
    finally:
        _LIFETIME.reset(token)


def lifetime():
    return _LIFETIME.get()


def checkpoint():
    active = lifetime()
    return active.remaining() if active else None


def pause(seconds):
    active = lifetime()
    remaining = active.remaining() if active else seconds
    delay = min(seconds, remaining)
    if active and active.cancel_event is not None:
        active.cancel_event.wait(delay)
    else:
        time.sleep(delay)
    checkpoint()


_CLIENTS = {}
_CLIENTS_LOCK = threading.Lock()


def pooled_client(url, token, transport=None):
    # Include PID so pre-fork processes never reuse their parent's socket pool.
    key = (os.getpid(), url, hashlib.sha256(token.encode()).digest(), id(transport))
    with _CLIENTS_LOCK:
        client = _CLIENTS.get(key)
        if client is None:
            if len(_CLIENTS) >= 64:
                raise RetrievalError("retrieval_connection_pool_limit")
            limit = setting("LLAMA_RETRIEVAL_HTTP_CONNECTIONS", 16, 1, 128, integer=True)
            client = httpx.Client(trust_env=False, follow_redirects=False, transport=transport,
                limits=httpx.Limits(max_connections=limit, max_keepalive_connections=limit,
                                   keepalive_expiry=30))
            _CLIENTS[key] = client
        return client


def close_retrieval_clients():
    """Call after in-flight work drains, at API/worker/script shutdown."""
    with _CLIENTS_LOCK:
        clients = list(_CLIENTS.values())
        _CLIENTS.clear()
    for client in clients:
        client.close()


atexit.register(close_retrieval_clients)
