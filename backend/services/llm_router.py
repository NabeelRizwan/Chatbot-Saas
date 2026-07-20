"""
LLM Router
==========
Dispatches generation requests to the correct provider.

Key resolution order:
1. bot.provider_api_key  → BYOK (custom key, plaintext stored in bots table)
2. Platform key pool     → Admin-managed encrypted key allocated to this bot

Usage metrics are updated after every successful generation.
"""
from __future__ import annotations

from collections.abc import Iterator
from time import perf_counter

from database.models import Bot
from services.observability_service import observe_latency
from services.providers.base_provider import ProviderError
from services.providers.gemini_provider import GeminiProvider
from services.providers.openai_provider import OpenAIProvider
from services.providers.claude_provider import ClaudeProvider
from services.providers.grok_provider import GrokProvider


class LLMRouterError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


PROVIDERS = {
    "gemini": GeminiProvider(),
    "openai": OpenAIProvider(),
    "claude": ClaudeProvider(),
    "grok": GrokProvider(),
}


def _resolve_api_key(bot: Bot) -> tuple[str, bool]:
    """
    Resolve which API key to use for this bot.

    Returns:
        (api_key, is_platform_key)  — is_platform_key=True when using pool key
    """
    # Priority 1: BYOK — custom key stored on the bot
    if bot.provider_api_key and bot.provider_api_key.strip():
        return bot.provider_api_key.strip(), False

    # Priority 2: Platform-managed encrypted key allocated to this bot
    from database.connection import SessionLocal
    from services.platform_key_service import get_decrypted_key_for_bot
    with SessionLocal() as db:
        plaintext = get_decrypted_key_for_bot(db, bot.id)
        if plaintext:
            return plaintext, True

    # Priority 3: Fallback to the transitioned global key from environment/dotenv
    import os
    env_key = os.getenv("GEMINI_API_KEY")
    if env_key and env_key.strip() and (bot.provider or "").lower().strip() == "gemini":
        return env_key.strip(), False

    raise LLMRouterError(
        f"No API key available for bot '{bot.name}' on {(bot.provider or 'unknown').upper()}. "
        "Please add a custom API key or contact your admin to allocate a platform key.",
        status_code=400,
    )


def _track_usage(bot_id: int, tokens: int) -> None:
    """Increment platform key usage metrics asynchronously (best-effort)."""
    try:
        from database.connection import SessionLocal
        from services.platform_key_service import increment_usage
        with SessionLocal() as db:
            increment_usage(db, bot_id, tokens=tokens)
    except Exception:
        pass  # Non-critical — never raise from here


def generate(bot: Bot, prompt: str, system_instruction: str | None = None) -> str:
    """
    Dispatch generation to the provider configured on the bot.

    RAG stays provider-agnostic: retrieval builds the prompt, then this router
    selects the correct model SDK using the resolved API key.
    """
    provider_name = (bot.provider or "").lower().strip()
    provider = PROVIDERS.get(provider_name)

    if not provider:
        raise LLMRouterError(
            f"Unsupported provider '{bot.provider}'. Supported providers: {', '.join(sorted(PROVIDERS))}.",
            status_code=400,
        )

    api_key, is_platform_key = _resolve_api_key(bot)

    # Extract temperature from capabilities (default to 0.7)
    capabilities = bot.capabilities or {}
    temperature = float(capabilities.get("temperature", 0.7))

    try:
        started_at = perf_counter()
        result = provider.generate(
            api_key=api_key,
            model_name=bot.model_name,
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=temperature,
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        observe_latency("provider.generate_ms", elapsed_ms)

        # Update usage metrics for platform-managed keys
        if is_platform_key:
            # Rough token estimate (provider may not expose exact count here)
            estimated_tokens = max(1, len(prompt.split()) + len(result.split()))
            _track_usage(bot.id, estimated_tokens)

        return result
    except ProviderError as exc:
        raise LLMRouterError(exc.message, status_code=exc.status_code) from exc


def generate_stream(bot: Bot, prompt: str, system_instruction: str | None = None) -> Iterator[str]:
    """Streaming variant of generate(). Yields chunks as they arrive."""
    provider_name = (bot.provider or "").lower().strip()
    provider = PROVIDERS.get(provider_name)

    if not provider:
        raise LLMRouterError(
            f"Unsupported provider '{bot.provider}'. Supported providers: {', '.join(sorted(PROVIDERS))}.",
            status_code=400,
        )

    api_key, is_platform_key = _resolve_api_key(bot)

    # Extract temperature from capabilities (default to 0.7)
    capabilities = bot.capabilities or {}
    temperature = float(capabilities.get("temperature", 0.7))

    try:
        started_at = perf_counter()
        chunks_collected: list[str] = []

        for chunk in provider.generate_stream(
            api_key=api_key,
            model_name=bot.model_name,
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=temperature,
        ):
            chunks_collected.append(chunk)
            yield chunk

        elapsed_ms = int((perf_counter() - started_at) * 1000)
        observe_latency("provider.stream_ms", elapsed_ms)

        # Update usage metrics after full stream
        if is_platform_key:
            full_response = "".join(chunks_collected)
            estimated_tokens = max(1, len(prompt.split()) + len(full_response.split()))
            _track_usage(bot.id, estimated_tokens)

    except ProviderError as exc:
        raise LLMRouterError(exc.message, status_code=exc.status_code) from exc
