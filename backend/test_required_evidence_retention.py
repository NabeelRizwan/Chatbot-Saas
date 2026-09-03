"""Exercise the real RRF -> cutoff -> context path with deterministic recall."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from database.models import Chunk, Document
from services import rag_service as rag
from services.conversational_engine import compress_and_rerank_chunks
from test_phase_l3_multi_entity_conversational_rag import chunk, contract, document, item


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class FixtureDB:
    def __init__(self, docs, pairs):
        self.docs, self.pairs = docs, pairs

    def query(self, *entities):
        if len(entities) == 1 and entities[0] is Document:
            return Rows(self.docs)
        if len(entities) == 1 and entities[0] is Chunk:
            return Rows([c for c, _doc in self.pairs])
        if len(entities) == 2 and entities[0] is Chunk and entities[1] is Document:
            return Rows(self.pairs)
        return Rows([(1,)])


def retrieve_fixture(docs, pairs, query, *, with_trace=False):
    qc = contract(query, docs)
    lookup = {c.id: (c, d) for c, d in pairs}
    vector = [(c.id, d.id, 0.01 if d.id == 1 else 0.85) for c, d in pairs]
    trace = rag.ChatTrace() if with_trace else None
    with patch.object(rag, "get_knowledge_scope", return_value={"exists": True, "organization_id": 1}), \
         patch.object(rag, "resolve_active_embedding_profile", return_value=SimpleNamespace(provider="fixture", model="fixture", version=1, dimensions=1)), \
         patch.object(rag, "generate_embedding", return_value=[0.0]), \
         patch.object(rag, "_vector_candidate_ids", return_value=vector), \
         patch.object(rag, "_lexical_candidate_ids", return_value=[(c.id, d.id) for c, d in pairs]), \
         patch.object(rag, "_hydrate_chunk_document_pairs", side_effect=lambda _db, ids: [lookup[i] for i in ids]):
        result = rag.retrieve_relevant_chunks(FixtureDB(docs, pairs), 1, query, query_contract=qc, trace=trace)
    return result, qc, trace


class RequiredEvidenceRetentionTests(unittest.TestCase):
    def setUp(self):
        self.docs = [document(1, "Alpha"), document(2, "Beta")]
        self.pairs = []
        for doc in self.docs:
            for index, text in enumerate([
                f"# {doc.title} Price\nCurrent price: ${doc.id * 10}. One-time purchase.",
                f"# {doc.title} Ingredients\nIngredients: mineral A, mineral B, and mineral C.",
                f"# {doc.title} Directions\nTake {doc.id} capsule daily with water.",
                f"# {doc.title}\n### How soon will I see results?\nResults may appear in {doc.id * 2}-{doc.id * 2 + 1} weeks; individual results vary.",
            ]):
                c = chunk(doc.id * 100 + index, index, text)
                c.document_id = doc.id
                self.pairs.append((c, doc))
        for index in range(25):
            c = chunk(1000 + index, 20 + index, f"# Alpha overview\nOptional marketing detail {index}. " + "Unrequested information. " * 30)
            c.document_id = 1
            self.pairs.insert(0, (c, self.docs[0]))
        self.query = "Compare Alpha and Beta on price, ingredients, directions and results timelines"

    def test_full_live_path_keeps_lower_rrf_entity_fields(self):
        result, qc, _ = retrieve_fixture(self.docs, self.pairs, self.query)
        for doc in self.docs:
            required = {field for row in result if row["document"].id == doc.id for field in row.get("required_fields", [])}
            self.assertTrue({"price", "ingredients", "directions", "results_timeframe"} <= required)
        self.assertTrue(any(row.get("required_fields") and row["evidence_priority"] == 0.12 for row in result))
        _used, context = compress_and_rerank_chunks(result, self.query, 2500, qc.mode, qc)
        for value in ("$10", "$20", "Take 1", "Take 2", "2-3 weeks", "4-5 weeks"):
            self.assertIn(value, context)

    def test_required_low_raw_score_survives_optional_cutoff(self):
        required = item(1, 2, "Beta", "Directions: Take 2 capsules daily.", 0.01)
        required["required_fields"] = ["directions"]
        optional = item(2, 1, "Alpha", "Highly ranked optional narrative.", 1.0)
        result = rag._reserve_required_evidence([optional, required], [optional], top_k=1)
        self.assertEqual(result, [required])

    def test_tight_context_preserves_matrix_before_optional(self):
        result, qc, _ = retrieve_fixture(self.docs, self.pairs, self.query)
        _used, context = compress_and_rerank_chunks(result, self.query, 1600, qc.mode, qc)
        self.assertLessEqual(len(context), 1600)
        if "Unrequested information" in context:
            self.assertGreater(context.index("Unrequested information"), context.index("4-5 weeks"))
        for value in ("$10", "$20", "Take 1", "Take 2", "2-3 weeks", "4-5 weeks", "mineral C"):
            self.assertIn(value, context)

    def test_unavailable_field_status_survives_context(self):
        pairs = [(c, d) for c, d in self.pairs if c.id != 203]
        result, qc, _ = retrieve_fixture(self.docs, pairs, self.query)
        beta = [row for row in result if row["document"].id == 2]
        self.assertEqual(beta[0]["field_coverage"]["results_timeframe"], "ABSENT_AFTER_ADEQUATE_SEARCH")
        _used, context = compress_and_rerank_chunks(result, self.query, 2500, qc.mode, qc)
        self.assertIn("results_timeframe: Unavailable after the field search.", context)

    def test_single_entity_keeps_ordinary_ranking_path(self):
        result, _qc, _ = retrieve_fixture(self.docs, self.pairs, "What is the price of Alpha?")
        self.assertFalse(any(row.get("required_fields") for row in result))
        ranked = list(reversed(result))
        self.assertIs(rag._reserve_required_evidence(result, ranked, top_k=1), ranked)

    def test_catalog_without_multi_field_does_not_reserve(self):
        result, qc, _ = retrieve_fixture(self.docs, self.pairs, "What products do you have?")
        self.assertEqual(qc.mode, "catalog")
        self.assertFalse(any(row.get("required_fields") for row in result))

    def test_identical_values_do_not_deduplicate_other_entity(self):
        rows = []
        for doc in self.docs:
            row = item(doc.id, doc.id, doc.title, "Ingredients: mineral A. Directions: Take 1 capsule daily.")
            row["required_fields"] = ["ingredients", "directions"]
            rows.append(row)
        _used, context = compress_and_rerank_chunks(rows, self.query, 2000, "comparison", contract(self.query, self.docs))
        self.assertIn("Source: Alpha", context)
        self.assertIn("Source: Beta", context)

    def test_split_numbered_stages_remain_attached_to_correct_body(self):
        rows = []
        for doc in self.docs:
            for index, text in enumerate(["## What to Expect\n\n2-3 WEEKS", "### Early stage\n\nEarly support may begin.\n\n5-7 WEEKS", "### Later stage\n\nLater support may follow."]):
                row = item(doc.id * 10 + index, doc.id, doc.title, text)
                row["required_fields"] = ["results_timeframe"]
                rows.append(row)
        _used, context = compress_and_rerank_chunks(rows, self.query, 2000, "comparison", contract(self.query, self.docs))
        self.assertIn("2-3 WEEKS Early stage Early support may begin.", context)
        self.assertIn("5-7 WEEKS Later stage Later support may follow.", context)

    def test_impossibly_small_budget_never_slices_a_factual_value(self):
        result, qc, _ = retrieve_fixture(self.docs, self.pairs, self.query)
        used, context = compress_and_rerank_chunks(result, self.query, 100, qc.mode, qc)
        self.assertEqual(used, [])
        self.assertLessEqual(len(context), 100)
        self.assertIn("exceeds the context budget", context)

    def test_retrieval_cache_retains_required_and_missing_metadata(self):
        row = item(1, 1, "Alpha", "Directions: Take 1 capsule daily.")
        row["required_fields"] = ["directions"]
        row["field_coverage"] = {"directions": "SUPPORTED", "price": "ABSENT_AFTER_ADEQUATE_SEARCH"}
        qc = contract(self.query, self.docs)
        with patch.object(rag, "_RETRIEVAL_CACHE", {}), patch.object(rag, "retrieve_relevant_chunks", return_value=[row]) as retrieve:
            rag.retrieve_relevant_chunks_cached(None, 1, self.query, query_contract=qc)
            cached = rag.retrieve_relevant_chunks_cached(None, 1, self.query, query_contract=qc)
            self.assertEqual(retrieve.call_count, 1)
            self.assertEqual(cached[0]["required_fields"], row["required_fields"])
            self.assertEqual(cached[0]["field_coverage"], row["field_coverage"])


if __name__ == "__main__":
    unittest.main()
