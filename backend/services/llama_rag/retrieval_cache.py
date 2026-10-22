"""Exact evidence cache. Authority and evidence validation remain in KnowledgeScope."""
import hashlib
import json
import os
import secrets
import time

from redis.exceptions import RedisError
from utils.redis_client import get_redis
from .client_runtime import checkpoint, enabled, lifetime, pause, setting


_PREFIX = "llama:retrieval:{evidence-v1}:"
_STORE = """
local index, sizes = KEYS[1], KEYS[2]
local key, value = KEYS[3], ARGV[1]
local ttl, maxbytes, maxentries = tonumber(ARGV[2]), tonumber(ARGV[3]), tonumber(ARGV[4])
local nowparts = redis.call('TIME')
local now = tonumber(nowparts[1]) * 1000 + math.floor(tonumber(nowparts[2]) / 1000)
local total = tonumber(redis.call('HGET', sizes, '_bytes') or '0')
local function remove(k)
    total = total - tonumber(redis.call('HGET', sizes, k) or '0')
    redis.call('DEL', k)
    redis.call('ZREM', index, k)
    redis.call('HDEL', sizes, k)
end
for _, expired in ipairs(redis.call('ZRANGEBYSCORE', index, '-inf', now)) do remove(expired) end
remove(key)
local bytes = string.len(value)
while total + bytes > maxbytes or redis.call('ZCARD', index) >= maxentries do
    local oldest = redis.call('ZRANGE', index, 0, 0)
    if #oldest == 0 then break end
    remove(oldest[1])
end
redis.call('SET', key, value, 'PX', ttl)
redis.call('ZADD', index, now + ttl, key)
redis.call('HSET', sizes, key, bytes, '_bytes', math.max(0, total) + bytes)
redis.call('PEXPIRE', index, ttl + 60000)
redis.call('PEXPIRE', sizes, ttl + 60000)
return 1
"""
_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end
return 0
"""


class EvidenceCache:
    def __init__(self, redis_client, key, revision):
        self.redis = redis_client
        self.key = key
        self.revision = revision
        self.owner = secrets.token_hex(16)
        self.owned = False
        self.available = True
        self.max_item = setting("LLAMA_RETRIEVAL_CACHE_ITEM_BYTES", 512 * 1024, 1024, 5 * 1024 * 1024, integer=True)

    @classmethod
    def configured(cls, scope, question):
        if not enabled("LLAMA_RETRIEVAL_CACHE_ENABLED"):
            return None
        revision = os.getenv("LLAMA_RETRIEVAL_PIPELINE_REVISION", "").strip()
        # An operator must pin this to the complete model/config/code revision.
        # Without it, use the normal path rather than risk stale cross-version data.
        if not revision or len(revision) > 256:
            return None
        identity = {"organization_id": scope["organization_id"], "bot_id": scope["bot_id"],
                    "fingerprint": scope["fingerprint"], "question": question, "pipeline": revision}
        from services.knowledge_policy import current_pipeline_policy
        policy = current_pipeline_policy()
        if policy is not None:
            if policy.organization_id != scope["organization_id"]:
                raise ValueError("Knowledge policy tenant mismatch")
            identity["accepted_policy"] = policy.model_dump()
        digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True,
                                          separators=(",", ":")).encode()).hexdigest()
        redis_client = get_redis()
        return cls(redis_client, _PREFIX + "item:" + digest, revision) if redis_client is not None else None

    def read(self):
        if not self.available:
            return None
        checkpoint()
        try:
            raw = self.redis.get(self.key)
            if raw is None or len(raw.encode() if isinstance(raw, str) else raw) > self.max_item:
                return None
            data = json.loads(raw)
            if isinstance(data, dict) and data.get("pipeline") == self.revision and isinstance(data.get("result"), dict):
                return data["result"]
        except (RedisError, OSError, ValueError, TypeError):
            self.available = False
        return None

    def claim_or_wait(self):
        """Collapse equal misses across API processes; timeout falls through safely."""
        if not self.available:
            return None
        try:
            active = lifetime()
            ttl = int(((active.remaining() if active else 420) + 1) * 1000)
            self.owned = bool(self.redis.set(self.key + ":flight", self.owner, nx=True, px=ttl))
            if self.owned:
                return self.read()
            end = time.monotonic() + setting("LLAMA_RETRIEVAL_CACHE_WAIT_SECONDS", 5, 0, 30)
            while time.monotonic() < end:
                value = self.read()
                if value is not None or not self.available:
                    return value
                if not self.redis.exists(self.key + ":flight"):
                    self.owned = bool(self.redis.set(self.key + ":flight", self.owner, nx=True, px=ttl))
                    if self.owned:
                        return self.read()
                pause(min(0.05, max(0, end - time.monotonic())))
        except (RedisError, OSError):
            self.available = False
        return None

    def store(self, result, scope, question):
        if not self.available or result.get("fingerprint") != scope["fingerprint"] or result.get("question") != question:
            return
        context, evidence = result.get("context"), result.get("evidence")
        if (not isinstance(context, str) or not isinstance(evidence, list) or len(evidence) > 64
                or hashlib.sha256(context.encode()).hexdigest() != result.get("context_sha256")):
            return
        try:
            raw = json.dumps({"pipeline": self.revision, "result": result}, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode()
            budget = setting("LLAMA_RETRIEVAL_CACHE_BYTES", 32 * 1024 * 1024, 1024, 512 * 1024 * 1024, integer=True)
            if len(raw) > min(self.max_item, budget):
                return
            ttl = int(setting("LLAMA_RETRIEVAL_CACHE_TTL_SECONDS", 300, 1, 3600) * 1000)
            entries = setting("LLAMA_RETRIEVAL_CACHE_ENTRIES", 256, 1, 4096, integer=True)
            self.redis.eval(_STORE, 3, _PREFIX + "index", _PREFIX + "sizes", self.key,
                            raw, ttl, budget, entries)
        except (RedisError, OSError, ValueError, TypeError):
            self.available = False

    def release(self):
        if self.owned:
            try:
                self.redis.eval(_RELEASE, 1, self.key + ":flight", self.owner)
            except (RedisError, OSError):
                pass
            self.owned = False
