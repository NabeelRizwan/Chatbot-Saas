"""Explicit dev-only Gemini transport, bounded budget, no credential discovery."""
import copy
import logging
import os
import threading
from ragflow_derived.contracts import EngineError
from ragflow_derived.upstream.gemini import GeminiProvider

PROJECT = "068a5695-2cf6-4c7f-89fc-3d24a225e4a5"


class DevGemini:
    def __init__(self, provider, *, max_calls=20, provider_factory=None):
        self.provider, self.max_calls, self.provider_factory = provider, max_calls, provider_factory
        self.llm_name, self.max_length = provider.model_name, 32768
        self.calls, self.tokens, self.failures = 0, 0, 0
        self.lock = threading.Lock()

    async def async_chat(self, system, history, gen_conf=None, **kwargs):
        messages = copy.deepcopy(history)
        if system and (not messages or messages[0].get("role") != "system"):
            messages.insert(0, {"role": "system", "content": system})
        # Resource guard, not a prompt or retrieval-quality transformation.
        if len(system) + sum(len(m.get("content", "")) for m in history) > 131072:
            raise EngineError("CHAT_MODEL_UNAVAILABLE", "input budget")
        with self.lock:
            if self.calls >= self.max_calls:
                raise EngineError("CHAT_MODEL_UNAVAILABLE", "call budget")
            self.calls += 1
        try:
            # Runtime uses a fresh asyncio loop per request. Do not retain an SDK
            # async connection pool across those loops.
            provider = self.provider_factory() if self.provider_factory else self.provider
            try:
                answer, tokens = await provider._async_chat(messages, gen_conf or {}, **kwargs)
            finally:
                if self.provider_factory:
                    await provider.client.aio.aclose()
                    provider.client.close()
            with self.lock:
                self.tokens += int(tokens or 0)
            return answer
        except Exception:
            with self.lock:
                self.failures += 1
            raise EngineError("CHAT_MODEL_UNAVAILABLE", "Gemini transport") from None

    def close(self):
        if not self.provider_factory:
            self.provider.client.close()


def from_env(project_id):
    if project_id != PROJECT:
        raise EngineError("UNAUTHORIZED_SCOPE", "Gemini development project")
    key = os.environ.get("RAGFLOW_DEV_GEMINI_API_KEY", "")
    if not key:
        return None
    # No GOOGLE_API_KEY/GEMINI_API_KEY/production settings or dotenv fallback.
    from google import genai
    from google.genai import types
    for name in ("google.genai", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    def factory():
        client = genai.Client(api_key=key, vertexai=False, http_options=types.HttpOptions(
            base_url="https://generativelanguage.googleapis.com", timeout=60000,
            retry_options=types.HttpRetryOptions(attempts=1)))
        return GeminiProvider(client, "gemini-2.5-flash-lite")
    return DevGemini(GeminiProvider(None, "gemini-2.5-flash-lite"), provider_factory=factory)
