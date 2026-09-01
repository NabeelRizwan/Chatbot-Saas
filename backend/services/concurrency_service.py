import contextlib
import logging
import os
import threading
import time
import uuid
from typing import Generator, Optional, Tuple

from utils.redis_client import get_redis, is_redis_available

logger = logging.getLogger("backend.concurrency")

# Default Configurable Limits
GLOBAL_MAX_CRAWLS = int(os.getenv("GLOBAL_MAX_CRAWLS", "5"))
PER_ORG_MAX_CRAWLS = int(os.getenv("PER_ORG_MAX_CRAWLS", "2"))

GLOBAL_MAX_LLM_REQUESTS = int(os.getenv("GLOBAL_MAX_LLM_REQUESTS", "50"))
PER_ORG_MAX_LLM_REQUESTS = int(os.getenv("PER_ORG_MAX_LLM_REQUESTS", "10"))

GLOBAL_MAX_EMBEDDING_REQUESTS = int(os.getenv("GLOBAL_MAX_EMBEDDING_REQUESTS", "20"))
PER_ORG_MAX_EMBEDDING_REQUESTS = int(os.getenv("PER_ORG_MAX_EMBEDDING_REQUESTS", "5"))

SEMAPHORE_DEFAULT_TTL = int(os.getenv("SEMAPHORE_DEFAULT_TTL", "60"))

# In-memory fallbacks when Redis is not reachable
_LOCAL_SEMAPHORES: dict[str, threading.Semaphore] = {}
_LOCAL_LOCK = threading.Lock()

# Lua scripts for atomic semaphore operations
LUA_ACQUIRE_SEMAPHORE = """
-- KEYS[1] = semaphore_key
-- ARGV[1] = max_permits
-- ARGV[2] = current_time (seconds)
-- ARGV[3] = ttl (seconds)
-- ARGV[4] = owner_token

-- 1. Remove expired permits
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[2])

-- 2. Count active permits
local count = redis.call('ZCARD', KEYS[1])
if count < tonumber(ARGV[1]) then
    local expire_at = tonumber(ARGV[2]) + tonumber(ARGV[3])
    redis.call('ZADD', KEYS[1], expire_at, ARGV[4])
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]) + 15)
    return 1
else
    return 0
end
"""

LUA_RELEASE_SEMAPHORE = """
-- KEYS[1] = semaphore_key
-- ARGV[1] = owner_token
return redis.call('ZREM', KEYS[1], ARGV[1])
"""


def _get_semaphore_key(resource_name: str, org_id: Optional[int] = None) -> str:
    sanitized_resource = "".join(c for c in resource_name if c.isalnum() or c in ("_", "-"))
    if org_id is not None:
        return f"semaphore:{sanitized_resource}:org_{org_id}"
    return f"semaphore:{sanitized_resource}:global"


def get_resource_limit(resource_name: str, org_id: Optional[int] = None) -> int:
    """Resolves limit based on resource type and scope."""
    if resource_name == "crawl":
        return PER_ORG_MAX_CRAWLS if org_id is not None else GLOBAL_MAX_CRAWLS
    elif resource_name == "llm":
        return PER_ORG_MAX_LLM_REQUESTS if org_id is not None else GLOBAL_MAX_LLM_REQUESTS
    elif resource_name == "embedding":
        return PER_ORG_MAX_EMBEDDING_REQUESTS if org_id is not None else GLOBAL_MAX_EMBEDDING_REQUESTS
    return 10


def acquire_distributed_permit(
    resource_name: str,
    org_id: Optional[int] = None,
    max_permits: Optional[int] = None,
    ttl_seconds: Optional[int] = None,
) -> Tuple[bool, str]:
    """
    Acquires an ownership-protected permit from the distributed semaphore.
    Returns: (acquired: bool, owner_token: str)
    """
    if max_permits is None:
        max_permits = get_resource_limit(resource_name, org_id)
    if ttl_seconds is None:
        ttl_seconds = SEMAPHORE_DEFAULT_TTL

    owner_token = f"tok_{uuid.uuid4().hex[:16]}"
    key = _get_semaphore_key(resource_name, org_id)

    redis_client = get_redis()
    if redis_client is not None:
        try:
            now = time.time()
            res = redis_client.eval(
                LUA_ACQUIRE_SEMAPHORE,
                1,
                key,
                max_permits,
                now,
                ttl_seconds,
                owner_token,
            )
            acquired = bool(res == 1)
            if acquired:
                logger.debug(f"Acquired semaphore permit: {key} (token={owner_token})")
            else:
                logger.warning(f"Semaphore capacity exceeded for {key} (limit={max_permits})")
            return acquired, owner_token
        except Exception as exc:
            logger.warning(f"Redis semaphore acquire failed: {exc}, using local fallback")

    # In-memory fallback if Redis is unavailable
    with _LOCAL_LOCK:
        if key not in _LOCAL_SEMAPHORES:
            _LOCAL_SEMAPHORES[key] = threading.Semaphore(max_permits)
        sem = _LOCAL_SEMAPHORES[key]

    acquired = sem.acquire(blocking=False)
    return acquired, owner_token


def release_distributed_permit(
    resource_name: str,
    owner_token: str,
    org_id: Optional[int] = None,
) -> bool:
    """
    Safely releases an acquired permit using ownership verification.
    Prevents cross-tenant release.
    """
    if not owner_token:
        return False

    key = _get_semaphore_key(resource_name, org_id)
    redis_client = get_redis()

    if redis_client is not None:
        try:
            res = redis_client.eval(LUA_RELEASE_SEMAPHORE, 1, key, owner_token)
            released = bool(res >= 1)
            if released:
                logger.debug(f"Released semaphore permit: {key} (token={owner_token})")
            return released
        except Exception as exc:
            logger.warning(f"Redis semaphore release failed: {exc}, releasing local fallback")

    # In-memory fallback
    with _LOCAL_LOCK:
        if key in _LOCAL_SEMAPHORES:
            try:
                _LOCAL_SEMAPHORES[key].release()
                return True
            except ValueError:
                return False
    return False


@contextlib.contextmanager
def distributed_concurrency_guard(
    resource_name: str,
    org_id: Optional[int] = None,
    max_permits: Optional[int] = None,
    ttl_seconds: Optional[int] = None,
) -> Generator[bool, None, None]:
    """
    Context manager for distributed concurrency limiting.
    Yields True if permit acquired, False if capacity exhausted.
    Guarantees permit release on exit.
    """
    acquired, token = acquire_distributed_permit(
        resource_name, org_id=org_id, max_permits=max_permits, ttl_seconds=ttl_seconds
    )
    try:
        yield acquired
    finally:
        if acquired:
            release_distributed_permit(resource_name, token, org_id=org_id)
