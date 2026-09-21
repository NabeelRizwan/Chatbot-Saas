"""Outside-container synthetic native smoke. Credentials are process-only env vars.

Run initial once, restart only the new ES service through Railway, then run
--phase persistence. This is not the 90-case benchmark or a tuning harness.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlsplit

DOCUMENTS = [
    ("library", "Library borrowing", "md", "# Library borrowing\n\nMembers may borrow printed books for 21 days. Renewals add 7 days when no other reader is waiting.\n\n- Bring a membership card.\n- Return books to the indoor desk."),
    ("museum", "Museum visits", "html", "<h1>Museum visits</h1><p>The town museum opens Tuesday through Sunday, from 10:00 to 17:00. It is closed on Monday.</p><h2>Admission</h2><p>General admission costs 8 credits. Children under twelve enter free.</p>"),
    ("workshop", "Community workshop", "md", "# Community workshop\n\nResidents can reserve woodworking tools for a two-hour session. Safety induction is required before the first booking.\n\n## Booking\nBook at least one day ahead using the workshop desk."),
    ("transit", "Transit passes", "md", "# Transit passes\n\n| Pass | Price | Validity |\n| --- | --- | --- |\n| Day | 5 credits | One calendar day |\n| Week | 22 credits | Seven consecutive days |\n\nBoth passes cover buses and trams. They do not cover airport coaches."),
    ("garden", "Garden irrigation", "txt", "Garden irrigation\nWater young vegetable seedlings in the early morning. The demonstration garden runs its drip irrigation for fifteen minutes at 06:00. Rain sensors pause watering after heavy rain."),
    ("cafe", "Community cafe", "html", "<h1>Community cafe</h1><p>The cafe serves tea, coffee and sandwiches. Oat milk is available on request.</p><p>Food is prepared in a kitchen that handles wheat, milk and nuts. Ask staff before ordering if you have an allergy.</p>"),
    ("fitness", "Fitness class booking", "md", "# Fitness classes\n\nBeginner yoga meets at 18:00 on Wednesday. Stretching meets at 09:00 on Saturday. Cancel a reservation at least six hours before class to release your place."),
    ("study", "Study rooms", "md", "# Study rooms\n\nThe quiet study room seats twelve people. Group study room Cedar seats six people and can be booked for up to three hours. Food and amplified music are not allowed in either room."),
    ("kayak", "Kayak rental", "md", "# Kayak rental\n\nSingle kayaks cost 14 credits per hour. Double kayaks cost 20 credits per hour. A buoyancy aid is included. Rentals pause during thunderstorms or strong winds."),
    ("recycling", "Recycling depot", "txt", "Recycling depot\nTake used household batteries to the labelled battery bin at the depot. Do not place batteries in mixed recycling. The depot also accepts clean cardboard, glass bottles and aluminium cans."),
    ("delivery", "Parcel collection", "md", "# Parcel collection\n\nParcels are held at reception for five business days. Bring photographic identification and the collection reference. Collection hours are 08:00 to 18:00 on weekdays."),
    ("membership", "Membership plans", "md", "# Membership plans\n\n| Plan | Monthly fee | Included services |\n| --- | --- | --- |\n| Basic | 12 credits | Library and study rooms |\n| Plus | 18 credits | Library, study rooms and fitness classes |\n\nCancel before the next renewal date. Workshop and kayak charges remain separate on both plans."),
]
QUESTIONS = [
    ("exact_fact", "How many days can members borrow printed library books?", "library"),
    ("semantic_paraphrase", "Where can I leave spent household power cells safely?", "recycling"),
    ("lexical", "Cedar group study room capacity", "study"),
    ("multi_document", "What are the opening hours for the museum and parcel collection?", None),
    ("discovery", "Which community services offer book borrowing, classes or shared tools?", None),
    ("comparison", "Compare the Basic and Plus membership monthly fees and included services.", "membership"),
    ("qualified_policy", "Can I rent a kayak during thunderstorms?", "kayak"),
    ("rerank_candidates", "How can I reserve a room or a woodworking workshop session?", None),
]


class Client:
    def __init__(self, url):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname.endswith(".up.railway.app") or parsed.username or parsed.password:
            raise SystemExit("EXPLICIT_RAILWAY_DEV_URL_REQUIRED")
        self.url = url.rstrip("/")

    def call(self, method, path, data=None, tenant="a", expected=200):
        variable = {"a": "RAGFLOW_DEV_TOKEN_A", "b": "RAGFLOW_DEV_TOKEN_B", "admin": "RAGFLOW_DEV_ADMIN_TOKEN"}
        headers = {"Content-Type": "application/json"}
        if tenant:
            headers["Authorization"] = "Bearer " + os.environ[variable[tenant]]
        request = Request(self.url + path, method=method, headers=headers,
                          data=json.dumps(data).encode() if data is not None else None)
        try:
            with urlopen(request, timeout=180) as response:
                code, raw = response.status, response.read()
        except HTTPError as exc:
            code, raw = exc.code, exc.read()
        result = json.loads(raw)
        if code != expected:
            raise RuntimeError("HTTP_STATUS_" + str(code) + "_EXPECTED_" + str(expected))
        return result


def verify_pack(result, tenant):
    assert result["engine"] == "ragflow-derived"
    assert result["organization_id"] == "synthetic-org-" + tenant
    assert result["bot_id"] == "synthetic-bot-" + tenant
    assert result["context_bytes"] == len(result["context"].encode()) <= 131072
    assert result["context_tokens"] <= 8192 and result["units"] <= 48
    ids = set()
    for item, citation in zip(result["evidence"], result["citations"], strict=True):
        assert hashlib.sha256(item["text"].encode()).hexdigest() == item["text_sha256"]
        assert item["chunk_id"] == citation["chunk_id"]
        assert item["version"] == citation["version"]
        assert item["id"] not in ids and item["id"] in result["context"]
        ids.add(item["id"])


def initial(client):
    report = {"health": client.call("GET", "/ragflow-dev/health", tenant=None), "ingestion": [], "queries": [], "security": []}
    for tenant in ("a", "b"):
        for sid, title, kind, content in DOCUMENTS:
            body = content + "\n\n" + ("Tenant amber private reference: AMBER-41." if tenant == "a" else "Tenant cobalt private reference: COBALT-92.")
            report["ingestion"].append(client.call("POST", "/ragflow-dev/ingest", {
                "source_id": sid, "expected_version": 0, "content": body, "kind": kind,
                "title": title, "url": "https://example.test/" + tenant + "/" + sid}, tenant=tenant))
    for category, question, target in QUESTIONS:
        result = client.call("POST", "/ragflow-dev/retrieve", {"query": question, "trace": True})
        verify_pack(result, "a")
        assert "COBALT-92" not in result["context"]
        report["queries"].append({"category": category, "question": question,
            "functional_hit": bool(result["evidence"]) and (target is None or target in {e["source_id"] for e in result["evidence"]}),
            "result": result})
    for tenant, forbidden in (("a", "COBALT-92"), ("b", "AMBER-41")):
        result = client.call("POST", "/ragflow-dev/context", {"query": "Library books " + forbidden, "trace": True}, tenant=tenant)
        verify_pack(result, tenant)
        assert forbidden not in result["context"]
        report["security"].append({"tenant": tenant, "foreign_reference_excluded": True,
            "result_sources": [e["source_id"] for e in result["evidence"]]})
    for payload in ({"organization_id": "synthetic-org-b"}, {"bot_id": "synthetic-bot-b"},
                    {"generation": "stale-generation"}, {"document_ids": ["foreign-document"]}):
        result = client.call("POST", "/ragflow-dev/retrieve", dict(query="Library books", **payload), expected=403)
        assert result["error"] == "UNAUTHORIZED_SCOPE"
    client.call("POST", "/ragflow-dev/retrieve", {"query": "Library books", "source_versions": {"library": 99}}, expected=409)
    client.call("POST", "/ragflow-dev/retrieve", {"query": "Library books"}, tenant=None, expected=401)
    client.call("POST", "/ragflow-dev/ingest", {"content": "missing identity"}, expected=422)
    for fault in ("storage", "embedding", "reranker"):
        result = client.call("POST", "/ragflow-dev/failure-check", {"fault": fault, "query": "Library books"}, tenant="admin", expected=503)
        report.setdefault("controlled_failure_injection", {})[fault] = result
    # A separate synthetic source demonstrates full lifecycle, not a quality fix.
    for version, word in ((0, "LIFECYCLE-FIRST"), (1, "LIFECYCLE-SECOND")):
        client.call("POST", "/ragflow-dev/ingest", {"source_id": "sentinel", "expected_version": version,
            "content": "# Persistence sentinel\n\nThe persistence sentinel code is " + word + ".", "title": "Persistence sentinel"})
        result = client.call("POST", "/ragflow-dev/context", {"query": "Persistence sentinel code", "document_ids": ["doc-sentinel"]})
        verify_pack(result, "a")
        assert word in result["context"]
        if version:
            assert "LIFECYCLE-FIRST" not in result["context"]
    client.call("DELETE", "/ragflow-dev/source/sentinel", {"expected_version": 2})
    client.call("POST", "/ragflow-dev/retrieve", {"query": "sentinel", "document_ids": ["doc-sentinel"]}, expected=403)
    client.call("POST", "/ragflow-dev/ingest", {"source_id": "sentinel", "expected_version": 2,
        "content": "# Persistence sentinel\n\nThe persistence sentinel code is PERSISTENT-ORCHID-73.", "title": "Persistence sentinel"})
    sentinel = client.call("POST", "/ragflow-dev/context", {"query": "Persistence sentinel code", "document_ids": ["doc-sentinel"]})
    verify_pack(sentinel, "a")
    assert "PERSISTENT-ORCHID-73" in sentinel["context"]
    repeated = client.call("POST", "/ragflow-dev/context", {"query": "Persistence sentinel code", "document_ids": ["doc-sentinel"]})
    assert repeated["context"] == sentinel["context"]
    report["sentinel_before_restart"] = sentinel
    report["lifecycle"] = "PASS"
    report["authority_a"] = client.call("GET", "/ragflow-dev/sources")
    report["authority_b"] = client.call("GET", "/ragflow-dev/sources", tenant="b")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--phase", choices=("initial", "persistence"), required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    client = Client(args.url)
    if args.phase == "initial":
        report = initial(client)
        Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"phase": "initial", "generic_queries": len(report["queries"]),
            "functional_hits": sum(q["functional_hit"] for q in report["queries"]),
            "lifecycle": report["lifecycle"], "seconds": time.perf_counter() - started}))
    else:
        report = json.loads(Path(args.output).read_text(encoding="utf-8"))
        result = client.call("POST", "/ragflow-dev/context", {"query": "Persistence sentinel code", "document_ids": ["doc-sentinel"]})
        verify_pack(result, "a")
        assert result["context"] == report["sentinel_before_restart"]["context"]
        assert result["citations"] == report["sentinel_before_restart"]["citations"]
        report["sentinel_after_restart"] = result
        report["restart_persistence"] = "PASS"
        Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("Restart persistence: PASS")


if __name__ == "__main__":
    try:
        main()
    finally:
        for key in ("RAGFLOW_DEV_TOKEN_A", "RAGFLOW_DEV_TOKEN_B", "RAGFLOW_DEV_ADMIN_TOKEN"):
            os.environ.pop(key, None)
