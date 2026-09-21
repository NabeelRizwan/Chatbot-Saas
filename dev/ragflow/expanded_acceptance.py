"""One-shot native validation, authored AFTER retrieval runtime freeze.

Expected fields are post-result assessment only, never query/ranking inputs.
No retries or result-conditioned engine changes. No prior corpus mutations.
"""
import hashlib
import base64
import gzip
import json
import os
from pathlib import Path
import time
from native_acceptance import Client, QUESTIONS, verify_pack
from acceptance_job import emit_report

REPORT = {"retrieval_algorithm_freeze": "ef97a2dca4874e1a53b409738b3037b418b3f9a8",
          "runtime_freeze": "ed6dde00dc3742bf899cac3dbcd38fc7e0d4e2f3",
          "queries": [], "holdout": [], "security": [],
          "quality_mode": "uniform upstream keyword=True; other optional query modes off"}


def emit_expanded(report, mode):
    # Lossless trace transport only. Scan plaintext BEFORE compressing it.
    raw = json.dumps(report, sort_keys=True).encode()
    for name in ("RAGFLOW_DEV_TOKEN_A", "RAGFLOW_DEV_TOKEN_B", "RAGFLOW_DEV_ADMIN_TOKEN", "RAGFLOW_DEV_GEMINI_API_KEY"):
        secret = os.environ.get(name, "")
        assert not secret or secret.encode() not in raw
    emit_report({"encoding": "gzip+base64", "sha256": hashlib.sha256(raw).hexdigest(),
        "uncompressed_bytes": len(raw), "payload": base64.b64encode(gzip.compress(raw, mtime=0)).decode()}, mode)


def validate_trace_observations(result, tenant):
    """Assessment only: never supplies a query, scope, score or selection input."""
    trace = result["trace"]
    observation = trace["observation"]
    assert observation["dropped_events"] == 0
    rows = {}
    for event in observation["events"]:
        if event["kind"] != "authorized_candidate":
            continue
        assert event["organization_id"] == result["organization_id"] == "synthetic-org-" + tenant
        assert event["bot_id"] == result["bot_id"] == "synthetic-bot-" + tenant
        assert event["generation"] == result["generation"]
        assert event["ready_verified"] and event["text_hash_verified"]
        assert event["auxiliary"] in (None, "parent", "toc")
        assert event["available"] == (0 if event["auxiliary"] else 1)
        if event["requested_documents"] is not None:
            assert event["document_id"] in event["requested_documents"]
        rows[event["chunk_id"]] = event
    ids = {h["chunk_id"] for h in trace["lexical_candidates"] + trace["vector_candidates"]}
    ids.update(h["chunk_id"] for call in trace["hybrid_calls"] for h in call["hits"])
    ids.update(h["chunk_id"] for h in result["evidence"] + result["citations"])
    assert ids <= rows.keys()
    for item in result["evidence"]:
        row = rows[item["chunk_id"]]
        for key in ("scope_key", "source_id", "document_id", "version", "text_sha256"):
            assert item[key] == row[key]
    return rows


def main():
    from ragflow_dev.config import Settings
    from elasticsearch import Elasticsearch
    from ragflow_dev.authority import Authority
    from ragflow_derived.storage import ScopedStore, ElasticsearchBackend
    settings = Settings.from_env()
    if os.environ.get("RAGFLOW_DEV_EXPANSION_GATE") != "ONCE_AFTER_FREEZE":
        raise RuntimeError("EXPLICIT_GATE_REQUIRED")
    client = Client("https://ragflow-dev-backend-production.up.railway.app")
    started = time.perf_counter()
    REPORT["health"] = client.call("GET", "/ragflow-dev/health", tenant=None)
    assert REPORT["health"]["upstream_components"]["parent_child"] == "available"
    assert REPORT["health"]["upstream_components"]["chat_callback"] == "configured"
    assert REPORT["health"]["upstream_components"]["chat_calls"] == 0
    REPORT["starting_inventory"] = {t: client.call("GET", "/ragflow-dev/sources", tenant=t) for t in ("a", "b")}
    # Assert this cannot silently replay after fixture creation.
    assert all(not any(s.startswith("hb-") or s in ("expanded-parent", "expanded-toc") for s in v["sources"])
               for v in REPORT["starting_inventory"].values())
    candidate_sets = {"a": set(), "b": set()}
    candidate_roles = {"a": {}, "b": {}}
    def capture(result, tenant):
        verify_pack(result, tenant)
        rows = validate_trace_observations(result, tenant)
        candidate_sets[tenant].update(rows)
        candidate_roles[tenant].update({cid: row["auxiliary"] for cid, row in rows.items()})

    for category, question, _ in QUESTIONS:
        result = client.call("POST", "/ragflow-dev/retrieve", {"query": question, "trace": True, "options": {"keyword": True}})
        capture(result, "a")
        REPORT["queries"].append({"category": category, "question": question, "result": result})

    data = json.loads(Path(__file__).with_name("generic_holdout_b.json").read_text())
    REPORT["holdout_definition_sha256"] = hashlib.sha256(Path(__file__).with_name("generic_holdout_b.json").read_bytes()).hexdigest()
    REPORT["holdout_ingestion"] = []
    for tenant in ("a", "b"):
        for doc in data["documents"]:
            body = dict(doc, expected_version=0, url="https://example.test/holdout-b/" + tenant + "/" + doc["source_id"])
            body["content"] += "\n\nPrivate fixture marker: " + ("TOPAZ-18" if tenant == "a" else "ZIRCON-27") + "."
            REPORT["holdout_ingestion"].append(client.call("POST", "/ragflow-dev/ingest", body, tenant=tenant))
    holdout_docs = ["doc-" + d["source_id"] for d in data["documents"]]
    for item in data["questions"]:
        # Entire holdout corpus scope, NOT expected-answer document scope.
        result = client.call("POST", "/ragflow-dev/retrieve", {"query": item["question"], "trace": True,
            "document_ids": holdout_docs, "options": {"keyword": True}})
        capture(result, "a")
        text = "\n".join(e["text"] for e in result["evidence"]).casefold()
        sources = {e["source_id"] for e in result["evidence"]}
        missing = [s for s in item["required_sources"] if s not in sources]
        absent = [v for v in item["required_text"] if v.casefold() not in text]
        REPORT["holdout"].append(dict(item, result=result, missing_sources=missing, missing_fields=absent,
                                      classification="full" if not missing and not absent else "partial" if sources else "empty"))

    # Separate mechanical new-component test; not a quality rescue/tuning fixture.
    text = "Calibration card. Calibration marker is MECHANICAL-64. Close the cover before operation."
    REPORT["parent_ingest"] = client.call("POST", "/ragflow-dev/ingest", {
        "source_id": "expanded-parent", "expected_version": 0, "title": "Calibration card",
        "kind": "txt", "content": text, "child_delimiters": ["."]})
    parent = client.call("POST", "/ragflow-dev/context", {
        "query": "Calibration marker", "document_ids": ["doc-expanded-parent"], "trace": True})
    capture(parent, "a")
    REPORT["parent_result"] = parent
    assert len(parent["evidence"]) == 1 and parent["evidence"][0]["text"] == text
    assert any(call["expressions"] == [] for call in parent["trace"]["hybrid_calls"])

    for tenant, foreign in (("a", "ZIRCON-27"), ("b", "TOPAZ-18")):
        result = client.call("POST", "/ragflow-dev/retrieve", {"query": "Soil sample bag label " + foreign,
            "document_ids": holdout_docs, "trace": True}, tenant=tenant)
        capture(result, tenant)
        assert foreign not in result["context"]
        REPORT["security"].append({"tenant": tenant, "foreign_marker_excluded": True, "result": result})
    def validate_saved_candidates():
        es = Elasticsearch(settings.es_url, request_timeout=20, max_retries=0)
        try:
            authority = Authority(es)
            for tenant, ids in candidate_sets.items():
                s = authority.active_scope(tenant)
                store = ScopedStore(ElasticsearchBackend(es), s, lambda candidate: authority.authorized(tenant, candidate))
                store.check()
                ready = store.backend.ready_sources(s)
                for row in es.mget(index=s.index, ids=sorted(ids))["docs"]:
                    assert row.get("found")
                    store.validate_row(row["_source"], candidate_roles[tenant][row["_id"]])
                    assert row["_source"]["source_version_kwd"] in ready
                store.check()
            assert candidate_sets["a"].isdisjoint(candidate_sets["b"])
            REPORT["candidate_isolation"] = {"a_validated": len(candidate_sets["a"]), "b_validated": len(candidate_sets["b"]), "overlap": 0,
                "coverage": "SAME8 + HOLDOUT_B + diagnostic/hybrid/parent/TOC/citations"}
        finally:
            es.close()
    validate_saved_candidates()
    for payload in ({"organization_id": "synthetic-org-b"}, {"bot_id": "synthetic-bot-b"},
                    {"generation": "stale"}, {"document_ids": ["foreign-document"]}):
        client.call("POST", "/ragflow-dev/retrieve", dict(query="protocol", **payload), expected=403)
    client.call("POST", "/ragflow-dev/retrieve", {"query": "protocol"}, tenant=None, expected=401)
    # Independent component smoke. At most four calls remain in the process
    # budget after the sixteen fixed quality requests. No automatic retry run.
    toc_text = "# Instrument protocol\n\n## Calibration\nRun the calibration lamp for ten minutes.\n\n## Shutdown\nClose the shutter before disconnecting the power cable."
    REPORT["toc_ingest"] = client.call("POST", "/ragflow-dev/ingest", {"source_id": "expanded-toc",
        "expected_version": 0, "content": toc_text, "kind": "md", "title": "Instrument protocol", "generate_toc": True})
    toc_result = client.call("POST", "/ragflow-dev/retrieve", {"query": "Instrument protocol shutdown",
        "document_ids": ["doc-expanded-toc"], "trace": True, "options": {"toc_enhance": True}})
    capture(toc_result, "a")
    REPORT["toc_result"] = toc_result
    REPORT["followup_result"] = client.call("POST", "/ragflow-dev/retrieve", {
        "query": "And what must I close before disconnecting its power?", "document_ids": ["doc-expanded-toc"],
        "messages": [{"role": "user", "content": "I am reading the Instrument protocol."}],
        "options": {"refine_multiturn": True}, "trace": True})
    capture(REPORT["followup_result"], "a")
    validate_saved_candidates()
    client.call("DELETE", "/ragflow-dev/source/expanded-parent", {"expected_version": 1})
    client.call("POST", "/ragflow-dev/retrieve", {"query": "Calibration marker", "document_ids": ["doc-expanded-parent"]}, expected=403)
    REPORT["parent_lifecycle"] = "PASS"
    REPORT["model_health_after"] = client.call("GET", "/ragflow-dev/health", tenant=None)["upstream_components"]
    REPORT["provider_calls"] = REPORT["model_health_after"]["chat_calls"]
    assert REPORT["provider_calls"] <= 20
    REPORT["final_inventory"] = {t: client.call("GET", "/ragflow-dev/sources", tenant=t) for t in ("a", "b")}
    for tenant in ("a", "b"):
        old = REPORT["starting_inventory"][tenant]["sources"]
        assert all(REPORT["final_inventory"][tenant]["sources"][sid] == value for sid, value in old.items())
    REPORT["original_source_inventory_unchanged"] = True
    REPORT["elapsed_seconds"] = time.perf_counter() - started
    emit_expanded(REPORT, "expanded")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback
        import re
        frames = traceback.extract_tb(exc.__traceback__)
        REPORT["failure"] = {"type": type(exc).__name__,
            "http_status": str(exc) if re.fullmatch(r"HTTP_STATUS_\d+_EXPECTED_\d+", str(exc)) else None}
        # Observation only: no provider retry or additional retrieval request.
        try:
            REPORT["model_health_after"] = Client("https://ragflow-dev-backend-production.up.railway.app").call(
                "GET", "/ragflow-dev/health", tenant=None)["upstream_components"]
            REPORT["provider_calls"] = REPORT["model_health_after"]["chat_calls"]
        except Exception:
            REPORT["failure_health_unavailable"] = True
        print("EXPANDED_ACCEPTANCE_FAILED " + json.dumps({"type": type(exc).__name__,
            "frames": [{"file": os.path.basename(f.filename), "line": f.lineno} for f in frames]}), flush=True)
        emit_expanded(REPORT, "expanded_partial")
        raise SystemExit(1) from None
    finally:
        for key in ("RAGFLOW_DEV_TOKEN_A", "RAGFLOW_DEV_TOKEN_B", "RAGFLOW_DEV_ADMIN_TOKEN", "RAGFLOW_DEV_GEMINI_API_KEY"):
            os.environ.pop(key, None)
