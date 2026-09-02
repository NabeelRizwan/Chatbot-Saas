from collections.abc import Iterator
from openai import APIConnectionError, APIError, AuthenticationError, OpenAI, RateLimitError
from services.providers.base_provider import (
    BaseProvider,
    GenerationResult,
    ProviderCapabilities,
    ProviderError,
    ProviderErrorKind,
    ProviderUsage,
)

class GrokProvider(BaseProvider):
    provider_name = "grok"
    capabilities = ProviderCapabilities(streaming=True, usage_reporting=True)
    _clients: dict[str, OpenAI] = {}

    def _client(self, api_key: str) -> OpenAI:
        if api_key in self._clients:
            return self._clients[api_key]
        client = OpenAI(
            api_key=api_key,
            base_url="https://api.x.ai/v1",
            timeout=20.0,
            max_retries=0
        )
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
            raise ProviderError("Grok provider API key is missing.", status_code=400, kind=ProviderErrorKind.AUTHENTICATION)

        client = self._client(api_key)
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=temperature,
            )
            raw_usage = getattr(response, "usage", None)
            return GenerationResult(
                text=response.choices[0].message.content or "",
                provider=self.provider_name,
                model=model_name,
                usage=ProviderUsage(
                    input_tokens=getattr(raw_usage, "prompt_tokens", None),
                    output_tokens=getattr(raw_usage, "completion_tokens", None),
                ) if raw_usage is not None else None,
            )
        except RateLimitError as exc:
            raise ProviderError("xAI rate limit or quota exceeded for this bot's API key.", status_code=429, kind=ProviderErrorKind.RATE_LIMIT) from exc
        except AuthenticationError as exc:
            raise ProviderError("xAI API key for this bot is invalid or not authorized.", status_code=401, kind=ProviderErrorKind.AUTHENTICATION) from exc
        except APIConnectionError as exc:
            raise ProviderError("Could not connect to xAI.", status_code=502, kind=ProviderErrorKind.UNAVAILABLE) from exc
        except APIError as exc:
            status_code = getattr(exc, "status_code", 502) or 502
            kind = ProviderErrorKind.INVALID_MODEL if status_code == 404 else (
                ProviderErrorKind.BILLING_RESTRICTION if status_code == 402 else (
                    ProviderErrorKind.TEMPORARY if status_code >= 500 else ProviderErrorKind.INVALID_REQUEST
                )
            )
            raise ProviderError(f"xAI provider error: {exc}", status_code=status_code, kind=kind) from exc
        except Exception as exc:
            kind = ProviderErrorKind.TIMEOUT if "timeout" in str(exc).lower() else ProviderErrorKind.UNKNOWN
            raise ProviderError(f"Grok request failed: {exc}", status_code=502, kind=kind) from exc

    def generate_stream(
        self,
        api_key: str,
        model_name: str,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.2,
    ) -> Iterator[str]:
        if not api_key:
            raise ProviderError("Grok provider API key is missing.", status_code=400)

        client = self._client(api_key)
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        try:
            stream = client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=temperature,
                stream=True
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as exc:
            raise ProviderError(f"Grok request failed: {exc}", status_code=502) from exc
