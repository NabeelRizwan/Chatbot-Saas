"""Phase 1.5: real scoped SQL/selection/context, deterministic model boundaries."""
import contextlib
import io
import json
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from database.models import Bot, Chunk, Document
from services import rag_service as rag, rag_planning as planning
from services.conversational_engine import compress_and_rerank_chunks
from services.knowledge_scope import ready_chunks
from services.observability_service import ChatTrace, compact_chat_diagnostics
from services.retrieval_selection import POLICY
import test_retrieval_candidate_recall as fixtures
from test_scoped_rag_architecture import plan


def item(number, content, score=0.1, doc_id=1):
    return {"chunk": SimpleNamespace(id=number, content=content, chunk_index=number, token_count=10, metadata_json={}),
            "document": SimpleNamespace(id=doc_id, title=f"Manual {doc_id}", filename="manual.txt", source_url=None),
            "score": score}


class RetrievalSafetyGateTests(unittest.TestCase):
    setUp = fixtures.RetrievalCandidateRecallTests.setUp
    tearDown = fixtures.RetrievalCandidateRecallTests.tearDown
    add_document = fixtures.RetrievalCandidateRecallTests.add_document
    contract = fixtures.RetrievalCandidateRecallTests.contract
    retrieve = fixtures.RetrievalCandidateRecallTests.retrieve

    def fixture(self):
        self.add_document(1, "Field Ops Manual", [
            "Normal operation stays between negative ten and forty degrees Celsius.",
            "Rest intervals are mandatory before restarting equipment.",
            "The operating modes can be changed with the side switch.",
        ])
        self.db.commit()
        return self.contract(self.bot, "tell me about Field Ops Manual")[0]

    def low_vector(self, bot_id, org_id, embedding, limit, profile, document_ids=None):
        with self.sessions() as db:
            rows = ready_chunks(db.query(Chunk.id, Document.id).join(Document), bot_id, org_id, document_ids).all()
        return [(chunk_id, doc_id, 0.92) for chunk_id, doc_id in rows[:limit]]

    def test_low_cosine_reaches_real_reviewer_and_context(self):
        contract = self.fixture()
        with patch.object(rag, "_vector_candidate_ids", side_effect=self.low_vector), \
             patch.object(rag, "_lexical_candidate_ids", return_value=[]):
            rows, trace = self.retrieve(self.bot, contract)
        with patch.object(planning, "generate_auxiliary", return_value='{"ranked_candidates":[0]}') as reviewer:
            reviewed = planning.review_evidence(self.bot, contract, rows, trace)
        used, context = compress_and_rerank_chunks(reviewed, contract.original_query, query_contract=contract, trace=trace)
        self.assertTrue(used)
        self.assertIn("degrees Celsius", context)
        self.assertEqual(reviewer.call_count, 1)
        self.assertIsNone(trace.retrieval.fallback_reason)
        traced = trace.retrieval.candidates[(1, 10000)]
        self.assertAlmostEqual(traced.vector_score, 0.08)
        self.assertTrue(traced.reached_reviewer)
        self.assertTrue(traced.included_final_context)

    def test_top_and_average_are_diagnostics_not_an_evidence_gate(self):
        rows = [item(1, "The limit is twelve.", 0.01), item(2, "Rest before restarting.", 0.02)]
        stats = rag.retrieval_confidence(rows)
        self.assertTrue(stats["retrieval_has_candidates"])
        self.assertLess(stats["top_score"], 0.65)
        self.assertLess(stats["average_score"], 0.55)
        self.assertEqual(len(rag.clean_retrieved_chunks(rows, 4)), 2)

    def test_cleanup_does_not_drop_low_ranked_value_beside_high_score(self):
        rows = [item(1, "Welcome to the reference manual.", 0.99), item(2, "Max 24h", 0.08)]
        clean = rag.clean_retrieved_chunks(rows, 4)
        self.assertEqual({i["chunk"].id for i in clean}, {1, 2})
        used, context = compress_and_rerank_chunks(clean, "What is the maximum duration?", 150)
        self.assertIn("Max 24h", context)
        self.assertTrue(any(i["chunk"].id == 2 for i in used))

    def test_alias_field_wording_remains_eligible(self):
        rows = [item(1, "## Instructions\nUse the dial.", 0.8),
                item(2, "Turn clockwise until the indicator illuminates.", 0.12)]
        trace = ChatTrace(1, "test")
        used, context = compress_and_rerank_chunks(rows, "How do I operate it?", 1000, "factual", trace=trace)
        self.assertEqual({i["chunk"].id for i in used}, {1, 2})
        self.assertIn("Turn clockwise", context)
        self.assertTrue(trace.retrieval.final_context_has_evidence)

    def run_answer(self, contract, rows, reviewer_result, *, strict=False):
        self.bot.capabilities = {} if strict else {"web_search": True}
        trace = ChatTrace(1, "test")
        with patch.object(rag, "prepare_query", return_value=contract), \
             patch.object(rag.global_semantic_cache, "get", return_value=None), \
             patch.object(rag.global_semantic_cache, "set"), \
             patch.object(rag, "retrieve_relevant_chunks_cached", return_value=rows), \
             patch.object(planning, "generate_auxiliary", return_value=reviewer_result), \
             patch.object(rag, "generate", return_value="Turn clockwise until the indicator illuminates.") as generate, \
             patch.object(rag, "verify_answer", side_effect=lambda **kw: kw["draft_answer"]), \
             patch.object(rag, "polish_answer", side_effect=lambda **kw: kw["answer"]), \
             contextlib.redirect_stdout(io.StringIO()):
            answer = rag.answer_question(self.db, self.bot, contract.original_query, trace=trace, knowledge_version=1)
        return answer, trace, generate.call_count

    def test_no_candidates_and_explicit_rejection_stop_generation(self):
        contract = self.fixture()
        for strict in (False, True):
            with self.subTest(strict=strict, reason="no_candidates"):
                answer, trace, count = self.run_answer(contract, [], '{"ranked_candidates":[]}', strict=strict)
                self.assertEqual(answer, (rag.FRIENDLY_FALLBACK, [], []))
                self.assertEqual(trace.retrieval.fallback_reason, "no_retrieval_candidates")
                self.assertEqual(count, 0)
            with self.subTest(strict=strict, reason="reviewer_rejection"):
                answer, trace, count = self.run_answer(contract, [item(1, "Irrelevant facts.")],
                    '{"ranked_candidates":[],"reject_all":true}', strict=strict)
                self.assertEqual(answer, (rag.FRIENDLY_FALLBACK, [], []))
                self.assertEqual(trace.retrieval.fallback_reason, "reviewer_rejected_all")
                self.assertEqual(count, 0)
            with self.subTest(strict=strict, reason="rejection_with_missing_fields"):
                answer, trace, count = self.run_answer(contract, [item(1, "Irrelevant facts.")],
                    '{"ranked_candidates":[],"reject_all":true,"missing_fields":["directions"]}', strict=strict)
                self.assertEqual(answer, (rag.FRIENDLY_FALLBACK, [], []))
                self.assertEqual(trace.retrieval.fallback_reason, "reviewer_rejected_all")
                self.assertEqual(count, 0)

    def test_low_confidence_flexible_path_reaches_generation(self):
        contract = self.fixture()
        answer, trace, calls = self.run_answer(contract, [item(1, "Turn clockwise until the indicator illuminates.", 0.02)], '{"ranked_candidates":[0]}')
        self.assertEqual(calls, 1)
        self.assertIn("Turn clockwise", answer[0])
        self.assertFalse(trace.used_fallback)

    def test_ineligible_channel_ids_cannot_survive_hydration(self):
        contract = self.fixture()
        self.db.add(Bot(id=2, customer_id=2, organization_id=2, name="Other"))
        self.add_document(2, "Foreign manual", ["Private information."], bot_id=2, org_id=2)
        self.add_document(3, "Other bot same org", ["Other bot information."], bot_id=2, org_id=1)
        self.db.commit()
        with patch.object(rag, "_vector_candidate_ids", return_value=[(20000, 2, 0.0), (30000, 3, 0.0), (10000, 1, 0.9)]), \
             patch.object(rag, "_lexical_candidate_ids", return_value=[]):
            rows, trace = self.retrieve(self.bot, contract)
        self.assertTrue(rows)
        self.assertEqual({r["document"].id for r in rows}, {1})
        self.assertEqual(trace.retrieval.candidates[(2, 20000)].final_reason, "excluded_security_or_lifecycle_scope")
        self.assertEqual(trace.retrieval.candidates[(3, 30000)].final_reason, "excluded_security_or_lifecycle_scope")
        self.assertEqual(trace.retrieval.candidates[(1, 10000)].vector_rank, 3)

    def test_lifecycle_and_embedding_profile_are_absolute(self):
        contract = self.fixture()
        for status in ("pending", "processing_failed", "deleted"):
            with self.subTest(status=status):
                self.db.get(Chunk, 10000).status = status
                self.db.commit()
                with patch.object(rag, "_vector_candidate_ids", return_value=[(10000, 1, 0.0), (10001, 1, 0.9)]):
                    rows, _ = self.retrieve(self.bot, contract)
                self.assertNotIn(10000, {r["chunk"].id for r in rows})
        self.db.get(Chunk, 10000).status = "ready"
        self.db.get(Chunk, 10000).embedding_model = "incompatible"
        self.db.commit()
        with patch.object(rag, "_vector_candidate_ids", return_value=[(10000, 1, 0.0), (10001, 1, 0.9)]):
            rows, trace = self.retrieve(self.bot, contract)
        self.assertNotIn(10000, {r["chunk"].id for r in rows})
        self.assertEqual(trace.retrieval.candidates[(1, 10000)].final_reason, "excluded_embedding_profile")

    def test_active_subject_chain_remains_scoped_at_low_scores(self):
        self.add_document(1, "Sea Essence Omega 3 Fish Oil", ["Ingredients: oil. Directions: daily. Price $37."])
        self.add_document(2, "Turmeric Boost", ["Ingredients: extract. Directions: daily. Price $33."])
        self.db.commit()
        _, state = self.contract(self.bot, "tell me about Sea Essence Omega 3")
        for query in ("ingredients?", "how to use it?", "price?"):
            contract, state = self.contract(self.bot, query, state=state)
            with patch.object(rag, "_vector_candidate_ids", side_effect=self.low_vector):
                rows, _ = self.retrieve(self.bot, contract)
            self.assertTrue(rows)
            self.assertEqual({r["document"].id for r in rows}, {1})

    def test_trace_records_stages_scores_and_final_dispositions(self):
        contract = self.fixture()
        rows, trace = self.retrieve(self.bot, contract)
        with patch.object(planning, "generate_auxiliary", return_value='{"ranked_candidates":[0]}'):
            reviewed = planning.review_evidence(self.bot, contract, rows, trace)
        compress_and_rerank_chunks(reviewed, contract.original_query, 140, query_contract=contract, trace=trace)
        payload = compact_chat_diagnostics(trace)["diagnostics"]["retrieval_trace"]
        self.assertEqual(payload["original_user_message"], contract.original_query)
        self.assertEqual(payload["selected_document_ids"], [1])
        for name in ("vector_channel", "lexical_channel", "fusion", "review_pool", "reviewer_visible",
                     "context_validated", "context_ranked", "context_distinct", "context_fair_allocation", "final_context"):
            self.assertIn(name, payload["stage_counts"])
        for candidate in payload["candidates"]:
            self.assertTrue(candidate["entry_stage"])
            self.assertTrue(candidate["final_reason"])
            self.assertTrue(candidate["events"])
            self.assertIn("signals", candidate)
            self.assertNotIn("content", candidate)
        vector = next(c for c in payload["candidates"] if c["vector_rank"] == 1)
        self.assertIsNotNone(vector["vector_distance"])
        self.assertIsNotNone(vector["fusion_rank"])

    def test_context_budget_and_duplicates_are_traced_and_ranked(self):
        rows = [item(1, "Identical factual sentence.", 0.1),
                item(2, "Identical factual sentence.", 0.9),
                item(3, "A distinct lower ranked fact which needs some space.", 0.02)]
        trace = ChatTrace(1, "test")
        used, context = compress_and_rerank_chunks(rows, "Explain", 65, trace=trace)
        self.assertLessEqual(len(context), 65)
        self.assertEqual([r["chunk"].id for r in used], [2])
        self.assertEqual(trace.retrieval.candidates[(1, 1)].final_reason, "excluded_duplicate")
        self.assertEqual(trace.retrieval.candidates[(1, 3)].final_reason, "excluded_context_budget")

    def test_reviewer_failure_keeps_ranked_scope(self):
        contract = self.fixture()
        rows, trace = self.retrieve(self.bot, contract)
        with patch.object(planning, "generate_auxiliary", side_effect=TimeoutError("offline")) as model:
            reviewed = planning.review_evidence(self.bot, contract, rows, trace)
        self.assertEqual([r["chunk"].id for r in reviewed], [r["chunk"].id for r in rows])
        self.assertEqual({r["document"].id for r in reviewed}, {1})
        self.assertEqual(model.call_count, 1)
        self.assertIn("reviewer_failure_fallback_used", trace.retrieval.fallback_events)

    def test_no_extra_model_or_embedding_calls(self):
        self.fixture()
        def auxiliary(_bot, payload, _instructions, **_kwargs):
            data = json.loads(payload)
            if "candidates" in data:
                return '{"ranked_candidates":[0]}'
            return plan(active_subjects=["Field Ops Manual"], scope_mode="single_entity").model_dump_json()
        with patch.object(planning, "generate_auxiliary", side_effect=auxiliary) as auxiliary_call, \
             patch.object(rag, "generate_embedding", return_value=[0.0] * 768) as embedding, \
             patch.object(rag.global_semantic_cache, "get", return_value=None), \
             patch.object(rag.global_semantic_cache, "set"), patch.object(rag, "_RETRIEVAL_CACHE", {}), \
             patch.object(rag, "generate", return_value="The equipment operates within the stated range.") as generate, \
             patch.object(rag, "verify_answer", side_effect=AssertionError("Unnecessary verifier call")), \
             patch.object(rag, "polish_answer", side_effect=lambda **kw: kw["answer"]), contextlib.redirect_stdout(io.StringIO()):
            rag.answer_question(self.db, self.bot, "tell me about Field Ops Manual", knowledge_version=1)
        self.assertEqual(auxiliary_call.call_count, 2)  # one planner, one reviewer
        self.assertEqual(embedding.call_count, 1)
        self.assertEqual(generate.call_count, 1)
        self.assertIn("\nUSER QUESTION\ntell me about Field Ops Manual\n", generate.call_args.kwargs["prompt"])

    def test_review_pool_hard_cap_and_comparison_fairness(self):
        rows = [item(i, f"Distinct required fact {i}.", doc_id=1 if i < 55 else 2) for i in range(60)]
        selected = POLICY.select(rows, POLICY.reviewer_max, POLICY.reviewer_max, [1, 2])
        self.assertEqual(len(selected), 48)
        self.assertEqual({r["document"].id for r in selected}, {1, 2})

    def test_required_field_budget_reports_the_actual_lost_chunk(self):
        rows = [item(1, "Directions: Turn the dial clockwise.", 0.8),
                item(2, "Directions: " + "Additional safety instructions must be observed. " * 30, 0.2)]
        for row in rows:
            row["required_fields"] = ["directions"]
        trace = ChatTrace(1, "test")
        used, context = compress_and_rerank_chunks(rows, "What are the directions?", 180, trace=trace)
        self.assertEqual([row["chunk"].id for row in used], [1])
        self.assertIn("Turn the dial", context)
        self.assertNotIn("Additional safety", context)
        self.assertEqual(trace.retrieval.candidates[(1, 2)].final_reason, "excluded_context_budget")
        self.assertEqual(trace.retrieval.candidates[(1, 2)].indicators["budget_omitted_field_parts"], {"directions": 1})
        self.assertLessEqual(len(context), 180)

    def test_retrieval_cache_revalidates_profile_and_preserves_trace(self):
        contract = self.fixture()
        with patch.object(rag, "_RETRIEVAL_CACHE", {}):
            first = ChatTrace(1, "test")
            rows = rag.retrieve_relevant_chunks_cached(self.db, 1, contract.retrieval_query, query_contract=contract, trace=first)
            self.assertTrue(rows)
            hit = ChatTrace(1, "test")
            cached = rag.retrieve_relevant_chunks_cached(self.db, 1, contract.retrieval_query, query_contract=contract, trace=hit)
            self.assertEqual(hit.retrieval.cache, "retrieval_hit")
            self.assertEqual(hit.retrieval.original_user_message, contract.original_query)
            self.assertEqual(hit.retrieval.candidates[(1, rows[0]["chunk"].id)].vector_rank,
                             first.retrieval.candidates[(1, rows[0]["chunk"].id)].vector_rank)
            changed_id = cached[0]["chunk"].id
            self.db.get(Chunk, changed_id).embedding_model = "incompatible"
            self.db.commit()
            refreshed = rag.retrieve_relevant_chunks_cached(self.db, 1, contract.retrieval_query, query_contract=contract, trace=ChatTrace(1, "test"))
            self.assertNotIn(changed_id, {row["chunk"].id for row in refreshed})

    def test_trace_redacts_synthetic_secrets_without_changing_original(self):
        trace = ChatTrace(1, "test")
        synthetic = "AIza" + "x" * 35
        original = "Please check api_key=" + synthetic + " password=fixture-only"
        trace.retrieval.configure(original, original)
        trace.retrieval.requested_fields = [original]
        trace.retrieval.candidate(item(1, "Never persist this body."), "test").indicators["field"] = original
        serialized = json.dumps(trace.retrieval.to_dict())
        self.assertNotIn(synthetic, serialized)
        self.assertNotIn("fixture-only", serialized)
        self.assertNotIn("Never persist this body", serialized)
        self.assertEqual(trace.retrieval.original_user_message, original)

    def test_named_signals_are_not_applied_twice_or_mutated_in_cached_rows(self):
        row = item(1, "A field-specific phrase.")
        row["selection_signals"] = {"lexical_term_match": 0.12}
        trace = ChatTrace(1, "test")
        compress_and_rerank_chunks([row], "A field-specific phrase", 200, trace=trace)
        self.assertEqual(row["selection_signals"], {"lexical_term_match": 0.12})
        self.assertNotIn("lexical_term_match", trace.retrieval.candidates[(1, 1)].signals["context_ranking"])

    def test_adjacent_expansion_defaults_cannot_displace_primary_recall(self):
        contract = replace(self.fixture(), subject_document_id=None, resolved_subject=None, mode="factual")
        with patch.object(rag, "_vector_candidate_ids", return_value=[(10000, 1, 0.92)]), \
             patch.object(rag, "_lexical_candidate_ids", return_value=[]):
            rows, trace = self.retrieve(self.bot, contract)
        self.assertEqual(rows[0]["chunk"].id, 10000)
        self.assertTrue(any(row["adjacent_only"] for row in rows))
        with patch.object(planning, "generate_auxiliary", side_effect=TimeoutError("offline")):
            reviewed = planning.review_evidence(self.bot, contract, rows, trace)
        used, context = compress_and_rerank_chunks(reviewed, contract.original_query, 160, trace=trace)
        self.assertEqual(used[0]["chunk"].id, 10000)
        self.assertIn("degrees Celsius", context)

    def test_global_alias_miss_still_reaches_the_review_pool(self):
        self.add_document(1, "Handheld Monitor", ["This compact unit fits in a pocket and runs on a battery."])
        self.add_document(2, "Desk Monitor", ["This unit stays on the workbench and needs mains power."])
        self.db.commit()
        contract, _ = self.contract(self.bot, "What do you have?")
        contract = replace(contract, original_query="Which portable monitors are available?",
                           retrieval_query="portable monitors", mode="catalog", catalog_scope=["portable"],
                           requested_fields=["features"], include_constraints=["portable"],
                           permitted_document_ids=[1, 2], subject_document_id=None, resolved_subject=None)
        with patch.object(rag, "_vector_candidate_ids", side_effect=self.low_vector), \
             patch.object(rag, "_lexical_candidate_ids", return_value=[]):
            rows, trace = self.retrieve(self.bot, contract)
        self.assertIn(1, {row["document"].id for row in rows})
        self.assertIsNone(trace.retrieval.fallback_reason)

    def test_no_ready_documents_never_calls_embedding_or_reviewer(self):
        contract = self.fixture()
        self.db.get(Document, 1).status = "deleted"
        self.db.commit()
        with patch.object(rag, "generate_embedding", side_effect=AssertionError("No eligible scope")) as embedding, \
             patch.object(planning, "generate_auxiliary", side_effect=AssertionError("No candidates")) as reviewer:
            rows, trace = self.retrieve(self.bot, contract)
        self.assertEqual(rows, [])
        self.assertEqual(trace.retrieval.fallback_reason, "no_authorized_documents")
        self.assertEqual(embedding.call_count, 0)
        self.assertEqual(reviewer.call_count, 0)


if __name__ == "__main__":
    unittest.main()
