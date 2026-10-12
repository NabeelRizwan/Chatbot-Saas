"""Provider quota policy and feedback, without extra provider requests.

Configured budgets are rolling windows. Daily windows are a conservative 24h
budget, not a claim about a provider's calendar reset. Unknown quotas remain
unknown; deployment must configure providers that do not report their limits.
"""
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import math
import os
import time


DIMENSIONS = {
    'rpm': ('requests', 60), 'rpd': ('requests', 86400),
    'input_tpm': ('input_tokens', 60), 'output_tpm': ('output_tokens', 60),
    'tpm': ('total_tokens', 60), 'tpd': ('total_tokens', 86400),
}
PREFIX = 'provider-capacity:{v1}:quota:'


def integer(value, *, minimum=0, maximum=10**12):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('provider_capacity_configuration_invalid')
    if not math.isfinite(value) or int(value) != value or not minimum <= value <= maximum:
        raise ValueError('provider_capacity_configuration_invalid')
    return int(value)


@lru_cache(maxsize=16)
def _configuration(raw):
    data = json.loads(raw)
    if not isinstance(data, dict) or len(data) > 4096:
        raise ValueError('provider_capacity_configuration_invalid')
    for name, budgets in data.items():
        if not isinstance(name, str) or not name or len(name) > 512 or not isinstance(budgets, dict):
            raise ValueError('provider_capacity_configuration_invalid')
        if set(budgets) - set(DIMENSIONS):
            raise ValueError('provider_capacity_configuration_invalid')
        for amount in budgets.values():
            integer(amount)
    return data


def model_name(provider, model):
    name = str(model or 'default').strip()
    if provider == 'gemini' and name.startswith('models/'):
        name = name[7:]
    aliases = json.loads(os.getenv('PROVIDER_CAPACITY_MODEL_GROUPS_JSON', '{}'))
    if not isinstance(aliases, dict) or len(aliases) > 4096:
        raise ValueError('provider_capacity_configuration_invalid')
    alias = aliases.get(f'{provider}:{name}', name)
    if not isinstance(alias, str) or not alias or len(alias) > 256:
        raise ValueError('provider_capacity_configuration_invalid')
    return alias


def _base(scope):
    return PREFIX + hashlib.sha256(scope.encode()).hexdigest()


def cooldown_keys(group_scope, model_scope):
    return [_base(scope) + ':cooldown' for scope in (group_scope, model_scope)]


@dataclass(frozen=True)
class TokenReservation:
    input_tokens: int = 0
    output_tokens: int = 0

    def amount(self, dimension):
        return {'requests': 1, 'input_tokens': self.input_tokens,
                'output_tokens': self.output_tokens,
                'total_tokens': self.input_tokens + self.output_tokens}[dimension]


@lru_cache(maxsize=1)
def _encoding():
    from services.structural_chunking import local_tokenizer
    return local_tokenizer()[0]


def estimate_tokens(prompt, system_instruction=None, output_limit=None):
    """Local estimate only: never perform a countTokens network round trip.

    A reserve is not an output cap. Ordinary generation settings are unchanged.
    Usage reconciliation only increases consumption, since many providers charge
    admission against the original requested maximum even for shorter replies.
    """
    text = (system_instruction or '') + '\n' + str(prompt or '')
    estimate = len(_encoding().encode(text, disallowed_special=()))
    margin = float(os.getenv('PROVIDER_CAPACITY_TOKEN_ESTIMATE_MARGIN', '1.2'))
    if not math.isfinite(margin) or not 1 <= margin <= 4:
        raise ValueError('provider_capacity_configuration_invalid')
    output = output_limit if output_limit is not None else int(os.getenv('PROVIDER_CAPACITY_OUTPUT_RESERVE', '2048'))
    return TokenReservation(math.ceil(estimate * margin) + 128, integer(output, minimum=1, maximum=1000000))


def constraints(redis_client, group_scope, model_scope, reservation):
    configured = _configuration(os.getenv('PROVIDER_CAPACITY_BUDGETS_JSON', '{}'))
    scopes = [group_scope, model_scope]
    defaults = configured.get(group_scope.split(':', 1)[0] + ':*', {})
    pipe = redis_client.pipeline(transaction=False)
    for scope in scopes:
        pipe.hgetall(_base(scope) + ':learned')
    learned = pipe.execute()
    result = []
    for scope, observed in zip(scopes, learned):
        budgets = dict(defaults if scope == model_scope else {})
        budgets.update(configured.get(scope, {}))
        observed = {(k.decode() if isinstance(k, bytes) else k):
                    (v.decode() if isinstance(v, bytes) else v) for k, v in observed.items()}
        for label, (dimension, seconds) in DIMENSIONS.items():
            limit = budgets.get(label, 0)
            observed_present = label in observed
            observed_limit = int(observed.get(label, 0))
            if observed_present:
                limit = min(limit, observed_limit) if limit else observed_limit
            if not limit and not observed_present:
                continue
            amount = reservation.amount(dimension)
            if dimension != 'requests' and amount <= 0:
                raise ValueError('provider_capacity_token_reservation_required')
            base = _base(scope) + ':' + label
            result.append({'label': label, 'dimension': dimension, 'window_ms': seconds * 1000,
                           'limit': limit, 'amount': amount,
                           'keys': [base + ':events', base + ':amounts'],
                           'source': 'configured+observed' if label in budgets and observed_present else
                                     'configured' if label in budgets else 'observed'})
    return result


# Ceilings only decrease while live; a later response cannot reopen consumed
# capacity. Expiry allows a newly purchased tier to be learned on later traffic.
_LEARN = """
local current = redis.call('HGET', KEYS[1], ARGV[1])
local observed = tonumber(ARGV[2])
if not current or observed < tonumber(current) then
    redis.call('HSET', KEYS[1], ARGV[1], observed)
    if redis.call('TTL', KEYS[1]) < 0 then redis.call('EXPIRE', KEYS[1], 3600) end
end
return 1
"""
_BLOCK = """
if redis.call('PTTL', KEYS[1]) < tonumber(ARGV[1]) then
    redis.call('PSETEX', KEYS[1], ARGV[1], 'exhausted')
end
return 1
"""


def record_feedback(redis_client, group_scope, model_scope, feedback):
    """Learn explicit window limits; return longest explicit exhausted reset.

    Remaining headers may be rounded or arrive out of order. They never refill
    local counters. A confirmed exhausted window only extends its cooldown.
    """
    if feedback is None:
        return 0.0
    reset = 0.0
    observed_at = getattr(feedback, 'observed_at_unix', None)
    age = max(0.0, time.time()-observed_at) if isinstance(observed_at, (int, float)) and math.isfinite(observed_at) else 0
    for item in getattr(feedback, 'rate_limits', ())[:16]:
        dimension = getattr(item, 'dimension', None)
        window = getattr(item, 'window_seconds', None)
        labels = [key for key, value in DIMENSIONS.items() if value == (dimension, window)]
        if not labels:
            continue
        scope = group_scope if getattr(item, 'scope', 'model') == 'project' else model_scope
        limit = getattr(item, 'limit', None)
        if limit is not None:
            limit = integer(limit)
            redis_client.eval(_LEARN, 1, _base(scope) + ':learned', labels[0], limit)
        remaining = getattr(item, 'remaining', None)
        delay = getattr(item, 'reset_after_seconds', None)
        if remaining == 0 and isinstance(delay, (int, float)) and math.isfinite(delay) and 0 < delay <= 86400:
            delay = max(0.0, delay-age)
            if delay > 0:
                redis_client.eval(_BLOCK, 1, _base(scope)+':cooldown', math.ceil(delay*1000))
                reset = max(reset, delay)
    return reset


# Used only while the event still exists. Late completion must not resurrect a
# prior window. Failed attempts keep their reservations without reconciliation.
_RECONCILE = """
local t = redis.call('TIME')
local now = tonumber(t[1])*1000 + math.floor(tonumber(t[2])/1000)
for i = 1, #KEYS, 2 do
    local score = tonumber(redis.call('ZSCORE', KEYS[i], ARGV[1]) or '0')
    local arg = 2 + i-1
    if score > 0 and score > now-tonumber(ARGV[arg+1]) then
        local old = tonumber(redis.call('HGET', KEYS[i+1], ARGV[1]) or '0')
        local actual = tonumber(ARGV[arg])
        if actual > old then
            redis.call('HSET', KEYS[i+1], ARGV[1], actual)
            redis.call('HINCRBY', KEYS[i+1], '__total', actual-old)
        end
    end
end
return 1
"""


def reconcile(redis_client, budgets, token, usage):
    if usage is None or not budgets:
        return
    actual = TokenReservation(max(0, int(getattr(usage, 'input_tokens', 0) or 0)),
                              max(0, int(getattr(usage, 'output_tokens', 0) or 0)))
    keys = [key for budget in budgets for key in budget['keys']]
    redis_client.eval(_RECONCILE, len(keys), *keys, token,
                      *(value for budget in budgets for value in
                        (actual.amount(budget['dimension']), budget['window_ms'])))


_REFUND = """
redis.call('ZREM', KEYS[1], ARGV[1])
for i = 2, #KEYS, 2 do
    if redis.call('ZREM', KEYS[i], ARGV[1]) == 1 then
        local old = tonumber(redis.call('HGET', KEYS[i+1], ARGV[1]) or '0')
        redis.call('HINCRBY', KEYS[i+1], '__total', -old)
        redis.call('HDEL', KEYS[i+1], ARGV[1])
    end
end
return 1
"""


def refund_unsent(redis_client, rpm_key, budgets, token):
    keys = [rpm_key] + [key for budget in budgets for key in budget['keys']]
    redis_client.eval(_REFUND, len(keys), *keys, token)
