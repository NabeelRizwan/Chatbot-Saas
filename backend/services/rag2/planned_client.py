"""Exact planned evidence, with no cross-plan cache or unknown-outcome replay."""
from contextlib import nullcontext
from time import perf_counter

from services.llama_rag.client_runtime import (
    RetrievalError, checkpoint, retrieval_request_context, record_retrieval_metadata,
)
from .worker_routing import worker_slot
from .search_planning import validate_queries


def retrieve_planned(client, scope, documents, question, queries):
    queries = validate_queries(queries)
    started = perf_counter()
    try:
        with retrieval_request_context(timeout=1500, max_timeout=1800):
            manager = worker_slot(client.urls) if client._routing else nullcontext(client.url)
            with manager as url:
                def request():
                    remaining = checkpoint()
                    # Leave transport/serialization time outside the service budget.
                    budget = min(1440.0, max(0.0, remaining - 5))
                    if budget <= 0:
                        raise RetrievalError('retrieval_deadline_exceeded')
                    body = {**scope, 'question': question, 'queries': queries,
                            'timeout_seconds': budget}
                    return client._request_at(url, '/v1/retrieve', body, timeout=remaining)
                try:
                    return request()
                except RetrievalError as error:
                    if str(error) != 'snapshot_required':
                        raise
                client._snapshot_at(url, scope, documents)
                return request()
    finally:
        record_retrieval_metadata(cache_hit=False,
            client_elapsed_ms=round((perf_counter() - started) * 1000, 3))
