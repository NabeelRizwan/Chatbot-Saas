import hashlib
import hmac
import os
import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from database.models import Bot, ConversationSession


def _is_production() -> bool:
    return os.getenv("APP_ENV", "development").lower() in {"production", "prod"}


def _origin_from_value(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError:
        return None
    default_port = 443 if scheme == "https" else 80
    port_suffix = f":{port}" if port and port != default_port else ""
    return f"{scheme}://{host}{port_suffix}"


def normalize_allowed_origins(values: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for raw in values or []:
        value = str(raw).strip()
        if not value:
            continue
        if value == "*":
            candidate = "*"
        elif "://*." in value:
            scheme, suffix = value.split("://*.", 1)
            candidate_origin = _origin_from_value(f"{scheme}://wildcard.{suffix}")
            if not candidate_origin:
                raise ValueError(f"Invalid allowed origin: {value}")
            candidate = candidate_origin.replace("://wildcard.", "://*.", 1)
        else:
            candidate = _origin_from_value(value)
            if not candidate:
                raise ValueError(
                    f"Invalid allowed origin '{value}'. Use a complete http:// or https:// origin."
                )
        if candidate not in normalized:
            normalized.append(candidate)
    return normalized


def _matches_allowed_origin(origin: str, allowed: str) -> bool:
    if allowed == "*":
        return True
    if "://*." not in allowed:
        return hmac.compare_digest(origin, allowed)
    origin_parts = urlsplit(origin)
    allowed_parts = urlsplit(allowed.replace("://*.", "://wildcard.", 1))
    if origin_parts.scheme != allowed_parts.scheme or origin_parts.port != allowed_parts.port:
        return False
    suffix = (allowed_parts.hostname or "").removeprefix("wildcard.")
    hostname = (origin_parts.hostname or "").lower()
    return bool(suffix and hostname.endswith("." + suffix) and hostname != suffix)


def request_origin(request: Request | None) -> str | None:
    if request is None:
        return None
    origin = _origin_from_value(request.headers.get("origin"))
    if origin:
        return origin
    return _origin_from_value(request.headers.get("referer"))


def enforce_public_origin(bot: Bot, request: Request | None) -> str | None:
    # Direct function calls are retained for deterministic internal tests. Real HTTP
    # requests always carry the FastAPI Request object and follow the policy below.
    if request is None:
        return None
    origin = request_origin(request)
    if origin is None:
        direct_default = "false" if _is_production() else "true"
        if os.getenv("PUBLIC_DIRECT_API_ENABLED", direct_default).lower() in {"1", "true", "yes"}:
            return None
        raise HTTPException(status_code=403, detail="Public browser origin is required")

    try:
        allowed = normalize_allowed_origins(getattr(bot, "allowed_origins", None))
    except ValueError:
        raise HTTPException(status_code=403, detail="This bot has an invalid origin policy")

    hostname = (urlsplit(origin).hostname or "").lower()
    if not _is_production() and hostname in {"localhost", "127.0.0.1", "::1"} and not allowed:
        return origin
    if any(_matches_allowed_origin(origin, candidate) for candidate in allowed):
        return origin
    raise HTTPException(status_code=403, detail="This origin is not allowed to use the widget")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_public_session(db: Session, bot: Bot) -> tuple[str, str]:
    session_id = secrets.token_urlsafe(24)
    token = secrets.token_urlsafe(32)
    session = ConversationSession(
        bot_id=bot.id,
        organization_id=bot.organization_id,
        session_id=session_id,
        public_token_hash=_token_hash(token),
        channel="widget",
    )
    db.add(session)
    db.commit()
    return session_id, token


def validate_public_session(
    db: Session,
    bot: Bot,
    session_id: str | None,
    token: str | None,
    *,
    allow_internal_test_call: bool = False,
) -> ConversationSession | None:
    if allow_internal_test_call and not session_id and not token:
        return None
    if not session_id or not token:
        raise HTTPException(status_code=401, detail="A valid widget session is required")
    session = (
        db.query(ConversationSession)
        .filter(ConversationSession.bot_id == bot.id)
        .filter(ConversationSession.session_id == session_id)
        .first()
    )
    stored_hash = getattr(session, "public_token_hash", None) if session else None
    if not stored_hash or not hmac.compare_digest(stored_hash, _token_hash(token)):
        raise HTTPException(status_code=401, detail="Invalid widget session")
    return session
