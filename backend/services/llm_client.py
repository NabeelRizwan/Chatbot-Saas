import enum
from contextlib import nullcontext
import logging
import math
import os
import random
import re
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from services.concurrency_service import distributed_concurrency_guard
from services.providers.base_provider import ProviderErrorKind, generation_deadline
from utils.redis_client import get_redis
from utils.secret_redaction import redact_secrets

logger = logging.getLogger("backend.llm_client")

# Configuration
# Retry/transport budget per generation call, excluding retrieval and planning.
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

    if isinstance(exc, CentralizedLLMError):
        return exc.code, exc.retryable, exc.status_code, 0

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
        retry_delay = max(0.0, exc.retry_after_seconds or 0.0)
        retry_after = math.ceil(retry_delay) if math.isfinite(retry_delay) else 0
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
    *,
    skip_legacy_guard: bool = False,
    can_retry: Optional[Callable[[], bool]] = None,
    attempt_admission: Optional[Callable] = None,
    remaining_budget: Optional[Callable[[], float | None]] = None,
    on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    generation_timeout_seconds: float | None = None,
) -> str:
    """
    Centralized execution wrapper enforcing:
    1. Circuit breaker validation
    2. Concurrency semaphore acquisition
    3. Bounded exponential backoff with jitter
    4. Safe error classification & sanitized customer messages
    5. Automatic provider fallback if primary fails

    Optional diagnostics emit at most 64 safe records. ``attempt_finished``
    reports one-based attempts (zero means preflight rejection), admission and
    provider time, and normalized error fields. ``retry_wait_finished`` reports
    requested and actual waiting, including interrupted waits. Callback failure
    never changes provider execution, retry eligibility, or answer delivery.
    """
    diagnostic_count = 0

    def emit(event):
        nonlocal diagnostic_count
        if on_event is None or diagnostic_count >= 64:
            return
        diagnostic_count += 1
        try:
            on_event(event)
        except Exception:
            # Diagnostics must never turn a delivered answer into a retry.
            logger.debug("Provider diagnostic callback failed.")

    def attempt_event(number, outcome, *, started=False, provider_ms=0.0,
                      admission_ms=0.0, code=None, status=None, error=None, retry_after=0):
        if on_event is None:
            return
        kind = getattr(error, "kind", None)
        feedback = getattr(error, "feedback", None)
        quota_category = getattr(feedback, "quota_category", None)
        if not isinstance(quota_category, str) or quota_category not in {"rate_limit", "daily_quota", "insufficient_quota", "billing_restriction",
                                  "request_rate_limit", "input_token_rate_limit", "output_token_rate_limit",
                                  "token_rate_limit"}:
            quota_category = None
        request_id = getattr(feedback, "request_id", None)
        if (not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id)
                or request_id.lower().startswith(("sk-", "sk_", "aiza", "bearer", "xai-"))):
            request_id = None
        original_delay = getattr(error, "retry_after_seconds", None)
        if (not isinstance(original_delay, (int, float)) or isinstance(original_delay, bool)
                or not math.isfinite(original_delay) or original_delay < 0):
            original_delay = retry_after
        emit({"event": "attempt_finished", "attempt": number, "outcome": outcome,
              "provider_started": started, "error_code": code.value if code else None,
              "status_code": status, "error_kind": kind.value if isinstance(kind, ProviderErrorKind) else None,
              "quota_category": quota_category, "request_id": request_id,
              "retry_after_seconds": original_delay,
              "provider_call_ms": round(max(0.0, provider_ms), 3),
              "admission_wait_ms": round(max(0.0, admission_ms), 3)})

    # Opt-in per-call allowance; ordinary callers retain their configured OG
    # budget. A transport timeout alone must not extend the retry budget.
    if generation_timeout_seconds is not None and (
            not isinstance(generation_timeout_seconds, (float, int))
            or isinstance(generation_timeout_seconds, bool)
            or not math.isfinite(generation_timeout_seconds)
            or not 10 <= generation_timeout_seconds <= 180):
        raise ValueError('invalid_generation_budget_timeout')
    deadline = time.monotonic() + (LLM_TIMEOUT if generation_timeout_seconds is None
                                  else generation_timeout_seconds)
    inherited_deadline = generation_deadline.get()
    if inherited_deadline is not None:
        deadline = min(deadline, inherited_deadline)
    # Gemini rejects server deadlines below ten seconds. Other adapters can
    # accept subsecond transport budgets; no short deadline is rounded up here.
    minimum_attempt = 10.0 if provider_name.lower() == "gemini" else 0.001
    # 1. Circuit Breaker Check
    if not global_circuit_breaker.is_allowed(provider_name, model_name):
        logger.warning(f"Request rejected by circuit breaker for {provider_name}:{model_name}.")
        attempt_event(0, "error", code=LLMErrorCode.LLM_CIRCUIT_OPEN, status=503)
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
    guard = nullcontext(True) if skip_legacy_guard else distributed_concurrency_guard("llm", org_id=org_id)
    with guard as acquired:
        if not acquired:
            attempt_event(0, "error", code=LLMErrorCode.LLM_CONCURRENCY_EXCEEDED, status=429)
            raise CentralizedLLMError(
                LLMErrorCode.LLM_CONCURRENCY_EXCEEDED,
                "Concurrent LLM requests exceeded tenant capacity.",
                status_code=429,
                retryable=True,
            )

        attempt = 0
        last_error = None

        while attempt <= max_retries:
            if deadline - time.monotonic() < minimum_attempt:
                if last_error:
                    raise last_error
                attempt_event(0, "error", code=LLMErrorCode.LLM_TIMEOUT, status=504)
                raise CentralizedLLMError(
                    LLMErrorCode.LLM_TIMEOUT, "AI generation retry budget was exhausted.",
                    status_code=504, retryable=True,
                )
            provider_call_started = False
            started_at = time.monotonic()
            admission_wait_ms = None
            provider_call_ms = 0.0
            try:
                admission = attempt_admission() if attempt_admission else nullcontext()
                with admission:
                    admission_wait_ms = (time.monotonic() - started_at) * 1000
                    if attempt_admission:
                        # Capacity waiting has its own bounded queue deadline.
                        # Preserve the provider's generation/retry allowance,
                        # while never extending an inherited whole-call limit.
                        deadline += time.monotonic() - started_at
                    if inherited_deadline is not None:
                        deadline = min(deadline, inherited_deadline)
                    remaining = remaining_budget() if remaining_budget else None
                    if remaining is not None:
                        deadline = min(deadline, time.monotonic() + remaining)
                    if deadline - time.monotonic() < minimum_attempt:
                        raise CentralizedLLMError(LLMErrorCode.LLM_TIMEOUT,
                            "Insufficient remaining time for the provider request.", 504, True)
                    budget_token = generation_deadline.set(deadline)
                    provider_started_at = time.monotonic()
                    try:
                        provider_call_started = True
                        result = generate_fn()
                    finally:
                        provider_call_ms = (time.monotonic() - provider_started_at) * 1000
                        generation_deadline.reset(budget_token)
                elapsed = time.monotonic() - started_at

                if not result or not str(result).strip():
                    raise ValueError("Received empty response from AI model provider.")

                # Record success in circuit breaker
                global_circuit_breaker.record_success(provider_name, model_name)
                logger.debug(f"LLM call {provider_name}:{model_name} succeeded in {elapsed:.2f}s (attempt={attempt+1}).")
                attempt_event(attempt + 1, "success", started=provider_call_started,
                              provider_ms=provider_call_ms, admission_ms=admission_wait_ms)
                return result

            except Exception as raw_exc:
                err_code, retryable, status_code, retry_after = classify_exception(raw_exc)
                attempt_event(attempt + 1, "error", started=provider_call_started,
                              provider_ms=provider_call_ms,
                              admission_ms=admission_wait_ms if admission_wait_ms is not None
                              else (time.monotonic() - started_at) * 1000,
                              code=err_code, status=status_code, error=raw_exc, retry_after=retry_after)
                last_error = CentralizedLLMError(
                    err_code,
                    redact_secrets(raw_exc),
                    status_code=status_code,
                    retryable=retryable,
                )

                turn_remaining = (remaining_budget() if retryable and
                    err_code == LLMErrorCode.LLM_RATE_LIMITED and attempt_admission and remaining_budget else None)
                queued_rate_limit = turn_remaining is not None

                # This circuit is shared across tenants. Admission failures,
                # cancellations and credential/request errors do not establish
                # a provider outage and must not suspend unrelated callers.
                if provider_call_started and err_code in {
                    LLMErrorCode.LLM_TIMEOUT,
                    LLMErrorCode.LLM_PROVIDER_UNAVAILABLE,
                }:
                    global_circuit_breaker.record_failure(provider_name, model_name)

                if retryable and retry_after > LLM_BACKOFF_MAX and not queued_rate_limit:
                    # Leave a long provider cooldown to a later request. Do
                    # not occupy a chat worker or retry before its minimum wait.
                    raise last_error from raw_exc

                if not retryable or attempt >= max_retries or (can_retry is not None and not can_retry()):
                    break

                # Exponential backoff with jitter
                delay = min(LLM_BACKOFF_MAX, LLM_BACKOFF_BASE * (2 ** attempt)) + random.uniform(0.1, 0.5)
                if retry_after > 0:
                    delay = max(delay, float(retry_after))

                # Do not spend time sleeping when a useful next attempt cannot
                # fit, and never shorten the provider's required retry wait.
                retry_budget = deadline - time.monotonic()
                if queued_rate_limit:
                    if inherited_deadline is not None:
                        turn_remaining = min(turn_remaining, inherited_deadline - time.monotonic())
                    fits = retry_budget >= minimum_attempt and delay + minimum_attempt <= turn_remaining
                else:
                    fits = delay + minimum_attempt <= retry_budget
                if not fits:
                    raise last_error from raw_exc

                logger.warning(
                    f"LLM {provider_name}:{model_name} attempt {attempt+1} failed with {err_code.value}. "
                    f"Retrying in {delay:.2f}s..."
                )
                wait_started = time.monotonic()
                wait_outcome = "interrupted"
                try:
                    if queued_rate_limit:
                        # A provider cooldown is admission waiting, not inference.
                        # Retain the unused generation budget, release the attempt
                        # lease while waiting, and check whole-turn cancellation.
                        wait_until = wait_started + delay
                        while time.monotonic() < wait_until:
                            remaining = remaining_budget()
                            if remaining is not None and inherited_deadline is not None:
                                remaining = min(remaining, inherited_deadline - time.monotonic())
                            if remaining is None or remaining < minimum_attempt:
                                raise last_error from raw_exc
                            if can_retry is not None and not can_retry():
                                raise last_error from raw_exc
                            time.sleep(max(0, min(.1, wait_until - time.monotonic())))
                        deadline += time.monotonic() - wait_started
                        if inherited_deadline is not None:
                            deadline = min(deadline, inherited_deadline)
                        remaining = remaining_budget()
                        if remaining is not None:
                            deadline = min(deadline, time.monotonic() + remaining)
                    else:
                        time.sleep(delay)
                    wait_outcome = "completed" if deadline - time.monotonic() >= minimum_attempt else "interrupted"
                finally:
                    emit({"event": "retry_wait_finished", "attempt": attempt + 1,
                          "outcome": wait_outcome, "error_code": err_code.value,
                          "reason": "provider_cooldown" if queued_rate_limit else "retry_backoff",
                          "requested_wait_ms": round(delay * 1000, 3),
                          "actual_wait_ms": round(max(0.0, time.monotonic() - wait_started) * 1000, 3)})
                attempt += 1

        # If primary provider completely failed, attempt fallback if configured
        if fallback_fn and (can_retry is None or can_retry()):
            logger.info(f"Primary provider {provider_name} exhausted retries. Attempting fallback...")
            try:
                return fallback_fn()
            except Exception as fb_exc:
                logger.error("Fallback provider generation failed: %s", redact_secrets(fb_exc))

        if last_error:
            raise last_error
        raise CentralizedLLMError(LLMErrorCode.LLM_UNKNOWN_ERROR, "LLM generation failed.")
