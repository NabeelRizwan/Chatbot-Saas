from collections.abc import Iterator

from google import genai
from google.genai import errors, types

from services.providers.base_provider import (
    BaseProvider,
    GenerationResult,
    ProviderCapabilities,
    ProviderError,
    ProviderErrorKind,
    ProviderUsage,
)


class GeminiProvider(BaseProvider):
    provider_name = "gemini"
    capabilities = ProviderCapabilities(streaming=True, usage_reporting=True)
    _clients: dict[str, genai.Client] = {}

    def _client(self, api_key: str) -> genai.Client:
        if api_key in self._clients:
            return self._clients[api_key]
        # Central resilience owns retry policy. Keep the SDK to one transport
        # attempt so retries do not multiply invisibly across layers.
        retry_options = types.HttpRetryOptions(attempts=1, initialDelay=0.2, maxDelay=1.0, httpStatusCodes=[408, 429, 500, 502, 503, 504])
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
        return self.generate_with_metadata(
            api_key=api_key,
            model_name=model_name,
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=temperature,
        ).text

    def generate_with_metadata(
        self,
        api_key: str,
        model_name: str,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.2,
    ) -> GenerationResult:
        if not api_key:
            raise ProviderError(
                "Gemini provider API key is missing.",
                status_code=400,
                kind=ProviderErrorKind.AUTHENTICATION,
            )

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
            usage_metadata = getattr(response, "usage_metadata", None)
            usage = ProviderUsage(
                input_tokens=getattr(usage_metadata, "prompt_token_count", None),
                output_tokens=getattr(usage_metadata, "candidates_token_count", None),
            ) if usage_metadata is not None else None
            return GenerationResult(
                text=response.text or "",
                provider=self.provider_name,
                model=model_name,
                usage=usage,
            )
        except errors.ClientError as exc:
            status_code = getattr(exc, "status_code", 502)
            if status_code == 429:
                message = "Gemini quota exceeded for this bot's API key."
                kind = ProviderErrorKind.RATE_LIMIT
            elif status_code in (401, 403):
                message = "Gemini API key for this bot is invalid or not authorized."
                kind = ProviderErrorKind.AUTHENTICATION
            elif status_code == 404:
                message = "The configured Gemini model is unavailable."
                kind = ProviderErrorKind.INVALID_MODEL
            elif status_code == 402:
                message = "Gemini billing is not enabled for this credential."
                kind = ProviderErrorKind.BILLING_RESTRICTION
            else:
                message = f"Gemini provider error: {exc}"
                kind = ProviderErrorKind.TEMPORARY if status_code >= 500 else ProviderErrorKind.INVALID_REQUEST
            raise ProviderError(message, status_code=status_code, kind=kind) from exc
        except Exception as exc:
            kind = ProviderErrorKind.TIMEOUT if "timeout" in str(exc).lower() else ProviderErrorKind.UNAVAILABLE
            raise ProviderError(f"Gemini request failed: {exc}", status_code=502, kind=kind) from exc

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
                import time
                time.sleep(2.5)
                try:
                    for chunk in client.models.generate_content_stream(
                        model=model_name,
                        contents=prompt,
                        config=config,
                    ):
                        if chunk.text:
                            yield chunk.text
                    return
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
