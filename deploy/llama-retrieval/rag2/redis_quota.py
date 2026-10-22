"""Atomic Voyage account admission across independent retrieval containers."""
import hashlib
import math
import uuid

from redis.exceptions import RedisError
from .request_budget import VoyageError


_RESERVE = """
local t = redis.call('TIME')
local now = tonumber(t[1])*1000 + math.floor(tonumber(t[2])/1000)
local window, rpm, tpm = tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3])
local policy = ARGV[1] .. ':' .. ARGV[2] .. ':' .. ARGV[3]
local previous = redis.call('GET', KEYS[4])
if previous and previous ~= policy then return {-1, 0} end
redis.call('PSETEX', KEYS[4], window+1000, policy)
for _, id in ipairs(redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', now-window)) do
  redis.call('ZREM', KEYS[1], id)
  redis.call('HDEL', KEYS[2], id)
end
local rows = redis.call('ZRANGE', KEYS[1], 0, -1, 'WITHSCORES')
local total = 0
for i=1,#rows,2 do total = total + tonumber(redis.call('HGET', KEYS[2], rows[i]) or '0') end
local cooldown = math.max(0, tonumber(redis.call('GET', KEYS[3]) or '0')-now)
local quota = #rows / 2 < rpm and total + tonumber(ARGV[4]) <= tpm
if cooldown == 0 and quota then
  redis.call('ZADD', KEYS[1], now, ARGV[5])
  redis.call('HSET', KEYS[2], ARGV[5], ARGV[4])
  redis.call('PEXPIRE', KEYS[1], window+1000)
  redis.call('PEXPIRE', KEYS[2], window+1000)
  return {1, 0}
end
local wait = 0
if not quota then wait = tonumber(rows[2] or now) + window - now end
return {0, math.max(50, cooldown, wait)}
"""
_RECONCILE = """
if redis.call('ZSCORE', KEYS[1], ARGV[1]) then
  local old = tonumber(redis.call('HGET', KEYS[2], ARGV[1]) or '0')
  redis.call('HSET', KEYS[2], ARGV[1], math.max(old, tonumber(ARGV[2])))
end
return 1
"""
_DEFER = """
local t = redis.call('TIME')
local now = tonumber(t[1])*1000 + math.floor(tonumber(t[2])/1000)
local until_at = math.max(tonumber(redis.call('GET', KEYS[1]) or '0'), now+tonumber(ARGV[1]))
redis.call('PSETEX', KEYS[1], math.max(1, until_at-now+1000), until_at)
return 1
"""


class QuotaLedger:
    """Redis time avoids clock skew; failed calls retain reservations.

    No process-local fallback. Same-account keys use one configured account ID;
    when omitted, identical API keys derive identical opaque ledger namespaces.
    """
    def __init__(self, redis_client, account, *, rpm=3, tpm=10000, window_seconds=62):
        if (not account or type(rpm) is not int or type(tpm) is not int
                or rpm < 1 or tpm < 3602 or window_seconds < 62):
            raise VoyageError('voyage_quota_configuration_invalid')
        self.redis = redis_client
        self.rpm, self.tpm, self.window_ms = rpm, tpm, int(window_seconds*1000)
        prefix = 'voyage:quota:{' + hashlib.sha256(account.encode()).hexdigest() + '}:'
        self.keys = [prefix+suffix for suffix in ('reservations','tokens','cooldown','policy')]

    def _eval(self, script, keys, *args):
        try:
            return self.redis.eval(script, len(keys), *keys, *args)
        except (RedisError, OSError):
            raise VoyageError('voyage_quota_store_unavailable') from None

    def ready(self):
        try:
            if not self.redis.ping():
                raise VoyageError('voyage_quota_store_unavailable')
        except (RedisError, OSError):
            raise VoyageError('voyage_quota_store_unavailable') from None

    def reserve(self, tokens, budget):
        if type(tokens) is not int or not 0 < tokens <= self.tpm:
            raise VoyageError('voyage_batch_token_limit')
        key = uuid.uuid4().hex
        while True:
            budget.remaining()
            allowed, wait_ms = self._eval(_RESERVE, self.keys,
                self.window_ms, self.rpm, self.tpm, tokens, key)
            if allowed == -1:
                raise VoyageError('voyage_quota_configuration_mismatch')
            if allowed:
                return key
            budget.pause(wait_ms/1000)

    def reconcile(self, key, tokens):
        self._eval(_RECONCILE, self.keys[:2], key, tokens)

    def defer(self, seconds):
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError('Provider cooldown must be finite and nonnegative.')
        self._eval(_DEFER, [self.keys[2]], math.ceil(seconds*1000))
