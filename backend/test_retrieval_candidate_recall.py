"""Retrieval-only recall tests: inspect the PRE-REVIEW candidate pool.

These tests never reach the AI Evidence Reviewer or final generation. They
call `rag.retrieve_relevant_chunks()` directly (the exact function
`retrieve_relevant_chunks_cached()` -> `answer_question()` calls before
`review_evidence()` runs) and assert on the returned chunk/document ids.

No network, no real accounts, no real embeddings, no Gemini quota spent.
Vector recall is mocked with a controllable, deterministic ranking so tests
are hermetic; lexical recall runs for real against the in-memory SQLite
fixture unless a test explicitly disables it to isolate the vector/candidate
budget behavior being verified (Cases A and D).
"""
import contextlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.connection import Base
from database.models import Bot, Chunk, Document
from services import rag_service as rag, rag_planning as planning
from services.knowledge_scope import ready_chunks
from services.observability_service import ChatTrace


class RetrievalCandidateRecallTests(unittest.TestCase):
    """Fixture mirrors test_scoped_rag_architecture.py's proven patterns."""

    def setUp(self):
        self.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.db = self.sessions()
        self.bot = Bot(id=1, customer_id=1, organization_id=1, name="Fixture", provider="fixture", model_name="fixture", capabilities={})
        self.db.add(self.bot)
        self.db.commit()

        self.patches = contextlib.ExitStack()
        self.patches.enter_context(patch.object(planning, "generate_auxiliary", side_effect=TimeoutError("offline")))
        self.patches.enter_context(patch.object(rag, "SessionLocal", self.sessions))
        self.patches.enter_context(patch.object(rag, "resolve_active_embedding_profile", return_value=SimpleNamespace(provider="gemini", model="gemini-embedding-001", version=1, dimensions=768)))
        self.patches.enter_context(patch.object(rag, "generate_embedding", return_value=[0.0] * 768))

        # Deterministic vector mock: ranking is controlled per-test via
        # `self.vector_rank_key`; default mirrors the existing suite's
        # convention (highest chunk id ranks first).
        self.vector_calls: list[dict] = []
        self.vector_rank_key = lambda row: -row[0]

        def vector(bot_id, org_id, embedding, limit, profile, document_ids=None):
            self.vector_calls.append({"document_ids": list(document_ids) if document_ids is not None else None, "limit": limit})
            with self.sessions() as db:
                rows = ready_chunks(
                    db.query(Chunk.id, Document.id, Chunk.chunk_index).join(Document, Chunk.document_id == Document.id),
                    bot_id, org_id, document_ids,
                ).all()
            ranked = sorted(rows, key=self.vector_rank_key)[:limit]
            return [(chunk_id, doc_id, 0.02) for chunk_id, doc_id, _idx in ranked]

        self.patches.enter_context(patch.object(rag, "_vector_candidate_ids", side_effect=vector))

        # Lexical recall runs for real by default (through the same mocked
        # SessionLocal); Cases A/D disable it to isolate the vector/candidate
        # budget behavior they specifically target.
        self.lexical_calls: list[dict] = []
        self.lexical_disabled = False
        real_lexical = rag._lexical_candidate_ids

        def lexical(bot_id, org_id, terms, limit, document_ids=None):
            self.lexical_calls.append({"document_ids": list(document_ids) if document_ids is not None else None, "limit": limit, "terms": list(terms)})
            if self.lexical_disabled:
                return []
            return real_lexical(bot_id, org_id, terms, limit, document_ids)

        self.patches.enter_context(patch.object(rag, "_lexical_candidate_ids", side_effect=lexical))

    def tearDown(self):
        self.patches.close()
        self.db.close()
        self.engine.dispose()

    # ---- fixture helpers -------------------------------------------------

    def add_document(self, number, title, content, bot_id=1, org_id=1):
        doc = Document(
            id=number, bot_id=bot_id, organization_id=org_id, title=title, filename=title,
            source_type="txt", status="ready", processing_status="completed",
            source_url=f"https://fixture.test/{number}", canonical_url=f"https://fixture.test/{number}", version=1,
        )
        self.db.add(doc)
        for index, body in enumerate(content):
            self.db.add(Chunk(
                id=number * 10000 + index, document_id=number, bot_id=bot_id, organization_id=org_id,
                content=body, embedding=[0.0] * 768, chunk_index=index, status="ready", metadata_json={},
            ))
        self.db.flush()
        return doc

    def contract(self, bot, question, history=None, state=None, response=None):
        trace = ChatTrace(1, "widget")
        with patch.object(planning, "plan_query", return_value=response):
            c = planning.prepare_query(self.db, bot, question, history or [], state or {}, rag._build_turn_query_contract, trace)
        return c, trace.conversation_state

    def retrieve(self, bot, contract):
        trace = ChatTrace(1, "test")
        result = rag.retrieve_relevant_chunks(self.db, bot.id, contract.retrieval_query, query_contract=contract, trace=trace)
        return result, trace

    # ---- A. large single-document generic fact ---------------------------

    def test_large_single_document_generic_fact_reaches_pool(self):
        """>60 chunk document; target fact at rank 36 (old flat cutoffs were 25/35)."""
        target_index = 35
        content = [
            f"Filler note {i}: unrelated general information about topic {i}."
            for i in range(65)
        ]
        content[target_index] = "Standard operating temperature range is negative ten to forty degrees Celsius."
        doc = self.add_document(1, "Field Ops Manual", content)
        self.db.commit()

        self.lexical_disabled = True  # isolate the vector/candidate-budget fix
        self.vector_rank_key = lambda row: row[2]  # ascending chunk_index -> rank == chunk_index

        _, state = self.contract(self.bot, "tell me about Field Ops Manual")
        c, _ = self.contract(self.bot, "Tell me more about it.", state=state)
        self.assertEqual(c.permitted_document_ids, [doc.id])

        rows, trace = self.retrieve(self.bot, c)
        target_id = doc.id * 10000 + target_index
        found_ids = {r["chunk"].id for r in rows}

        adaptive = trace.diagnostics.get("adaptive_recall")
        self.assertIsNotNone(adaptive, "adaptive widening should trigger for a single resolved document")
        self.assertEqual(adaptive["chunk_counts"], {doc.id: 65})
        print(
            f"CASE A | doc_chunks=65 | old_candidate_limit=25 | new_candidate_limit={adaptive['candidate_limit']} | "
            f"review_pool_size={trace.diagnostics['review_pool_size']} | target_rank=36 | "
            f"target_reached_pool={target_id in found_ids} | pool_size={len(rows)}"
        )
        self.assertIn(target_id, found_ids, "target chunk ranked 36th must survive into the pre-review pool")
        self.assertLessEqual(len(rows), 48, "pre-review pool must stay bounded at the reviewer's ceiling")

    # ---- D. generic fact not in FIELD_ONTOLOGY ---------------------------

    def test_generic_non_ontology_fact_reaches_pool(self):
        """Fact/attribute with zero overlap with any FIELD_ONTOLOGY pattern."""
        target_index = 40
        content = [
            f"Reference entry {i}: background context unrelated to the question."
            for i in range(65)
        ]
        content[target_index] = "The team mascot is a cartoon fox named Circuit."
        doc = self.add_document(1, "Community Notes", content)
        self.db.commit()

        self.lexical_disabled = True
        self.vector_rank_key = lambda row: row[2]

        _, state = self.contract(self.bot, "tell me about Community Notes")
        c, _ = self.contract(self.bot, "Tell me more about it.", state=state)
        self.assertEqual(c.permitted_document_ids, [doc.id])
        self.assertEqual(c.requested_fields, [], "fact must not be classified as a known ontology field")

        rows, trace = self.retrieve(self.bot, c)
        target_id = doc.id * 10000 + target_index
        found_ids = {r["chunk"].id for r in rows}

        adaptive = trace.diagnostics.get("adaptive_recall")
        print(
            f"CASE D | doc_chunks=65 | new_candidate_limit={adaptive['candidate_limit']} | "
            f"review_pool_size={trace.diagnostics['review_pool_size']} | target_rank=41 | "
            f"target_reached_pool={target_id in found_ids} | pool_size={len(rows)}"
        )
        self.assertIn(target_id, found_ids, "non-ontology fact must still reach the candidate pool")

    # ---- B. Sea Essence price -----------------------------------------

    def _add_pricing_documents(self):
        sea_essence = self.add_document(1, "Sea Essence Omega 3 Fish Oil", [
            "# Sea Essence Omega 3 Fish Oil\n## Overview\nSupports everyday wellness.",
            "[Sea Essence Omega 3 Fish Oil]\n## Ingredients\n- Fish Oil Concentrate\n- Vitamin E",
            "[Sea Essence Omega 3 Fish Oil]\n## Directions\nTake two softgels daily with a meal.",
            "[Sea Essence Omega 3 Fish Oil]\n## Pricing\nOne-time purchase $37.00. Subscription $35.15.",
            "[Sea Essence Omega 3 Fish Oil]\n## Shipping and returns\nFree shipping on orders over $50.",
        ])
        turmeric = self.add_document(2, "Turmeric Boost", [
            "# Turmeric Boost\n## Overview\nSupports joint comfort.",
            "[Turmeric Boost]\n## Ingredients\n- Turmeric Root Extract\n- Black Pepper Extract",
            "[Turmeric Boost]\n## Directions\nTake one capsule daily with food.",
            "[Turmeric Boost]\n## Pricing\nOne-time purchase $24.99. Subscription $22.49.",
            "[Turmeric Boost]\n## Shipping and returns\nFree shipping on orders over $40.",
        ])
        self.db.commit()
        return sea_essence, turmeric

    def test_sea_essence_price_candidate_recall(self):
        sea_essence, turmeric = self._add_pricing_documents()
        _, state = self.contract(self.bot, "tell me about Sea Essence Omega 3 Fish Oil")
        c, _ = self.contract(self.bot, "price?", state=state)
        self.assertEqual(c.permitted_document_ids, [sea_essence.id])

        rows, trace = self.retrieve(self.bot, c)
        docs = {r["document"].id for r in rows}
        texts = " ".join(r["chunk"].content for r in rows)
        print(f"CASE B | permitted_docs={c.permitted_document_ids} | pool_size={len(rows)} | doc_ids_in_pool={docs}")

        self.assertEqual(docs, {sea_essence.id})
        self.assertIn("$37.00", texts)
        self.assertIn("$35.15", texts)
        self.assertNotIn(turmeric.id, docs)

    # ---- C. Turmeric price (regression, isolation from Sea Essence) ------

    def test_turmeric_price_candidate_recall(self):
        sea_essence, turmeric = self._add_pricing_documents()
        _, state = self.contract(self.bot, "tell me about Turmeric Boost")
        c, _ = self.contract(self.bot, "price?", state=state)
        self.assertEqual(c.permitted_document_ids, [turmeric.id])

        rows, trace = self.retrieve(self.bot, c)
        docs = {r["document"].id for r in rows}
        texts = " ".join(r["chunk"].content for r in rows)
        print(f"CASE C | permitted_docs={c.permitted_document_ids} | pool_size={len(rows)} | doc_ids_in_pool={docs}")

        self.assertEqual(docs, {turmeric.id})
        self.assertIn("$24.99", texts)
        self.assertIn("$22.49", texts)
        self.assertNotIn(sea_essence.id, docs)
        self.assertNotIn("$37.00", texts)
        self.assertNotIn("$35.15", texts)

    # ---- E. Comparison fairness ------------------------------------------

    def test_comparison_fairness_both_documents_reach_pool(self):
        alpha_target, beta_target = 15, 15
        alpha_content = [f"Alpha filler {i}: general plan information." for i in range(50)]
        alpha_content[alpha_target] = "Alpha Suite costs $120 per month."
        beta_content = [f"Beta filler {i}: general plan information." for i in range(50)]
        beta_content[beta_target] = "Beta Suite costs $95 per month."
        alpha = self.add_document(1, "Alpha Suite", alpha_content)
        beta = self.add_document(2, "Beta Suite", beta_content)
        self.db.commit()

        c, _ = self.contract(self.bot, "Compare Alpha Suite and Beta Suite pricing.")
        self.assertEqual(set(c.permitted_document_ids or []), {alpha.id, beta.id})

        rows, trace = self.retrieve(self.bot, c)
        docs_present = {r["document"].id for r in rows}
        texts = " ".join(r["chunk"].content for r in rows)
        per_doc_counts = {doc_id: sum(1 for r in rows if r["document"].id == doc_id) for doc_id in (alpha.id, beta.id)}
        print(
            f"CASE E | doc_chunks=50+50 | pool_size={len(rows)} | per_doc_counts={per_doc_counts} | "
            f"review_pool_size={trace.diagnostics.get('review_pool_size')}"
        )

        self.assertEqual(docs_present, {alpha.id, beta.id}, "both compared documents must contribute evidence")
        self.assertIn("$120", texts)
        self.assertIn("$95", texts)
        self.assertGreater(per_doc_counts[alpha.id], 0)
        self.assertGreater(per_doc_counts[beta.id], 0)
        # No single document may consume the entire bounded review pool.
        self.assertLess(max(per_doc_counts.values()), len(rows))

    # ---- F. Required field survival ---------------------------------------

    def test_required_field_survives_candidate_widening(self):
        content = [f"Filler note {i}: unrelated general information." for i in range(60)]
        content += [
            "[Sea Essence Omega 3 Fish Oil]\n## Ingredients\n- Fish Oil Concentrate\n- Vitamin E",
            "[Sea Essence Omega 3 Fish Oil]\n## Ingredients (continued)\n- Gelatin\n- Glycerin",
        ]
        doc = self.add_document(1, "Sea Essence Omega 3 Fish Oil", content)
        self.db.commit()

        _, state = self.contract(self.bot, "tell me about Sea Essence Omega 3 Fish Oil")
        c, _ = self.contract(self.bot, "ingredients?", state=state)
        self.assertEqual(c.permitted_document_ids, [doc.id])
        self.assertEqual(c.requested_fields, ["ingredients"])

        rows, trace = self.retrieve(self.bot, c)
        required_ids = {r["chunk"].id for r in rows if r.get("required_fields")}
        texts = " ".join(r["chunk"].content for r in rows)
        print(f"CASE F | pool_size={len(rows)} | required_chunk_count={len(required_ids)}")

        self.assertTrue(required_ids, "at least one chunk must be marked as required evidence")
        for keyword in ("Fish Oil Concentrate", "Vitamin E"):
            self.assertIn(keyword, texts)

    # ---- G. Tenant isolation ----------------------------------------------

    def test_tenant_isolation_survives_wider_candidates(self):
        bot_b = Bot(id=2, customer_id=2, organization_id=2, name="Other", provider="fixture", model_name="fixture", capabilities={})
        self.db.add(bot_b)
        self.db.commit()

        content_a = [f"Tenant A filler {i}: general information." for i in range(60)]
        content_a[30] = "Tenant A secret figure: the code is Alpha-9."
        content_b = [f"Tenant B filler {i}: general information." for i in range(60)]
        content_b[30] = "Tenant B secret figure: the code is Beta-7."
        doc_a = self.add_document(1, "Shared Title", content_a, bot_id=1, org_id=1)
        doc_b = self.add_document(2, "Shared Title", content_b, bot_id=2, org_id=2)
        self.db.commit()

        self.vector_rank_key = lambda row: row[2]

        _, state_a = self.contract(self.bot, "tell me about Shared Title")
        c_a, _ = self.contract(self.bot, "Tell me more about it.", state=state_a)
        self.assertEqual(c_a.permitted_document_ids, [doc_a.id])
        rows_a, _ = self.retrieve(self.bot, c_a)
        docs_a = {r["document"].id for r in rows_a}
        texts_a = " ".join(r["chunk"].content for r in rows_a)

        _, state_b = self.contract(bot_b, "tell me about Shared Title")
        c_b, _ = self.contract(bot_b, "Tell me more about it.", state=state_b)
        self.assertEqual(c_b.permitted_document_ids, [doc_b.id])
        rows_b, _ = self.retrieve(bot_b, c_b)
        docs_b = {r["document"].id for r in rows_b}
        texts_b = " ".join(r["chunk"].content for r in rows_b)

        print(f"CASE G | tenant_a_docs={docs_a} | tenant_b_docs={docs_b}")

        self.assertEqual(docs_a, {doc_a.id})
        self.assertEqual(docs_b, {doc_b.id})
        self.assertNotIn("Beta-7", texts_a)
        self.assertNotIn("Alpha-9", texts_b)

    # ---- H. 1000 document scope --------------------------------------------

    def test_scope_stays_bounded_at_1000_documents(self):
        target = self.add_document(1, "Distinct Flagship Product", [
            "# Distinct Flagship Product\n## Overview\nA distinct item in a very large catalog.",
            "[Distinct Flagship Product]\n## Pricing\nOne-time purchase $199.00.",
        ])
        for number in range(2, 1001):
            self.add_document(number, f"Similar Offering {number}", [
                f"# Similar Offering {number}\nGeneric description for offering {number}.",
            ])
        self.db.commit()

        c, _ = self.contract(self.bot, "tell me about Distinct Flagship Product")
        self.assertEqual(c.permitted_document_ids, [target.id])

        rows, trace = self.retrieve(self.bot, c)
        docs_present = {r["document"].id for r in rows}
        print(
            f"CASE H | total_documents=1000 | candidate_document_count={trace.diagnostics['candidate_document_count']} | "
            f"vector_call_doc_ids={self.vector_calls[-1]['document_ids']} | pool_size={len(rows)}"
        )

        self.assertEqual(trace.diagnostics["candidate_document_count"], 1)
        self.assertEqual(self.vector_calls[-1]["document_ids"], [target.id])
        self.assertEqual(docs_present, {target.id})


if __name__ == "__main__":
    unittest.main()
