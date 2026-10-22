"""RAG2 network admission does not occupy OG's CPU-oriented endpoint leases."""
from contextlib import contextmanager
import hashlib
import secrets
import threading
import time

from redis.exceptions import RedisError
from utils.redis_client import get_redis
from services.llama_rag.client_runtime import RetrievalError, lifetime, pause, setting
from services.llama_rag.worker_routing import _ACQUIRE

_LOCK = threading.Lock()
_ORDER = 0


@contextmanager
def worker_slot(urls):
    global _ORDER
    with _LOCK:
        offset = _ORDER % len(urls)
        _ORDER += 1
    urls = list(urls[offset:]) + list(urls[:offset])
    keys = ['rag2:routing:{workers-v1}:' + hashlib.sha256(url.encode()).hexdigest()[:24]
            for url in urls]
    redis_client = get_redis()
    if redis_client is None:
        raise RetrievalError('retrieval_routing_unavailable')
    token = secrets.token_hex(16)
    end = time.monotonic() + setting('RAG2_QUEUE_TIMEOUT_SECONDS', 120, 0, 300)
    selected = None
    try:
        while True:
            active = lifetime()
            ttl = int(((active.remaining() if active else 1500) + 1) * 1000)
            # Provider and CPU concurrency are enforced independently in the service.
            index = int(redis_client.eval(_ACQUIRE, len(keys), *keys, token, 1, ttl))
            if index:
                selected = index - 1
                break
            if time.monotonic() >= end:
                raise RetrievalError('retrieval_busy')
            pause(min(.1, max(0, end - time.monotonic())))
    except (RedisError, OSError):
        raise RetrievalError('retrieval_routing_unavailable') from None
    try:
        yield urls[selected]
    finally:
        try:
            redis_client.zrem(keys[selected], token)
        except (RedisError, OSError):
            pass  # The bounded lease expires even after a disconnected caller.
