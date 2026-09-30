"""Operator-owned configuration; widget input cannot choose model endpoints."""

from dataclasses import dataclass, field
import os
from urllib.parse import urlsplit

from .errors import CombinedRetrievalError

MODEL = "BAAI/bge-reranker-v2-m3"
REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
SOURCE_TOKEN_BUDGET = 4000
CONTEXT_MAX_CHARS = 65536
CANDIDATES_PER_FOCUS = 32
NATIVE_POOL_SIZE = 128
MAX_INPUT_TOKENS = 8192
POLICY_VERSION = "focused-bge32-interleave-saas-v2"


def policy_identity():
    """No credential or endpoint enters answer-cache identities."""
    return {"policy": POLICY_VERSION, "model": MODEL, "revision": REVISION,
            "focus_candidates": CANDIDATES_PER_FOCUS, "native_pool": NATIVE_POOL_SIZE,
            "source_tokens": SOURCE_TOKEN_BUDGET, "context_max_chars": CONTEXT_MAX_CHARS,
            "planner": "configured-bot-query-only-v1",
            "tokenizer": "offline-cl100k-base", "context": "whole-prefix-plus-app-char-cap"}


@dataclass(frozen=True)
class Config:
    url: str
    token: str = field(repr=False)
    reranker_timeout: float = 120.0
    planner_timeout: float = 5.0

    def __post_init__(self):
        try:
            url = urlsplit(self.url)
            valid = (url.scheme in {"http", "https"} and bool(url.hostname) and
                     not url.username and not url.password and not url.query and
                     not url.fragment and url.path == "/rerank")
            # Evaluate the optional port too: urlsplit defers invalid-port errors.
            _ = url.port
            valid = (valid and isinstance(self.token, str) and bool(self.token) and
                     all(33 <= ord(c) <= 126 for c in self.token))
            for value in (self.reranker_timeout, self.planner_timeout):
                valid = valid and type(value) in (int, float) and 0 < value <= 300
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise CombinedRetrievalError("configuration_invalid")

    @classmethod
    def from_env(cls):
        try:
            return cls(
                os.environ.get("RAG_COMBINED_RERANKER_URL", ""),
                os.environ.get("RAG_COMBINED_RERANKER_TOKEN", ""),
                float(os.environ.get("RAG_COMBINED_RERANKER_TIMEOUT_SECONDS", "120")),
                float(os.environ.get("RAG_COMBINED_PLANNER_TIMEOUT_SECONDS", "5")),
            )
        except (TypeError, ValueError) as error:
            raise CombinedRetrievalError("configuration_invalid") from error
