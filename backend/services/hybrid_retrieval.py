"""Phase 2 channel policy and rank-only fusion (no provider or DB ownership).

RRF formula references: pgvector-python examples/hybrid_search/rrf.py and
https://supabase.com/docs/guides/ai/hybrid-search. Implementation is original;
demo schemas, models, score scales and fixed candidate limits are not reused.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
import json
import math
import os
from time import perf_counter


FTS_CONFIGURATION = "english"
RETRIEVAL_VERSION = "postgres-fts-rrf-v1"


@dataclass(frozen=True)
class HybridConfig:
    lexical_backend: str = "legacy"  # Temporary, deprecated rollback/A-B path.
    dense_weight: float = 1.0
    fts_weight: float = 1.0
    rrf_k: float = 60.0
    candidate_ceiling: int = 500

    def __post_init__(self):
        if self.lexical_backend not in {"legacy", "postgres_fts"}:
            raise ValueError("RAG_LEXICAL_BACKEND must be legacy or postgres_fts")
        for name in ("dense_weight", "fts_weight", "rrf_k"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) < 0:
                raise ValueError(f"Hybrid retrieval {name} must be finite and nonnegative")
        if self.rrf_k == 0 or self.dense_weight + self.fts_weight <= 0:
            raise ValueError("Hybrid retrieval requires positive k and at least one positive weight")
        if type(self.candidate_ceiling) is not int or not 1 <= self.candidate_ceiling <= 2000:
            raise ValueError("RAG_CANDIDATE_CEILING must be an integer from 1 to 2000")

    def identity(self):
        return {**asdict(self), "version": RETRIEVAL_VERSION, "fts_configuration": FTS_CONFIGURATION}

    def cache_fragment(self):
        return json.dumps(self.identity(), sort_keys=True, separators=(",", ":"))

    def bound(self, adaptive_limit):
        if type(adaptive_limit) is not int or adaptive_limit <= 0:
            raise ValueError("Candidate limit must be a positive integer")
        return min(adaptive_limit, self.candidate_ceiling)


def hybrid_config():
    """Read only declared, non-secret settings; invalid values fail explicitly."""
    try:
        return HybridConfig(
            lexical_backend=os.getenv("RAG_LEXICAL_BACKEND", "legacy").strip().lower(),
            dense_weight=float(os.getenv("RAG_DENSE_WEIGHT", "1")),
            fts_weight=float(os.getenv("RAG_FTS_WEIGHT", "1")),
            rrf_k=float(os.getenv("RAG_RRF_K", "60")),
            candidate_ceiling=int(os.getenv("RAG_CANDIDATE_CEILING", "500")),
        )
    except (TypeError, ValueError):
        # Never echo environment values, even for configuration errors.
        raise ValueError("Invalid hybrid retrieval configuration") from None


@dataclass(frozen=True)
class ChannelCandidate:
    chunk_id: int
    document_id: int
    raw_score: float
    rank: int
    backend: str
    section_signal: str = "content"


@dataclass(frozen=True)
class FusedCandidate:
    chunk_id: int
    document_id: int
    dense: ChannelCandidate | None
    fts: ChannelCandidate | None
    dense_contribution: float
    fts_contribution: float
    score: float
    rank: int


def weighted_rrf(dense, fts, config):
    """Independent one-based ranks, union by canonical chunk ID, zero missing leg.

    Raw channel scores NEVER participate in fusion. Duplicate IDs take their
    first rank; conflicting document IDs are invalid, not arbitrarily merged.
    """
    union = {}
    for channel, candidates in (("dense", dense), ("fts", fts)):
        for candidate in candidates:
            if candidate.rank < 1 or candidate.chunk_id <= 0 or candidate.document_id <= 0:
                raise ValueError("Invalid channel candidate identity/rank")
            entry = union.setdefault(candidate.chunk_id, {"document_id": candidate.document_id})
            if entry["document_id"] != candidate.document_id:
                raise ValueError("Conflicting chunk/document identity")
            entry.setdefault(channel, candidate)
    ranked = []
    for chunk_id, entry in union.items():
        d, f = entry.get("dense"), entry.get("fts")
        dc = config.dense_weight / (config.rrf_k + d.rank) if d else 0.0
        fc = config.fts_weight / (config.rrf_k + f.rank) if f else 0.0
        best_rank = min(c.rank for c in (d, f) if c is not None)
        ranked.append((dc + fc, best_rank, entry["document_id"], chunk_id, d, f, dc, fc))
    ranked.sort(key=lambda row: (-row[0], row[1], row[2], row[3]))
    return [FusedCandidate(chunk, doc, d, f, dc, fc, score, rank)
            for rank, (score, _best, doc, chunk, d, f, dc, fc) in enumerate(ranked, 1)]


def weighted_rank_union(channels, weights, rrf_k=60.0):
    """Generalization of the accepted one-based formula for resource identities.

    Input per channel: (tenant-qualified immutable identity, one-based rank).
    No raw score, text deduplication, or change to chunk weighted_rrf above.
    Return (identity, total, contributions); callers hydrate identities separately.
    """
    if not math.isfinite(rrf_k) or rrf_k <= 0:
        raise ValueError("RRF k must be positive and finite")
    union = {}
    for channel, rows in channels.items():
        weight = weights[channel]
        if not math.isfinite(weight) or weight < 0:
            raise ValueError("Invalid RRF channel weight")
        seen = set()
        for identity, rank in rows:
            if type(rank) is not int or rank < 1:
                raise ValueError("RRF ranks must be one-based")
            if identity in seen:
                continue
            seen.add(identity)
            union.setdefault(identity, {})[channel] = weight / (rrf_k + rank)
    rows = [(identity, sum(parts.values()), tuple(sorted(parts.items()))) for identity, parts in union.items()]
    return sorted(rows, key=lambda row: (-row[1], row[0]))


class HybridRetrievalError(RuntimeError):
    """Both independent recall channels failed; never means evidence is absent."""


def _leg(call):
    start = perf_counter()
    try:
        return call(), {"status": "success", "error_category": None,
                        "ms": round((perf_counter() - start) * 1000, 3)}
    except Exception as exc:
        code = getattr(getattr(exc, "orig", None), "pgcode", None)
        category = ("schema_unavailable" if code in {"42P01", "42703", "42883"}
                    else "timeout" if isinstance(exc, TimeoutError) or code == "57014"
                    else "channel_error")
        return None, {"status": "error", "error_category": category,
                      "ms": round((perf_counter() - start) * 1000, 3)}


def recall_parallel(dense_call, fts_call, trace):
    """FTS runs while the dense callback embeds, including when embedding fails.

    No retries or legacy fallback. Callbacks own/close separate sessions.
    Exceptions are converted to fixed categories, never persisted verbatim.
    """
    start = perf_counter()
    with ThreadPoolExecutor(max_workers=2) as pool:
        dense_future = pool.submit(_leg, dense_call)
        fts_future = pool.submit(_leg, fts_call)
        dense, ds = dense_future.result()
        fts, fs = fts_future.result()
    mode = ("both_failed" if ds["status"] == fs["status"] == "error"
            else "fts_only" if ds["status"] == "error"
            else "dense_only" if fs["status"] == "error" else "full_hybrid")
    if trace:
        rt = trace.retrieval
        rt.hybrid.update(dense_leg=ds, fts_leg=fs, degradation=mode)
        trace.timings_ms.update(dense_leg_ms=ds["ms"], fts_search_ms=fs["ms"],
                               parallel_retrieval_wall_ms=round((perf_counter()-start)*1000, 3))
        for channel, status in (("dense", ds), ("fts", fs)):
            if status["status"] == "error":
                rt.fallback(channel + "_leg_error", terminal=False)
        if mode != "full_hybrid":
            rt.fallback("both_retrieval_channels_failed" if mode == "both_failed" else "degraded_" + mode,
                        terminal=mode == "both_failed")
    if mode == "both_failed":
        raise HybridRetrievalError("Both retrieval channels failed")
    return dense or [], fts
