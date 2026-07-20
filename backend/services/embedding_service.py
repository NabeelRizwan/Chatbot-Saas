import hashlib
import math
import os
from pathlib import Path
from typing import Protocol

from dotenv import load_dotenv
from google import genai
from google.genai import types
from openai import OpenAI

from database.models import EMBEDDING_DIMENSIONS

BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")

GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"
OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"


class EmbeddingProvider(Protocol):
    name: str
    dimensions: int

    def embed(self, text: str) -> list[float]:
        ...


def _fallback_embedding(text: str) -> list[float]:
    """Deterministic fallback keeps dev flows alive when Gemini is not configured."""
    vector = [0.0] * EMBEDDING_DIMENSIONS
    words = text.lower().split()
    for word in words:
        digest = hashlib.sha256(word.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS
        vector[index] += 1.0

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def validate_embedding(vector: list[float]) -> list[float]:
    if len(vector) != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Embedding dimension mismatch: expected {EMBEDDING_DIMENSIONS}, received {len(vector)}"
        )
    return vector


class GeminiEmbeddingProvider:
    name = "gemini"
    dimensions = EMBEDDING_DIMENSIONS

    def __init__(self, api_key: str | None = None, model_name: str = GEMINI_EMBEDDING_MODEL):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model_name

    def embed(self, text: str) -> list[float]:
        if not self.api_key or self.api_key == "your_api_key_here":
            return _fallback_embedding(text)
        client = genai.Client(api_key=self.api_key)
        result = client.models.embed_content(
            model=self.model_name,
            contents=text,
            config=types.EmbedContentConfig(output_dimensionality=self.dimensions),
        )
        return validate_embedding(list(result.embeddings[0].values))


class OpenAIEmbeddingProvider:
    name = "openai"
    dimensions = EMBEDDING_DIMENSIONS

    def __init__(self, api_key: str | None = None, model_name: str = OPENAI_EMBEDDING_MODEL):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model_name = model_name

    def embed(self, text: str) -> list[float]:
        if not self.api_key:
            return _fallback_embedding(text)
        client = OpenAI(api_key=self.api_key)
        result = client.embeddings.create(
            model=self.model_name,
            input=text,
            dimensions=self.dimensions,
        )
        return validate_embedding(list(result.data[0].embedding))


def get_embedding_provider(provider_name: str | None = None) -> EmbeddingProvider:
    selected = (provider_name or os.getenv("EMBEDDING_PROVIDER") or "gemini").lower().strip()
    if selected == "openai":
        return OpenAIEmbeddingProvider(model_name=os.getenv("OPENAI_EMBEDDING_MODEL", OPENAI_EMBEDDING_MODEL))
    if selected == "gemini":
        return GeminiEmbeddingProvider(model_name=os.getenv("GEMINI_EMBEDDING_MODEL", GEMINI_EMBEDDING_MODEL))
    raise ValueError("Unsupported embedding provider. Use 'gemini' or 'openai'.")


_EMBEDDING_CACHE: dict[tuple[str, str | None], list[float]] = {}


def generate_embedding(text: str, provider_name: str | None = None) -> list[float]:
    cache_key = (text, provider_name)
    if cache_key in _EMBEDDING_CACHE:
        return _EMBEDDING_CACHE[cache_key]

    try:
        embedding = validate_embedding(get_embedding_provider(provider_name).embed(text))
    except Exception:
        embedding = _fallback_embedding(text)

    if len(_EMBEDDING_CACHE) >= 1000:
        _EMBEDDING_CACHE.clear()
    _EMBEDDING_CACHE[cache_key] = embedding
    return embedding
