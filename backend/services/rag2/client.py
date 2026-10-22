"""Same trusted service transport as OG, with isolated RAG2 admission and scope."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
from contextvars import copy_context
import asyncio
import json
from contextlib import suppress

import httpx

from services.llama_rag.client import RetrievalClient as OGClient
from services.llama_rag.client_runtime import RetrievalError, retrieval_request_context, checkpoint
from .worker_routing import worker_slot


class RetrievalClient(OGClient):
    def _request_at(self, url, path, body=None, *, method='POST', timeout=60):
        if path not in {'/v1/prepare', '/v1/snapshots', '/v1/retrieve', '/health/rag2', '/health/ready'}:
            raise RetrievalError('retrieval_route_invalid')
        remaining = checkpoint()
        timeout = min(float(timeout), remaining) if remaining is not None else float(timeout)

        async def perform():
            limits = httpx.Timeout(timeout, connect=min(timeout, 10), pool=min(timeout, 5))
            async with httpx.AsyncClient(trust_env=False, follow_redirects=False,
                                         transport=self.transport, timeout=limits) as client:
                async with client.stream(method, url + path, json=body,
                        headers={'Authorization': 'Bearer ' + self.token}) as response:
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        checkpoint()
                        size += len(chunk)
                        if size > 5 * 1024 * 1024:
                            raise RetrievalError('retrieval_response_too_large')
                        chunks.append(chunk)
                    return response.status_code, b''.join(chunks)

        async def bounded_request():
            # Waiting for response headers also observes Stop/deadline. Closing
            # the request lets the retrieval service cancel its Voyage work.
            task = asyncio.create_task(perform())
            try:
                while not task.done():
                    checkpoint()
                    await asyncio.wait({task}, timeout=.1)
                checkpoint()
                return await task
            finally:
                if not task.done():
                    task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

        try:
            status, content = asyncio.run(bounded_request())
            if status == 409:
                raise RetrievalError('snapshot_required')
            if status == 422:
                detail = json.loads(content)
                if isinstance(detail, dict) and detail.get('detail') == 'question_too_long':
                    raise RetrievalError('question_too_long')
            if status != 200:
                raise RetrievalError('retrieval_service_' + str(status), retryable=status == 503)
            result = json.loads(content)
            if not isinstance(result, dict):
                raise RetrievalError('retrieval_response_invalid')
            return result
        except (httpx.HTTPError, ValueError, TypeError):
            raise RetrievalError('retrieval_service_unavailable') from None

    def request(self, path, body=None, *, method='POST', timeout=60):
        if path == '/v1/prepare':
            body = {**body, 'pipeline': 'rag2_improved', 'pipeline_build_revision': 'rag2-voyage-v1'}
            manager = worker_slot(self.urls) if self._routing else nullcontext(self.url)
            with retrieval_request_context(timeout=timeout), manager as url:
                return self._request_at(url, path, body, method=method, timeout=timeout)
        return super().request(path, body, method=method, timeout=timeout)

    def readiness(self):
        expected = {'status': 'ready', 'engine': 'llamaindex', 'protocol': 1,
                    'pipeline': 'rag2_improved', 'pipeline_build_revision': 'rag2-voyage-v1',
                    'quota_store': 'ready', 'provider_validation': 'not_probed'}
        def probe(url):
            result = self._request_at(url, '/health/rag2', method='GET', timeout=5)
            if result != expected:
                raise RetrievalError('retrieval_readiness_invalid')
        with retrieval_request_context(timeout=5):
            with ThreadPoolExecutor(max_workers=min(len(self.urls), 4), thread_name_prefix='rag2-ready') as pool:
                futures = [pool.submit(copy_context().run, probe, url) for url in self.urls]
                for future in as_completed(futures):
                    future.result()
        return 'ready'

    def snapshot(self, scope, documents):
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
        results, error = {}, None
        with ThreadPoolExecutor(max_workers=min(len(self.urls), 4), thread_name_prefix='rag2-warm') as pool:
            futures = {pool.submit(copy_context().run, warm, url): url for url in self.urls}
            for future in as_completed(futures):
                try:
                    results[futures[future]] = future.result()
                except Exception as caught:
                    error = error or caught
        if error:
            raise error
        return results[self.urls[0]]

    def _snapshot_at(self, url, scope, documents):
        result = super()._snapshot_at(url, scope, documents)
        if (result.get('pipeline') != scope['pipeline']
                or result.get('pipeline_build_revision') != scope['pipeline_build_revision']):
            raise RetrievalError('retrieval_pipeline_mismatch')
        return result
