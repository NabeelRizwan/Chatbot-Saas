"""Provider feedback, normalized at the HTTP boundary without extra API calls."""

from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import replace
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import wraps
import math
import re

from services.providers.base_provider import (
    GenerationResult, GenerationStreamEvent, ProviderError, ProviderErrorKind,
    ProviderFeedback, ProviderRateLimit,
)


_response_feedback: ContextVar[ProviderFeedback | None] = ContextVar("provider_response_feedback", default=None)
_MAX_DELAY = 315576000000
_MAX_COUNT = 10**15
_DURATION = re.compile(r"(?:[0-9]+(?:\.[0-9]+)?(?:ms|s|m|h|d))+")
_DURATION_PART = re.compile(r"([0-9]+(?:\.[0-9]+)?)(ms|s|m|h|d)")
_UNITS = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400}


def _number(value, *, integer=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    if isinstance(value, str) and (len(value) > 48 or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value)):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    maximum = _MAX_COUNT if integer else _MAX_DELAY
    if not math.isfinite(number) or number < 0 or number > maximum or (integer and number != int(number)):
        return None
    return int(number) if integer else number


def _date_seconds(value, now):
    if not isinstance(value, str) or len(value) > 80:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        return None
    return _number(max(0.0, (parsed - now).total_seconds()))


def _duration_seconds(value, *, now):
    number = _number(value)
    if number is not None:
        return number
    if isinstance(value, str) and len(value) <= 80 and _DURATION.fullmatch(value):
        return _number(sum(float(amount) * _UNITS[unit] for amount, unit in _DURATION_PART.findall(value)))
    return _date_seconds(value, now)


def _headers(headers):
    if not isinstance(headers, Mapping):
        return {}
    # Only known fields are subsequently read; unknown values never enter feedback.
    return {key.lower(): value for key, value in headers.items() if isinstance(key, str)}


def _request_id(headers):
    value = headers.get("x-request-id") or headers.get("request-id")
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        return None
    if value.lower().startswith(("sk-", "sk_", "aiza", "bearer", "xai-")):
        return None
    return value


def feedback_from_headers(provider: str, headers, *, now: datetime | None = None) -> ProviderFeedback | None:
    values = _headers(headers)
    now = now or datetime.now(timezone.utc)
    retry = _duration_seconds(values.get("retry-after"), now=now)
    retry_ms = _number(values.get("retry-after-ms"))
    if retry_ms is not None:
        retry = max(retry or 0.0, retry_ms / 1000.0)
    specs = []
    if provider in {"openai", "grok"}:
        # xAI's documentation does not specify header window semantics. Do not
        # turn its compatibility headers into an invented per-minute allowance.
        window = 60.0 if provider == "openai" else None
        specs = [("requests", "requests", "model", window),
                 ("tokens", "total_tokens", "model", window)]
        if provider == "openai":
            specs.append(("project-tokens", "total_tokens", "project", 60.0))
        prefix, pattern = "x-ratelimit-", "{prefix}{field}-{name}"
    elif provider == "claude":
        specs = [("requests", "requests", "model", 60.0),
                 ("input-tokens", "input_tokens", "model", 60.0),
                 ("output-tokens", "output_tokens", "model", 60.0),
                 ("tokens", "total_tokens", "model", 60.0)]
        prefix, pattern = "anthropic-ratelimit-", "{prefix}{name}-{field}"
    limits = []
    for name, dimension, scope, window in specs:
        read = lambda field: values.get(pattern.format(prefix=prefix, name=name, field=field))
        limit, remaining = _number(read("limit"), integer=True), _number(read("remaining"), integer=True)
        reset = _duration_seconds(read("reset"), now=now)
        if limit is not None or remaining is not None or reset is not None:
            limits.append(ProviderRateLimit(dimension=dimension, limit=limit, remaining=remaining,
                                           reset_after_seconds=reset, window_seconds=window, scope=scope))
    request_id = _request_id(values)
    if not limits and retry is None and request_id is None:
        return None
    return ProviderFeedback(rate_limits=tuple(limits), retry_after_seconds=retry, request_id=request_id,
                            observed_at_unix=now.timestamp())


def _quota_category(body):
    if not isinstance(body, dict):
        return None
    error = body.get("error", body)
    if not isinstance(error, dict):
        return None
    categories = {"insufficient_quota": "insufficient_quota", "billing_hard_limit_reached": "billing_restriction",
                  "billing_not_active": "billing_restriction", "rate_limit_exceeded": "rate_limit",
                  "rate_limit_error": "rate_limit"}
    for name in ("code", "type"):
        value = error.get(name)
        if isinstance(value, str) and value in categories:
            return categories[value]
    return None


def feedback_from_exception(provider: str, exc) -> ProviderFeedback | None:
    feedback = feedback_from_headers(provider, getattr(getattr(exc, "response", None), "headers", None))
    category = _quota_category(getattr(exc, "body", None))
    return replace(feedback or ProviderFeedback(observed_at_unix=datetime.now(timezone.utc).timestamp()),
                   quota_category=category) if category else feedback


def gemini_error_feedback(details: list[dict], *, headers=None) -> ProviderFeedback | None:
    feedback = feedback_from_headers("gemini", headers) or ProviderFeedback()
    limits, categories, retries = [], set(), []
    for detail in details[:32]:
        if detail.get("@type") == "type.googleapis.com/google.rpc.RetryInfo":
            value = detail.get("retryDelay")
            if isinstance(value, str) and re.fullmatch(r"[0-9]{1,12}(?:\.[0-9]{1,9})?s", value):
                seconds = _number(value[:-1])
                if seconds is not None:
                    retries.append(seconds)
        if detail.get("@type") != "type.googleapis.com/google.rpc.QuotaFailure":
            continue
        violations = detail.get("violations")
        if not isinstance(violations, list):
            continue
        for item in violations[:32]:
            if not isinstance(item, dict):
                continue
            identity = " ".join(str(item.get(field, ""))[:256] for field in ("quotaId", "quotaMetric", "quota_id", "quota_metric"))
            identity = re.sub(r"[^a-z]", "", identity.lower())
            window = 86400.0 if "perday" in identity else 60.0 if "perminute" in identity else None
            dimension = ("input_tokens" if "inputtoken" in identity else "output_tokens" if "outputtoken" in identity else
                         "total_tokens" if "token" in identity else "requests" if "request" in identity else None)
            if window == 86400:
                categories.add("daily_quota")
            elif dimension:
                categories.add({"requests": "request_rate_limit", "input_tokens": "input_token_rate_limit",
                                "output_tokens": "output_token_rate_limit", "total_tokens": "token_rate_limit"}[dimension])
            limit = _number(item.get("quotaValue", item.get("quota_value")), integer=True)
            if dimension and window is not None and limit is not None:
                if limit == 0:
                    categories.add("insufficient_quota")
                dimensions = item.get("quotaDimensions", item.get("quota_dimensions"))
                per_model = "permodel" in identity or (isinstance(dimensions, dict) and isinstance(dimensions.get("model"), str))
                limits.append(ProviderRateLimit(dimension=dimension, limit=limit, window_seconds=window,
                                               scope="project" if "perproject" in identity and not per_model else "model"))
    if feedback.retry_after_seconds is not None:
        retries.append(feedback.retry_after_seconds)
    category = ("daily_quota" if "daily_quota" in categories else
                "insufficient_quota" if "insufficient_quota" in categories else
                next(iter(categories)) if len(categories) == 1 else "rate_limit" if categories else None)
    if not limits and not retries and not category and not feedback.request_id:
        return None
    return replace(feedback, rate_limits=tuple(limits[:32]), retry_after_seconds=max(retries) if retries else None,
                   quota_category=category,
                   observed_at_unix=feedback.observed_at_unix or datetime.now(timezone.utc).timestamp())


def capture_response(provider: str, response) -> None:
    """An httpx response hook; does not read or retain the response body."""
    feedback = feedback_from_headers(provider, getattr(response, "headers", None))
    if feedback is not None:
        _response_feedback.set(feedback)


def _attach_error_feedback(provider, exc):
    feedback = exc.feedback or feedback_from_exception(provider, exc.__cause__) or _response_feedback.get()
    if feedback is not None:
        exc.feedback = feedback
        if feedback.retry_after_seconds is not None:
            exc.retry_after_seconds = max(exc.retry_after_seconds or 0.0, feedback.retry_after_seconds)
        if exc.kind == ProviderErrorKind.RATE_LIMIT:
            if feedback.quota_category in {"daily_quota", "insufficient_quota"}:
                exc.kind = ProviderErrorKind.QUOTA_EXHAUSTED
            elif feedback.quota_category == "billing_restriction":
                exc.kind = ProviderErrorKind.BILLING_RESTRICTION


def capture_generation_feedback(*, streaming=False):
    """Scope transport feedback to one call, including generators and failures."""
    def decorate(function):
        if streaming:
            @wraps(function)
            def streamed(self, *args, **kwargs):
                iterator = iter(function(self, *args, **kwargs))
                feedback = None
                try:
                    while True:
                        # Do not leave a ContextVar set while yielded to a caller:
                        # two generators can be interleaved on the same thread.
                        token = _response_feedback.set(feedback)
                        try:
                            event = next(iterator)
                            feedback = _response_feedback.get()
                            if isinstance(event, GenerationStreamEvent) and event.result and event.result.feedback is None:
                                event = replace(event, result=replace(event.result, feedback=feedback))
                        except StopIteration:
                            return
                        except ProviderError as exc:
                            _attach_error_feedback(self.provider_name, exc)
                            raise
                        finally:
                            _response_feedback.reset(token)
                        yield event
                finally:
                    close = getattr(iterator, "close", None)
                    if callable(close):
                        close()
            return streamed
        @wraps(function)
        def buffered(self, *args, **kwargs):
            token = _response_feedback.set(None)
            try:
                result = function(self, *args, **kwargs)
                if isinstance(result, GenerationResult) and result.feedback is None:
                    result = replace(result, feedback=_response_feedback.get())
                return result
            except ProviderError as exc:
                _attach_error_feedback(self.provider_name, exc)
                raise
            finally:
                _response_feedback.reset(token)
        return buffered
    return decorate
