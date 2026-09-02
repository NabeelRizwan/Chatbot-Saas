import hashlib
import json
import logging
import math
import os
import re
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from contextvars import ContextVar
from pathlib import Path
from typing import Optional, Protocol


from dotenv import load_dotenv
from google import genai
from google.genai import types
from openai import OpenAI

from database.models import EMBEDDING_DIMENSIONS

BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")

GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"
OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
DETERMINISTIC_EMBEDDING_MODEL = "deterministic-hash-v1"

logger = logging.getLogger("backend.embedding")


class EmbeddingProviderUnavailable(RuntimeError):
    """Raised when real embeddings are required but no provider can produce them."""


class IncompatibleEmbeddingProfile(RuntimeError):
    """Raised before vector search when active knowledge mixes vector spaces."""


@dataclass(frozen=True)
class EmbeddingProfile:
    provider: str
    model: str
    version: int
    dimensions: int


def deterministic_fallback_allowed() -> bool:
    """Deterministic vectors are a local/test aid and are forbidden in production."""
    environment = (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "development").lower()
    if environment in {"production", "prod"}:
        return False
    configured = os.getenv("ALLOW_DETERMINISTIC_EMBEDDING_FALLBACK")
    return configured is None or configured.lower() in {"1", "true", "yes"}


_LAST_EMBEDDING_METADATA: ContextVar[dict[str, object]] = ContextVar(
    "last_embedding_metadata",
    default={},
)


def get_last_embedding_metadata() -> dict[str, object]:
    return dict(_LAST_EMBEDDING_METADATA.get())


class EmbeddingProvider(Protocol):
    name: str
    dimensions: int

    def embed(self, text: str) -> list[float]:
        ...


def _fallback_embedding(text: str) -> list[float]:
    """Deterministic fallback keeps dev flows alive when Gemini is not configured."""
    vector = [0.0] * EMBEDDING_DIMENSIONS
    words = text.lower().split()
    for word in words:
        digest = hashlib.sha256(word.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS
        vector[index] += 1.0

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def validate_embedding(vector: list[float]) -> list[float]:
    if len(vector) != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Embedding dimension mismatch: expected {EMBEDDING_DIMENSIONS}, received {len(vector)}"
        )
    return vector


class GeminiEmbeddingProvider:
    name = "gemini"
    dimensions = EMBEDDING_DIMENSIONS

    def __init__(self, api_key: str | None = None, model_name: str = GEMINI_EMBEDDING_MODEL):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model_name
        self._client = None
        if self.api_key and self.api_key != "your_api_key_here":
            try:
                self._client = genai.Client(api_key=self.api_key)
            except Exception:
                self._client = None

    def embed(self, text: str) -> list[float]:
        if not self._client:
            raise EmbeddingProviderUnavailable("Gemini embedding credentials are not configured.")
        result = self._client.models.embed_content(
            model=self.model_name,
            contents=text,
            config=types.EmbedContentConfig(output_dimensionality=self.dimensions),
        )
        return validate_embedding(list(result.embeddings[0].values))

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self._client:
            raise EmbeddingProviderUnavailable("Gemini embedding credentials are not configured.")
        result = self._client.models.embed_content(
            model=self.model_name,
            contents=texts,
            config=types.EmbedContentConfig(output_dimensionality=self.dimensions),
        )
        return [validate_embedding(list(emb.values)) for emb in result.embeddings]


class OpenAIEmbeddingProvider:
    name = "openai"
    dimensions = EMBEDDING_DIMENSIONS

    def __init__(self, api_key: str | None = None, model_name: str = OPENAI_EMBEDDING_MODEL):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model_name = model_name
        self._client = None
        if self.api_key:
            try:
                self._client = OpenAI(api_key=self.api_key)
            except Exception:
                self._client = None

    def embed(self, text: str) -> list[float]:
        if not self._client:
            raise EmbeddingProviderUnavailable("OpenAI embedding credentials are not configured.")
        result = self._client.embeddings.create(
            model=self.model_name,
            input=text,
            dimensions=self.dimensions,
        )
        return validate_embedding(list(result.data[0].embedding))

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self._client:
            raise EmbeddingProviderUnavailable("OpenAI embedding credentials are not configured.")
        result = self._client.embeddings.create(
            model=self.model_name,
            input=texts,
            dimensions=self.dimensions,
        )
        return [validate_embedding(list(item.embedding)) for item in result.data]


class DeterministicEmbeddingProvider:
    name = "deterministic"
    dimensions = EMBEDDING_DIMENSIONS
    model_name = DETERMINISTIC_EMBEDDING_MODEL

    def embed(self, text: str) -> list[float]:
        if not deterministic_fallback_allowed():
            raise EmbeddingProviderUnavailable("Deterministic embeddings are disabled in production.")
        return _fallback_embedding(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


_PROVIDER_INSTANCES: dict[tuple[str, str], EmbeddingProvider] = {}


def get_embedding_provider(
    provider_name: str | None = None,
    model_name: str | None = None,
) -> EmbeddingProvider:
    selected = (provider_name or os.getenv("EMBEDDING_PROVIDER") or "gemini").lower().strip()
    if selected == "openai":
        selected_model = model_name or os.getenv("OPENAI_EMBEDDING_MODEL", OPENAI_EMBEDDING_MODEL)
        cache_key = (selected, selected_model)
        if cache_key in _PROVIDER_INSTANCES:
            return _PROVIDER_INSTANCES[cache_key]
        prov = OpenAIEmbeddingProvider(model_name=selected_model)
    elif selected == "gemini":
        selected_model = model_name or os.getenv("GEMINI_EMBEDDING_MODEL", GEMINI_EMBEDDING_MODEL)
        cache_key = (selected, selected_model)
        if cache_key in _PROVIDER_INSTANCES:
            return _PROVIDER_INSTANCES[cache_key]
        prov = GeminiEmbeddingProvider(model_name=selected_model)
    elif selected == "deterministic":
        selected_model = model_name or DETERMINISTIC_EMBEDDING_MODEL
        if selected_model != DETERMINISTIC_EMBEDDING_MODEL:
            raise ValueError("Unsupported deterministic embedding model.")
        cache_key = (selected, selected_model)
        if cache_key in _PROVIDER_INSTANCES:
            return _PROVIDER_INSTANCES[cache_key]
        prov = DeterministicEmbeddingProvider()
    else:
        raise ValueError("Unsupported embedding provider. Use 'gemini', 'openai', or development-only 'deterministic'.")

    _PROVIDER_INSTANCES[cache_key] = prov
    return prov


_EMBEDDING_CACHE: dict[tuple[str, str, str], list[float]] = {}


def generate_embedding(
    text: str,
    provider_name: str | None = None,
    org_id: int | None = None,
    model_name: str | None = None,
) -> list[float]:
    """Generates one embedding; production never substitutes deterministic vectors."""
    results = generate_embeddings_batch(
        [text], provider_name=provider_name, org_id=org_id, model_name=model_name
    )
    if not results:
        raise EmbeddingProviderUnavailable("Embedding provider returned no vectors.")
    return results[0]


from services.concurrency_service import distributed_concurrency_guard

EMBEDDING_MAX_RETRIES = int(os.getenv("EMBEDDING_MAX_RETRIES", "3"))
EMBEDDING_RATE_LIMIT_MAX_RETRIES = int(os.getenv("EMBEDDING_RATE_LIMIT_MAX_RETRIES", "1"))
EMBEDDING_MAX_RETRY_DELAY_SECONDS = float(os.getenv("EMBEDDING_MAX_RETRY_DELAY_SECONDS", "30"))
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "20"))


@dataclass(frozen=True)
class EmbeddingRetryDecision:
    retryable: bool
    reason: str
    retry_after_seconds: float | None = None
    max_retries: int | None = None


def _embedding_error_status(exc: Exception) -> int | None:
    for value in (
        getattr(exc, "code", None),
        getattr(exc, "status_code", None),
        getattr(getattr(exc, "response", None), "status_code", None),
    ):
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _embedding_error_text(exc: Exception) -> str:
    values: list[object] = [
        getattr(exc, "message", None),
        getattr(exc, "details", None),
        getattr(exc, "response_json", None),
        str(exc),
    ]
    return " ".join(
        json.dumps(value, default=str) if isinstance(value, (dict, list)) else str(value)
        for value in values
        if value
    ).lower()


def _duration_seconds(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    if isinstance(value, dict):
        seconds = float(value.get("seconds", 0) or 0)
        nanos = float(value.get("nanos", 0) or 0)
        return max(0.0, seconds + nanos / 1_000_000_000)
    if isinstance(value, str):
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)s?\s*", value)
        if match:
            return float(match.group(1))
    return None


def _find_retry_delay(value: object) -> float | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower().replace("_", "")
            if normalized in {"retryafter", "retrydelay"}:
                delay = _duration_seconds(nested)
                if delay is not None:
                    return delay
            delay = _find_retry_delay(nested)
            if delay is not None:
                return delay
    elif isinstance(value, list):
        for nested in value:
            delay = _find_retry_delay(nested)
            if delay is not None:
                return delay
    return None


def _provider_retry_after_seconds(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    header_value = headers.get("retry-after") or headers.get("Retry-After")
    if header_value:
        delay = _duration_seconds(header_value)
        if delay is not None:
            return delay
        try:
            return max(0.0, parsedate_to_datetime(str(header_value)).timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            pass

    for value in (getattr(exc, "details", None), getattr(exc, "response_json", None)):
        delay = _find_retry_delay(value)
        if delay is not None:
            return delay
    return None


def classify_embedding_retry(exc: Exception) -> EmbeddingRetryDecision:
    """Classify provider errors without leaking provider payloads into user-facing errors."""
    status = _embedding_error_status(exc)
    text = _embedding_error_text(exc)
    retry_after = _provider_retry_after_seconds(exc)

    if isinstance(exc, EmbeddingProviderUnavailable):
        return EmbeddingRetryDecision(False, "provider_unavailable")

    if status == 429 or "resource_exhausted" in text or "rate limit" in text:
        non_recoverable_quota = any(
            marker in text
            for marker in (
                "requests_per_day",
                "per_day",
                "daily quota",
                "quota_value\": 0",
                "quota value: 0",
                "billing account",
                "billing disabled",
                "project restriction",
            )
        )
        if non_recoverable_quota:
            return EmbeddingRetryDecision(False, "non_recoverable_quota")

        temporary_rate_limit = retry_after is not None or any(
            marker in text
            for marker in ("per_minute", "per_second", "requests per minute", "requests per second", "rate limit")
        )
        if temporary_rate_limit:
            return EmbeddingRetryDecision(
                True,
                "temporary_rate_limit",
                retry_after_seconds=retry_after,
                max_retries=EMBEDDING_RATE_LIMIT_MAX_RETRIES,
            )
        return EmbeddingRetryDecision(False, "quota_exhausted")

    if status in {408, 500, 502, 503, 504} or any(
        marker in text for marker in ("timeout", "timed out", "temporarily unavailable", "connection reset")
    ):
        return EmbeddingRetryDecision(True, "transient_provider_error")

    if status is not None and 400 <= status < 500:
        return EmbeddingRetryDecision(False, "non_retryable_client_error")

    # Preserve bounded resilience for unknown transport/provider failures.
    return EmbeddingRetryDecision(True, "unknown_provider_error")


def generate_embeddings_batch(
    texts: list[str],
    provider_name: str | None = None,
    org_id: int | None = None,
    batch_size: int | None = None,
    model_name: str | None = None,
) -> list[list[float]]:
    """
    Batch processes texts into embedding vectors with strict order preservation,
    caching, distributed concurrency control, and retry resilience.
    """
    if not texts:
        _LAST_EMBEDDING_METADATA.set({})
        return []

    if batch_size is None:
        batch_size = EMBEDDING_BATCH_SIZE

    results: list[Optional[list[float]]] = [None] * len(texts)
    uncached_indices: list[int] = []

    selected = (provider_name or os.getenv("EMBEDDING_PROVIDER") or "gemini").lower().strip()
    selected_model = model_name or (
        os.getenv("OPENAI_EMBEDDING_MODEL", OPENAI_EMBEDDING_MODEL)
        if selected == "openai"
        else os.getenv("GEMINI_EMBEDDING_MODEL", GEMINI_EMBEDDING_MODEL)
    )

    # 1. Check in-memory cache; model identity is part of the key so vectors
    # from different spaces can never collide in process memory.
    for idx, txt in enumerate(texts):
        cache_key = (txt, selected, selected_model)
        if cache_key in _EMBEDDING_CACHE:
            results[idx] = _EMBEDDING_CACHE[cache_key]
        else:
            uncached_indices.append(idx)

    if not uncached_indices:
        _LAST_EMBEDDING_METADATA.set(
            {"provider": selected, "model": selected_model, "dimensions": EMBEDDING_DIMENSIONS, "version": 1}
        )
        return [r for r in results if r is not None]

    # 2. Acquire Concurrency Semaphore
    with distributed_concurrency_guard("embedding", org_id=org_id) as acquired:
        provider = None
        provider_error: Exception | None = None
        if acquired:
            try:
                provider = get_embedding_provider(provider_name, model_name=selected_model)
            except Exception as exc:
                provider_error = exc

        if provider is None and not deterministic_fallback_allowed():
            raise EmbeddingProviderUnavailable(
                "A real embedding provider is unavailable; deterministic fallback is disabled."
            ) from provider_error

        used_fallback = provider is None

        # 3. Process in batches
        for i in range(0, len(uncached_indices), batch_size):
            chunk_indices = uncached_indices[i : i + batch_size]
            chunk_texts = [texts[idx] for idx in chunk_indices]

            attempt = 0
            success = False
            batch_vectors: list[list[float]] = []

            while attempt <= EMBEDDING_MAX_RETRIES and not success:
                try:
                    if provider is not None:
                        if hasattr(provider, "embed_batch"):
                            batch_vectors = provider.embed_batch(chunk_texts)
                        else:
                            batch_vectors = [validate_embedding(provider.embed(t)) for t in chunk_texts]
                    else:
                        batch_vectors = [_fallback_embedding(t) for t in chunk_texts]
                    success = True
                except Exception as exc:
                    attempt += 1
                    decision = classify_embedding_retry(exc)
                    retry_limit = (
                        EMBEDDING_MAX_RETRIES
                        if decision.max_retries is None
                        else min(EMBEDDING_MAX_RETRIES, decision.max_retries)
                    )
                    delay = (
                        decision.retry_after_seconds
                        if decision.retry_after_seconds is not None
                        else min(5.0, 1.0 * (2 ** (attempt - 1))) + 0.1
                    )
                    can_retry = (
                        decision.retryable
                        and attempt <= retry_limit
                        and delay <= EMBEDDING_MAX_RETRY_DELAY_SECONDS
                    )
                    if can_retry:
                        time.sleep(delay)
                        continue

                    logger.warning(
                        "Embedding provider unavailable after bounded retry policy "
                        "(reason=%s, attempts=%s).",
                        decision.reason,
                        attempt,
                    )
                    if not deterministic_fallback_allowed():
                        raise EmbeddingProviderUnavailable(
                            "Embedding provider could not produce compatible vectors; "
                            "deterministic fallback is disabled."
                        ) from exc
                    batch_vectors = [_fallback_embedding(t) for t in chunk_texts]
                    used_fallback = True
                    success = True

            # Populate results in exact index order & cache
            for idx, vec in zip(chunk_indices, batch_vectors):
                results[idx] = vec
                cache_key = (texts[idx], selected, selected_model)
                if len(_EMBEDDING_CACHE) >= 5000:
                    _EMBEDDING_CACHE.clear()
                _EMBEDDING_CACHE[cache_key] = vec

    if any(r is None for r in results):
        if not deterministic_fallback_allowed():
            raise EmbeddingProviderUnavailable("Embedding provider returned an incomplete batch.")
        used_fallback = True

    if used_fallback:
        # Never mix deterministic and provider vectors in one persisted ingestion batch.
        for text in texts:
            _EMBEDDING_CACHE.pop((text, selected, selected_model), None)
        final_results = [_fallback_embedding(text) for text in texts]
        _LAST_EMBEDDING_METADATA.set(
            {
                "provider": "deterministic",
                "model": DETERMINISTIC_EMBEDDING_MODEL,
                "dimensions": EMBEDDING_DIMENSIONS,
                "version": 1,
            }
        )
        return final_results

    model = getattr(provider, "model_name", None) or selected_model
    _LAST_EMBEDDING_METADATA.set(
        {"provider": selected, "model": model, "dimensions": EMBEDDING_DIMENSIONS, "version": 1}
    )
    return [r for r in results if r is not None]


def resolve_active_embedding_profile(
    db,
    *,
    bot_id: int,
    organization_id: int,
) -> EmbeddingProfile:
    """Resolve one compatible vector space from the tenant's active chunks."""
    from database.models import Chunk, Document

    rows = (
        db.query(
            Chunk.embedding_provider,
            Chunk.embedding_model,
            Chunk.embedding_version,
            Document.embedding_dimensions,
        )
        .join(Document, Chunk.document_id == Document.id)
        .filter(
            Chunk.bot_id == bot_id,
            Chunk.organization_id == organization_id,
            Chunk.status == "ready",
            Document.bot_id == bot_id,
            Document.organization_id == organization_id,
            Document.status == "ready",
        )
        .distinct()
        .all()
    )
    if not rows:
        raise IncompatibleEmbeddingProfile("No active embedding profile exists for this bot.")

    profiles = {
        EmbeddingProfile(
            provider=str(provider or "gemini"),
            model=str(model or GEMINI_EMBEDDING_MODEL),
            version=int(version or 1),
            dimensions=int(dimensions or EMBEDDING_DIMENSIONS),
        )
        for provider, model, version, dimensions in rows
    }
    if len(profiles) != 1:
        raise IncompatibleEmbeddingProfile(
            "Active knowledge contains incompatible embedding profiles; build and atomically promote one compatible version."
        )
    profile = next(iter(profiles))
    if profile.dimensions != EMBEDDING_DIMENSIONS:
        raise IncompatibleEmbeddingProfile(
            f"Active embedding dimensions ({profile.dimensions}) do not match the vector index ({EMBEDDING_DIMENSIONS})."
        )
    return profile
