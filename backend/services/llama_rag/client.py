from dataclasses import dataclass, field
import os
from urllib.parse import urlsplit

import httpx


class RetrievalError(RuntimeError):
    """Safe category; credentials and upstream response bodies never escape."""


@dataclass(frozen=True)
class RetrievalClient:
    url: str = field(default_factory=lambda: os.getenv("LLAMA_RETRIEVAL_URL", "").rstrip("/"))
    token: str = field(default_factory=lambda: os.getenv("LLAMA_RETRIEVAL_TOKEN", ""), repr=False)
    transport: httpx.BaseTransport | None = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        try:
            parsed = urlsplit(self.url)
            valid = (parsed.scheme in {"http", "https"} and parsed.hostname
                and not parsed.username and not parsed.password and not parsed.query
                and not parsed.fragment and parsed.path in {"", "/"}
                and len(self.token) >= 32 and all(33 <= ord(c) <= 126 for c in self.token))
            _ = parsed.port
        except ValueError:
            valid = False
        if not valid:
            raise RetrievalError("retrieval_configuration_invalid")

    def request(self, path, body=None, *, method="POST", timeout=60):
        try:
            with httpx.Client(trust_env=False, follow_redirects=False, timeout=timeout, transport=self.transport) as client:
                response = client.request(method, self.url + path, json=body,
                    headers={"Authorization": "Bearer " + self.token})
            if response.status_code == 409:
                raise RetrievalError("snapshot_required")
            if response.status_code == 422 and response.json().get('detail') == 'question_too_long':
                raise RetrievalError('question_too_long')
            if response.status_code != 200:
                raise RetrievalError("retrieval_service_" + str(response.status_code))
            if len(response.content) > 5 * 1024 * 1024:
                raise RetrievalError("retrieval_response_too_large")
            result = response.json()
            if not isinstance(result, dict):
                raise RetrievalError("retrieval_response_invalid")
            return result
        except (httpx.HTTPError, ValueError) as error:
            raise RetrievalError("retrieval_service_unavailable") from error

    def snapshot(self, scope, documents):
        result = self.request("/v1/snapshots", {**scope, "documents": documents}, timeout=300)
        if result.get("fingerprint") != scope["fingerprint"] or not result.get("status", {}).get("ready"):
            raise RetrievalError("retrieval_snapshot_invalid")
        return result

    def retrieve(self, scope, documents, question):
        body = {**scope, "question": question}
        try:
            return self.request("/v1/retrieve", body)
        except RetrievalError as error:
            if str(error) != "snapshot_required":
                raise
        self.snapshot(scope, documents)
        return self.request("/v1/retrieve", body)
