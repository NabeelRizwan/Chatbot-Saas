"""Mandatory scope guard around every upstream search, including fallback/vector lookups."""
import copy
import hashlib
import json
import threading
from pathlib import Path
from .contracts import EngineError
from .observation import record
from .upstream.es_query import ElasticsearchQuery


class ElasticsearchBackend:
    """Only explicit local service URLs; never reads DATABASE_URL or application .env."""
    def __init__(self, client):
        self.client = client
        self.query = ElasticsearchQuery(client)

    @classmethod
    def local(cls, url="http://127.0.0.1:19200"):
        from urllib.parse import urlsplit
        from elasticsearch import Elasticsearch
        parsed = urlsplit(url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password:
            raise EngineError("UNAUTHORIZED_SCOPE", "development backend")
        return cls(Elasticsearch(url, request_timeout=15, max_retries=0))

    def create(self, scope):
        if self.client.indices.exists(index=scope.index):
            return
        mapping = json.loads(Path(__file__).parent.joinpath("upstream/mapping.json").read_text())
        # Preserve upstream mapping/analyzers/similarity. Explicit dimensional field
        # prevents accidental cross-profile dynamic vector mappings.
        mapping["mappings"]["properties"][f"q_{scope.dimension}_vec"] = {
            "type": "dense_vector", "dims": scope.dimension, "index": True, "similarity": "cosine"}
        self.client.indices.create(index=scope.index, **mapping)

    def replace(self, scope, source, rows):
        self.create(scope)
        operations = []
        for row in rows:
            operations += [{"index": {"_index": scope.index, "_id": row["id"]}}, row]
        result = self.client.bulk(operations=operations, refresh="wait_for")
        if result.get("errors"):
            # Fail closed; never treat partial indexing as successful activation.
            self.delete(scope, source)
            raise EngineError("INDEX_FAILED", "bulk")
        self.client.update(index=scope.index, id="manifest_" + source.key,
                           doc={"source_ready_int": 1}, refresh="wait_for")
        # Deterministic IDs make repeated identical ingestion idempotent. A source
        # may change only under a new version, enforced by the adapter registry.

    def claim_source(self, scope, source, digest):
        from elasticsearch import ConflictError
        self.create(scope)
        marker = {"scope_key_kwd": scope.key, "source_version_kwd": source.key,
                  "artifact_sha_kwd": digest, "available_int": 0, "source_ready_int": 0}
        try:
            self.client.create(index=scope.index, id="manifest_" + source.key,
                               document=marker, refresh="wait_for")
        except ConflictError:
            current = self.client.get(index=scope.index, id="manifest_" + source.key)["_source"]
            if {k: v for k, v in current.items() if k != "source_ready_int"} != {k: v for k, v in marker.items() if k != "source_ready_int"}:
                raise EngineError("INGESTION_FAILED", "changed source version") from None

    def ready_sources(self, scope):
        if not scope.sources or not self.client.indices.exists(index=scope.index):
            return set()
        result = self.client.mget(index=scope.index, ids=["manifest_" + s.key for s in scope.sources])
        allowed = {s.key for s in scope.sources}
        ready = set()
        for item in result["docs"]:
            if not item.get("found"):
                continue
            row = item["_source"]
            if row.get("scope_key_kwd") != scope.key or row.get("source_version_kwd") not in allowed:
                raise EngineError("UNAUTHORIZED_SCOPE", "index marker")
            if row.get("source_ready_int") == 1:
                ready.add(row["source_version_kwd"])
        return ready

    def delete(self, scope, source):
        if not self.client.indices.exists(index=scope.index):
            return
        result = self.client.delete_by_query(index=scope.index, refresh=True, query={"bool": {"filter": [
            {"term": {"scope_key_kwd": scope.key}}, {"term": {"source_version_kwd": source.key}}]}})
        if result.get("timed_out") or result.get("failures") or result.get("version_conflicts"):
            raise EngineError("INDEX_FAILED", "incomplete source deletion")

    def search(self, *args, **kwargs):
        return self.query.search(*args, **kwargs)

    def close(self):
        self.client.close()


class ScopedStore:
    """Per-request wrapper. Authorization is out-of-band and cannot be widened by query text."""
    SECURITY_FIELDS = ["scope_key_kwd", "source_version_kwd", "source_id", "version_kwd", "generation_kwd",
                       "content_sha_kwd", "url_kwd", "doc_id", "kb_id", "available_int", "chunk_order_int",
                       "docnm_kwd", "content_with_weight", "structure_kwd"]

    def __init__(self, backend, scope, still_authorized):
        self.backend, self.scope, self.still_authorized = backend, scope, still_authorized
        self.seen = {}
        self.document_ids = None
        self.auxiliary_ids = {}

    def check(self):
        if not self.still_authorized(self.scope):
            raise EngineError("UNAUTHORIZED_SCOPE", "revoked/stale scope")

    def validate_row(self, row, auxiliary=None):
        allowed = {s.key: s for s in self.scope.sources}
        source = allowed.get(row.get("source_version_kwd"))
        if (not source or row.get("scope_key_kwd") != self.scope.key
                or str(row.get("doc_id")) != source.document_id
                or str(row.get("source_id")) != source.source_id
                or row.get("version_kwd") != source.version
                or row.get("generation_kwd") != self.scope.generation
                or row.get("kb_id") != self.scope.bot_id
                or row.get("available_int") != (0 if auxiliary else 1)
                or (auxiliary and row.get("artifact_role_kwd") != auxiliary)
                or (self.document_ids is not None and source.document_id not in self.document_ids)):
            raise EngineError("UNAUTHORIZED_SCOPE", "returned identity")
        text = row.get("content_with_weight")
        if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != row.get("content_sha_kwd"):
            raise EngineError("PROVENANCE_FAILED", "stored text")
        return source

    def search(self, fields, highlights, condition, expressions, order, offset, limit, indexes, kb_ids, **kwargs):
        # Upstream TOC is an unavailable auxiliary row, never an ordinary hit.
        auxiliary = "toc" if condition.get("toc_kwd") == "toc" else None
        if auxiliary and not condition.get("doc_id"):
            raise EngineError("UNAUTHORIZED_SCOPE", "TOC requires selected document")
        return self._search(fields, highlights, condition, expressions, order, offset, limit,
                            indexes, kb_ids, auxiliary=auxiliary, **kwargs)

    def _search(self, fields, highlights, condition, expressions, order, offset, limit, indexes, kb_ids,
                *, auxiliary=None, **kwargs):
        self.check()
        if indexes != [self.scope.index] or kb_ids != [self.scope.bot_id]:
            raise EngineError("UNAUTHORIZED_SCOPE", "backend routing")
        if not self.scope.sources:
            return {"hits": {"total": {"value": 0}, "hits": []}}
        condition = copy.deepcopy(condition)
        permitted = {s.document_id for s in self.scope.sources}
        if self.document_ids is not None:
            permitted &= self.document_ids
        if isinstance(condition.get("doc_id"), str):
            condition["doc_id"] = [condition["doc_id"]]
        if condition.get("doc_id") is not None and not set(condition["doc_id"]).issubset(permitted):
            raise EngineError("UNAUTHORIZED_SCOPE", "document filter")
        if not permitted or condition.get("doc_id") == []:
            return {"hits": {"total": {"value": 0}, "hits": []}}
        if self.document_ids is not None and "doc_id" not in condition:
            condition["doc_id"] = sorted(permitted)
        try:
            ready_keys = self.backend.ready_sources(self.scope)
            allowed_keys = {s.key for s in self.scope.sources}
            if not ready_keys.issubset(allowed_keys):
                raise EngineError("UNAUTHORIZED_SCOPE", "index readiness")
            if not ready_keys:
                return {"hits": {"total": {"value": 0}, "hits": []}}
            condition.update(scope_key_kwd=self.scope.key, available_int=0 if auxiliary else 1,
                             source_version_kwd=sorted(ready_keys))
            if auxiliary:
                condition["artifact_role_kwd"] = auxiliary
            fields = list(dict.fromkeys(list(fields) + self.SECURITY_FIELDS + ["mom_id", "artifact_role_kwd"]))
            result = self.backend.search(fields, highlights, condition, expressions, order,
                                         offset, limit, indexes, kb_ids, **kwargs)
        except EngineError:
            raise
        except Exception:
            raise EngineError("RETRIEVAL_FAILED", "backend") from None
        self.check()
        for hit in result.get("hits", {}).get("hits", []):
            row = hit.get("_source", {})
            self.validate_row(row, auxiliary)
            if row.get("source_version_kwd") not in ready_keys:
                raise EngineError("UNAUTHORIZED_SCOPE", "returned readiness")
            if condition.get("doc_id") is not None and row.get("doc_id") not in condition["doc_id"]:
                raise EngineError("UNAUTHORIZED_SCOPE", "returned document filter")
            if auxiliary:
                self.auxiliary_ids[hit["_id"]] = auxiliary
            self.seen[hit["_id"]] = copy.deepcopy(row)
            record("authorized_candidate", chunk_id=hit["_id"], organization_id=self.scope.organization_id,
                   bot_id=self.scope.bot_id, scope_key=self.scope.key, generation=self.scope.generation,
                   source_id=row["source_id"], document_id=row["doc_id"], version=row["version_kwd"],
                   source_version_key=row["source_version_kwd"], text_sha256=row["content_sha_kwd"],
                   available=row["available_int"], auxiliary=auxiliary,
                   ready_verified=True, text_hash_verified=True,
                   requested_documents=sorted(self.document_ids) if self.document_ids is not None else None)
        return result

    def get(self, chunk_id, index, kb_ids):
        """Upstream ID lookup, with explicit linked-parent or current-TOC provenance."""
        from .upstream.doc_store import OrderByExpr
        if index != self.scope.index or not kb_ids or set(kb_ids) != {self.scope.bot_id}:
            raise EngineError("UNAUTHORIZED_SCOPE", "ID routing")
        children = [r for r in self.seen.values() if r.get("mom_id") == chunk_id and r.get("available_int") == 1]
        auxiliary = "parent" if children else None
        condition = {"id": [chunk_id]}
        if children:
            keys = {r["source_version_kwd"] for r in children}
            if len(keys) != 1:
                raise EngineError("UNAUTHORIZED_SCOPE", "cross-source parent link")
            condition["doc_id"] = [children[0]["doc_id"]]
        else:
            # TOC-supplied IDs may only retrieve rows in the TOC's own document.
            toc_rows = [r for i, r in self.seen.items() if self.auxiliary_ids.get(i) == "toc"
                        and any(chunk_id in item.get("ids", []) for item in json.loads(r["content_with_weight"]))]
            if not toc_rows:
                raise EngineError("UNAUTHORIZED_SCOPE", "unproven auxiliary ID")
            keys = {r["source_version_kwd"] for r in toc_rows}
            if len(keys) != 1:
                raise EngineError("UNAUTHORIZED_SCOPE", "ambiguous TOC link")
            condition["doc_id"] = [toc_rows[0]["doc_id"]]
        # Unlike the fixture backend, Elasticsearch honors _source projection.
        # Upstream get() returns these payload fields as well as identity fields.
        payload_fields = ["content_ltks", "important_kwd", "position_int", "doc_type_kwd",
                          f"q_{self.scope.dimension}_vec"]
        result = self._search(payload_fields, [], condition, [], OrderByExpr(), 0, 1,
                              [index], [self.scope.bot_id], auxiliary=auxiliary)
        hits = result["hits"]["hits"]
        if not hits:
            return None
        row = hits[0]["_source"]
        if hits[0]["_id"] != chunk_id or row["source_version_kwd"] not in keys:
            raise EngineError("UNAUTHORIZED_SCOPE", "auxiliary relationship")
        record("authorized_relationship", chunk_id=chunk_id, route=auxiliary or "toc_leaf",
               source_version_key=row["source_version_kwd"], linked_source_versions=sorted(keys))
        return copy.deepcopy(row)

    def existing_doc_ids(self, ids):
        self.check()
        return set(ids) & {s.document_id for s in self.scope.sources}

    @staticmethod
    def get_total(result):
        return result["hits"]["total"]["value"]

    @staticmethod
    def get_doc_ids(result):
        return [h["_id"] for h in result["hits"]["hits"]]

    @staticmethod
    def get_fields(result, fields):
        return {h["_id"]: dict(h["_source"], _score=h.get("_score", 0))
                for h in result["hits"]["hits"]}

    @staticmethod
    def get_scores(result):
        # Elasticsearch cosine KNN encodes score as (1 + cosine) / 2.
        return {h["_id"]: 2 * float(h["_score"]) - 1 for h in result["hits"]["hits"]}

    @staticmethod
    def get_highlight(result, keywords, field):
        return {}

    @staticmethod
    def get_aggregation(result, field):
        return []


class SourceRegistry:
    """Local engine's write ledger only, not an authorization database."""
    def __init__(self):
        self._digests = {}
        self.lock = threading.RLock()

    def register(self, scope, source, digest):
        key = (scope.key, source.key)
        if key in self._digests and self._digests[key] != digest:
            raise EngineError("INGESTION_FAILED", "changed content requires new source version")
        return key
