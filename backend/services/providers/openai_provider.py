from collections.abc import Iterator

from openai import APIConnectionError, APIError, APITimeoutError, AuthenticationError, OpenAI, RateLimitError

from services.providers.base_provider import (
    BaseProvider,
    GenerationResult,
    GenerationStreamEvent,
    ProviderCapabilities,
    ProviderError,
    ProviderErrorKind,
    ProviderUsage,
    auxiliary_budget,
    generation_deadline,
    generation_timeout,
)


class OpenAIProvider(BaseProvider):
    provider_name = "openai"
    capabilities = ProviderCapabilities(streaming=True, usage_reporting=True)
    _clients: dict[str, OpenAI] = {}

    def _client(self, api_key: str) -> OpenAI:
        if api_key in self._clients:
            return self._clients[api_key]
        client = OpenAI(api_key=api_key, timeout=20.0, max_retries=0)
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
            raise ProviderError("OpenAI provider API key is missing.", status_code=400, kind=ProviderErrorKind.AUTHENTICATION)

        client = self._client(api_key)
        input_messages = []
        if system_instruction:
            input_messages.append({"role": "developer", "content": system_instruction})
        input_messages.append({"role": "user", "content": prompt})

        options = {}
        budget = auxiliary_budget.get()
        if budget or generation_deadline.get() is not None:
            options["timeout"] = generation_timeout(20.0)
        if budget:
            options["max_output_tokens"] = budget["tokens"]

        try:
            # Latest OpenAI SDK pattern: use the Responses API for new apps.
            response = client.responses.create(
                model=model_name,
                input=input_messages,
                temperature=temperature,
                **options,
            )
            raw_usage = getattr(response, "usage", None)
            usage = ProviderUsage(
                input_tokens=getattr(raw_usage, "input_tokens", None),
                output_tokens=getattr(raw_usage, "output_tokens", None),
            ) if raw_usage is not None else None
            return GenerationResult(
                text=response.output_text or "",
                provider=self.provider_name,
                model=model_name,
                usage=usage,
            )
        except RateLimitError as exc:
            raise ProviderError("OpenAI quota or rate limit exceeded for this bot's API key.", status_code=429, kind=ProviderErrorKind.RATE_LIMIT) from exc
        except AuthenticationError as exc:
            raise ProviderError("OpenAI API key for this bot is invalid or not authorized.", status_code=401, kind=ProviderErrorKind.AUTHENTICATION) from exc
        except APITimeoutError as exc:
            raise ProviderError("OpenAI request timed out.", status_code=504, kind=ProviderErrorKind.TIMEOUT) from exc
        except APIConnectionError as exc:
            raise ProviderError("Could not connect to OpenAI.", status_code=502, kind=ProviderErrorKind.UNAVAILABLE) from exc
        except APIError as exc:
            status_code = getattr(exc, "status_code", 502) or 502
            if status_code in (408, 504):
                raise ProviderError("OpenAI request timed out.", status_code=status_code,
                                    kind=ProviderErrorKind.TIMEOUT) from exc
            kind = ProviderErrorKind.INVALID_MODEL if status_code == 404 else (
                ProviderErrorKind.BILLING_RESTRICTION if status_code == 402 else (
                    ProviderErrorKind.TEMPORARY if status_code >= 500 else ProviderErrorKind.INVALID_REQUEST
                )
            )
            raise ProviderError(f"OpenAI provider error: {exc}", status_code=status_code, kind=kind) from exc
        except Exception as exc:
            kind = ProviderErrorKind.TIMEOUT if "timeout" in str(exc).lower() else ProviderErrorKind.UNKNOWN
            raise ProviderError(f"OpenAI request failed: {exc}", status_code=502, kind=kind) from exc

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
        except APITimeoutError as exc:
            raise ProviderError("OpenAI request timed out.", status_code=504, kind=ProviderErrorKind.TIMEOUT) from exc
        except APIConnectionError as exc:
            raise ProviderError("Could not connect to OpenAI.", status_code=502) from exc
        except APIError as exc:
            status_code = getattr(exc, "status_code", 502) or 502
            if status_code in (408, 504):
                raise ProviderError("OpenAI request timed out.", status_code=status_code,
                                    kind=ProviderErrorKind.TIMEOUT) from exc
            raise ProviderError(f"OpenAI provider error: {exc}", status_code=status_code) from exc
        except Exception as exc:
            raise ProviderError(f"OpenAI request failed: {exc}", status_code=502) from exc

    def generate_stream_with_metadata(
        self, api_key: str, model_name: str, prompt: str,
        system_instruction: str | None = None, temperature: float = 0.2,
    ) -> Iterator[GenerationStreamEvent]:
        if not api_key:
            raise ProviderError('OpenAI provider API key is missing.', status_code=400,
                                kind=ProviderErrorKind.AUTHENTICATION)
        client = self._client(api_key)
        messages = ([{'role': 'developer', 'content': system_instruction}] if system_instruction else [])
        messages.append({'role': 'user', 'content': prompt})
        options = {}
        budget = auxiliary_budget.get()
        if budget or generation_deadline.get() is not None:
            options['timeout'] = generation_timeout(20.0)
        if budget:
            options['max_output_tokens'] = budget['tokens']
        try:
            with client.responses.stream(model=model_name, input=messages, temperature=temperature, **options) as stream:
                completed = False
                for event in stream:
                    if event.type == 'response.output_text.delta' and event.delta:
                        yield GenerationStreamEvent(delta=event.delta)
                    elif event.type == 'response.completed':
                        completed = True
                    elif event.type in {'error', 'response.error', 'response.failed', 'response.incomplete'}:
                        raise ProviderError('OpenAI did not complete the answer stream.', status_code=502,
                                            kind=ProviderErrorKind.INVALID_REQUEST)
                if not completed:
                    raise ProviderError('OpenAI answer stream ended before completion.', status_code=502,
                                        kind=ProviderErrorKind.UNAVAILABLE)
                response = stream.get_final_response()
                if response.status != 'completed':
                    raise ProviderError('OpenAI did not complete the answer stream.', status_code=502,
                                        kind=ProviderErrorKind.INVALID_REQUEST)
                raw_usage = getattr(response, 'usage', None)
                usage = ProviderUsage(input_tokens=getattr(raw_usage, 'input_tokens', None),
                                      output_tokens=getattr(raw_usage, 'output_tokens', None)) if raw_usage else None
                yield GenerationStreamEvent(result=GenerationResult(
                    text=response.output_text or '', provider=self.provider_name,
                    model=model_name, usage=usage, finish_reason='completed'))
        except ProviderError:
            raise
        except RateLimitError as exc:
            raise ProviderError("OpenAI quota or rate limit exceeded for this bot's API key.", status_code=429,
                                kind=ProviderErrorKind.RATE_LIMIT) from exc
        except AuthenticationError as exc:
            raise ProviderError('OpenAI API key for this bot is invalid or not authorized.', status_code=401,
                                kind=ProviderErrorKind.AUTHENTICATION) from exc
        except APITimeoutError as exc:
            raise ProviderError('OpenAI request timed out.', status_code=504, kind=ProviderErrorKind.TIMEOUT) from exc
        except APIConnectionError as exc:
            raise ProviderError('Could not connect to OpenAI.', status_code=502, kind=ProviderErrorKind.UNAVAILABLE) from exc
        except APIError as exc:
            status = getattr(exc, 'status_code', 502) or 502
            kind = (ProviderErrorKind.TIMEOUT if status in (408, 504) else
                    ProviderErrorKind.INVALID_MODEL if status == 404 else
                    ProviderErrorKind.BILLING_RESTRICTION if status == 402 else
                    ProviderErrorKind.TEMPORARY if status >= 500 else ProviderErrorKind.INVALID_REQUEST)
            raise ProviderError('OpenAI provider request failed.', status_code=status, kind=kind) from exc
        except Exception as exc:
            kind = ProviderErrorKind.TIMEOUT if 'timeout' in str(exc).lower() else ProviderErrorKind.UNKNOWN
            raise ProviderError('OpenAI request failed.', status_code=502, kind=kind) from exc
