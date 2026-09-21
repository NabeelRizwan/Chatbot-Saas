"""Allowlisted provider metadata only: never serialize errors, messages or headers."""
import asyncio
import json

import httpx
from google.genai import errors
from pydantic import ValidationError

STATUSES = frozenset({"INVALID_ARGUMENT", "UNAUTHENTICATED", "PERMISSION_DENIED",
    "RESOURCE_EXHAUSTED", "NOT_FOUND", "DEADLINE_EXCEEDED", "UNAVAILABLE", "INTERNAL",
    "FAILED_PRECONDITION", "CANCELLED", "UNKNOWN"})
REASONS = frozenset({"API_KEY_INVALID", "API_KEY_EXPIRED", "API_KEY_SERVICE_BLOCKED",
    "API_KEY_HTTP_REFERRER_BLOCKED", "API_KEY_IP_ADDRESS_BLOCKED", "SERVICE_DISABLED",
    "ACCESS_TOKEN_SCOPE_INSUFFICIENT", "BILLING_DISABLED", "CONSUMER_INVALID"})
CLASSES = frozenset({"APIError", "ClientError", "ServerError", "TimeoutError",
    "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout", "ConnectError",
    "ReadError", "WriteError", "RemoteProtocolError", "LocalProtocolError",
    "ValidationError", "TypeError", "AttributeError", "ValueError", "KeyError",
    "JSONDecodeError", "RuntimeError", "ImportError", "ModuleNotFoundError"})
PHASES = frozenset({"factory", "request", "cleanup", "response_usage"})


def safe_diagnostic(exc, model, phase):
    code, status, reason = None, None, None
    if isinstance(exc, errors.APIError):
        code = exc.code if type(exc.code) is int and 100 <= exc.code <= 599 else None
        status = exc.status if isinstance(exc.status, str) and exc.status in STATUSES else None
        details = exc.details if isinstance(exc.details, dict) else {}
        body = details.get("error", details)
        entries = body.get("details", []) if isinstance(body, dict) else []
        for item in entries[:16] if isinstance(entries, list) else []:
            candidate = item.get("reason") if isinstance(item, dict) else None
            if isinstance(candidate, str) and candidate in REASONS:
                reason = candidate
                break
    if code == 401 or status == "UNAUTHENTICATED" or reason in ("API_KEY_INVALID", "API_KEY_EXPIRED"):
        category = "AUTHENTICATION"
    elif code == 403 or status == "PERMISSION_DENIED" or reason in REASONS:
        category = "PERMISSION"
    elif code == 429 or status == "RESOURCE_EXHAUSTED":
        category = "QUOTA"
    elif code == 404 or status == "NOT_FOUND":
        category = "MODEL_NOT_FOUND"
    elif code in (408, 504) or isinstance(exc, (TimeoutError, asyncio.TimeoutError, httpx.TimeoutException)):
        category = "TIMEOUT"
    elif isinstance(exc, httpx.TransportError):
        category = "NETWORK"
    elif code == 400 or status == "INVALID_ARGUMENT":
        category = "INVALID_REQUEST"
    elif isinstance(exc, json.JSONDecodeError) or phase == "response_usage":
        category = "RESPONSE_PARSE"
    elif isinstance(exc, (ValidationError, TypeError, AttributeError, ImportError)):
        category = "SDK"
    else:
        category = "UNKNOWN"
    name = type(exc).__name__
    return {"provider": "gemini", "model": model if model in ("gemini-2.5-flash-lite", "gemini-3.5-flash-lite") else "OTHER",
        "exception_class": name if name in CLASSES else "OTHER",
        "http_status": code, "provider_code": status, "provider_reason": reason,
        "category": category, "phase": phase if phase in PHASES else "UNKNOWN",
        "retryable": category in ("QUOTA", "NETWORK", "TIMEOUT") or code in (500, 502, 503, 504)}
