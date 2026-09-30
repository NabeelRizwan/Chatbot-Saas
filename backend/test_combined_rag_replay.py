"""Frozen candidate/score replay, not a live PostgreSQL or Gemini quality test.

Adapt the 65 recorded cases to SaaS source objects. Production code supplies the
actual ranking and offline tokenizer; only retrieval, query plans and BGE scores
are frozen doubles. Expected answers never enter runtime or planner inputs.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace as Object
import unittest
from unittest.mock import patch

from services.combined_rag import pipeline
from services.retrieval_contracts import HardKnowledgeScope, ProfileIdentity

FIXTURE = Path(__file__).parent / "tests/fixtures/combined_rag/replay.json.gz"
SHA256 = "de7cf8b015bc39ff1221341da24ef13f37442996fe2652fb1efd53a8601c3c20"


class RecordedCombinationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = FIXTURE.read_bytes()
        if hashlib.sha256(raw).hexdigest() != SHA256:
            raise RuntimeError("Frozen replay fixture changed")
        cls.data = json.loads(gzip.decompress(raw))
        cls.original_ids = {index + 1: key for index, key in enumerate(sorted(cls.data["chunks"]))}
        cls.chunk_ids = {key: index for index, key in cls.original_ids.items()}
        doc_keys = sorted({chunk["doc_id"] for chunk in cls.data["chunks"].values()})
        cls.document_ids = {key: index + 1 for index, key in enumerate(doc_keys)}

    def replay(self, case):
        data, lookups = self.data, {}
        for key, chunk in data["chunks"].items():
            doc_id = self.document_ids[chunk["doc_id"]]
            lookups[key] = {
                "chunk": Object(id=self.chunk_ids[key], document_id=doc_id, bot_id=1,
                                organization_id=7, content=chunk["content_with_weight"],
                                metadata_json={}, status="ready", crawl_id=None,
                                embedding_provider="fixture", embedding_model="frozen", embedding_version=1),
                "document": Object(id=doc_id, bot_id=1, organization_id=7, status="ready",
                                   processing_status="completed", title=chunk["docnm_kwd"],
                                   filename=chunk["docnm_kwd"], source_url=chunk.get("url", ""),
                                   metadata_json={}, version=1, crawl_id=None),
            }
        allowed_docs = sorted({self.document_ids[c["doc_id"]] for c in data["chunks"].values()
                               if c["kb_id"] in case["kb_ids"]})
        hard = HardKnowledgeScope(organization_id=7, bot_id=1,
            authorized_document_ids=tuple(allowed_docs),
            embedding_profile=ProfileIdentity("fixture", "frozen", 1, 3),
            active_document_versions=tuple((identifier, 1, None) for identifier in allowed_docs))
        contract = Object(execution=Object(hard_scope=hard,
                          scope_decision=Object(effective_document_ids=tuple(allowed_docs))),
                          permitted_document_ids=allowed_docs)
        bot = Object(id=1, organization_id=7)
        query_pools = {case["question"]: case["raw_pool"]}
        query_pools.update({lane["query"]: lane["pool"] for lane in case["lanes"]})
        # The recorded raw/focus result for an identical query must agree.
        if case["question"] in {lane["query"] for lane in case["lanes"]}:
            self.assertEqual(query_pools[case["question"]], case["raw_pool"])

        def native(query, given_contract, top_k):
            self.assertIs(given_contract, contract)
            self.assertEqual(top_k, 128)
            return [dict(lookups[key], score=metrics.get("similarity", 0))
                    for key, metrics, _ in data["pools"][query_pools[query]]["chunk_refs"]]

        def score(query, documents):
            lane = next(lane for lane in case["lanes"] if lane["query"] == query)
            self.assertEqual([hashlib.sha256(text.encode()).hexdigest() for text in documents],
                             lane["document_sha256"])
            return lane["scores"]

        ranked = []
        formatter = pipeline.format_context
        def format_actual(items, budget):
            ranked.extend(self.original_ids[row["chunk"].id] for row in items)
            return formatter(items, budget)

        environment = {"RAG_COMBINED_RERANKER_URL": "http://ranker.invalid/rerank",
                       "RAG_COMBINED_RERANKER_TOKEN": "offline-fixture-token"}
        with patch.dict(os.environ, environment), \
                patch.object(pipeline, "focused_queries", return_value=[lane["query"] for lane in case["lanes"]]), \
                patch.object(pipeline.BGEClient, "score", side_effect=score), \
                patch.object(pipeline, "format_context", side_effect=format_actual):
            selected, context = pipeline.collect_evidence(
                bot=bot, question=case["question"], query_contract=contract,
                trace=Object(diagnostics={}), retrieve_native=native, budget_chars=65536)
        selected_ids = [self.original_ids[row["chunk"].id] for row in selected]
        self.assertEqual(ranked, case["expected"]["ranked_ids"])
        self.assertEqual(selected_ids, case["expected"]["selected_ids"])
        tokens = sum(pipeline.count_tokens(row["chunk"].content) for row in selected)
        self.assertEqual(tokens, case["expected"]["source_tokens"])
        self.assertLessEqual(tokens, 4000)
        self.assertLessEqual(len(context), 65536)
        groups = case["expected"]["witness_groups"]
        complete = all(set(group) & set(selected_ids) for group in groups) if groups else None
        self.assertEqual(complete, case["expected"]["complete"])
        return complete

    def check_group(self, group, expected_successes, expected_misses):
        results = {}
        for case in self.data["cases"]:
            if case["group"] == group:
                with self.subTest(case=case["id"]):
                    results[case["id"]] = self.replay(case)
        self.assertEqual(len(results), 45 if group == "ikea_products" else 10)
        self.assertEqual(sum(result is True for result in results.values()), expected_successes)
        self.assertEqual({key for key, value in results.items() if value is False}, set(expected_misses))

    def test_original_ten(self):
        self.check_group("wowmd_original", 9, [])

    def test_natural_ten(self):
        self.check_group("wowmd_natural", 9, [])

    def test_ikea_answerable_cases_keep_known_misses(self):
        self.check_group("ikea_products", 43, ["U22", "U34"])


if __name__ == "__main__":
    unittest.main()
