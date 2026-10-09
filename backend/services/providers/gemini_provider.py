from collections.abc import Iterator
import math
import re
import httpx

from google import genai
from google.genai import errors, types

from services.providers.base_provider import (
    BaseProvider,
    GenerationResult,
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
    if status_code == 429:
        exhausted = _daily_quota_exhausted(details)
        kind = ProviderErrorKind.QUOTA_EXHAUSTED if exhausted else ProviderErrorKind.RATE_LIMIT
        message = "Gemini daily quota is exhausted for this bot's credential." if exhausted else "Gemini rate limit exceeded for this bot's credential."
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
                         retry_after_seconds=_retry_after_seconds(exc, details))


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
                contents=prompt,
                config=config,
            )
            usage_metadata = getattr(response, "usage_metadata", None)
            usage = ProviderUsage(
                input_tokens=getattr(usage_metadata, "prompt_token_count", None),
                output_tokens=getattr(usage_metadata, "candidates_token_count", None),
            ) if usage_metadata is not None else None
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
                contents=prompt,
                config=config,
            ):
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
