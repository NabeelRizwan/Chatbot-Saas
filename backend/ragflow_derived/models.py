"""Explicit model ports. No defaults, credentials or automatic provider fallback."""
from dataclasses import dataclass
import numpy as np


@dataclass
class CallableEmbeddingAdapter:
    profile: str
    dimension: int
    encode_documents: object
    encode_query: object
    max_tokens: int = 8192

    def encode(self, texts):
        from .upstream.embedding_utils import EmbeddingUtils
        bounded = EmbeddingUtils.truncate_texts(texts, self.max_tokens)
        return np.asarray(self.encode_documents(bounded), dtype=float), 0

    def encode_queries(self, text):
        from .upstream.embedding_utils import EmbeddingUtils
        bounded = EmbeddingUtils.truncate_texts([text], self.max_tokens)[0]
        return self.encode_query(bounded), 0


@dataclass
class CallableRerankerAdapter:
    score: object

    def similarity(self, query, texts):
        # The model adapter must normalize to [0,1], the release's contract.
        return np.asarray(self.score(query, texts), dtype=float), 0
