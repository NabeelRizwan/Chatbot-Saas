import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta
from typing import Any

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import AuthRefreshSession, User

ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))
JWT_SECRET = os.getenv("JWT_SECRET") or os.getenv("SECRET_KEY") or "dev-change-me-before-production"
JWT_ISSUER = "chatbot-saas"


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
    session = (
        db.query(AuthRefreshSession)
        .filter(AuthRefreshSession.token_hash == _hash_token(refresh_token))
        .filter(AuthRefreshSession.revoked_at.is_(None))
        .first()
    )
    if not session or session.expires_at < datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")
    user = db.query(User).filter(User.id == session.user_id, User.disabled.is_(False)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User session is no longer active")
    session.revoked_at = datetime.utcnow()
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


def revoke_refresh_token(db: Session, refresh_token: str | None) -> None:
    if not refresh_token:
        return
    session = db.query(AuthRefreshSession).filter(AuthRefreshSession.token_hash == _hash_token(refresh_token)).first()
    if session and not session.revoked_at:
        session.revoked_at = datetime.utcnow()
        db.commit()


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


def token_response(db: Session, user: User) -> dict:
    access_token, expires_in = create_access_token(user)
    refresh_token = create_refresh_session(db, user)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
        "user": {"id": user.id, "name": user.name, "email": user.email},
    }
