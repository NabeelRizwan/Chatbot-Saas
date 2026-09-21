"""Test-only doubles: NOT an Elasticsearch implementation or a retrieval quality benchmark."""
import copy
import hashlib
import re
import unicodedata
import numpy as np
from ragflow_derived.contracts import EngineError, AuthorizedScope, SourceRef
from ragflow_derived.engine import RagFlowDerivedEngine, EngineConfig
from ragflow_derived.upstream.doc_store import MatchTextExpr, MatchDenseExpr


class TokenizerDouble:
    def tokenize(self, text):
        return " ".join(re.findall(r"\w+", text.casefold()))
    fine_grained_tokenize = tokenize
    def tag(self, text): return ""
    def freq(self, text): return 0
    def tradi2simp(self, text): return text
    def strQ2B(self, text): return unicodedata.normalize("NFKC", text)


class SynonymsDouble:
    def lookup(self, token, topn=8): return []


class EmbeddingDouble:
    profile = "synthetic-v1"
    dimension = 64
    def encode_queries(self, text): return self.encode([text])[0][0].tolist(), 0
    def encode(self, texts):
        values = []
        for text in texts:
            vector = np.zeros(self.dimension)
            for word in re.findall(r"\w+", text.lower()):
                vector[int(hashlib.sha256(word.encode()).hexdigest()[:8], 16) % self.dimension] += 1
            vector[0] += 0.01
            values.append(vector / np.linalg.norm(vector))
        return np.asarray(values), 0


class MemoryFixtureBackend:
    def __init__(self):
        self.rows, self.markers, self.calls = {}, {}, []
        self.closed = False
        self.fail = False
        self.ready = set()

    def claim_source(self, scope, source, digest):
        key = scope.key, source.key
        if key in self.markers and self.markers[key] != digest:
            raise EngineError("INGESTION_FAILED", "immutable source")
        self.markers[key] = digest

    def replace(self, scope, source, rows):
        self.rows.update({r["id"]: copy.deepcopy(r) for r in rows})
        self.ready.add((scope.key, source.key))

    def ready_sources(self, scope):
        if self.fail:
            raise RuntimeError("simulated backend failure")
        return {s.key for s in scope.sources if (scope.key, s.key) in self.ready}

    def delete(self, scope, source):
        self.rows = {key: row for key, row in self.rows.items()
                     if not (row["scope_key_kwd"] == scope.key and row["source_version_kwd"] == source.key)}
        self.markers.pop((scope.key, source.key), None)
        self.ready.discard((scope.key, source.key))

    def search(self, fields, highlights, condition, expressions, order, offset, limit, indexes, kb_ids, **kwargs):
        self.calls.append(copy.deepcopy((condition, expressions, indexes, kb_ids)))
        if self.fail:
            raise RuntimeError("simulated backend failure")
        candidates = []
        for cid, row in self.rows.items():
            if "ragflow_" + row["scope_key_kwd"] not in indexes or row["kb_id"] not in kb_ids:
                continue
            if any(not set((cid if key == "id" else row.get(key)) if isinstance((cid if key == "id" else row.get(key)), list)
                           else [cid if key == "id" else row.get(key)]).intersection(value if isinstance(value, list) else [value])
                   for key, value in condition.items() if key != "must_not"):
                continue
            score = 0.
            for expr in expressions:
                if isinstance(expr, MatchTextExpr):
                    words = TokenizerDouble().tokenize(expr.extra_options.get("original_query", "")).split()
                    text = row["content_ltks"].split()
                    score += sum(w in text for w in words) / max(1, len(words))
                elif isinstance(expr, MatchDenseExpr):
                    a, b = np.asarray(expr.embedding_data), np.asarray(row[expr.vector_column_name])
                    cosine = float(np.dot(a, b) / np.linalg.norm(a) / np.linalg.norm(b))
                    score += (1 + cosine) / 2
            if expressions and score <= 0:
                continue
            candidates.append({"_id": cid, "_source": copy.deepcopy(row), "_score": score})
        candidates.sort(key=lambda row: (-row["_score"], row["_id"]))
        return {"hits": {"total": {"value": len(candidates)}, "hits": candidates[offset:offset + limit]}}

    def close(self): self.closed = True


def scope(org="tenant-a", bot="bot-a", version="1", generation="gen-a"):
    return AuthorizedScope(org, bot, generation, "synthetic-v1", 64,
                           (SourceRef("manual", "doc-a", version), SourceRef("terms", "doc-b", version)))


def engine(backend=None, scope_check=None, config=None, reranker=None):
    return RagFlowDerivedEngine(backend or MemoryFixtureBackend(), EmbeddingDouble(),
        still_authorized=scope_check or (lambda s: True), tokenizer=TokenizerDouble(),
        synonyms=SynonymsDouble(), config=config or EngineConfig(similarity_threshold=0),
        reranker=reranker, count_tokens=lambda text: len(text.split()))
