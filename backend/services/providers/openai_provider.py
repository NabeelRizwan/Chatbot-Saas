from collections.abc import Iterator

from openai import APIConnectionError, APIError, AuthenticationError, OpenAI, RateLimitError

from services.providers.base_provider import BaseProvider, ProviderError


class OpenAIProvider(BaseProvider):
    provider_name = "openai"
    _clients: dict[str, OpenAI] = {}

    def _client(self, api_key: str) -> OpenAI:
        if api_key in self._clients:
            return self._clients[api_key]
        client = OpenAI(api_key=api_key, timeout=20.0, max_retries=1)
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
            raise ProviderError("OpenAI provider API key is missing.", status_code=400)

        client = self._client(api_key)
        input_messages = []
        if system_instruction:
            input_messages.append({"role": "developer", "content": system_instruction})
        input_messages.append({"role": "user", "content": prompt})

        try:
            # Latest OpenAI SDK pattern: use the Responses API for new apps.
            response = client.responses.create(
                model=model_name,
                input=input_messages,
                temperature=temperature,
            )
            return response.output_text or ""
        except RateLimitError as exc:
            raise ProviderError("OpenAI quota or rate limit exceeded for this bot's API key.", status_code=429) from exc
        except AuthenticationError as exc:
            raise ProviderError("OpenAI API key for this bot is invalid or not authorized.", status_code=401) from exc
        except APIConnectionError as exc:
            raise ProviderError("Could not connect to OpenAI.", status_code=502) from exc
        except APIError as exc:
            status_code = getattr(exc, "status_code", 502) or 502
            raise ProviderError(f"OpenAI provider error: {exc}", status_code=status_code) from exc
        except Exception as exc:
            raise ProviderError(f"OpenAI request failed: {exc}", status_code=502) from exc

    def generate_stream(
        self,
        api_key: str,
        model_name: str,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.2,
    ) -> Iterator[str]:
        if not api_key:
            raise ProviderError("OpenAI provider API key is missing.", status_code=400)
        client = self._client(api_key)
        input_messages = []
        if system_instruction:
            input_messages.append({"role": "developer", "content": system_instruction})
        input_messages.append({"role": "user", "content": prompt})

        try:
            with client.responses.stream(
                model=model_name,
                input=input_messages,
                temperature=temperature,
            ) as stream:
                for event in stream:
                    if event.type == "response.output_text.delta" and event.delta:
                        yield event.delta
        except RateLimitError as exc:
            raise ProviderError("OpenAI quota or rate limit exceeded for this bot's API key.", status_code=429) from exc
        except AuthenticationError as exc:
            raise ProviderError("OpenAI API key for this bot is invalid or not authorized.", status_code=401) from exc
        except APIConnectionError as exc:
            raise ProviderError("Could not connect to OpenAI.", status_code=502) from exc
        except APIError as exc:
            status_code = getattr(exc, "status_code", 502) or 502
            raise ProviderError(f"OpenAI provider error: {exc}", status_code=status_code) from exc
        except Exception as exc:
            raise ProviderError(f"OpenAI request failed: {exc}", status_code=502) from exc
