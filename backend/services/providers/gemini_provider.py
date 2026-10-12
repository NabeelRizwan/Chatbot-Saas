from collections.abc import Iterator
import math
import re
import httpx

from google import genai
from google.genai import errors, types
from services.providers.generation_input import gemini_contents
from services.providers.rate_feedback import (
    capture_generation_feedback, capture_response, gemini_error_feedback,
)

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


def _api_error_details(exc: errors.APIError) -> list[dict]:
    payload = getattr(exc, "details", None)
    if not isinstance(payload, dict):
        return []
    error = payload.get("error", payload)
    details = error.get("details", []) if isinstance(error, dict) else []
    return [detail for detail in details if isinstance(detail, dict)] if isinstance(details, list) else []


def _usage(metadata) -> ProviderUsage | None:
    if metadata is None:
        return None
    generated = getattr(metadata, "candidates_token_count", None)
    thoughts = getattr(metadata, "thoughts_token_count", None)
    output_counts = [count for count in (generated, thoughts) if isinstance(count, int) and not isinstance(count, bool) and count >= 0]
    # Gemini reports thinking separately; it still consumed generation capacity.
    return ProviderUsage(input_tokens=getattr(metadata, "prompt_token_count", None),
                         output_tokens=sum(output_counts) if output_counts else None)


def _daily_quota_exhausted(details: list[dict]) -> bool:
    for detail in details:
        if detail.get("@type") != "type.googleapis.com/google.rpc.QuotaFailure":
            continue
        violations = detail.get("violations", [])
        if not isinstance(violations, list):
            continue
        for violation in violations:
            if not isinstance(violation, dict):
                continue
            # QuotaFailure includes RPM as well as daily limits. Only the
            # structured limit identity establishes daily exhaustion.
            for field in ("quotaId", "quotaMetric", "quota_id", "quota_metric"):
                value = violation.get(field)
                if isinstance(value, str) and "perday" in re.sub(r"[^a-z]", "", value.lower()):
                    return True
    return False


def _retry_after_seconds(exc: errors.APIError, details: list[dict]) -> int | None:
    delays = []
    for detail in details:
        if detail.get("@type") == "type.googleapis.com/google.rpc.RetryInfo":
            value = detail.get("retryDelay")
            # Protobuf Duration's JSON form is a seconds string, with at most
            # nine fractional digits. Reject malformed and negative delays.
            if isinstance(value, str) and re.fullmatch(r"[0-9]{1,12}(?:\.[0-9]{1,9})?s", value):
                delays.append(float(value[:-1]))
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers is not None:
        value = headers.get("retry-after")
        if isinstance(value, str) and re.fullmatch(r"[0-9]{1,12}(?:\.[0-9]{1,9})?", value):
            delays.append(float(value))
    delays = [delay for delay in delays if math.isfinite(delay) and 0 <= delay <= 315576000000]
    # The shared retry classifier uses integer seconds. Round up, never below
    # the provider's minimum wait, and prefer the longer hint if both exist.
    return math.ceil(max(delays)) if delays else None


def _map_api_error(exc: errors.APIError) -> ProviderError:
    status_code = 502
    for value in (getattr(exc, "code", None), getattr(exc, "status_code", None)):
        if isinstance(value, int) and not isinstance(value, bool) and 400 <= value <= 599:
            status_code = value
            break
    details = _api_error_details(exc)
    feedback = gemini_error_feedback(details, headers=getattr(getattr(exc, "response", None), "headers", None))
    if status_code == 429:
        daily_exhausted = _daily_quota_exhausted(details)
        exhausted = daily_exhausted or (feedback is not None and feedback.quota_category == "insufficient_quota")
        kind = ProviderErrorKind.QUOTA_EXHAUSTED if exhausted else ProviderErrorKind.RATE_LIMIT
        message = ("Gemini daily quota is exhausted for this bot's credential." if daily_exhausted else
                   "Gemini reports no quota allowance for this bot's credential." if exhausted else
                   "Gemini rate limit exceeded for this bot's credential.")
    elif status_code in (401, 403):
        kind, message = ProviderErrorKind.AUTHENTICATION, "Gemini API key for this bot is invalid or not authorized."
    elif status_code == 404:
        kind, message = ProviderErrorKind.INVALID_MODEL, "The configured Gemini model is unavailable."
    elif status_code == 402:
        kind, message = ProviderErrorKind.BILLING_RESTRICTION, "Gemini billing is not enabled for this credential."
    elif status_code in (408, 504):
        kind, message = ProviderErrorKind.TIMEOUT, "Gemini request timed out."
    elif status_code >= 500:
        kind, message = ProviderErrorKind.TEMPORARY, "Gemini is temporarily unavailable."
    else:
        kind, message = ProviderErrorKind.INVALID_REQUEST, "Gemini rejected the request."
    return ProviderError(message, status_code=status_code, kind=kind,
                         retry_after_seconds=_retry_after_seconds(exc, details),
                         feedback=feedback)


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
        budget = auxiliary_budget.get()
        if budget or generation_deadline.get() is not None:
            config.http_options = types.HttpOptions(
                timeout=int(generation_timeout(20.0, minimum=10.0) * 1000))
        if budget:
            # Gemini rejects server deadlines below ten seconds. The router's
            # shorter caller deadline still bounds chat; outstanding transports
            # retain their bounded executor slot until this deadline expires.
            config.max_output_tokens = budget["tokens"]
            if budget.get('json_mode', True):
                config.response_mime_type = "application/json"
            if model_name.startswith("gemini-2.5-flash"):
                config.thinking_config = types.ThinkingConfig(thinking_budget=0)

        try:
            response = client.models.generate_content(
                model=model_name,
                contents=gemini_contents(prompt, config),
                config=config,
            )
            capture_response(self.provider_name, getattr(response, "sdk_http_response", None))
            usage_metadata = getattr(response, "usage_metadata", None)
            usage = _usage(usage_metadata)
            candidates = getattr(response, 'candidates', None) or []
            reason = getattr(candidates[0], 'finish_reason', None) if candidates else None
            # SDK enum only, not provider free text; missing metadata stays unknown.
            finish_reason = reason.name if isinstance(reason, types.FinishReason) else None
            return GenerationResult(
                text=response.text or "",
                provider=self.provider_name,
                model=model_name,
                usage=usage,
                finish_reason=finish_reason,
            )
        except errors.APIError as exc:
            raise _map_api_error(exc) from exc
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise ProviderError("Gemini request timed out.", status_code=504,
                                kind=ProviderErrorKind.TIMEOUT) from exc
        except Exception as exc:
            kind = ProviderErrorKind.TIMEOUT if "timeout" in str(exc).lower() else ProviderErrorKind.UNAVAILABLE
            raise ProviderError("Gemini request failed.", status_code=502, kind=kind) from exc

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
            raise ProviderError("Gemini provider API key is missing.", status_code=400,
                                kind=ProviderErrorKind.AUTHENTICATION)

        client = self._client(api_key)
        config = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_instruction,
        )

        try:
            for chunk in client.models.generate_content_stream(
                model=model_name,
                contents=gemini_contents(prompt, config),
                config=config,
            ):
                capture_response(self.provider_name, getattr(chunk, "sdk_http_response", None))
                if chunk.text:
                    yield chunk.text
        except errors.APIError as exc:
            raise _map_api_error(exc) from exc
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise ProviderError("Gemini request timed out.", status_code=504,
                                kind=ProviderErrorKind.TIMEOUT) from exc
        except Exception as exc:
            kind = ProviderErrorKind.TIMEOUT if "timeout" in str(exc).lower() else ProviderErrorKind.UNAVAILABLE
            raise ProviderError("Gemini request failed.", status_code=502, kind=kind) from exc

    @capture_generation_feedback(streaming=True)
    def generate_stream_with_metadata(
        self, api_key: str, model_name: str, prompt: str,
        system_instruction: str | None = None, temperature: float = 0.2,
    ) -> Iterator[GenerationStreamEvent]:
        if not api_key:
            raise ProviderError('Gemini provider API key is missing.', status_code=400,
                                kind=ProviderErrorKind.AUTHENTICATION)
        client = self._client(api_key)
        config = types.GenerateContentConfig(temperature=temperature, system_instruction=system_instruction)
        budget = auxiliary_budget.get()
        if budget or generation_deadline.get() is not None:
            config.http_options = types.HttpOptions(
                timeout=int(generation_timeout(20.0, minimum=10.0) * 1000))
        if budget:
            config.max_output_tokens = budget['tokens']
            if budget.get('json_mode', True):
                config.response_mime_type = 'application/json'
            if model_name.startswith('gemini-2.5-flash'):
                config.thinking_config = types.ThinkingConfig(thinking_budget=0)
        stream = None
        try:
            stream = client.models.generate_content_stream(model=model_name, contents=gemini_contents(prompt, config), config=config)
            parts, usage, finish_reason = [], None, None
            for chunk in stream:
                capture_response(self.provider_name, getattr(chunk, "sdk_http_response", None))
                metadata = getattr(chunk, 'usage_metadata', None)
                if metadata is not None:
                    # Chunk metadata is cumulative, so retain the latest values.
                    usage = _usage(metadata)
                candidates = getattr(chunk, 'candidates', None) or []
                reason = getattr(candidates[0], 'finish_reason', None) if candidates else None
                if isinstance(reason, types.FinishReason) and reason != types.FinishReason.FINISH_REASON_UNSPECIFIED:
                    finish_reason = reason.name
                # The SDK text accessor excludes thought parts and non-text data.
                text = chunk.text or ''
                if text:
                    parts.append(text)
                    yield GenerationStreamEvent(delta=text)
            if finish_reason != 'STOP':
                raise ProviderError('Gemini did not complete the answer stream.', status_code=502,
                                    kind=ProviderErrorKind.INVALID_REQUEST)
            yield GenerationStreamEvent(result=GenerationResult(
                text=''.join(parts), provider=self.provider_name, model=model_name,
                usage=usage, finish_reason=finish_reason))
        except ProviderError:
            raise
        except errors.APIError as exc:
            raise _map_api_error(exc) from exc
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise ProviderError('Gemini request timed out.', status_code=504,
                                kind=ProviderErrorKind.TIMEOUT) from exc
        except Exception as exc:
            kind = ProviderErrorKind.TIMEOUT if 'timeout' in str(exc).lower() else ProviderErrorKind.UNAVAILABLE
            raise ProviderError('Gemini request failed.', status_code=502, kind=kind) from exc
        finally:
            if stream is not None and callable(getattr(stream, 'close', None)):
                stream.close()
