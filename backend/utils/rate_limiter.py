import logging
import os
import random
import time
from typing import Optional, Tuple

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from utils.redis_client import get_redis

logger = logging.getLogger("backend.ratelimit")

# Configurable Rate Limits
RATE_LIMIT_PUBLIC_CHAT_MAX = int(os.getenv("RATE_LIMIT_PUBLIC_CHAT_MAX", "30"))
RATE_LIMIT_PUBLIC_CHAT_WINDOW = int(os.getenv("RATE_LIMIT_PUBLIC_CHAT_WINDOW", "60"))

RATE_LIMIT_AUTH_CHAT_MAX = int(os.getenv("RATE_LIMIT_AUTH_CHAT_MAX", "120"))
RATE_LIMIT_AUTH_CHAT_WINDOW = int(os.getenv("RATE_LIMIT_AUTH_CHAT_WINDOW", "60"))

RATE_LIMIT_CRAWL_MAX = int(os.getenv("RATE_LIMIT_CRAWL_MAX", "10"))
RATE_LIMIT_CRAWL_WINDOW = int(os.getenv("RATE_LIMIT_CRAWL_WINDOW", "3600"))

RATE_LIMIT_UPLOAD_MAX = int(os.getenv("RATE_LIMIT_UPLOAD_MAX", "20"))
RATE_LIMIT_UPLOAD_WINDOW = int(os.getenv("RATE_LIMIT_UPLOAD_WINDOW", "3600"))

RATE_LIMIT_ADMIN_MAX = int(os.getenv("RATE_LIMIT_ADMIN_MAX", "300"))
RATE_LIMIT_ADMIN_WINDOW = int(os.getenv("RATE_LIMIT_ADMIN_WINDOW", "60"))

# Lua script for atomic sliding window rate limiting
LUA_SLIDING_WINDOW_RATE_LIMIT = """
-- KEYS[1] = ratelimit_key
-- ARGV[1] = current_time (float/int seconds)
-- ARGV[2] = window_seconds
-- ARGV[3] = max_requests
-- ARGV[4] = random_suffix

local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local max_req = tonumber(ARGV[3])
local clear_before = now - window

-- 1. Remove entries outside the sliding window
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', clear_before)

-- 2. Count requests in current window
local current_requests = redis.call('ZCARD', KEYS[1])

if current_requests < max_req then
    -- Record new request
    redis.call('ZADD', KEYS[1], now, now .. '-' .. ARGV[4])
    redis.call('EXPIRE', KEYS[1], window + 10)
    return {1, 0, max_req - current_requests - 1}
else
    -- Find oldest request timestamp to calculate precise retry-after
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    local retry_after = 1
    if oldest and #oldest >= 2 then
        local oldest_time = tonumber(oldest[2])
        retry_after = math.max(1, math.ceil(oldest_time + window - now))
    end
    return {0, retry_after, 0}
end
"""

# Local in-memory sliding window fallback when Redis is unavailable
_LOCAL_WINDOWS: dict[str, list[float]] = {}


def _get_rate_limit_key(
    scope: str,
    org_id: Optional[int] = None,
    bot_id: Optional[int] = None,
    client_id: Optional[str] = None,
) -> str:
    parts = ["ratelimit", scope]
    if org_id is not None:
        parts.append(f"org_{org_id}")
    else:
        parts.append("org_global")

    if bot_id is not None:
        parts.append(f"bot_{bot_id}")

    if client_id is not None:
        sanitized_client = "".join(c for c in str(client_id) if c.isalnum() or c in ("-", "_", "."))
        parts.append(f"client_{sanitized_client}")

    return ":".join(parts)


def check_rate_limit(
    scope: str,
    org_id: Optional[int] = None,
    bot_id: Optional[int] = None,
    client_id: Optional[str] = None,
    limit: Optional[int] = None,
    window_seconds: Optional[int] = None,
) -> Tuple[bool, int, int]:
    """
    Checks rate limit using distributed Redis sliding window.
    Returns: (is_allowed: bool, retry_after_seconds: int, remaining: int)
    """
    if limit is None:
        if scope == "crawl":
            limit = RATE_LIMIT_CRAWL_MAX
            window_seconds = RATE_LIMIT_CRAWL_WINDOW
        elif scope == "upload":
            limit = RATE_LIMIT_UPLOAD_MAX
            window_seconds = RATE_LIMIT_UPLOAD_WINDOW
        elif scope == "auth_chat":
            limit = RATE_LIMIT_AUTH_CHAT_MAX
            window_seconds = RATE_LIMIT_AUTH_CHAT_WINDOW
        elif scope == "public_chat":
            limit = RATE_LIMIT_PUBLIC_CHAT_MAX
            window_seconds = RATE_LIMIT_PUBLIC_CHAT_WINDOW
        else:
            limit = RATE_LIMIT_ADMIN_MAX
            window_seconds = RATE_LIMIT_ADMIN_WINDOW

    if window_seconds is None:
        window_seconds = 60

    key = _get_rate_limit_key(scope, org_id, bot_id, client_id)
    redis_client = get_redis()

    if redis_client is not None:
        try:
            now = time.time()
            rand_suffix = str(random.randint(100000, 999999))
            res = redis_client.eval(
                LUA_SLIDING_WINDOW_RATE_LIMIT,
                1,
                key,
                now,
                window_seconds,
                limit,
                rand_suffix,
            )
            is_allowed = bool(res[0] == 1)
            retry_after = int(res[1])
            remaining = int(res[2])
            return is_allowed, retry_after, remaining
        except Exception as exc:
            logger.warning(f"Redis rate limit check error: {exc}, using in-memory fallback")

    # In-memory sliding window fallback
    now = time.time()
    cutoff = now - window_seconds
    if key not in _LOCAL_WINDOWS:
        _LOCAL_WINDOWS[key] = []

    # Clean expired
    _LOCAL_WINDOWS[key] = [t for t in _LOCAL_WINDOWS[key] if t > cutoff]

    if len(_LOCAL_WINDOWS[key]) < limit:
        _LOCAL_WINDOWS[key].append(now)
        remaining = limit - len(_LOCAL_WINDOWS[key])
        return True, 0, remaining
    else:
        oldest = _LOCAL_WINDOWS[key][0]
        retry_after = max(1, int(oldest + window_seconds - now))
        return False, retry_after, 0


def enforce_rate_limit(
    scope: str,
    org_id: Optional[int] = None,
    bot_id: Optional[int] = None,
    client_id: Optional[str] = None,
    limit: Optional[int] = None,
    window_seconds: Optional[int] = None,
) -> None:
    """Raises HTTP 429 if the rate limit is exceeded."""
    allowed, retry_after, _ = check_rate_limit(scope, org_id, bot_id, client_id, limit, window_seconds)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Rate limit exceeded. Please retry later.",
            headers={"Retry-After": str(retry_after)},
        )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Global HTTP middleware enforcing IP/client level burst and baseline limits.
    """
    def __init__(self, app, rate_limit: float = 10.0, capacity: float = 100.0):
        super().__init__(app)
        self.capacity = int(capacity)
        self.window = 60

    async def dispatch(self, request: Request, call_next):
        # Whitelisted endpoints
        if request.url.path in ("/", "/health", "/health/live", "/health/ready"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        allowed, retry_after, remaining = check_rate_limit(
            scope="http_global",
            client_id=client_ip,
            limit=self.capacity,
            window_seconds=self.window,
        )

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Rate limit exceeded. Please retry later."},
                headers={"Retry-After": str(retry_after)},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.capacity)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
