"""Synthetic tenant authority persisted in the NEW Elasticsearch service only.

One bounded control document per tenant. CAS writes plus fresh pre/post scope
checks fail closed across concurrent requests and overlapping deployments.
An inactive/pending source is never included in a retrieval scope.
"""
import copy
from elasticsearch import ConflictError, NotFoundError
from ragflow_derived.contracts import AuthorizedScope, EngineError, SourceRef, identifier
from .config import TENANTS, PROFILE, DIMENSION

CONTROL_INDEX = "ragflow_dev_authority_v1"


class Authority:
    def __init__(self, client):
        self.client = client

    def initialize(self):
        if not self.client.indices.exists(index=CONTROL_INDEX):
            try:
                self.client.indices.create(index=CONTROL_INDEX, settings={"number_of_shards": 1,
                    "number_of_replicas": 0}, mappings={"dynamic": False})
            except Exception:
                if not self.client.indices.exists(index=CONTROL_INDEX):
                    raise
        for tenant, (org, bot) in TENANTS.items():
            try:
                self.client.create(index=CONTROL_INDEX, id=tenant, refresh="wait_for", document={
                    "organization": org, "bot": bot, "generation": "native-v1", "sources": {}})
            except ConflictError:
                self.read(tenant)

    def read(self, tenant):
        if tenant not in TENANTS:
            raise EngineError("UNAUTHORIZED_SCOPE", "tenant")
        record = self.client.get(index=CONTROL_INDEX, id=tenant)
        data = record["_source"]
        org, bot = TENANTS[tenant]
        if (data.get("organization") != org or data.get("bot") != bot
                or data.get("generation") != "native-v1" or not isinstance(data.get("sources"), dict)
                or len(data["sources"]) > 30):
            raise EngineError("UNAUTHORIZED_SCOPE", "authority integrity")
        return record

    def write(self, tenant, record, data):
        try:
            self.client.index(index=CONTROL_INDEX, id=tenant, document=data, refresh="wait_for",
                if_seq_no=record["_seq_no"], if_primary_term=record["_primary_term"])
        except ConflictError:
            raise EngineError("CONCURRENT_MODIFICATION", "authority CAS") from None

    @staticmethod
    def scope(data, sources):
        return AuthorizedScope(data["organization"], data["bot"], data["generation"],
                               PROFILE, DIMENSION, tuple(sources))

    @staticmethod
    def ref(source_id, entry):
        return SourceRef(source_id, entry["document_id"], str(entry["version"]))

    def active_scope(self, tenant):
        data = self.read(tenant)["_source"]
        return self.scope(data, [self.ref(sid, entry) for sid, entry in sorted(data["sources"].items())
                                 if entry["state"] == "ready"])

    def authorized(self, tenant, scope, *, pending=False):
        data = self.read(tenant)["_source"]
        if scope.key != self.scope(data, ()).key:
            return False
        for ref in scope.sources:
            entry = data["sources"].get(ref.source_id)
            if (not entry or entry["state"] != ("pending" if pending else "ready")
                    or ref != self.ref(ref.source_id, entry)):
                return False
        return True

    def begin(self, tenant, source_id, expected_version):
        identifier(source_id)
        record = self.read(tenant)
        data = copy.deepcopy(record["_source"])
        previous = data["sources"].get(source_id)
        if previous and previous["state"] == "pending":
            raise EngineError("CONCURRENT_MODIFICATION", "pending source")
        current_version = previous["version"] if previous else 0
        if expected_version != current_version:
            raise EngineError("STALE_VERSION", "source version")
        if not previous and len(data["sources"]) >= 30:
            raise EngineError("CAPACITY_EXCEEDED", "synthetic corpus bound")
        entry = {"document_id": "doc-" + source_id, "version": current_version + 1, "state": "pending"}
        identifier(entry["document_id"])
        data["sources"][source_id] = entry
        self.write(tenant, record, data)
        return self.scope(data, [self.ref(source_id, entry)]), previous

    def finish(self, tenant, source_id, version, *, ready):
        record = self.read(tenant)
        data = copy.deepcopy(record["_source"])
        entry = data["sources"].get(source_id)
        if not entry or entry["version"] != version or entry["state"] != "pending":
            raise EngineError("CONCURRENT_MODIFICATION", "activation")
        entry["state"] = "ready" if ready else "failed"
        self.write(tenant, record, data)

    def deactivate(self, tenant, source_id, expected_version):
        record = self.read(tenant)
        data = copy.deepcopy(record["_source"])
        entry = data["sources"].get(source_id)
        if not entry or entry["state"] == "deleted":
            raise EngineError("SOURCE_NOT_FOUND", "source")
        if entry["version"] != expected_version:
            raise EngineError("STALE_VERSION", "delete version")
        if entry["state"] == "pending":
            raise EngineError("CONCURRENT_MODIFICATION", "pending source")
        scope = self.scope(data, [self.ref(source_id, entry)])
        entry["state"] = "deleted"
        self.write(tenant, record, data)  # Revoke before physical deletion.
        return scope
