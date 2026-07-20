from abc import ABC, abstractmethod
from collections.abc import Iterator


class ProviderError(Exception):
    """Normalized provider error used by the LLM router and FastAPI routes."""

    def __init__(self, message: str, status_code: int = 502):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class BaseProvider(ABC):
    """Provider contract.

    Each provider receives the bot-owned API key at request time. This keeps
    generation multi-tenant and avoids coupling chat to one server-wide key.
    """

    provider_name: str

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
