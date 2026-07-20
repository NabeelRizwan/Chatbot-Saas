from collections.abc import Iterator
import json
import httpx
from services.providers.base_provider import BaseProvider, ProviderError

class ClaudeProvider(BaseProvider):
    provider_name = "claude"

    def generate(
        self,
        api_key: str,
        model_name: str,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.2,
    ) -> str:
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
                    raise ProviderError(f"Anthropic API returned status {response.status_code}: {response.text}", status_code=response.status_code)
                data = response.json()
                return data["content"][0]["text"] or ""
        except Exception as exc:
            if isinstance(exc, ProviderError):
                raise exc
            raise ProviderError(f"Claude request failed: {exc}", status_code=502) from exc

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
