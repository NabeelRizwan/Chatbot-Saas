from collections.abc import Iterator
import json
import httpx
from services.providers.rate_feedback import capture_generation_feedback, capture_response, feedback_from_headers
from services.providers.base_provider import (
    BaseProvider,
    GenerationResult,
    ProviderCapabilities,
    ProviderError,
    ProviderErrorKind,
    ProviderUsage,
    auxiliary_budget,
    generation_timeout,
)


def _retry_after(response: httpx.Response) -> float | None:
    feedback = feedback_from_headers("claude", response.headers)
    return feedback.retry_after_seconds if feedback else None

class ClaudeProvider(BaseProvider):
    provider_name = "claude"
    capabilities = ProviderCapabilities(streaming=True, usage_reporting=True)
    default_output_token_limit = 1024

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

    @capture_generation_feedback()
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
        budget = auxiliary_budget.get()
        if budget:
            payload["max_tokens"] = budget["tokens"]

        try:
            with httpx.Client() as client:
                response = client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json=payload,
                    timeout=generation_timeout(30.0)
                )
                capture_response(self.provider_name, response)
                if response.status_code != 200:
                    if response.status_code in (408, 504):
                        raise ProviderError("Claude request timed out.", status_code=response.status_code,
                                            kind=ProviderErrorKind.TIMEOUT)
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
                # Cache creation consumes input capacity. Cached reads are
                # excluded from the current Claude input-token rate limits.
                input_fields = ["input_tokens", "cache_creation_input_tokens"]
                # The documented legacy Haiku 3.5 exception also counts reads.
                if model_name.startswith("claude-3-5-haiku"):
                    input_fields.append("cache_read_input_tokens")
                input_counts = [raw_usage.get(field) for field in input_fields]
                input_counts = [count for count in input_counts if isinstance(count, int) and not isinstance(count, bool) and count >= 0]
                return GenerationResult(
                    text=data["content"][0]["text"] or "",
                    provider=self.provider_name,
                    model=model_name,
                    usage=ProviderUsage(
                        input_tokens=sum(input_counts) if input_counts else None,
                        output_tokens=raw_usage.get("output_tokens"),
                    ),
                )
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise ProviderError("Claude request timed out.", status_code=504,
                                kind=ProviderErrorKind.TIMEOUT) from exc
        except Exception as exc:
            if isinstance(exc, ProviderError):
                raise exc
            kind = ProviderErrorKind.TIMEOUT if "timeout" in str(exc).lower() else ProviderErrorKind.UNAVAILABLE
            raise ProviderError("Claude request failed.", status_code=502, kind=kind) from exc

    @capture_generation_feedback(streaming=True)
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
                capture_response(self.provider_name, response)
                if response.status_code != 200:
                    if response.status_code in (408, 504):
                        raise ProviderError("Claude request timed out.", status_code=response.status_code,
                                            kind=ProviderErrorKind.TIMEOUT)
                    kind = ProviderErrorKind.RATE_LIMIT if response.status_code == 429 else ProviderErrorKind.UNKNOWN
                    raise ProviderError(f"Anthropic API returned status {response.status_code}",
                                        status_code=response.status_code, kind=kind)

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
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise ProviderError("Claude request timed out.", status_code=504,
                                kind=ProviderErrorKind.TIMEOUT) from exc
        except Exception as exc:
            if isinstance(exc, ProviderError):
                raise exc
            raise ProviderError("Claude request failed.", status_code=502) from exc
