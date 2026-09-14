"""Safe, structured error outcomes. No credentials, raw exception text or calls."""
import re


TEMPORARY_SERVICE_REPLY = "I'm having trouble responding right now. Please try again shortly."


def provider_failure(exc, stage, bot=None):
    chain, seen = [], set()
    while exc is not None and id(exc) not in seen and len(chain) < 5:
        seen.add(id(exc))
        chain.append(exc)
        exc = exc.__cause__ or exc.__context__
    # Inspect only in memory. Never serialize free-form exceptions/project IDs.
    message = " ".join(str(e).lower() for e in chain)
    codes = " ".join(str(getattr(e, "code", "")) + " " + str(getattr(e, "kind", "")) for e in chain).lower()
    if "perday" in message or "daily" in message:
        category = "daily_quota"
    elif "perminute" in message or "minute quota" in message:
        category = "minute_quota"
    elif "circuit" in codes + message:
        category = "circuit_open"
    elif "429" in message or "resource_exhausted" in message or "rate_limit" in codes or "quota_exhausted" in codes or "rate limit" in message:
        category = "rate_limit"
    elif any(isinstance(e, TimeoutError) for e in chain) or "timeout" in codes + message or "timed out" in message:
        category = "timeout"
    elif "authentication" in codes or "auth_error" in codes or any(getattr(e, "status_code", None) in (401, 403) for e in chain):
        category = "authentication"
    elif "invalid_model" in codes or "model_unavailable" in codes:
        category = "invalid_model"
    elif "response_invalid" in codes or "empty_generation" in codes + message:
        category = "empty_generation"
    elif "unavailable" in codes or any(getattr(e, "status_code", None) in (502, 503, 504) for e in chain):
        category = "provider_unavailable"
    else:
        category = "unknown_provider_error"
    provider = getattr(bot, "provider", None)
    provider = provider if provider in {"gemini", "openai", "claude", "grok"} else "unknown"
    model = str(getattr(bot, "model_name", "") or "")
    # Configured model names only, never arbitrary diagnostic identifiers.
    model = model if re.fullmatch(r"(?:gemini|gpt|o[134]|claude|grok)[a-zA-Z0-9._:-]{0,75}", model) else None
    retryable = next((getattr(e, "retryable") for e in chain if isinstance(getattr(e, "retryable", None), bool)), None)
    if category == "daily_quota":
        retryable = False
    return {"stage": stage, "category": category, "provider": provider, "model": model, "retryable": retryable}
