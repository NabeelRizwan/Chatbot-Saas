import enum
import logging
import os
import random
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from services.concurrency_service import distributed_concurrency_guard
from utils.redis_client import get_redis
from utils.secret_redaction import redact_secrets

logger = logging.getLogger("backend.llm_client")

# Configuration
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "30.0"))
LLM_CONNECT_TIMEOUT = float(os.getenv("LLM_CONNECT_TIMEOUT", "5.0"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))
LLM_BACKOFF_BASE = float(os.getenv("LLM_BACKOFF_BASE", "1.0"))
LLM_BACKOFF_MAX = float(os.getenv("LLM_BACKOFF_MAX", "10.0"))
LLM_CIRCUIT_FAILURE_THRESHOLD = int(os.getenv("LLM_CIRCUIT_FAILURE_THRESHOLD", "5"))
LLM_CIRCUIT_RECOVERY_TIMEOUT = float(os.getenv("LLM_CIRCUIT_RECOVERY_TIMEOUT", "30.0"))


class LLMErrorCode(str, enum.Enum):
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_RATE_LIMITED = "LLM_RATE_LIMITED"
    LLM_PROVIDER_UNAVAILABLE = "LLM_PROVIDER_UNAVAILABLE"
    LLM_AUTH_ERROR = "LLM_AUTH_ERROR"
    LLM_INVALID_REQUEST = "LLM_INVALID_REQUEST"
    LLM_MODEL_UNAVAILABLE = "LLM_MODEL_UNAVAILABLE"
    LLM_RESPONSE_INVALID = "LLM_RESPONSE_INVALID"
    LLM_CIRCUIT_OPEN = "LLM_CIRCUIT_OPEN"
    LLM_CONCURRENCY_EXCEEDED = "LLM_CONCURRENCY_EXCEEDED"
    LLM_UNKNOWN_ERROR = "LLM_UNKNOWN_ERROR"


class CentralizedLLMError(Exception):
    def __init__(self, code: LLMErrorCode, message: str, status_code: int = 500, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable

    def customer_safe_dict(self) -> Dict[str, Any]:
        safe_messages = {
            LLMErrorCode.LLM_TIMEOUT: "AI provider took too long to generate a response. Please try again.",
            LLMErrorCode.LLM_RATE_LIMITED: "AI provider rate limit reached. Please wait a moment before trying again.",
            LLMErrorCode.LLM_PROVIDER_UNAVAILABLE: "The AI service is temporarily unavailable. Please retry shortly.",
            LLMErrorCode.LLM_AUTH_ERROR: "Authentication failure with AI provider. Please check bot credentials.",
            LLMErrorCode.LLM_INVALID_REQUEST: "The request parameters are invalid.",
            LLMErrorCode.LLM_MODEL_UNAVAILABLE: "The configured model is currently unavailable.",
            LLMErrorCode.LLM_RESPONSE_INVALID: "Received an empty or malformed response from the AI provider.",
            LLMErrorCode.LLM_CIRCUIT_OPEN: "AI service is temporarily suspended due to repeated provider outages. Retrying shortly.",
            LLMErrorCode.LLM_CONCURRENCY_EXCEEDED: "High system load: concurrent generation limit reached. Please retry in a moment.",
            LLMErrorCode.LLM_UNKNOWN_ERROR: "An error occurred while generating the AI response.",
        }
        return {
            "error_code": self.code.value,
            "detail": safe_messages.get(self.code, "AI generation failed. Please try again."),
            "status_code": self.status_code,
        }


class CircuitState(str, enum.Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """
    Provider/Model-aware circuit breaker with in-memory state and optional Redis synchronization.
    Transitions: CLOSED -> OPEN (on threshold consecutive failures) -> HALF_OPEN (after recovery timeout) -> CLOSED.
    """
    def __init__(
        self,
        failure_threshold: int = LLM_CIRCUIT_FAILURE_THRESHOLD,
        recovery_timeout: float = LLM_CIRCUIT_RECOVERY_TIMEOUT,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._states: Dict[str, Dict[str, Any]] = {}

    def _get_key(self, provider: str, model: str) -> str:
        return f"{provider.lower()}:{model.lower()}"

    def get_state(self, provider: str, model: str) -> CircuitState:
        key = self._get_key(provider, model)
        entry = self._states.get(key)
        if not entry:
            return CircuitState.CLOSED

        state = entry["state"]
        if state == CircuitState.OPEN:
            if time.time() - entry["last_failure_time"] >= self.recovery_timeout:
                entry["state"] = CircuitState.HALF_OPEN
                logger.info(f"Circuit for {key} transitioned from OPEN to HALF_OPEN (probing).")
                return CircuitState.HALF_OPEN
            return CircuitState.OPEN
        return state

    def record_success(self, provider: str, model: str) -> None:
        key = self._get_key(provider, model)
        if key in self._states:
            prev_state = self._states[key]["state"]
            self._states[key] = {
                "state": CircuitState.CLOSED,
                "failure_count": 0,
                "last_failure_time": 0.0,
            }
            if prev_state != CircuitState.CLOSED:
                logger.info(f"Circuit for {key} recovered and transitioned to CLOSED.")

    def record_failure(self, provider: str, model: str) -> None:
        key = self._get_key(provider, model)
        now = time.time()
        if key not in self._states:
            self._states[key] = {
                "state": CircuitState.CLOSED,
                "failure_count": 0,
                "last_failure_time": 0.0,
            }

        entry = self._states[key]
        entry["failure_count"] += 1
        entry["last_failure_time"] = now

        if entry["failure_count"] >= self.failure_threshold:
            entry["state"] = CircuitState.OPEN
            logger.warning(
                f"Circuit for {key} OPENED after {entry['failure_count']} consecutive failures. "
                f"Will probe in {self.recovery_timeout}s."
            )

    def is_allowed(self, provider: str, model: str) -> bool:
        state = self.get_state(provider, model)
        return state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)


# Global Circuit Breaker Singleton
global_circuit_breaker = CircuitBreaker()


def classify_exception(exc: Exception) -> Tuple[LLMErrorCode, bool, int, int]:
    """
    Classifies any raw provider exception into a standardized internal error code,
    retryability flag, HTTP status code, and retry-after delay.
    """
    from services.providers.base_provider import ProviderError, ProviderErrorKind

    if isinstance(exc, ProviderError):
        mapping = {
            ProviderErrorKind.RATE_LIMIT: (LLMErrorCode.LLM_RATE_LIMITED, True),
            ProviderErrorKind.QUOTA_EXHAUSTED: (LLMErrorCode.LLM_RATE_LIMITED, False),
            ProviderErrorKind.AUTHENTICATION: (LLMErrorCode.LLM_AUTH_ERROR, False),
            ProviderErrorKind.BILLING_RESTRICTION: (LLMErrorCode.LLM_AUTH_ERROR, False),
            ProviderErrorKind.TIMEOUT: (LLMErrorCode.LLM_TIMEOUT, True),
            ProviderErrorKind.TEMPORARY: (LLMErrorCode.LLM_PROVIDER_UNAVAILABLE, True),
            ProviderErrorKind.INVALID_MODEL: (LLMErrorCode.LLM_MODEL_UNAVAILABLE, False),
            ProviderErrorKind.INVALID_REQUEST: (LLMErrorCode.LLM_INVALID_REQUEST, False),
            ProviderErrorKind.UNAVAILABLE: (LLMErrorCode.LLM_PROVIDER_UNAVAILABLE, True),
            ProviderErrorKind.UNKNOWN: (LLMErrorCode.LLM_UNKNOWN_ERROR, False),
        }
        code, retryable = mapping.get(exc.kind, (LLMErrorCode.LLM_UNKNOWN_ERROR, False))
        retry_after = int(max(0.0, exc.retry_after_seconds or 0.0))
        return code, retryable, int(exc.status_code or 500), retry_after

    msg = str(exc).lower()
    retry_after = 0

    # Rate Limiting
    if "429" in msg or "quota" in msg or "rate limit" in msg or "resourceexhausted" in msg:
        # Check if Retry-After is specified in exception
        if "retry-after" in msg:
            try:
                import re
                match = re.search(r"retry-after[:\s]+(\d+)", msg)
                if match:
                    retry_after = int(match.group(1))
            except Exception:
                retry_after = 2
        return LLMErrorCode.LLM_RATE_LIMITED, True, 429, retry_after

    # Timeouts
    if "timeout" in msg or "timed out" in msg or "deadline" in msg:
        return LLMErrorCode.LLM_TIMEOUT, True, 504, 1

    # Authentication / Permissions (Non-retryable)
    if "401" in msg or "403" in msg or "unauthorized" in msg or "forbidden" in msg or "api_key" in msg or "invalid api key" in msg:
        return LLMErrorCode.LLM_AUTH_ERROR, False, 401, 0

    # Model not found / Unsupported (Non-retryable)
    if "404" in msg or "not found" in msg or "unsupported model" in msg or "model not found" in msg:
        return LLMErrorCode.LLM_MODEL_UNAVAILABLE, False, 404, 0

    # Malformed request / Bad parameters (Non-retryable)
    if "400" in msg or "bad request" in msg or "invalid argument" in msg:
        return LLMErrorCode.LLM_INVALID_REQUEST, False, 400, 0

    # Server / Connectivity Errors (Retryable)
    if "500" in msg or "502" in msg or "503" in msg or "504" in msg or "service unavailable" in msg or "connection reset" in msg or "connection error" in msg:
        return LLMErrorCode.LLM_PROVIDER_UNAVAILABLE, True, 503, 1

    # Default to non-retryable unknown error
    return LLMErrorCode.LLM_UNKNOWN_ERROR, False, 500, 0


def execute_with_resilience(
    generate_fn: Callable[[], str],
    provider_name: str,
    model_name: str,
    org_id: Optional[int] = None,
    max_retries: int = LLM_MAX_RETRIES,
    fallback_fn: Optional[Callable[[], str]] = None,
) -> str:
    """
    Centralized execution wrapper enforcing:
    1. Circuit breaker validation
    2. Concurrency semaphore acquisition
    3. Bounded exponential backoff with jitter
    4. Safe error classification & sanitized customer messages
    5. Automatic provider fallback if primary fails
    """
    # 1. Circuit Breaker Check
    if not global_circuit_breaker.is_allowed(provider_name, model_name):
        logger.warning(f"Request rejected by circuit breaker for {provider_name}:{model_name}.")
        if fallback_fn:
            logger.info("Invoking secondary fallback provider due to open circuit.")
            try:
                return fallback_fn()
            except Exception as f_exc:
                logger.error("Fallback provider also failed: %s", redact_secrets(f_exc))
        raise CentralizedLLMError(
            LLMErrorCode.LLM_CIRCUIT_OPEN,
            f"Provider {provider_name} is currently suspended due to repeated failures.",
            status_code=503,
            retryable=True,
        )

    # 2. Concurrency Guard Check
    with distributed_concurrency_guard("llm", org_id=org_id) as acquired:
        if not acquired:
            raise CentralizedLLMError(
                LLMErrorCode.LLM_CONCURRENCY_EXCEEDED,
                "Concurrent LLM requests exceeded tenant capacity.",
                status_code=429,
                retryable=True,
            )

        attempt = 0
        last_error = None

        while attempt <= max_retries:
            try:
                started_at = time.time()
                result = generate_fn()
                elapsed = time.time() - started_at

                if not result or not str(result).strip():
                    raise ValueError("Received empty response from AI model provider.")

                # Record success in circuit breaker
                global_circuit_breaker.record_success(provider_name, model_name)
                logger.debug(f"LLM call {provider_name}:{model_name} succeeded in {elapsed:.2f}s (attempt={attempt+1}).")
                return result

            except Exception as raw_exc:
                err_code, retryable, status_code, retry_after = classify_exception(raw_exc)
                last_error = CentralizedLLMError(
                    err_code,
                    redact_secrets(raw_exc),
                    status_code=status_code,
                    retryable=retryable,
                )

                # Record failure in circuit breaker
                global_circuit_breaker.record_failure(provider_name, model_name)

                if not retryable or attempt >= max_retries:
                    break

                # Exponential backoff with jitter
                delay = min(LLM_BACKOFF_MAX, LLM_BACKOFF_BASE * (2 ** attempt)) + random.uniform(0.1, 0.5)
                if retry_after > 0:
                    delay = max(delay, float(retry_after))

                logger.warning(
                    f"LLM {provider_name}:{model_name} attempt {attempt+1} failed with {err_code.value}. "
                    f"Retrying in {delay:.2f}s..."
                )
                time.sleep(delay)
                attempt += 1

        # If primary provider completely failed, attempt fallback if configured
        if fallback_fn:
            logger.info(f"Primary provider {provider_name} exhausted retries. Attempting fallback...")
            try:
                return fallback_fn()
            except Exception as fb_exc:
                logger.error("Fallback provider generation failed: %s", redact_secrets(fb_exc))

        if last_error:
            raise last_error
        raise CentralizedLLMError(LLMErrorCode.LLM_UNKNOWN_ERROR, "LLM generation failed.")
