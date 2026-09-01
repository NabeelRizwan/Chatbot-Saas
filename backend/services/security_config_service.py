from collections.abc import Mapping

from cryptography.fernet import Fernet


KNOWN_DEVELOPMENT_JWT_SECRETS = {
    "dev-change-me-before-production",
    "secret",
    "changeme",
}


def validate_production_security(environment: Mapping[str, str]) -> None:
    if environment.get("APP_ENV", "development").lower() not in {"production", "prod"}:
        return

    jwt_secret = environment.get("JWT_SECRET") or environment.get("SECRET_KEY") or ""
    if (
        not jwt_secret
        or jwt_secret.lower() in KNOWN_DEVELOPMENT_JWT_SECRETS
        or len(jwt_secret.encode("utf-8")) < 32
    ):
        raise RuntimeError(
            "JWT_SECRET must be configured with at least 32 unpredictable bytes in production."
        )

    encryption_secret = environment.get("PLATFORM_KEY_ENCRYPTION_KEY", "")
    if not encryption_secret:
        raise RuntimeError(
            "PLATFORM_KEY_ENCRYPTION_KEY is required in production for platform and BYOK credentials."
        )
    try:
        Fernet(encryption_secret.encode("ascii"))
    except Exception as exc:
        raise RuntimeError(
            "PLATFORM_KEY_ENCRYPTION_KEY is not a valid Fernet key."
        ) from exc

    access_ttl = int(environment.get("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
    if access_ttl <= 0 or access_ttl > 30:
        raise RuntimeError(
            "ACCESS_TOKEN_EXPIRE_MINUTES must be between 1 and 30 in production."
        )

    secure_cookie = environment.get("REFRESH_COOKIE_SECURE", "true").lower()
    if secure_cookie not in {"1", "true", "yes"}:
        raise RuntimeError("REFRESH_COOKIE_SECURE must be true in production.")

    same_site = environment.get("REFRESH_COOKIE_SAMESITE", "lax").lower()
    if same_site not in {"lax", "strict", "none"}:
        raise RuntimeError("REFRESH_COOKIE_SAMESITE must be lax, strict, or none.")
    if same_site == "none":
        allowed = environment.get("AUTH_ALLOWED_ORIGINS", "")
        if not allowed or "*" in {value.strip() for value in allowed.split(",")}:
            raise RuntimeError(
                "AUTH_ALLOWED_ORIGINS must be an explicit allowlist when SameSite=None."
            )
