from collections.abc import Iterator

from google import genai
from google.genai import errors, types

from services.providers.base_provider import BaseProvider, ProviderError


class GeminiProvider(BaseProvider):
    provider_name = "gemini"
    _clients: dict[str, genai.Client] = {}

    def _client(self, api_key: str) -> genai.Client:
        if api_key in self._clients:
            return self._clients[api_key]
        retry_options = types.HttpRetryOptions(attempts=2, initialDelay=0.2, maxDelay=1.0, httpStatusCodes=[408, 429, 500, 502, 503, 504])
        client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=20_000, retryOptions=retry_options))
        self._clients[api_key] = client
        return client

    def generate(
        self,
        api_key: str,
        model_name: str,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        if not api_key:
            raise ProviderError("Gemini provider API key is missing.", status_code=400)

        client = self._client(api_key)
        config = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_instruction,
        )

        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            return response.text or ""
        except errors.ClientError as exc:
            status_code = getattr(exc, "status_code", 502)
            if status_code == 429:
                import time
                time.sleep(2.0)
                try:
                    response = client.models.generate_content(model=model_name, contents=prompt, config=config)
                    return response.text or ""
                except Exception:
                    pass
                message = "Gemini quota exceeded for this bot's API key."
            elif status_code in (401, 403):
                message = "Gemini API key for this bot is invalid or not authorized."
            else:
                message = f"Gemini provider error: {exc}"
            raise ProviderError(message, status_code=status_code) from exc
        except Exception as exc:
            raise ProviderError(f"Gemini request failed: {exc}", status_code=502) from exc

    def generate_stream(
        self,
        api_key: str,
        model_name: str,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.2,
    ) -> Iterator[str]:
        if not api_key:
            raise ProviderError("Gemini provider API key is missing.", status_code=400)

        client = self._client(api_key)
        config = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_instruction,
        )

        try:
            for chunk in client.models.generate_content_stream(
                model=model_name,
                contents=prompt,
                config=config,
            ):
                if chunk.text:
                    yield chunk.text
        except errors.ClientError as exc:
            status_code = getattr(exc, "status_code", 502)
            if status_code == 429:
                message = "Gemini quota exceeded for this bot's API key."
            elif status_code in (401, 403):
                message = "Gemini API key for this bot is invalid or not authorized."
            else:
                message = f"Gemini provider error: {exc}"
            raise ProviderError(message, status_code=status_code) from exc
        except Exception as exc:
            raise ProviderError(f"Gemini request failed: {exc}", status_code=502) from exc
