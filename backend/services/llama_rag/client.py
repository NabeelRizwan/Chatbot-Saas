from dataclasses import dataclass, field
from contextlib import nullcontext
from contextvars import copy_context
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from time import perf_counter
from urllib.parse import urlsplit

import httpx


from .client_runtime import (RetrievalError, checkpoint, close_retrieval_clients, enabled,
                             pooled_client, retrieval_request_context, record_retrieval_metadata)
from .retrieval_cache import EvidenceCache
from .worker_routing import worker_slot


@dataclass(frozen=True)
class RetrievalClient:
    url: str = field(default_factory=lambda: os.getenv("LLAMA_RETRIEVAL_URL", "").rstrip("/"))
    token: str = field(default_factory=lambda: os.getenv("LLAMA_RETRIEVAL_TOKEN", ""), repr=False)
    transport: httpx.BaseTransport | None = field(default=None, repr=False, compare=False)
    urls: tuple[str, ...] | None = field(default=None, repr=False)

    def __post_init__(self):
        configured = self.urls
        if configured is None:
            configured = tuple(url.strip().rstrip('/') for url in os.getenv("LLAMA_RETRIEVAL_URLS", "").split(',') if url.strip())
        targets = configured or (self.url,)
        if not 1 <= len(targets) <= 16 or len(set(targets)) != len(targets):
            raise RetrievalError("retrieval_configuration_invalid")
        for url in targets:
            self._validate(url)
        object.__setattr__(self, "urls", tuple(targets))
        object.__setattr__(self, "_routing", bool(configured))
        if not self.url:
            object.__setattr__(self, "url", targets[0])
        self._validate(self.url)

    def _validate(self, url):
        try:
            parsed = urlsplit(url)
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
        if self._routing and path == "/health/ready":
            with retrieval_request_context(timeout=timeout):
                return self._readiness_all(body, method=method, timeout=timeout)
        if self._routing and path == "/v1/prepare":
            with retrieval_request_context(timeout=timeout), worker_slot(self.urls) as url:
                return self._request_at(url, path, body, method=method, timeout=timeout)
        return self._request_at(self.url, path, body, method=method, timeout=timeout)

    def _readiness_all(self, body, *, method, timeout):
        expected = {"status": "ready", "engine": "llamaindex", "protocol": 1}

        def probe(url):
            result = self._request_at(url, "/health/ready", body, method=method, timeout=timeout)
            if result != expected:
                raise RetrievalError("retrieval_readiness_invalid")

        first_error = None
        # Health checks do not occupy retrieval slots or depend on queue Redis.
        # Drain started requests; every probe inherits the same bounded lifetime.
        with ThreadPoolExecutor(max_workers=min(len(self.urls), 4), thread_name_prefix="retrieval-ready") as pool:
            futures = [pool.submit(copy_context().run, probe, url) for url in self.urls]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as error:
                    if first_error is None:
                        first_error = error
        if first_error is not None:
            raise first_error
        return expected

    def _request_at(self, url, path, body=None, *, method="POST", timeout=60):
        if path not in {"/v1/prepare", "/v1/snapshots", "/v1/retrieve", "/health/live", "/health/ready"}:
            raise RetrievalError("retrieval_route_invalid")
        remaining = checkpoint()
        timeout = min(float(timeout), remaining) if remaining is not None else float(timeout)
        use_pool = enabled("LLAMA_RETRIEVAL_POOL_ENABLED")
        limits = (httpx.Timeout(timeout, connect=min(timeout, 10), pool=min(timeout, 5))
                  if use_pool else httpx.Timeout(timeout))
        try:
            manager = (nullcontext(pooled_client(url, self.token, self.transport))
                       if use_pool else
                       httpx.Client(trust_env=False, follow_redirects=False, transport=self.transport))
            with manager as client:
                request = client.build_request(method, url + path, json=body, timeout=limits,
                    headers={"Authorization": "Bearer " + self.token})
                # Pool reuse must not turn upstream cookies into cross-request state.
                request.headers.pop("cookie", None)
                response = client.send(request, stream=True)
                try:
                    status = response.status_code
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        checkpoint()
                        size += len(chunk)
                        if size > 5 * 1024 * 1024:
                            raise RetrievalError("retrieval_response_too_large")
                        chunks.append(chunk)
                    content = b''.join(chunks)
                finally:
                    response.close()
            if status == 409:
                raise RetrievalError("snapshot_required")
            if status == 422:
                detail = json.loads(content)
                if isinstance(detail, dict) and detail.get('detail') == 'question_too_long':
                    raise RetrievalError('question_too_long')
            if status != 200:
                raise RetrievalError("retrieval_service_" + str(status), retryable=status == 503)
            result = json.loads(content)
            if not isinstance(result, dict):
                raise RetrievalError("retrieval_response_invalid")
            return result
        except (httpx.ConnectError, httpx.ConnectTimeout) as error:
            raise RetrievalError("retrieval_service_unavailable", retryable=True) from None
        except (httpx.HTTPError, ValueError) as error:
            raise RetrievalError("retrieval_service_unavailable") from None

    def snapshot(self, scope, documents):
        """Warm every configured replica before the caller promotes this corpus.

        New replicas also need trusted snapshots for existing bots before they
        enter live routing. Model readiness alone does not mean indexes are warm.
        """
        with retrieval_request_context(timeout=300):
            if self._routing and len(self.urls) > 1:
                return self._snapshot_all(scope, documents)
            manager = worker_slot(self.urls) if self._routing else nullcontext(self.url)
            with manager as url:
                return self._snapshot_at(url, scope, documents)

    def _snapshot_all(self, scope, documents):
        def warm(url):
            with worker_slot((url,)) as selected:
                return self._snapshot_at(selected, scope, documents)

        results, first_error = {}, None
        # Each endpoint holds its existing distributed lease independently.
        # Drain every submitted call, including after failure, before returning.
        with ThreadPoolExecutor(max_workers=min(len(self.urls), 4), thread_name_prefix='snapshot-warm') as pool:
            futures = {pool.submit(copy_context().run, warm, url): url for url in self.urls}
            for future in as_completed(futures):
                try:
                    results[futures[future]] = future.result()
                except Exception as error:
                    if first_error is None:
                        first_error = error
        if first_error is not None:
            raise first_error
        return results[self.urls[0]]

    def _snapshot_at(self, url, scope, documents):
        result = self._request_at(url, "/v1/snapshots", {**scope, "documents": documents}, timeout=300)
        status = result.get("status")
        if result.get("fingerprint") != scope["fingerprint"] or not isinstance(status, dict) or not status.get("ready"):
            raise RetrievalError("retrieval_snapshot_invalid")
        return result

    def retrieve(self, scope, documents, question):
        started, cache_hit = perf_counter(), False
        record_retrieval_metadata(cache_hit=False, client_elapsed_ms=0.0)
        try:
            with retrieval_request_context():
                cache = EvidenceCache.configured(scope, question)
                try:
                    if cache:
                        result = cache.read()
                        if result is None:
                            result = cache.claim_or_wait()
                        if result is not None:
                            cache_hit = True
                            return result
                    result = self._retrieve(scope, documents, question)
                    if cache:
                        cache.store(result, scope, question)
                    return result
                finally:
                    if cache:
                        cache.release()
        finally:
            record_retrieval_metadata(cache_hit=cache_hit,
                client_elapsed_ms=round((perf_counter() - started) * 1000, 3))

    def _retrieve(self, scope, documents, question):
        excluded = []
        while True:
            manager = worker_slot(self.urls, excluded=excluded) if self._routing else nullcontext(self.url)
            with manager as url:
                try:
                    return self._retrieve_at(url, scope, documents, question)
                except RetrievalError as error:
                    if not self._routing or not error.retryable or len(excluded) + 1 >= len(self.urls):
                        raise
                    excluded.append(url)

    def _retrieve_at(self, url, scope, documents, question):
        body = {**scope, "question": question}
        try:
            return self._request_at(url, "/v1/retrieve", body)
        except RetrievalError as error:
            if str(error) != "snapshot_required":
                raise
        try:
            self._snapshot_at(url, scope, documents)
            return self._request_at(url, "/v1/retrieve", body)
        except RetrievalError as error:
            # Snapshot outcomes can be unknown; never replay that sequence elsewhere.
            raise RetrievalError(str(error)) from None
