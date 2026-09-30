"""Synchronous private BGE client, with no provider credential/model switching."""

from math import isfinite

import httpx

from .config import MODEL, REVISION, MAX_INPUT_TOKENS, CANDIDATES_PER_FOCUS
from .errors import CombinedRetrievalError


def validate_response(payload, count):
    if not isinstance(payload, dict) or payload.get("model") != MODEL or payload.get("revision") != REVISION:
        raise CombinedRetrievalError("reranker_identity_mismatch")
    scores, lengths = payload.get("scores"), payload.get("token_counts")
    if (not isinstance(scores, list) or not isinstance(lengths, list) or
            len(scores) != count or len(lengths) != count):
        raise CombinedRetrievalError("reranker_incomplete_response")
    if any(type(v) not in (int, float) or not isfinite(v) for v in scores):
        raise CombinedRetrievalError("reranker_invalid_score")
    if any(type(v) is not int or v < 1 for v in lengths):
        raise CombinedRetrievalError("reranker_invalid_token_counts")
    if any(v > MAX_INPUT_TOKENS for v in lengths):
        raise CombinedRetrievalError("reranker_input_too_long")
    return [float(v) for v in scores]


class BGEClient:
    def __init__(self, config, *, transport=None):
        self.config = config
        self.transport = transport

    def score(self, query, documents):
        if (not isinstance(query, str) or not query.strip() or
                not isinstance(documents, list) or not 1 <= len(documents) <= CANDIDATES_PER_FOCUS or
                any(not isinstance(v, str) or not v.strip() for v in documents)):
            raise CombinedRetrievalError("reranker_invalid_input")
        try:
            with httpx.Client(timeout=self.config.reranker_timeout, follow_redirects=False,
                              trust_env=False, transport=self.transport) as client:
                response = client.post(self.config.url,
                    headers={"Authorization": "Bearer " + self.config.token},
                    json={"query": query, "documents": documents})
        except httpx.TransportError as error:
            raise CombinedRetrievalError("reranker_unavailable") from error
        if response.status_code in {413, 422}:
            raise CombinedRetrievalError("reranker_input_rejected")
        if response.status_code == 429 or response.status_code >= 500:
            raise CombinedRetrievalError("reranker_unavailable")
        if response.status_code != 200:
            raise CombinedRetrievalError("reranker_request_rejected")
        if len(response.content) > 32768:
            raise CombinedRetrievalError("reranker_oversized_response")
        try:
            payload = response.json()
        except ValueError as error:
            raise CombinedRetrievalError("reranker_invalid_json") from error
        return validate_response(payload, len(documents))
