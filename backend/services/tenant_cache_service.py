import hashlib
import json
import logging
import re
import threading
import time
from time import perf_counter
from typing import Any, Callable, Dict, Optional, Tuple

from utils.redis_client import get_redis

logger = logging.getLogger("backend.tenant_cache")


class TenantSafeCache:
    """
    Enterprise Tenant-Safe Semantic & Answer Cache with:
    1. Multi-Tenant Key Scoping (org_id, bot_id, knowledge_version, model_name, query)
    2. Redis distributed storage with JSON serialization & automatic TTL
    3. Thread-safe in-memory fallback with LRU eviction
    4. Knowledge-version isolation (new version promotion immediately misses old cache)
    5. Single-flight request coalescing (prevents cache stampedes on concurrent queries)
    """

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._memory_cache: Dict[Tuple[int, int, int, str, str], Dict[str, Any]] = {}
        self._in_flight_locks: Dict[Tuple[int, int, int, str, str], threading.Lock] = {}
        self._in_flight_results: Dict[Tuple[int, int, int, str, str], Any] = {}

    def _normalize_query(self, query: str) -> str:
        text = re.sub(r"\s+", " ", query.lower()).strip()
        text = re.sub(r"[^\w\s]", "", text)
        return text

    def _build_keys(
        self,
        bot_id: int,
        query: str,
        org_id: Optional[int] = None,
        knowledge_version: int = 1,
        model_name: Optional[str] = None,
    ) -> Tuple[Tuple[int, int, int, str, str], str]:
        normalized = self._normalize_query(query)
        effective_org = int(org_id) if org_id is not None else 0
        effective_model = (model_name or "default").lower().strip()
        query_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

        mem_key = (effective_org, bot_id, knowledge_version, effective_model, normalized)
        redis_key = f"cache:rag:org_{effective_org}:bot_{bot_id}:v{knowledge_version}:{effective_model}:{query_hash}"
        return mem_key, redis_key

    def get(
        self,
        bot_id: int,
        query: str,
        org_id: Optional[int] = None,
        knowledge_version: int = 1,
        model_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Retrieves cached response from Redis or local in-memory fallback."""
        mem_key, redis_key = self._build_keys(
            bot_id=bot_id,
            query=query,
            org_id=org_id,
            knowledge_version=knowledge_version,
            model_name=model_name,
        )

        # 1. Try Redis
        try:
            r = get_redis()
            if r is not None:
                cached_str = r.get(redis_key)
                if cached_str:
                    data = json.loads(cached_str)
                    return data
        except Exception as exc:
            logger.debug(f"Redis cache get failed ({exc}), using memory cache.")

        # 2. Try In-Memory Cache
        with self._lock:
            entry = self._memory_cache.get(mem_key)
            if not entry:
                return None
            if perf_counter() - entry["timestamp"] > self.ttl_seconds:
                del self._memory_cache[mem_key]
                return None
            return entry["data"]

    def set(
        self,
        bot_id: int,
        query: str,
        data: Dict[str, Any],
        org_id: Optional[int] = None,
        knowledge_version: int = 1,
        model_name: Optional[str] = None,
    ) -> None:
        """Saves response in Redis with TTL and local in-memory cache."""
        reply = str(data.get("reply", "") or "").lower()
        if not reply or "don't have information" in reply or "trouble generating" in reply or "don't have specific" in reply:
            return

        mem_key, redis_key = self._build_keys(
            bot_id=bot_id,
            query=query,
            org_id=org_id,
            knowledge_version=knowledge_version,
            model_name=model_name,
        )

        # 1. Save to Redis
        try:
            r = get_redis()
            if r is not None:
                r.setex(redis_key, self.ttl_seconds, json.dumps(data))
        except Exception as exc:
            logger.debug(f"Redis cache set failed ({exc}), stored in memory only.")

        # 2. Save to In-Memory Cache
        with self._lock:
            if len(self._memory_cache) >= self.max_size:
                oldest_key = min(self._memory_cache.keys(), key=lambda k: self._memory_cache[k]["timestamp"])
                del self._memory_cache[oldest_key]
            self._memory_cache[mem_key] = {
                "timestamp": perf_counter(),
                "data": data,
            }

    def clear(
        self,
        bot_id: Optional[int] = None,
        org_id: Optional[int] = None,
    ) -> None:
        """Clears memory cache and Redis keys for a bot or organization."""
        with self._lock:
            if bot_id is None and org_id is None:
                self._memory_cache.clear()
            else:
                keys_to_del = [
                    k for k in self._memory_cache.keys()
                    if (bot_id is None or k[1] == bot_id) and (org_id is None or k[0] == org_id)
                ]
                for k in keys_to_del:
                    del self._memory_cache[k]

        try:
            r = get_redis()
            if r is not None:
                pattern = "cache:rag:*"
                if org_id is not None and bot_id is not None:
                    pattern = f"cache:rag:org_{org_id}:bot_{bot_id}:*"
                elif bot_id is not None:
                    pattern = f"cache:rag:*:bot_{bot_id}:*"
                elif org_id is not None:
                    pattern = f"cache:rag:org_{org_id}:*"

                keys = r.keys(pattern)
                if keys:
                    r.delete(*keys)
        except Exception:
            pass

    def single_flight_execute(
        self,
        bot_id: int,
        query: str,
        fetch_fn: Callable[[], Any],
        org_id: Optional[int] = None,
        knowledge_version: int = 1,
        model_name: Optional[str] = None,
    ) -> Any:
        """
        Coalesces concurrent requests for the exact same query into a single execution,
        preventing cache stampedes on expensive RAG generation.
        """
        mem_key, _ = self._build_keys(
            bot_id=bot_id,
            query=query,
            org_id=org_id,
            knowledge_version=knowledge_version,
            model_name=model_name,
        )

        # Check existing cache first
        cached = self.get(
            bot_id=bot_id,
            query=query,
            org_id=org_id,
            knowledge_version=knowledge_version,
            model_name=model_name,
        )
        if cached is not None:
            return cached

        # Acquire per-key single flight lock
        with self._lock:
            if mem_key not in self._in_flight_locks:
                self._in_flight_locks[mem_key] = threading.Lock()
            flight_lock = self._in_flight_locks[mem_key]

        with flight_lock:
            # Check if previous flight completed and cached
            cached = self.get(
                bot_id=bot_id,
                query=query,
                org_id=org_id,
                knowledge_version=knowledge_version,
                model_name=model_name,
            )
            if cached is not None:
                return cached

            # Execute single flight
            result = fetch_fn()
            if isinstance(result, dict) and result.get("reply"):
                self.set(
                    bot_id=bot_id,
                    query=query,
                    data=result,
                    org_id=org_id,
                    knowledge_version=knowledge_version,
                    model_name=model_name,
                )
            return result


# Global singleton
global_tenant_cache = TenantSafeCache()


def invalidate_bot_cache(bot_id: int, org_id: Optional[int] = None) -> None:
    """Invalidates cached responses for a specific bot or organization."""
    global_tenant_cache.clear(bot_id=bot_id, org_id=org_id)

