from collections.abc import Iterator
import json
import httpx
from services.providers.base_provider import (
    BaseProvider,
    GenerationResult,
    ProviderCapabilities,
    ProviderError,
    ProviderErrorKind,
    ProviderUsage,
)


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None

class ClaudeProvider(BaseProvider):
    provider_name = "claude"
    capabilities = ProviderCapabilities(streaming=True, usage_reporting=True)

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
            raise ProviderError("Claude provider API key is missing.", status_code=400, kind=ProviderErrorKind.AUTHENTICATION)

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        payload = {
            "model": model_name,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature
        }
        if system_instruction:
            payload["system"] = system_instruction

        try:
            with httpx.Client() as client:
                response = client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json=payload,
                    timeout=30.0
                )
                if response.status_code != 200:
                    kind = ProviderErrorKind.RATE_LIMIT if response.status_code == 429 else (
                        ProviderErrorKind.AUTHENTICATION if response.status_code in {401, 403} else (
                            ProviderErrorKind.BILLING_RESTRICTION if response.status_code == 402 else (
                                ProviderErrorKind.INVALID_MODEL if response.status_code == 404 else (
                                    ProviderErrorKind.TEMPORARY if response.status_code >= 500 else ProviderErrorKind.INVALID_REQUEST
                                )
                            )
                        )
                    )
                    raise ProviderError(
                        f"Anthropic API returned status {response.status_code}.",
                        status_code=response.status_code,
                        kind=kind,
                        retry_after_seconds=_retry_after(response),
                    )
                data = response.json()
                raw_usage = data.get("usage") or {}
                return GenerationResult(
                    text=data["content"][0]["text"] or "",
                    provider=self.provider_name,
                    model=model_name,
                    usage=ProviderUsage(
                        input_tokens=raw_usage.get("input_tokens"),
                        output_tokens=raw_usage.get("output_tokens"),
                    ),
                )
        except Exception as exc:
            if isinstance(exc, ProviderError):
                raise exc
            kind = ProviderErrorKind.TIMEOUT if "timeout" in str(exc).lower() else ProviderErrorKind.UNAVAILABLE
            raise ProviderError(f"Claude request failed: {exc}", status_code=502, kind=kind) from exc

    def generate_stream(
        self,
        api_key: str,
        model_name: str,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.2,
    ) -> Iterator[str]:
        if not api_key:
            raise ProviderError("Claude provider API key is missing.", status_code=400)

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        payload = {
            "model": model_name,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "stream": True
        }
        if system_instruction:
            payload["system"] = system_instruction

        try:
            with httpx.stream(
                "POST",
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
                timeout=30.0
            ) as response:
                if response.status_code != 200:
                    raise ProviderError(f"Anthropic API returned status {response.status_code}", status_code=response.status_code)

                for line in response.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            event = json.loads(data_str)
                            if event.get("type") == "content_block_delta":
                                delta = event.get("delta", {})
                                if delta.get("type") == "text_delta":
                                    yield delta.get("text", "")
                        except Exception:
                            continue
        except Exception as exc:
            if isinstance(exc, ProviderError):
                raise exc
            raise ProviderError(f"Claude request failed: {exc}", status_code=502) from exc
