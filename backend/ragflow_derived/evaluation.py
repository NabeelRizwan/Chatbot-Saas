"""Future paired evaluation seam. No fixture/benchmark/GOLD paths or provider clients."""
import inspect
from time import perf_counter
from .contracts import EngineError


async def compare_saved_queries(queries, *, current_retrieve, derived, scope, limit=100):
    """Caller supplies independently authorized frozen queries and current adapter.

    Captures evidence identities/exact hashes/latency, NOT invented gold or scores.
    Never re-embeds documents. Query embedding is whatever caller explicitly
    configures on derived; use saved vectors for a provider-free benchmark.
    """
    if not 1 <= limit <= 1000:
        raise ValueError("Bounded evaluation required")
    queries = list(queries)
    if len(queries) > limit:
        raise ValueError("Evaluation query limit exceeded")
    rows = []
    for query in queries:
        lanes = {}
        for name in ("current", "ragflow"):
            start = perf_counter()
            if name == "current":
                result = current_retrieve(scope, query)
                evidence = await result if inspect.isawaitable(result) else result
            else:
                evidence = await derived.retrieve(scope, query)
            for item in evidence:
                source = scope.source(item.source_id)
                if item.scope_key != scope.key or item.version != source.version:
                    raise EngineError("UNAUTHORIZED_SCOPE", "evaluation parity")
            lanes[name] = {"elapsed_ms": (perf_counter() - start) * 1000,
                           "evidence": [item.citation() for item in evidence]}
        rows.append({"query": query, "scope_key": scope.key, "lanes": lanes})
    return rows
