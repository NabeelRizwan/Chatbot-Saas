"""Bounded provider admission shared by chat workers through Redis.

Quota groups are operator configuration, never inferred from separate API keys.
PROVIDER_CAPACITY_QUOTA_GROUPS_JSON maps credential_fingerprint(provider, key)
to a provider project/group name. RPM overrides use ``provider:group:model``;
``provider:group`` can intentionally share one RPM budget across models.
No RPM limit is assumed when none is configured. Token/day budgets continue to
belong to the provider and the platform's existing usage controls.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
import math
import os
import secrets
import threading
import time

from redis.exceptions import RedisError
from utils.redis_client import get_redis


class ProviderCapacityError(RuntimeError):
    """Safe admission category without provider credentials or Redis details."""


def enabled():
    return (os.getenv("CHAT_EXECUTION_MODE", "").strip().lower() == "hatchet"
            or os.getenv("PROVIDER_CAPACITY_ENABLED", "").strip().lower() in {"1", "true", "yes"})


def _number(name, default, low, high):
    try:
        number = float(os.getenv("PROVIDER_CAPACITY_" + name, str(default)))
        if math.isfinite(number) and low <= number <= high:
            return number
    except (TypeError, ValueError):
        pass
    raise ProviderCapacityError("provider_capacity_configuration_invalid")


def _mapping(name):
    try:
        value = json.loads(os.getenv("PROVIDER_CAPACITY_" + name, "{}"))
        if isinstance(value, dict) and len(value) <= 4096:
            return value
    except (ValueError, TypeError):
        pass
    raise ProviderCapacityError("provider_capacity_configuration_invalid")


def _digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def credential_fingerprint(provider, api_key):
    return _digest(str(provider).strip().lower() + "\0" + str(api_key))


@dataclass(frozen=True)
class CapacityContext:
    deadline: float
    cancel_event: threading.Event | None = None

    def remaining(self):
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise ProviderCapacityError("provider_capacity_cancelled")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ProviderCapacityError("provider_capacity_deadline_exceeded")
        return remaining


_CONTEXT = ContextVar("provider_capacity_context", default=None)


def provider_capacity_remaining():
    """Remaining outer chat budget, or None for a standalone provider call."""
    context = _CONTEXT.get()
    return context.remaining() if enabled() and context is not None else None


def provider_capacity_cancel_event():
    context = _CONTEXT.get()
    return context.cancel_event if context is not None else None


@contextmanager
def provider_capacity_context(timeout=60, cancel_event=None):
    parent = _CONTEXT.get()
    try:
        timeout = float(timeout)
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError()
    except (TypeError, ValueError):
        raise ProviderCapacityError("provider_capacity_configuration_invalid") from None
    deadline = time.monotonic() + timeout
    if parent is not None:
        deadline = min(deadline, parent.deadline)
        cancel_event = parent.cancel_event or cancel_event
    context = CapacityContext(deadline, cancel_event)
    token = _CONTEXT.set(context)
    try:
        if enabled():
            context.remaining()
        yield context
    finally:
        _CONTEXT.reset(token)


def scope_identity(provider, model, api_key, org_id):
    provider = str(provider).strip().lower()
    credential = credential_fingerprint(provider, api_key)
    group = _mapping("QUOTA_GROUPS_JSON").get(credential, credential)
    if not isinstance(group, str) or not group or len(group) > 256:
        raise ProviderCapacityError("provider_capacity_configuration_invalid")
    limits = _mapping("RPM_LIMITS_JSON")
    group_name, model_name = f"{provider}:{group}", f"{provider}:{group}:{model or ''}"
    quota_name = model_name if model_name in limits or group_name not in limits else group_name
    rpm = limits.get(quota_name, _number("RPM", 0, 0, 1000000))
    if (isinstance(rpm, bool) or not isinstance(rpm, (int, float)) or not math.isfinite(rpm)
            or not 0 <= rpm <= 1000000 or int(rpm) != rpm):
        raise ProviderCapacityError("provider_capacity_configuration_invalid")
    prefix = "provider-capacity:{v1}:"
    return {
        "keys": [prefix + "global", prefix + "org:" + _digest(org_id),
                 prefix + "credential:" + credential, prefix + "group:" + _digest(group_name),
                 prefix + "rpm:" + _digest(quota_name), prefix + "cooldown:" + _digest(quota_name)],
        "rpm": int(rpm),
        "credential": credential,
    }


_ACQUIRE = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local token, ttl, rpm = ARGV[1], tonumber(ARGV[2]), tonumber(ARGV[7])
local cooldown = redis.call('PTTL', KEYS[6])
if cooldown > 0 then return {0, cooldown} end
for i = 1, 4 do
    redis.call('ZREMRANGEBYSCORE', KEYS[i], '-inf', now)
    if redis.call('ZCARD', KEYS[i]) >= tonumber(ARGV[i + 2]) then return {0, 50} end
end
if rpm > 0 then
    redis.call('ZREMRANGEBYSCORE', KEYS[5], '-inf', now - 60000)
    if redis.call('ZCARD', KEYS[5]) >= rpm then
        local first = redis.call('ZRANGE', KEYS[5], 0, 0, 'WITHSCORES')
        return {0, math.max(1, tonumber(first[2]) + 60000 - now)}
    end
end
for i = 1, 4 do
    redis.call('ZADD', KEYS[i], now + ttl, token)
    local last = redis.call('ZRANGE', KEYS[i], -1, -1, 'WITHSCORES')
    redis.call('PEXPIRE', KEYS[i], tonumber(last[2]) - now + 1000)
end
if rpm > 0 then
    redis.call('ZADD', KEYS[5], now, token)
    redis.call('PEXPIRE', KEYS[5], 61000)
end
return {1, 0}
"""
_RENEW = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
for _, key in ipairs(KEYS) do
    local expiry = redis.call('ZSCORE', key, ARGV[1])
    if not expiry or tonumber(expiry) <= now then return 0 end
end
for _, key in ipairs(KEYS) do
    redis.call('ZADD', key, now + tonumber(ARGV[2]), ARGV[1])
    local last = redis.call('ZRANGE', key, -1, -1, 'WITHSCORES')
    redis.call('PEXPIRE', key, tonumber(last[2]) - now + 1000)
end
return 1
"""
_RELEASE = """
for _, key in ipairs(KEYS) do redis.call('ZREM', key, ARGV[1]) end
return 1
"""
_COOLDOWN = """
local current = redis.call('PTTL', KEYS[1])
if current < tonumber(ARGV[1]) then redis.call('PSETEX', KEYS[1], ARGV[1], 'limited') end
return 1
"""


class CapacityLease:
    def __init__(self, redis_client, keys, token, ttl):
        self.redis, self.keys, self.token, self.ttl = redis_client, keys[:4], token, ttl
        self.stop = threading.Event()
        self.lost = threading.Event()
        self.thread = threading.Thread(target=self._renew, name="provider-capacity-lease", daemon=True)

    def _renew(self):
        while not self.stop.wait(max(0.2, self.ttl / 3000)):
            try:
                if not self.redis.eval(_RENEW, len(self.keys), *self.keys, self.token, self.ttl):
                    self.lost.set()
                    return
            except (RedisError, OSError):
                self.lost.set()
                return

    def check(self):
        if self.lost.is_set():
            raise ProviderCapacityError("provider_capacity_lease_lost")

    def confirm(self):
        self.check()
        try:
            owned = self.redis.eval(_RENEW, len(self.keys), *self.keys, self.token, self.ttl)
        except (RedisError, OSError):
            self.lost.set()
            raise ProviderCapacityError("provider_capacity_lease_lost") from None
        if not owned:
            self.lost.set()
            raise ProviderCapacityError("provider_capacity_lease_lost")

    def close(self):
        self.stop.set()
        self.thread.join(timeout=0.1)
        try:
            self.redis.eval(_RELEASE, len(self.keys), *self.keys, self.token)
        except (RedisError, OSError):
            pass


@contextmanager
def provider_capacity_guard(provider, model, api_key, org_id):
    """Hold only around an actual provider attempt, including streamed iteration.

    Busy capacity waits within the caller's context deadline; it never changes
    provider/model selection. SDK timeouts must still bound the actual call.
    """
    if not enabled():
        yield None
        return
    identity = scope_identity(provider, model, api_key, org_id)
    redis_client = get_redis()
    if redis_client is None:
        raise ProviderCapacityError("provider_capacity_unavailable")
    context = _CONTEXT.get() or CapacityContext(time.monotonic() + _number("WAIT_SECONDS", 60, 0.01, 3600))
    configured_limits = [_number(name, default, 1, 100000) for name, default in
                         (("GLOBAL_LIMIT", 40), ("ORG_LIMIT", 20), ("CREDENTIAL_LIMIT", 10), ("GROUP_LIMIT", 10))]
    if any(int(limit) != limit for limit in configured_limits):
        raise ProviderCapacityError("provider_capacity_configuration_invalid")
    limits = [int(limit) for limit in configured_limits]
    token = secrets.token_hex(16)
    lease_ms = int(_number("LEASE_SECONDS", 120, 1, 3600) * 1000)
    while True:
        remaining = context.remaining()
        try:
            acquired, delay_ms = redis_client.eval(_ACQUIRE, 6, *identity["keys"], token,
                                                  lease_ms, *limits, identity["rpm"])
        except (RedisError, OSError):
            raise ProviderCapacityError("provider_capacity_unavailable") from None
        if acquired:
            break
        delay = min(0.1, max(0.01, delay_ms / 1000), remaining)
        if context.cancel_event is not None:
            context.cancel_event.wait(delay)
        else:
            time.sleep(delay)
    lease = CapacityLease(redis_client, identity["keys"], token, lease_ms)
    try:
        context.remaining()
        lease.thread.start()
        yield lease
        lease.confirm()
    finally:
        if lease.thread.ident is not None:
            lease.close()
        else:
            try:
                redis_client.eval(_RELEASE, 4, *identity["keys"][:4], token)
            except (RedisError, OSError):
                pass


def record_provider_cooldown(provider, model, api_key, seconds, org_id=None):
    """Apply a provider Retry-After to the same shared quota group."""
    if not enabled():
        return
    try:
        seconds = float(seconds)
        if not math.isfinite(seconds) or seconds <= 0:
            return
    except (TypeError, ValueError):
        return
    identity = scope_identity(provider, model, api_key, org_id)
    redis_client = get_redis()
    if redis_client is None:
        raise ProviderCapacityError("provider_capacity_unavailable")
    try:
        redis_client.eval(_COOLDOWN, 1, identity["keys"][5], int(min(seconds, 86400) * 1000))
    except (RedisError, OSError):
        raise ProviderCapacityError("provider_capacity_unavailable") from None
