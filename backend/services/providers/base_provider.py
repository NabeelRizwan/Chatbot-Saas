from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum


class ProviderErrorKind(str, Enum):
    RATE_LIMIT = "rate_limit"
    QUOTA_EXHAUSTED = "quota_exhausted"
    AUTHENTICATION = "authentication"
    BILLING_RESTRICTION = "billing_restriction"
    TIMEOUT = "timeout"
    TEMPORARY = "temporary"
    INVALID_MODEL = "invalid_model"
    INVALID_REQUEST = "invalid_request"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None and self.output_tokens is None:
            return None
        return int(self.input_tokens or 0) + int(self.output_tokens or 0)


@dataclass(frozen=True)
class GenerationResult:
    text: str
    provider: str
    model: str
    usage: ProviderUsage | None = None


@dataclass(frozen=True)
class ProviderCapabilities:
    streaming: bool = True
    usage_reporting: bool = False


class ProviderError(Exception):
    """Normalized provider error used by the LLM router and FastAPI routes."""

    def __init__(
        self,
        message: str,
        status_code: int = 502,
        *,
        kind: ProviderErrorKind = ProviderErrorKind.UNKNOWN,
        retry_after_seconds: float | None = None,
    ):
        self.message = message
        self.status_code = status_code
        self.kind = kind
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message)


class BaseProvider(ABC):
    """Provider contract.

    Each provider receives the bot-owned API key at request time. This keeps
    generation multi-tenant and avoids coupling chat to one server-wide key.
    """

    provider_name: str
    capabilities = ProviderCapabilities()

    @abstractmethod
    def generate(
        self,
        api_key: str,
        model_name: str,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        raise NotImplementedError

    def generate_stream(
        self,
        api_key: str,
        model_name: str,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.2,
    ) -> Iterator[str]:
        yield self.generate(
            api_key=api_key,
            model_name=model_name,
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=temperature,
        )

    def generate_with_metadata(
        self,
        api_key: str,
        model_name: str,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.2,
    ) -> GenerationResult:
        """Canonical result contract; adapters override when usage is available."""
        return GenerationResult(
            text=self.generate(
                api_key=api_key,
                model_name=model_name,
                prompt=prompt,
                system_instruction=system_instruction,
                temperature=temperature,
            ),
            provider=self.provider_name,
            model=model_name,
            usage=None,
        )
