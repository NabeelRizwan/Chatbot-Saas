"""Lease available trusted retrieval endpoints across backend processes."""
from contextlib import contextmanager
import hashlib
import secrets
import threading
import time

from redis.exceptions import RedisError
from utils.redis_client import get_redis
from .client_runtime import RetrievalError, lifetime, pause, setting


_ACQUIRE = """
local nowparts = redis.call('TIME')
local now = tonumber(nowparts[1]) * 1000 + math.floor(tonumber(nowparts[2]) / 1000)
local selected, lowest = 0, tonumber(ARGV[2])
for i, key in ipairs(KEYS) do
    redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
    local count = redis.call('ZCARD', key)
    if count < lowest then selected, lowest = i, count end
end
if selected == 0 then return 0 end
redis.call('ZADD', KEYS[selected], now + tonumber(ARGV[3]), ARGV[1])
local latest = redis.call('ZRANGE', KEYS[selected], -1, -1, 'WITHSCORES')
redis.call('PEXPIRE', KEYS[selected], tonumber(latest[2]) - now + 1000)
return selected
"""
_ORDER_LOCK = threading.Lock()
_ORDER = 0


@contextmanager
def worker_slot(urls, *, excluded=()):
    global _ORDER
    candidates = [url for url in urls if url not in excluded]
    if not candidates:
        raise RetrievalError("retrieval_service_unavailable")
    with _ORDER_LOCK:
        offset = _ORDER % len(candidates)
        _ORDER += 1
    candidates = candidates[offset:] + candidates[:offset]
    # Overlapping worker lists during a rollout must share the same capacity.
    keys = ["llama:routing:{workers-v1}:" + hashlib.sha256(url.encode()).hexdigest()[:24]
            for url in candidates]
    token = secrets.token_hex(16)
    redis_client = get_redis()
    if redis_client is None:
        raise RetrievalError("retrieval_routing_unavailable")
    slots = setting("LLAMA_RETRIEVAL_WORKER_SLOTS", 1, 1, 64, integer=True)
    end = time.monotonic() + setting("LLAMA_RETRIEVAL_QUEUE_TIMEOUT_SECONDS", 60, 0, 120)
    selected = None
    try:
        while True:
            active = lifetime()
            ttl = int(((active.remaining() if active else 420) + 1) * 1000)
            index = int(redis_client.eval(_ACQUIRE, len(keys), *keys, token, slots, ttl))
            if index:
                selected = index - 1
                break
            if time.monotonic() >= end:
                raise RetrievalError("retrieval_busy")
            pause(min(0.05, max(0, end - time.monotonic())))
    except (RedisError, OSError):
        raise RetrievalError("retrieval_routing_unavailable") from None
    try:
        yield candidates[selected]
    finally:
        try:
            redis_client.zrem(keys[selected], token)
        except (RedisError, OSError):
            # A failed release is recovered by the bounded lease expiration.
            pass
