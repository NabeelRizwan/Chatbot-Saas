"""Offline production combination contracts. No DB, provider or model calls."""

import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import httpx

from services.combined_rag import CONTEXT_MAX_CHARS, CombinedRetrievalError, collect_evidence, format_context, policy_identity
from services.combined_rag import pipeline, planner
from services.combined_rag.client import BGEClient, validate_response
from services.combined_rag.config import Config, MODEL, REVISION
from services.combined_rag.merge import interleave
from services.retrieval_contracts import HardKnowledgeScope, ProfileIdentity
from services.structural_chunking import count_tokens


ENV = {"RAG_COMBINED_RERANKER_URL": "http://private.test/rerank",
       "RAG_COMBINED_RERANKER_TOKEN": "synthetic-private-token"}


def item(identity, *, doc_id=10, content=None, org=7, bot=3):
    return {"score": .42,
            "chunk": NS(id=identity, document_id=doc_id, organization_id=org, bot_id=bot,
                content=content or f"Exact complete source {identity}: 1.25 mg, not 12.5 mg.",
                chunk_index=identity, metadata_json={"warning": "retain me"}, status="ready",
                website_id=None, crawl_id=None, document_version_id="version-one",
                embedding_provider="test", embedding_model="embed", embedding_version=1),
            "document": NS(id=doc_id, organization_id=org, bot_id=bot, title=f"Document {doc_id}",
                filename=f"source-{doc_id}.md", source_url=f"https://example.test/product/{doc_id}",
                canonical_url=f"https://example.test/product/{doc_id}", metadata_json={"original": True},
                status="ready", processing_status="completed", website_id=None, crawl_id=None, version=1),
            "match_reasons": ["Original native retrieval"], "selection_signals": {"original": .9}}


def contract():
    hard = HardKnowledgeScope(7, 3, authorized_document_ids=(10, 11),
        active_document_versions=((10, 1, None), (11, 1, None)),
        embedding_profile=ProfileIdentity("test", "embed", 1, 4))
    return NS(execution=NS(hard_scope=hard, scope_decision=NS(effective_document_ids=(10, 11))),
              permitted_document_ids=[10, 11])


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, ENV)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.bot = NS(id=3, organization_id=7, provider="gemini", model_name="configured-gemini")
        self.contract = contract()
        self.trace = NS(diagnostics={})
        self.rows = {"original": [item(1), item(2)],
                     "focus-a": [item(2), item(3)],
                     "focus-b": [item(4, doc_id=11), item(2)]}
        self.calls, self.scores_seen = [], []
        self.responses = {"focus-a": [.9, .2], "focus-b": [.8, .7], "original": [.1, .9]}
        self.auxiliary = patch.object(planner, "generate_auxiliary", return_value='{"queries":["focus-a","focus-b"]}')
        self.auxiliary_call = self.auxiliary.start()
        self.addCleanup(self.auxiliary.stop)
        self.metadata = patch.object(planner, "get_last_auxiliary_metadata", return_value={})
        self.metadata.start()
        self.addCleanup(self.metadata.stop)
        self.scorer_patch = patch.object(pipeline.BGEClient, "score", side_effect=self.score)
        self.scorer = self.scorer_patch.start()
        self.addCleanup(self.scorer_patch.stop)

    def native(self, query, contract, top_k):
        self.calls.append((query, contract, top_k))
        return self.rows[query]

    def score(self, query, documents):
        self.scores_seen.append((query, list(documents)))
        return self.responses.get(query, list(range(len(documents))))

    def run_collection(self, **changes):
        params = dict(bot=self.bot, question="original", query_contract=self.contract,
                      trace=self.trace, retrieve_native=self.native, budget_chars=100000)
        params.update(changes)
        return collect_evidence(**params)

    def test_multifocus_order_complete_evidence_original_metadata_and_provider(self):
        snapshot = deepcopy(self.rows)
        rows, context = self.run_collection()
        self.assertEqual([r["chunk"].id for r in rows], [2, 4, 3, 1])
        self.assertEqual(self.rows, snapshot)
        self.assertIs(rows[0]["chunk"], self.rows["original"][1]["chunk"])
        self.assertEqual(rows[0]["score"], .42)
        self.assertTrue(all(c[1] is self.contract and c[2] == 128 for c in self.calls))
        self.assertEqual(self.scores_seen[0][1][0],
            "Title: Document 10\nContent:\nExact complete source 2: 1.25 mg, not 12.5 mg.")
        self.assertIn("### Source: Document 11 | URL: https://example.test/product/11", context)
        self.assertEqual(context.count("### Source:"), 4)
        self.assertEqual(self.auxiliary_call.call_args.args[0], self.bot)
        self.assertEqual(self.auxiliary_call.call_args.args[1], "original")
        self.assertFalse(self.auxiliary_call.call_args.kwargs["use_auxiliary_model"])
        self.assertEqual(self.auxiliary_call.call_args.kwargs["timeout"], 5.0)
        self.assertTrue(self.trace.diagnostics["combined_rag"]["cacheable"])

    def test_scope_and_lifecycle_violations_fail_before_ranking(self):
        variants = [("document", "organization_id", 999), ("chunk", "bot_id", 999),
                    ("document", "id", 99), ("chunk", "document_id", 99),
                    ("document", "version", 2), ("document", "status", "deleted"),
                    ("document", "processing_status", "processing"),
                    ("chunk", "embedding_model", "foreign-model"), ("chunk", "crawl_id", 5)]
        for source, field, invalid in variants:
            bad = item(9)
            setattr(bad[source], field, invalid)
            self.rows["focus-a"] = [bad]
            with self.subTest(source=source, field=field), self.assertRaises(CombinedRetrievalError):
                self.run_collection()
        self.scorer.assert_not_called()

    def test_soft_scope_is_not_widened_by_planner_query(self):
        self.contract.permitted_document_ids = [10]
        with self.assertRaises(CombinedRetrievalError) as failure:
            self.run_collection()
        self.assertEqual(failure.exception.category, "source_scope_escape")

    def test_wrong_hard_scope_and_empty_scope_do_not_call_provider(self):
        self.contract.execution.hard_scope = replace(self.contract.execution.hard_scope, bot_id=400)
        with self.assertRaises(CombinedRetrievalError):
            self.run_collection()
        self.contract = contract()
        self.contract.execution.hard_scope = replace(self.contract.execution.hard_scope, authorized_document_ids=())
        self.assertEqual(self.run_collection(), ([], ""))
        self.auxiliary_call.assert_not_called()
        self.assertEqual(self.calls, [])

    def test_source_identity_change_even_same_orm_object_detected(self):
        def changing_native(query, contract, top_k):
            if query == "focus-a":
                self.rows["original"][1]["chunk"].content = "Changed evidence under the same ID"
                return [self.rows["original"][1]]
            return self.rows[query]
        with self.assertRaises(CombinedRetrievalError) as failure:
            self.run_collection(retrieve_native=changing_native)
        self.assertEqual(failure.exception.category, "source_identity_changed")

    def test_nonpositive_synthetic_ids_and_duplicate_native_ids_rejected(self):
        for rows in ([item(-10)], [item(0)], [item(2), item(2)]):
            self.rows["original"] = rows
            with self.subTest(ids=[r["chunk"].id for r in rows]), self.assertRaises(CombinedRetrievalError):
                self.run_collection()
        self.auxiliary_call.assert_not_called()

    def test_32_full_pairs_and_unscored_tail_retained(self):
        self.auxiliary_call.return_value = '{"queries":["focus-a"]}'
        self.rows["original"] = [item(100)]
        self.rows["focus-a"] = [item(i) for i in range(1, 41)]
        self.responses["focus-a"] = list(range(32))
        rows, _ = self.run_collection()
        self.assertEqual(len(self.scores_seen[0][1]), 32)
        self.assertEqual(rows[0]["chunk"].id, 32)
        self.assertEqual(len(rows), 41)
        self.assertEqual({r["chunk"].id for r in rows}, {100} | set(range(1, 41)))

    def test_invalid_planner_and_timeout_use_full_original_without_caching(self):
        for raw in ("not JSON", '{"queries":["x"],"document_ids":[999]}'):
            self.auxiliary_call.return_value = raw
            self.calls.clear()
            rows, _ = self.run_collection()
            self.assertEqual([c[0] for c in self.calls], ["original"])
            self.assertEqual([r["chunk"].id for r in rows], [2, 1])
            self.assertFalse(self.trace.diagnostics["combined_rag"]["cacheable"])
        self.auxiliary_call.side_effect = TimeoutError("sensitive message not logged")
        self.run_collection()
        self.assertEqual(self.trace.diagnostics["combined_rag"]["planner_error_type"], "TimeoutError")

    def test_focused_search_rescues_empty_native_and_all_empty_stays_empty(self):
        self.rows["original"] = []
        rows, _ = self.run_collection()
        self.assertEqual({r["chunk"].id for r in rows}, {2, 3, 4})
        self.rows = {key: [] for key in self.rows}
        self.scorer.reset_mock()
        self.assertEqual(self.run_collection(), ([], ""))
        self.scorer.assert_not_called()

    def test_empty_focus_lanes_still_require_bge_on_original_candidates(self):
        self.rows["focus-a"] = []
        self.rows["focus-b"] = []
        rows, _ = self.run_collection()
        self.assertEqual([row["chunk"].id for row in rows], [2, 1])
        self.assertEqual([query for query, _docs in self.scores_seen], ["original"])
        self.assertFalse(self.trace.diagnostics["combined_rag"]["cacheable"])
        self.assertTrue(self.trace.diagnostics["combined_rag"]["empty_focus_fallback"])

    def test_bge_failure_does_not_silently_fall_back(self):
        self.scorer.side_effect = CombinedRetrievalError("reranker_unavailable")
        with self.assertRaises(CombinedRetrievalError) as failure:
            self.run_collection()
        self.assertEqual(failure.exception.category, "reranker_unavailable")

    def test_incomplete_or_nonfinite_scores_fail(self):
        for scores in ([1], [1, float("nan")], [True, 1]):
            self.scorer.side_effect = None
            self.scorer.return_value = scores
            with self.subTest(scores=scores), self.assertRaises(CombinedRetrievalError):
                self.run_collection()

    def test_actual_tokenizer_and_whole_prefix_context_boundaries(self):
        first, second = item(1), item(2)
        selected, first_text = format_context([first], 100000)
        self.assertEqual(selected, [first])
        selected, text = format_context([first, second], len(first_text))
        self.assertEqual(selected, [first])
        self.assertEqual(text, first_text)
        huge = item(3, content="evidence " * 5000)
        self.assertGreater(count_tokens(huge["chunk"].content), 4000)
        self.assertEqual(format_context([huge, first], 1000000), ([], ""))
        with patch.object(pipeline, "count_tokens", side_effect=ValueError("corrupt local tokenizer")):
            with self.assertRaises(CombinedRetrievalError) as failure:
                format_context([first], 10000)
        self.assertEqual(failure.exception.category, "tokenizer_unavailable")

    def test_oversized_first_passage_is_technical_context_failure(self):
        with self.assertRaises(CombinedRetrievalError) as failure:
            self.run_collection(budget_chars=1)
        self.assertEqual(failure.exception.category, "context_budget_exhausted")

    def test_context_envelope_does_not_shrink_source_window_to_old_char_default(self):
        original = item(1, content="remarkable " * 1200)
        self.assertGreater(len(original["chunk"].content), 10000)
        self.assertLess(count_tokens(original["chunk"].content), 4000)
        rows, text = format_context([original], CONTEXT_MAX_CHARS)
        self.assertEqual(rows, [original])
        self.assertIn(original["chunk"].content, text)
        oversized_header = item(2)
        oversized_header["document"].title = "x" * CONTEXT_MAX_CHARS
        self.assertEqual(format_context([oversized_header], CONTEXT_MAX_CHARS * 2), ([], ""))
        self.assertEqual(policy_identity()["context_max_chars"], CONTEXT_MAX_CHARS)

    def test_native_exception_propagates_without_provider_retry(self):
        def offline(*args):
            raise RuntimeError("native retrieval offline")
        with self.assertRaises(RuntimeError):
            self.run_collection(retrieve_native=offline)
        self.auxiliary_call.assert_not_called()

    def test_concurrent_tenants_with_same_local_ids_do_not_share_evidence(self):
        self.auxiliary_call.side_effect = lambda bot, question, *args, **kwargs: json.dumps({"queries": [question]})
        self.scorer.side_effect = lambda query, documents: [1.0] * len(documents)
        def run(org):
            bot = NS(id=3, organization_id=org, provider="gemini", model_name="configured-gemini")
            scoped = contract()
            scoped.execution.hard_scope = replace(scoped.execution.hard_scope, organization_id=org)
            rows = [item(1, content=f"Private evidence owned by organization {org}.", org=org)]
            return collect_evidence(bot=bot, question=f"org-{org}", query_contract=scoped,
                trace=NS(diagnostics={}), retrieve_native=lambda *args: rows, budget_chars=10000)
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = list(pool.map(run, [7, 8]))
        self.assertIn("organization 7", a[1])
        self.assertNotIn("organization 8", a[1])
        self.assertIn("organization 8", b[1])
        self.assertNotIn("organization 7", b[1])


class HTTPAndConfigurationTests(unittest.TestCase):
    def request(self, *, status=200, payload=None):
        def handler(request):
            self.assertEqual(request.headers["Authorization"], "Bearer fixture")
            self.assertEqual(json.loads(request.content), {"query": "question", "documents": ["full original text"]})
            return httpx.Response(status, json=payload, headers={"Location": "https://foreign.test/rerank"})
        client = BGEClient(Config("http://private.test/rerank", "fixture"), transport=httpx.MockTransport(handler))
        return client.score("question", ["full original text"])

    def test_pinned_identity_exact_score_and_full_token_contract(self):
        good = {"model": MODEL, "revision": REVISION, "scores": [.5], "token_counts": [32]}
        self.assertEqual(self.request(payload=good), [.5])
        for change in ({"revision": "latest"}, {"model": "other"}, {"scores": []},
                       {"token_counts": [8193]}, {"token_counts": [True]}):
            with self.subTest(change=change), self.assertRaises(CombinedRetrievalError):
                self.request(payload={**good, **change})
        with self.assertRaises(CombinedRetrievalError):
            validate_response({**good, "scores": [float("inf")]}, 1)

    def test_no_redirects_and_failure_categories(self):
        for status, category in ((307, "reranker_request_rejected"), (401, "reranker_request_rejected"),
                                 (503, "reranker_unavailable"), (422, "reranker_input_rejected")):
            with self.subTest(status=status), self.assertRaises(CombinedRetrievalError) as failure:
                self.request(status=status)
            self.assertEqual(failure.exception.category, category)

    def test_endpoint_is_required_operator_configuration_without_legacy_bypass(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(CombinedRetrievalError):
                Config.from_env()
        # An obsolete feature flag cannot disable the mandatory pipeline or
        # make missing private-reranker configuration appear healthy.
        with patch.dict(os.environ, {"RAG_COMBINED_ENABLED": "0"}, clear=True):
            with self.assertRaises(CombinedRetrievalError):
                Config.from_env()
        for url in ("file:///rerank", "https://u:p@private.test/rerank", "https://private.test/rerank?target=x",
                    "http://private.test/rerank/", "http://private.test:bad/rerank"):
            with self.subTest(url=url), self.assertRaises(CombinedRetrievalError):
                Config(url, "secret")
        for token in (" ", "  secret", "secret ", "se cret", "secret\t", "secret\n"):
            with self.subTest(token=repr(token)), self.assertRaises(CombinedRetrievalError):
                Config("http://private.test/rerank", token)
        self.assertNotIn("secret", repr(Config("http://private.test/rerank", "secret")))
        self.assertNotIn("token", json.dumps(policy_identity()).replace("source_tokens", "").replace("tokenizer", ""))

    def test_strict_planner_schema_no_extra_permissions_or_unbounded_queries(self):
        for raw in ('[]', '{"queries":[]}', '{"queries":["x"],"scope":"all"}',
                    '{"queries":["a","b","c","d"]}', json.dumps({"queries": ["x" * 513]})):
            with self.subTest(raw=raw[:70]), self.assertRaises(ValueError):
                planner.parse_queries(raw)
        self.assertEqual(planner.parse_queries('{"queries":["Model X 1.25 mg","Model X 1.25 mg"]}'), ["Model X 1.25 mg"])

    def test_upstream_merge_and_vendored_license_hashes(self):
        self.assertEqual(interleave([[1, 2, 3], [1, 4], [5]]), [1, 5, 2, 4, 3])
        root = Path(__file__).parent / "services" / "combined_rag"
        for entry in json.loads((root / "vendor-manifest.json").read_text())["files"]:
            path = root.joinpath(*entry["path"].replace("\\", "/").split("/"))
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry["sha256"])


if __name__ == "__main__":
    unittest.main()
