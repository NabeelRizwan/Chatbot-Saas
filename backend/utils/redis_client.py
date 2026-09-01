import logging
import os
import time
from typing import Optional

import redis
import redis.asyncio as aioredis

logger = logging.getLogger("backend.redis")

_REDIS_CLIENT: Optional[redis.Redis] = None
_ASYNC_REDIS_CLIENT: Optional[aioredis.Redis] = None
_REDIS_AVAILABLE: bool = False
_LAST_PING_TIME: float = 0.0
_PING_CACHE_TTL: float = 5.0  # seconds between ping checks
_OVERRIDE_CLIENT: Optional[redis.Redis] = None
_OVERRIDE_ASYNC_CLIENT: Optional[aioredis.Redis] = None


def get_redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def get_redis_socket_timeout() -> float:
    try:
        return float(os.getenv("REDIS_SOCKET_TIMEOUT", "2.0"))
    except ValueError:
        return 2.0


def set_redis_override(sync_client: Optional[redis.Redis], async_client: Optional[aioredis.Redis] = None) -> None:
    """Used by test suites to inject a mock/fakeredis instance."""
    global _OVERRIDE_CLIENT, _OVERRIDE_ASYNC_CLIENT, _REDIS_AVAILABLE
    _OVERRIDE_CLIENT = sync_client
    _OVERRIDE_ASYNC_CLIENT = async_client
    _REDIS_AVAILABLE = sync_client is not None


_LAST_CONNECT_ATTEMPT: float = 0.0
_CONNECT_COOLDOWN: float = 5.0  # seconds to wait before retrying connection to an unavailable Redis


def get_redis() -> Optional[redis.Redis]:
    """
    Returns the singleton synchronous Redis client from the connection pool.
    Returns None safely if Redis is unreachable.
    """
    global _REDIS_CLIENT, _REDIS_AVAILABLE, _LAST_PING_TIME, _LAST_CONNECT_ATTEMPT

    if _OVERRIDE_CLIENT is not None:
        return _OVERRIDE_CLIENT

    now = time.time()

    if _REDIS_CLIENT is None:
        if now - _LAST_CONNECT_ATTEMPT < _CONNECT_COOLDOWN:
            return None
        _LAST_CONNECT_ATTEMPT = now
        try:
            url = get_redis_url()
            timeout = get_redis_socket_timeout()
            pool = redis.ConnectionPool.from_url(
                url,
                socket_timeout=timeout,
                socket_connect_timeout=timeout,
                max_connections=int(os.getenv("REDIS_MAX_CONNECTIONS", "50")),
                decode_responses=True,
            )
            _REDIS_CLIENT = redis.Redis(connection_pool=pool)
            _REDIS_CLIENT.ping()
            _REDIS_AVAILABLE = True
            _LAST_PING_TIME = now
            logger.info("Connected to Redis successfully.")
        except Exception as exc:
            _REDIS_CLIENT = None
            _REDIS_AVAILABLE = False
            logger.warning(f"Redis is unavailable: {exc}")
            return None

    # Periodic health check
    if now - _LAST_PING_TIME > _PING_CACHE_TTL:
        try:
            _REDIS_CLIENT.ping()
            _REDIS_AVAILABLE = True
            _LAST_PING_TIME = now
        except Exception as exc:
            _REDIS_AVAILABLE = False
            _REDIS_CLIENT = None
            _LAST_CONNECT_ATTEMPT = now
            logger.warning(f"Redis ping failed: {exc}")
            return None

    return _REDIS_CLIENT if _REDIS_AVAILABLE else None



async def get_async_redis() -> Optional[aioredis.Redis]:
    """
    Returns the singleton async Redis client from the connection pool.
    Returns None safely if Redis is unreachable.
    """
    global _ASYNC_REDIS_CLIENT, _REDIS_AVAILABLE

    if _OVERRIDE_ASYNC_CLIENT is not None:
        return _OVERRIDE_ASYNC_CLIENT

    if _ASYNC_REDIS_CLIENT is None:
        try:
            url = get_redis_url()
            timeout = get_redis_socket_timeout()
            pool = aioredis.ConnectionPool.from_url(
                url,
                socket_timeout=timeout,
                socket_connect_timeout=timeout,
                max_connections=int(os.getenv("REDIS_MAX_CONNECTIONS", "50")),
                decode_responses=True,
            )
            _ASYNC_REDIS_CLIENT = aioredis.Redis(connection_pool=pool)
            await _ASYNC_REDIS_CLIENT.ping()
            _REDIS_AVAILABLE = True
        except Exception as exc:
            _ASYNC_REDIS_CLIENT = None
            _REDIS_AVAILABLE = False
            logger.warning(f"Async Redis is unavailable: {exc}")
            return None

    return _ASYNC_REDIS_CLIENT


def is_redis_available() -> bool:
    """Fast check for Redis availability."""
    if _OVERRIDE_CLIENT is not None:
        return True
    client = get_redis()
    return client is not None


def close_redis() -> None:
    """Closes Redis connection pools during app shutdown."""
    global _REDIS_CLIENT, _ASYNC_REDIS_CLIENT, _REDIS_AVAILABLE
    if _REDIS_CLIENT is not None:
        try:
            _REDIS_CLIENT.close()
        except Exception:
            pass
        _REDIS_CLIENT = None

    if _ASYNC_REDIS_CLIENT is not None:
        try:
            # fire and forget close
            pass
        except Exception:
            pass
        _ASYNC_REDIS_CLIENT = None

    _REDIS_AVAILABLE = False
    logger.info("Redis connections closed.")
