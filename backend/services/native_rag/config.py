from dataclasses import dataclass, field
import os
from urllib.parse import urlsplit

UPSTREAM = "a024bea0cd93f39e6652a42bf84dd20c55bc560b"
EMBEDDING = "BAAI/bge-small-en-v1.5"
PROFILE = {"provider": "ragflow", "model": EMBEDDING, "version": 1, "dimensions": 384}
SEARCH_POLICY = {"version": "native-w128-v1", "upstream": UPSTREAM,
                 "candidates": 128, "knn_top_k": 1024, "knn_num_candidates": 2048,
                 "similarity_threshold": .1, "vector_similarity_weight": .3,
                 "embedding": EMBEDDING, "parent_expansion": "before_bge"}


class NativeRagError(RuntimeError):
    """Safe category only; upstream payloads and credentials are never forwarded."""


@dataclass(frozen=True)
class NativeConfig:
    url: str
    token: str = field(repr=False)
    tenant: str
    embedding_id: str
    timeout: float = 120
    parse_timeout: float = 1800

    def __post_init__(self):
        try:
            from re import fullmatch
            url = urlsplit(self.url)
            valid = (url.scheme in {"http", "https"} and url.hostname and
                     url.path in {"", "/"} and not url.query and not url.fragment and
                     not url.username and not url.password and
                     all(33 <= ord(c) <= 126 for c in self.token) and self.token and
                     fullmatch(r"[0-9a-f]{32}", self.tenant) and
                     (bool(fullmatch(r"[0-9a-f]{32}", self.embedding_id)) or
                      self.embedding_id == EMBEDDING + "@HuggingFace") and
                     0 < self.timeout <= 300 and 0 < self.parse_timeout <= 3600)
            _ = url.port
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise NativeRagError("native_configuration_invalid")

    @classmethod
    def from_env(cls):
        try:
            return cls(os.environ.get("RAGFLOW_URL", "").rstrip("/"),
                       os.environ.get("RAGFLOW_API_TOKEN", ""),
                       os.environ.get("RAGFLOW_TENANT_ID", ""),
                       os.environ.get("RAGFLOW_EMBEDDING_ID", ""),
                       float(os.environ.get("RAGFLOW_TIMEOUT_SECONDS", "120")),
                       float(os.environ.get("RAGFLOW_PARSE_TIMEOUT_SECONDS", "1800")))
        except ValueError:
            raise NativeRagError("native_configuration_invalid") from None
