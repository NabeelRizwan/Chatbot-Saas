"""Offline API/authority tests; NOT a substitute for Railway native acceptance."""
import copy
from dataclasses import replace
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from elasticsearch import ConflictError
from ragflow_derived.contracts import EngineError, SourceRef
from ragflow_dev.authority import Authority, CONTROL_INDEX
from ragflow_dev.app import create_app, Query
from ragflow_dev.config import Settings, FORBIDDEN_PROJECT
from ragflow_dev.runtime import Runtime


class CatalogDouble:
    def __init__(self):
        self.data = {}
        self.indices = SimpleNamespace(exists=lambda **kw: True)
        self.conflict = False

    def create(self, *, id, document, **kwargs):
        if id in self.data:
            raise ConflictError("CAS", meta=SimpleNamespace(status=409), body=None)
        self.data[id] = {"_source": copy.deepcopy(document), "_seq_no": 0, "_primary_term": 1}

    def get(self, *, id, **kwargs):
        return copy.deepcopy(self.data[id])

    def index(self, *, id, document, if_seq_no, **kwargs):
        if self.conflict or self.data[id]["_seq_no"] != if_seq_no:
            raise ConflictError("CAS", meta=SimpleNamespace(status=409), body=None)
        self.data[id] = {"_source": copy.deepcopy(document), "_seq_no": if_seq_no + 1, "_primary_term": 1}


@pytest.fixture
def authority():
    authority = Authority(CatalogDouble())
    authority.initialize()
    return authority


def seed(authority, tenant="a"):
    pending, _ = authority.begin(tenant, "manual", 0)
    authority.finish(tenant, "manual", 1, ready=True)
    return authority.active_scope(tenant)


def test_authority_pending_is_not_retrievable(authority):
    pending, _ = authority.begin("a", "manual", 0)
    assert not authority.active_scope("a").sources
    assert not authority.authorized("a", pending)
    assert authority.authorized("a", pending, pending=True)


def test_authority_update_revokes_old_before_new_ready(authority):
    old = seed(authority)
    current, _ = authority.begin("a", "manual", 1)
    assert not authority.authorized("a", old)
    assert not authority.active_scope("a").sources
    authority.finish("a", "manual", 2, ready=True)
    assert authority.authorized("a", current)
    assert not authority.authorized("a", old)


def test_delete_and_reingest_preserve_monotonic_version(authority):
    old = seed(authority)
    deleted = authority.deactivate("a", "manual", 1)
    assert deleted == old
    assert not authority.authorized("a", old)
    pending, _ = authority.begin("a", "manual", 1)
    assert pending.sources[0].version == "2"


@pytest.mark.parametrize("change", ["organization_id", "bot_id", "generation", "embedding_profile", "dimension", "sources"])
def test_forged_scope_fails_closed(authority, change):
    scope = seed(authority)
    value = 383 if change == "dimension" else (SourceRef("manual", "doc-manual", "999"),) if change == "sources" else "foreign"
    assert not authority.authorized("a", replace(scope, **{change: value}))


def test_overlapping_tenants_are_independent(authority):
    a, b = seed(authority, "a"), seed(authority, "b")
    assert a.index != b.index
    assert not authority.authorized("a", b)
    assert not authority.authorized("b", a)
    authority.deactivate("a", "manual", 1)
    assert authority.authorized("b", b)


def test_authority_write_conflict_never_activates(authority):
    authority.client.conflict = True
    with pytest.raises(EngineError, match="CONCURRENT_MODIFICATION"):
        authority.begin("a", "manual", 0)
    assert not authority.active_scope("a").sources


def test_pending_cannot_be_overwritten_or_deleted(authority):
    authority.begin("a", "manual", 0)
    for action in (lambda: authority.begin("a", "manual", 1), lambda: authority.deactivate("a", "manual", 1)):
        with pytest.raises(EngineError, match="CONCURRENT_MODIFICATION"):
            action()


def test_failed_write_is_inactive(authority):
    authority.begin("a", "manual", 0)
    authority.finish("a", "manual", 1, ready=False)
    assert not authority.active_scope("a").sources


def test_stale_mutation_fails(authority):
    seed(authority)
    for action in (lambda: authority.begin("a", "manual", 0), lambda: authority.deactivate("a", "manual", 2)):
        with pytest.raises(EngineError, match="STALE_VERSION"):
            action()


@pytest.mark.parametrize("field,value", [("organization_id", "synthetic-org-b"), ("bot_id", "synthetic-bot-b"),
                                       ("generation", "stale"), ("source_versions", {"manual": 99})])
def test_query_scope_assertions_cannot_expand(authority, field, value):
    scope = seed(authority)
    with pytest.raises(EngineError):
        Runtime.check_assertions(scope, Query(query="library", **{field: value}))


def test_authority_corruption_fails(authority):
    authority.client.data["a"]["_source"]["bot"] = "foreign"
    with pytest.raises(EngineError, match="UNAUTHORIZED_SCOPE"):
        authority.active_scope("a")


def test_authority_survives_instance_restart(authority):
    expected = seed(authority)
    restarted = Authority(authority.client)
    restarted.initialize()
    assert restarted.active_scope("a") == expected


def test_corpus_capacity_is_bounded(authority):
    for i in range(30):
        authority.begin("a", "source-" + str(i), 0)
    with pytest.raises(EngineError, match="CAPACITY_EXCEEDED"):
        authority.begin("a", "over-limit", 0)


class ApiRuntimeDouble:
    def __init__(self, settings):
        self.closed = False
    def health(self): return {"healthy": True}
    def status(self, tenant): return {"tenant": tenant}
    def ingest(self, tenant, payload): return {"tenant": tenant}
    def retrieve(self, tenant, payload, **kwargs): return {"tenant": tenant}
    def delete(self, tenant, *args): return {"tenant": tenant}
    def close(self): self.closed = True


@pytest.fixture
def api():
    settings = Settings("unused", "a" * 48, "b" * 48, "c" * 48, "new-project")
    with TestClient(create_app(settings, ApiRuntimeDouble)) as client:
        yield client


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/ragflow-dev/sources", None),
    ("POST", "/ragflow-dev/ingest", {"source_id": "manual", "expected_version": 0, "content": "Text"}),
    ("POST", "/ragflow-dev/retrieve", {"query": "library"}),
    ("POST", "/ragflow-dev/context", {"query": "library"}),
    ("DELETE", "/ragflow-dev/source/manual", {"expected_version": 1}),
    ("POST", "/ragflow-dev/failure-check", {"fault": "storage", "query": "library"}),
])
def test_nonhealth_endpoints_need_credential(api, method, path, body):
    response = api.request(method, path, json=body)
    assert response.status_code == 401


def test_credentials_bind_tenants_server_side(api):
    for tenant in ("a", "b"):
        result = api.get("/ragflow-dev/sources", headers={"Authorization": "Bearer " + tenant * 48})
        assert result.json()["tenant"] == tenant
    assert api.get("/ragflow-dev/sources", headers={"Authorization": "Bearer " + "c" * 48}).status_code == 401
    assert api.post("/ragflow-dev/failure-check", headers={"Authorization": "Bearer " + "a" * 48},
                    json={"fault": "storage", "query": "library"}).status_code == 401


def test_unknown_fields_and_bad_input_are_sanitized(api):
    response = api.post("/ragflow-dev/ingest", headers={"Authorization": "Bearer " + "a" * 48},
                        json={"source_id": "manual", "expected_version": 0, "content": "Text", "organization": "foreign"})
    assert response.status_code == 422
    assert response.json() == {"error": "INVALID_INPUT"}


def test_production_project_guard(monkeypatch):
    monkeypatch.setenv("RAILWAY_PROJECT_ID", FORBIDDEN_PROJECT)
    monkeypatch.setenv("RAGFLOW_DEV_PROJECT_ID", FORBIDDEN_PROJECT)
    with pytest.raises(RuntimeError, match="ISOLATED_PROJECT_REQUIRED"):
        Settings.from_env()


@pytest.mark.parametrize("url", ["http://localhost:9200", "https://customer.example:9200", "http://user:pass@ragflow-dev-elasticsearch.railway.internal:9200"])
def test_no_unapproved_storage_url(monkeypatch, url):
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "new-project")
    monkeypatch.setenv("RAGFLOW_DEV_PROJECT_ID", "new-project")
    monkeypatch.setenv("RAGFLOW_DEV_ENGINE", "ragflow-derived")
    monkeypatch.setenv("RAGFLOW_DEV_ES_URL", url)
    with pytest.raises(RuntimeError, match="PRIVATE_DEV_ELASTICSEARCH_REQUIRED"):
        Settings.from_env()
