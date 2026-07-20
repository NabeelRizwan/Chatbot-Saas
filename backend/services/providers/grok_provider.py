from collections.abc import Iterator
from openai import OpenAI
from services.providers.base_provider import BaseProvider, ProviderError

class GrokProvider(BaseProvider):
    provider_name = "grok"
    _clients: dict[str, OpenAI] = {}

    def _client(self, api_key: str) -> OpenAI:
        if api_key in self._clients:
            return self._clients[api_key]
        client = OpenAI(
            api_key=api_key,
            base_url="https://api.x.ai/v1",
            timeout=20.0,
            max_retries=1
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
        if not api_key:
            raise ProviderError("Grok provider API key is missing.", status_code=400)

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
            return response.choices[0].message.content or ""
        except Exception as exc:
            raise ProviderError(f"Grok request failed: {exc}", status_code=502) from exc

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
