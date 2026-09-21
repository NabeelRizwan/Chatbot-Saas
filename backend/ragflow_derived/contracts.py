"""Neutral evidence and server-issued scope. No imports of application DB/settings."""
from dataclasses import dataclass, field
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlsplit


class EngineError(RuntimeError):
    def __init__(self, code, stage=""):
        self.code, self.stage = code, stage
        super().__init__(code)  # Never forward backend payloads/credentials.


def identifier(value):
    value = str(value)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise EngineError("UNAUTHORIZED_SCOPE", "identity")
    return value


@dataclass(frozen=True)
class SourceRef:
    source_id: str
    document_id: str
    version: str

    def __post_init__(self):
        for name in ("source_id", "document_id", "version"):
            object.__setattr__(self, name, identifier(getattr(self, name)))

    @property
    def key(self):
        return hashlib.sha256(json.dumps([self.source_id, self.document_id, self.version]).encode()).hexdigest()


@dataclass(frozen=True)
class AuthorizedScope:
    organization_id: str
    bot_id: str
    generation: str
    embedding_profile: str
    dimension: int
    sources: tuple[SourceRef, ...]

    def __post_init__(self):
        for name in ("organization_id", "bot_id", "generation", "embedding_profile"):
            object.__setattr__(self, name, identifier(getattr(self, name)))
        object.__setattr__(self, "sources", tuple(self.sources))
        if len(self.sources) > 10000 or any(not isinstance(s, SourceRef) for s in self.sources):
            raise EngineError("UNAUTHORIZED_SCOPE", "source inventory bounds")
        if not isinstance(self.dimension, int) or isinstance(self.dimension, bool) or not 1 <= self.dimension <= 4096:
            raise EngineError("UNAUTHORIZED_SCOPE", "dimension")
        if len({s.source_id for s in self.sources}) != len(self.sources):
            raise EngineError("UNAUTHORIZED_SCOPE", "duplicate source")

    @property
    def key(self):
        return hashlib.sha256(json.dumps([self.organization_id, self.bot_id, self.generation,
                                         self.embedding_profile, self.dimension]).encode()).hexdigest()

    @property
    def index(self):
        return "ragflow_" + self.key

    def source(self, source_id):
        matches = [s for s in self.sources if s.source_id == str(source_id)]
        if len(matches) != 1:
            raise EngineError("UNAUTHORIZED_SCOPE", "source")
        return matches[0]


@dataclass(frozen=True)
class Evidence:
    chunk_id: str
    source_id: str
    document_id: str
    version: str
    generation: str
    scope_key: str
    text: str
    text_sha256: str
    title: str
    url: str
    order: int
    similarity: float
    lexical_similarity: float
    vector_similarity: float
    channel: str
    metadata: Mapping = field(default_factory=dict)

    def __post_init__(self):
        if hashlib.sha256(self.text.encode()).hexdigest() != self.text_sha256:
            raise EngineError("PROVENANCE_FAILED", "text")
        if not all(math.isfinite(x) for x in (self.similarity, self.lexical_similarity, self.vector_similarity)):
            raise EngineError("RETRIEVAL_FAILED", "score")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def citation_id(self):
        return "rf_" + self.chunk_id

    def citation(self):
        return {"id": self.citation_id, "document_id": self.document_id, "source_id": self.source_id,
                "version": self.version, "chunk_id": self.chunk_id, "title": self.title,
                "url": self.url, "order": self.order, "text_sha256": self.text_sha256}


def safe_url(value):
    try:
        p = urlsplit(value)
        if p.scheme in ("https", "http") and p.hostname and not p.username and not p.password:
            return value
    except ValueError:
        pass
    return ""
