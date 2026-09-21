"""Request-local passive observations. Never supplies retrieval inputs or decisions."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps
import time

_current = ContextVar("ragflow_observation", default=None)


@contextmanager
def observation(enabled=True):
    data = {"events": [], "dropped_events": 0, "phase": "retrieval"} if enabled else None
    token = _current.set(data)
    try:
        yield data
    finally:
        _current.reset(token)


def phase(name):
    data = _current.get()
    if data is not None:
        data["phase"] = name


def record(kind, **values):
    data = _current.get()
    if data is not None:
        if len(data["events"]) >= 4096:
            data["dropped_events"] += 1
        else:
            data["events"].append({"kind": kind, "phase": data["phase"], **deepcopy(values)})


async def component(name, operation):
    started = time.perf_counter()
    result = await operation
    record("query_component", component=name, output=result,
           milliseconds=(time.perf_counter() - started) * 1000)
    return result


def chunks_summary(chunks):
    return [{key: chunk[key] for key in ("chunk_id", "doc_id", "similarity",
             "term_similarity", "vector_similarity") if key in chunk} for chunk in chunks]


def observe_dealer(dealer, threshold):
    """Wrap only this request's bound methods; forward/return the exact same objects."""
    if _current.get() is None:
        return dealer
    original_rerank = dealer.rerank_by_model
    @wraps(original_rerank)
    def rerank(model, sres, query, *args, **kwargs):
        started = time.perf_counter()
        result = original_rerank(model, sres, query, *args, **kwargs)
        sim, term, neural = result
        record("rerank_scores", query=query, threshold=threshold,
               milliseconds=(time.perf_counter() - started) * 1000,
               candidates=[{"chunk_id": cid, "source_id": sres.field[cid].get("source_id"),
                   "similarity": float(sim[i]), "term_similarity": float(term[i]),
                   "neural_similarity": float(neural[i]), "passes_cutoff": bool(sim[i] >= threshold)}
                   for i, cid in enumerate(sres.ids)])
        return result
    dealer.rerank_by_model = rerank
    original_parent = dealer.retrieval_by_children
    @wraps(original_parent)
    def parent(chunks, *args, **kwargs):
        before = chunks_summary(chunks)
        started = time.perf_counter()
        result = original_parent(chunks, *args, **kwargs)
        record("parent_route", before=before, after=chunks_summary(result),
               milliseconds=(time.perf_counter() - started) * 1000)
        return result
    dealer.retrieval_by_children = parent
    original_toc = dealer.retrieval_by_toc
    @wraps(original_toc)
    async def toc(query, chunks, *args, **kwargs):
        before = chunks_summary(chunks)
        started = time.perf_counter()
        result = await original_toc(query, chunks, *args, **kwargs)
        record("toc_route", query=query, before=before, after=chunks_summary(result or []),
               milliseconds=(time.perf_counter() - started) * 1000)
        return result
    dealer.retrieval_by_toc = toc
    return dealer
