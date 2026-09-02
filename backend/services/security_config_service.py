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

    if environment.get("INGESTION_QUEUE_MODE", "").lower() != "arq":
        raise RuntimeError("INGESTION_QUEUE_MODE must be 'arq' in production.")

    if environment.get("ALLOW_DETERMINISTIC_EMBEDDING_FALLBACK", "").lower() not in {
        "0", "false", "no"
    }:
        raise RuntimeError("ALLOW_DETERMINISTIC_EMBEDDING_FALLBACK must be false in production.")

    if environment.get("ALLOW_LEGACY_PLAINTEXT_BYOK", "").lower() not in {"0", "false", "no"}:
        raise RuntimeError("ALLOW_LEGACY_PLAINTEXT_BYOK must be false in production.")

    cors_origins = {
        value.strip()
        for value in environment.get("CORS_ALLOWED_ORIGINS", "").split(",")
        if value.strip()
    }
    if not cors_origins or "*" in cors_origins:
        raise RuntimeError("CORS_ALLOWED_ORIGINS must be an explicit allowlist in production.")

    for required_name in ("DATABASE_URL", "REDIS_URL"):
        if not environment.get(required_name):
            raise RuntimeError(f"{required_name} is required in production.")

    crawler_provider = environment.get("CRAWLER_PROVIDER", "firecrawl").lower().strip()
    if crawler_provider != "firecrawl":
        raise RuntimeError("CRAWLER_PROVIDER must be 'firecrawl' until another crawler adapter is implemented.")

    placeholder_values = {"your_api_key_here", "changeme", "replace-me", "dummy"}
    for name in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY", "FIRECRAWL_API_KEY"):
        configured = environment.get(name, "").strip().lower()
        if configured in placeholder_values:
            raise RuntimeError(f"{name} contains a placeholder value in production.")

    from services.object_storage import validate_object_storage_config
    validate_object_storage_config(environment)
