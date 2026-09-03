import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta
from typing import Any

from fastapi import Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import AuthRefreshSession, User

ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))
JWT_SECRET = os.getenv("JWT_SECRET") or os.getenv("SECRET_KEY") or "dev-change-me-before-production"
JWT_ISSUER = "chatbot-saas"
REFRESH_COOKIE_NAME = os.getenv("REFRESH_COOKIE_NAME", "chatbot_refresh")
REFRESH_COOKIE_SAMESITE = os.getenv("REFRESH_COOKIE_SAMESITE", "lax").lower()


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 240_000)
    return f"pbkdf2_sha256$240000${_b64url_encode(salt)}${_b64url_encode(digest)}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt_value, digest_value = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = _b64url_decode(salt_value)
        expected = _b64url_decode(digest_value)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _sign(message: str) -> str:
    signature = hmac.new(JWT_SECRET.encode("utf-8"), message.encode("ascii"), hashlib.sha256).digest()
    return _b64url_encode(signature)


def create_access_token(user: User) -> tuple[str, int]:
    expires_at = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    header = {"alg": "HS256", "typ": "JWT"}
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "email": user.email,
        "iss": JWT_ISSUER,
        "iat": int(datetime.utcnow().timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    encoded_header = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_payload = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{encoded_header}.{encoded_payload}"
    return f"{signing_input}.{_sign(signing_input)}", ACCESS_TOKEN_EXPIRE_MINUTES * 60


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        encoded_header, encoded_payload, signature = token.split(".", 2)
        signing_input = f"{encoded_header}.{encoded_payload}"
        if not hmac.compare_digest(signature, _sign(signing_input)):
            raise ValueError("Invalid signature")
        payload = json.loads(_b64url_decode(encoded_payload))
        if payload.get("iss") != JWT_ISSUER:
            raise ValueError("Invalid issuer")
        if int(payload.get("exp", 0)) < int(datetime.utcnow().timestamp()):
            raise ValueError("Token expired")
        return payload
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired authentication token") from exc


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_refresh_session(db: Session, user: User) -> str:
    refresh_token = secrets.token_urlsafe(48)
    session = AuthRefreshSession(
        user_id=user.id,
        token_hash=_hash_token(refresh_token),
        expires_at=datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(session)
    db.commit()
    return refresh_token


def rotate_refresh_session(db: Session, refresh_token: str) -> tuple[User, str]:
    token_hash = _hash_token(refresh_token)
    now = datetime.utcnow()
    candidate = (
        db.query(AuthRefreshSession)
        .filter(AuthRefreshSession.token_hash == token_hash)
        .first()
    )
    if not candidate or candidate.revoked_at is not None or candidate.expires_at < now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    # Atomic compare-and-revoke. Concurrent rotations can both read the row,
    # but only one can change revoked_at from NULL and create a successor.
    updated = (
        db.query(AuthRefreshSession)
        .filter(AuthRefreshSession.id == candidate.id)
        .filter(AuthRefreshSession.revoked_at.is_(None))
        .filter(AuthRefreshSession.expires_at > now)
        .update({AuthRefreshSession.revoked_at: now}, synchronize_session=False)
    )
    if updated != 1:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    user = db.query(User).filter(User.id == candidate.user_id, User.disabled.is_(False)).first()
    if not user:
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User session is no longer active")
    next_refresh = secrets.token_urlsafe(48)
    db.add(
        AuthRefreshSession(
            user_id=user.id,
            token_hash=_hash_token(next_refresh),
            expires_at=datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        )
    )
    db.commit()
    return user, next_refresh


def revoke_refresh_token(db: Session, refresh_token: str | None) -> bool:
    if not refresh_token:
        return False
    updated = (
        db.query(AuthRefreshSession)
        .filter(AuthRefreshSession.token_hash == _hash_token(refresh_token))
        .filter(AuthRefreshSession.revoked_at.is_(None))
        .update({AuthRefreshSession.revoked_at: datetime.utcnow()}, synchronize_session=False)
    )
    db.commit()
    return bool(updated)


def revoke_all_refresh_sessions(db: Session, user_id: int) -> int:
    revoked = (
        db.query(AuthRefreshSession)
        .filter(AuthRefreshSession.user_id == user_id)
        .filter(AuthRefreshSession.revoked_at.is_(None))
        .update({AuthRefreshSession.revoked_at: datetime.utcnow()}, synchronize_session=False)
    )
    db.commit()
    return int(revoked)


def change_password_and_rotate_current_session(
    db: Session,
    user: User,
    new_password_hash: str,
    current_refresh_token: str,
) -> tuple[str, int]:
    """Replace every refresh session after a password change with one new current-device session."""
    now = datetime.utcnow()
    current_session = (
        db.query(AuthRefreshSession)
        .filter(AuthRefreshSession.user_id == user.id)
        .filter(AuthRefreshSession.token_hash == _hash_token(current_refresh_token))
        .with_for_update()
        .first()
    )
    if (
        not current_session
        or current_session.revoked_at is not None
        or current_session.expires_at <= now
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current refresh session is invalid")

    try:
        user.password_hash = new_password_hash
        revoked = (
            db.query(AuthRefreshSession)
            .filter(AuthRefreshSession.user_id == user.id)
            .filter(AuthRefreshSession.revoked_at.is_(None))
            .update({AuthRefreshSession.revoked_at: now}, synchronize_session=False)
        )
        next_refresh = secrets.token_urlsafe(48)
        db.add(
            AuthRefreshSession(
                user_id=user.id,
                token_hash=_hash_token(next_refresh),
                expires_at=datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return next_refresh, int(revoked)


def _is_production() -> bool:
    return os.getenv("APP_ENV", "development").lower() in {"production", "prod"}


def _cookie_secure() -> bool:
    configured = os.getenv("REFRESH_COOKIE_SECURE")
    if configured is not None:
        return configured.lower() in {"1", "true", "yes"}
    return _is_production()


def set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=_cookie_secure(),
        samesite=REFRESH_COOKIE_SAMESITE,
        path="/auth",
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        httponly=True,
        secure=_cookie_secure(),
        samesite=REFRESH_COOKIE_SAMESITE,
        path="/auth",
    )


def refresh_token_from_request(request: Request, body_token: str | None = None) -> str:
    token = request.cookies.get(REFRESH_COOKIE_NAME) or body_token
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh session is required")
    return token


def _normalized_origin(value: str) -> str | None:
    from urllib.parse import urlsplit
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        scheme = parsed.scheme.lower()
        host = parsed.hostname.lower().rstrip(".")
        port = parsed.port
        default_port = 443 if scheme == "https" else 80
        return f"{scheme}://{host}{f':{port}' if port and port != default_port else ''}"
    except ValueError:
        return None


def enforce_auth_cookie_request(request: Request | None) -> None:
    if request is None:
        return
    origin_header = request.headers.get("origin")
    if not origin_header:
        return
    origin = _normalized_origin(origin_header)
    raw_allowed = os.getenv("AUTH_ALLOWED_ORIGINS") or os.getenv("FRONTEND_URL") or ""
    allowed = {
        normalized
        for value in raw_allowed.split(",")
        if (normalized := _normalized_origin(value.strip()))
    }
    if not _is_production():
        allowed.update(
            {
                "http://localhost:3000",
                "http://127.0.0.1:3000",
            }
        )
    requested_with = request.headers.get("x-requested-with")
    if not origin or origin not in allowed or requested_with != "XMLHttpRequest":
        raise HTTPException(status_code=403, detail="Unauthorized authentication origin")


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return authorization.split(" ", 1)[1].strip()


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    payload = decode_access_token(_bearer_token(authorization))
    user = db.query(User).filter(User.id == int(payload["sub"]), User.disabled.is_(False)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def get_optional_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User | None:
    if not authorization:
        return None
    return get_current_user(authorization=authorization, db=db)


def issue_token_pair(db: Session, user: User) -> tuple[dict, str]:
    access_token, expires_in = create_access_token(user)
    refresh_token = create_refresh_session(db, user)
    return {
        "access_token": access_token,
        "refresh_token": None,
        "expires_in": expires_in,
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "is_admin": bool(user.is_admin),
        },
    }, refresh_token
