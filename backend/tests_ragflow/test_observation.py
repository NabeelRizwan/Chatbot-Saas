"""Offline non-interference proof; network is blocked by the suite fixture."""
import asyncio
import ast
import copy
import importlib
import json
import subprocess
from pathlib import Path
from unittest.mock import Mock
import pytest
from ragflow_derived.contracts import EngineError
from ragflow_derived.engine import EngineConfig
from ragflow_derived.observation import observation, record, observe_dealer
from ragflow_derived.orchestration import QueryOptions
from ragflow_derived.model_runtime import AuthorizedChatModel
from .fixtures import engine, scope
from .test_upstream_expansion import ChatDouble


@pytest.mark.parametrize("keyword,followup", [(False, False), (True, False), (False, True)])
@pytest.mark.parametrize("parent", [False, True])
@pytest.mark.parametrize("neural", [0.01, 0.8])
def test_identical_inputs_candidates_scores_evidence_context_with_observation(keyword, followup, parent, neural):
    s = scope()
    outputs = []
    for enabled in (False, True):
        reranker = Mock(similarity=Mock(side_effect=lambda q, docs: ([neural] * len(docs), 0)))
        e = engine(config=EngineConfig(similarity_threshold=0.2), reranker=reranker)
        e.chat_model = ChatDouble("maintenance email", "maintenance email")
        e.ingest(s, "manual", "Maintenance instructions. Email assistance available.",
                 child_delimiters=["."] if parent else [])
        e.ingest(s, "terms", "Renewal cancellation terms.")
        with observation(enabled) as observed:
            evidence = asyncio.run(e.retrieve(s, "maintenance details", options=QueryOptions(keyword=keyword,
                refine_multiturn=followup), messages=[{"role": "user", "content": "maintenance"}] if followup else []))
            pack = e.build_context(s, evidence)
        outputs.append((evidence, pack, e.chat_model.calls, reranker.similarity.call_args_list,
                        json.dumps(e.backend.calls, default=lambda x: vars(x), sort_keys=True)))
        if enabled:
            assert observed["dropped_events"] == 0
            events = observed["events"]
            assert any(x["kind"] == "prepared_query" for x in events)
            assert any(x["kind"] == "rerank_scores" for x in events)
            assert sum(x["kind"] == "model_callback" for x in events) == int(keyword or followup)
            for event in events:
                if event["kind"] == "rerank_scores":
                    for candidate in event["candidates"]:
                        assert candidate["passes_cutoff"] == (candidate["similarity"] >= 0.2)
            # Mutating diagnostic copies cannot mutate retrieved evidence.
            events.clear()
        else:
            assert observed is None
    assert outputs[0] == outputs[1]


def test_observation_is_request_local_bounded_and_copies_data():
    value = {"items": [1]}
    with observation() as outer:
        record("safe", value=value)
        value["items"].append(2)
        with observation() as inner:
            record("inner")
        for _ in range(4097):
            record("bounded")
    assert outer["events"][0]["value"] == {"items": [1]}
    assert len(inner["events"]) == 1
    assert len(outer["events"]) == 4096 and outer["dropped_events"] == 2
    record("outside")
    assert len(outer["events"]) == 4096


@pytest.mark.parametrize("enabled", [False, True])
def test_scope_failure_and_error_suppression_unchanged(enabled):
    e, s = engine(), scope()
    e.ingest(s, "manual", "Maintenance.")
    e.still_authorized = lambda s: False
    with observation(enabled) as data:
        with pytest.raises(EngineError, match="UNAUTHORIZED_SCOPE"):
            asyncio.run(e.retrieve(s, "maintenance"))
    if data:
        assert not data["events"]
    class Broken(ChatDouble):
        async def async_chat(self, *args, **kwargs):
            raise RuntimeError("SECRET_TOKEN")
    with observation(enabled) as data:
        with pytest.raises(EngineError) as exc:
            asyncio.run(AuthorizedChatModel(Broken(), lambda: None).async_chat("secret system", []))
    assert "SECRET" not in str(exc.value)
    assert "SECRET" not in json.dumps(data)
    assert "secret system" not in json.dumps(data)


def test_toc_and_parent_observers_forward_original_objects_unchanged():
    before = [{"chunk_id": "child", "similarity": 0.4}]
    after = [{"chunk_id": "parent", "similarity": 0.4}]
    class DealerDouble:
        def rerank_by_model(self, *args): return None
        def retrieval_by_children(self, chunks, tenants):
            assert chunks is before and tenants is authority
            return after
        async def retrieval_by_toc(self, query, chunks, tenants, model, topn):
            assert chunks is before and tenants is authority and model is callback
            return after
    authority, callback = ["scope"], object()
    with observation() as data:
        dealer = observe_dealer(DealerDouble(), 0.2)
        assert dealer.retrieval_by_children(before, authority) is after
        assert asyncio.run(dealer.retrieval_by_toc("q", before, authority, callback, 12)) is after
    assert before == [{"chunk_id": "child", "similarity": 0.4}]
    after[0]["similarity"] = 99
    assert data["events"][0]["after"][0]["similarity"] == 0.4


def test_actual_upstream_toc_output_identical_with_observation(monkeypatch):
    import ragflow_derived.upstream.structure as structure
    async def toc_output(*args):
        return [{"level": "1", "title": "Reference", "chunk_id": 0}]
    monkeypatch.setattr(structure, "run_toc_from_text", toc_output)
    outputs = []
    for enabled in (False, True):
        e, s = engine(), scope()
        e.chat_model = ChatDouble('[{"score": 10}]')
        e.ingest(s, "manual", "A reference fact.", generate_toc=True)
        with observation(enabled) as data:
            evidence = asyncio.run(e.retrieve(s, "reference", options=QueryOptions(toc_enhance=True)))
        outputs.append((evidence, e.build_context(s, evidence), e.chat_model.calls))
        if enabled:
            assert any(x["kind"] == "toc_route" for x in data["events"])
            assert any(x["kind"] == "authorized_candidate" and x["auxiliary"] == "toc" for x in data["events"])
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize("name", ["engine.py", "storage.py", "orchestration.py"])
def test_quality_ast_matches_frozen_commit_after_removing_passive_hooks(name):
    root = Path(__file__).resolve().parents[2]
    path = "backend/ragflow_derived/" + name
    old = subprocess.check_output(["git", "show", "8136c0926da39e87adecda1bfe620f07a05b8c4c:" + path], cwd=root)
    class RemoveObservations(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            return None if node.module == "observation" else node
        def visit_Expr(self, node):
            if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "record":
                return None
            return self.generic_visit(node)
        def visit_Call(self, node):
            node = self.generic_visit(node)
            if isinstance(node.func, ast.Name):
                if node.func.id == "observe_dealer": return node.args[0]
                if node.func.id == "component": return node.args[1]
            return node
    current = RemoveObservations().visit(ast.parse((root / path).read_text(encoding="utf-8")))
    assert ast.dump(current, include_attributes=False) == ast.dump(ast.parse(old), include_attributes=False)


@pytest.mark.parametrize("tamper", [None, "foreign", "missing", "dropped"])
def test_same8_scope_validator_detects_incomplete_or_foreign_trace(monkeypatch, tamper):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "dev/ragflow"))
    validate = importlib.import_module("expanded_acceptance").validate_trace_observations
    event = {"kind": "authorized_candidate", "chunk_id": "x", "organization_id": "synthetic-org-a",
        "bot_id": "synthetic-bot-a", "generation": "g", "ready_verified": True,
        "text_hash_verified": True, "auxiliary": None, "available": 1, "requested_documents": None}
    result = {"organization_id": "synthetic-org-a", "bot_id": "synthetic-bot-a", "generation": "g",
        "evidence": [], "citations": [], "trace": {"observation": {"dropped_events": 0, "events": [event]},
            "lexical_candidates": [{"chunk_id": "x"}], "vector_candidates": [], "hybrid_calls": []}}
    if tamper == "foreign": event["bot_id"] = "foreign"
    if tamper == "missing": result["trace"]["observation"]["events"] = []
    if tamper == "dropped": result["trace"]["observation"]["dropped_events"] = 1
    original = copy.deepcopy(result)
    if tamper:
        with pytest.raises(AssertionError): validate(result, "a")
    else:
        assert set(validate(result, "a")) == {"x"}
    assert result == original


def test_lossless_trace_transport_scans_plaintext_before_compression(monkeypatch):
    import base64
    import gzip
    import hashlib
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "dev/ragflow"))
    job = importlib.import_module("expanded_acceptance")
    emitted = []
    monkeypatch.setattr(job, "emit_report", lambda report, mode: emitted.append(report))
    monkeypatch.setenv("RAGFLOW_DEV_GEMINI_API_KEY", "OFFLINE_SECRET_FIXTURE")
    original = {"trace": ["synthetic observation"] * 500}
    job.emit_expanded(original, "test")
    raw = gzip.decompress(base64.b64decode(emitted[0]["payload"]))
    assert json.loads(raw) == original
    assert hashlib.sha256(raw).hexdigest() == emitted[0]["sha256"]
    with pytest.raises(AssertionError):
        job.emit_expanded({"accident": "OFFLINE_SECRET_FIXTURE"}, "test")
    assert len(emitted) == 1
