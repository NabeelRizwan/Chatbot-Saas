"""Offline Phase 2 contracts. SQL compilation is NOT a PostgreSQL execution test."""
import contextlib
import importlib.util
import json
import os
from pathlib import Path
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from services.hybrid_retrieval import (ChannelCandidate as C, HybridConfig, HybridRetrievalError,
                                      hybrid_config, recall_parallel, weighted_rrf)
from services.postgres_fts import FTSResult, content_vector, fts_candidates, fts_statement
from services.observability_service import ChatTrace
from services import rag_service as rag
import test_scoped_rag_architecture as fixture
import test_phase_1_6_post_live_correctness as phase16
from database.models import Chunk, Document
from services.knowledge_scope import ready_chunks


def candidate(cid, rank=1, score=0.1, doc=1, backend="dense"):
    return C(cid, doc, score, rank, backend)


class RRFConfigTests(unittest.TestCase):
    def test_dense_only(self):
        c = weighted_rrf([candidate(1)], [], HybridConfig())[0]
        self.assertEqual((c.dense_contribution, c.fts_contribution, c.score), (1/61, 0, 1/61))

    def test_fts_only(self):
        c = weighted_rrf([], [candidate(1)], HybridConfig())[0]
        self.assertEqual((c.dense_contribution, c.fts_contribution), (0, 1/61))

    def test_both(self):
        self.assertEqual(weighted_rrf([candidate(1)], [candidate(1, 2)], HybridConfig())[0].score, 1/61+1/62)

    def test_one_based(self):
        with self.assertRaises(ValueError):
            weighted_rrf([candidate(1, 0)], [], HybridConfig())

    def test_exact_weighted_formula(self):
        c = weighted_rrf([candidate(1, 3)], [candidate(1, 7)], HybridConfig(dense_weight=2, fts_weight=4, rrf_k=30))[0]
        self.assertEqual(c.score, 2/33 + 4/37)

    def test_raw_scores_do_not_affect_ranks(self):
        a = weighted_rrf([candidate(1, 1, -10000)], [candidate(2, 1, 1000000)], HybridConfig())
        b = weighted_rrf([candidate(1, 1, 10000)], [candidate(2, 1, -1000000)], HybridConfig())
        self.assertEqual([(x.chunk_id, x.score) for x in a], [(x.chunk_id, x.score) for x in b])

    def test_deterministic_ties(self):
        c = weighted_rrf([candidate(3, doc=2), candidate(2, doc=1)], [candidate(1, doc=1)], HybridConfig())
        self.assertEqual([x.chunk_id for x in c], [1, 2, 3])

    def test_weights_change_order(self):
        self.assertEqual(weighted_rrf([candidate(1)], [candidate(2)], HybridConfig(fts_weight=2))[0].chunk_id, 2)

    def test_k_changes_contribution(self):
        self.assertEqual(weighted_rrf([candidate(1)], [], HybridConfig(rrf_k=10))[0].score, 1/11)

    def test_deduplication(self):
        self.assertEqual(len(weighted_rrf([candidate(1), candidate(1, 2)], [candidate(1)], HybridConfig())), 1)

    def test_conflicting_identity_rejected(self):
        with self.assertRaises(ValueError):
            weighted_rrf([candidate(1, doc=1)], [candidate(1, doc=2)], HybridConfig())

    def test_zero_weight_supported(self):
        self.assertEqual(weighted_rrf([candidate(1)], [], HybridConfig(dense_weight=0))[0].score, 0)

    def test_invalid_configuration(self):
        for values in [dict(lexical_backend="auto"), dict(rrf_k=0), dict(rrf_k=float("inf")),
                       dict(fts_weight=float("nan")), dict(dense_weight=-1),
                       dict(dense_weight=0, fts_weight=0), dict(candidate_ceiling=0),
                       dict(candidate_ceiling=2001), dict(candidate_ceiling=1.2)]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                HybridConfig(**values)

    def test_default_is_legacy(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(hybrid_config(), HybridConfig())

    def test_env_validation_does_not_echo_value(self):
        with patch.dict(os.environ, {"RAG_LEXICAL_BACKEND": "do-not-log-this"}):
            with self.assertRaisesRegex(ValueError, "^Invalid hybrid retrieval configuration$"):
                hybrid_config()

    def test_adaptive_bound(self):
        self.assertEqual([HybridConfig().bound(x) for x in (25, 80, 160, 501)], [25, 80, 160, 500])
        with self.assertRaises(ValueError):
            HybridConfig().bound(0)

    def test_cache_identity_all_settings(self):
        base = HybridConfig().cache_fragment()
        for kwargs in [dict(lexical_backend="postgres_fts"), dict(rrf_k=10), dict(fts_weight=2),
                       dict(dense_weight=2), dict(candidate_ceiling=160)]:
            self.assertNotEqual(base, HybridConfig(**kwargs).cache_fragment())


class FTSQueryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.db = Session(self.engine)
        self.profile = SimpleNamespace(provider="fixture", model="fixture", version=1)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def compile(self, query="silver prices", **kwargs):
        values = dict(bot_id=7, organization_id=8, document_ids=[9], profile=self.profile, limit=12)
        values.update(kwargs)
        return fts_statement(self.db, query, **values).compile(dialect=postgresql.dialect())

    def test_sql_rank_precedes_limit(self):
        sql = str(self.compile())
        self.assertLess(sql.index("ORDER BY fts_score DESC"), sql.index("LIMIT"))
        self.assertIn("documents.id, chunks.id", sql)

    def test_uses_single_materialized_tsquery(self):
        sql = str(self.compile())
        self.assertEqual(sql.count("websearch_to_tsquery("), 1)
        self.assertIn("AS MATERIALIZED", sql)

    def test_phrase_or_negative_not_rewritten(self):
        query = '"silver package" OR bronze -phone'
        self.assertIn(query, self.compile(query).params.values())

    def test_injection_is_bound(self):
        query = "silver'); DROP TABLE chunks; --"
        sql = self.compile(query)
        self.assertNotIn(query, str(sql))
        self.assertIn(query, sql.params.values())

    def test_numeric_terms_not_removed(self):
        query = "$33 60-day COA EPA SKU-123"
        self.assertIn(query, self.compile(query).params.values())

    def test_indexable_guards(self):
        sql = str(self.compile())
        self.assertIn("numnode(", sql)
        self.assertIn("querytree(", sql)
        self.assertIn("NOT IN", sql)

    def test_scope_applied_before_limit(self):
        sql = str(self.compile()).split("LIMIT")[0]
        for name in ("documents.bot_id", "documents.organization_id", "chunks.bot_id", "chunks.organization_id",
                     "documents.processing_status", "chunks.status", "documents.status", "documents.id IN",
                     "websites.active_crawl_id", "website_crawls.version", "chunks.crawl_id",
                     "chunks.embedding_provider", "chunks.embedding_model", "chunks.embedding_version"):
            self.assertIn(name, sql)

    def test_null_tenant_fails_closed(self):
        self.assertIn("false", str(self.compile(organization_id=None)))

    def test_empty_scope_is_not_discovery(self):
        compiled = self.compile(document_ids=[])
        self.assertIn([], compiled.params.values())

    def test_no_content_or_embedding_hydration_in_sql(self):
        sql = str(self.compile())
        self.assertNotIn("chunks.embedding ", sql)
        self.assertNotIn("documents.title", sql)
        self.assertNotIn(" ILIKE ", sql)

    def test_expression_matches_migration(self):
        sql = str(content_vector().compile(dialect=postgresql.dialect()))
        self.assertEqual(sql, "to_tsvector('english'::regconfig, coalesce(chunks.content, ''))")
        path = Path(__file__).parent / "migrations/versions/20260910_01_postgres_fts.py"
        spec = importlib.util.spec_from_file_location("phase2_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        self.assertIn(sql.replace("chunks.content", "content"), migration.CREATE_SQL)
        with patch.object(migration.op, "get_context") as ctx, patch.object(migration.op, "execute") as execute:
            migration.upgrade()
            execute.assert_called_once_with(migration.CREATE_SQL)
            ctx.return_value.autocommit_block.assert_called_once()
            execute.reset_mock()
            migration.downgrade()
            execute.assert_called_once_with(migration.DROP_SQL)

    def test_bounded_query_and_candidates(self):
        for query, limit in [("a"*8193, 10), ("abc", 0), ("abc", 2001)]:
            with self.assertRaises(ValueError):
                self.compile(query, limit=limit)


class ChannelFailureTests(unittest.TestCase):
    def run_channels(self, dense=lambda: [1], fts=lambda: FTSResult((), "indexable")):
        t = ChatTrace(1, "offline")
        return recall_parallel(dense, fts, t), t

    @staticmethod
    def fail():
        raise TimeoutError("secret exception text must not escape")

    def test_fts_failure(self):
        (dense, _), trace = self.run_channels(fts=self.fail)
        self.assertEqual(dense, [1])
        self.assertEqual(trace.retrieval.hybrid["degradation"], "dense_only")
        self.assertIn("fts_leg_error", trace.retrieval.fallback_events)

    def test_dense_failure(self):
        (_, fts), trace = self.run_channels(dense=self.fail)
        self.assertIsNotNone(fts)
        self.assertEqual(trace.retrieval.hybrid["degradation"], "fts_only")

    def test_both_failure(self):
        t = ChatTrace(1, "offline")
        with self.assertRaises(HybridRetrievalError):
            recall_parallel(self.fail, self.fail, t)
        self.assertEqual(t.retrieval.fallback_reason, "both_retrieval_channels_failed")
        self.assertNotIn("secret exception", json.dumps(t.to_debug_dict()))

    def test_embedding_and_fts_are_independent(self):
        event = Event()
        def dense():
            if not event.wait(2):
                raise AssertionError("FTS never started")
            return [1]
        def fts():
            event.set()
            return FTSResult((), "empty")
        (_, _), trace = self.run_channels(dense, fts)
        self.assertEqual(trace.retrieval.hybrid["degradation"], "full_hybrid")


class HybridApplicationTests(unittest.TestCase):
    add_document = fixture.ScopedRagTests.add_document
    contract = fixture.ScopedRagTests.contract
    retrieve = fixture.ScopedRagTests.retrieve
    tearDown = fixture.ScopedRagTests.tearDown
    answer = phase16.PostLiveCorrectnessTests.answer

    def setUp(self):
        fixture.ScopedRagTests.setUp(self)
        self.patches.enter_context(patch.dict(os.environ, {"RAG_LEXICAL_BACKEND": "postgres_fts"}))
        self.patches.enter_context(patch.object(rag, "_RETRIEVAL_CACHE", {}))
        self.patches.enter_context(patch.object(rag.global_semantic_cache, "get", return_value=None))
        self.patches.enter_context(patch.object(rag.global_semantic_cache, "set"))
        # Only the PostgreSQL boundary is mocked here. Real scope resolution,
        # hydration, RRF, field reservation, review pool and compression run.
        def lexical(factory, text, bot_id, org_id, ids, profile, limit):
            with factory() as db:
                rows = ready_chunks(db.query(Chunk.id, Document.id).join(Document, Chunk.document_id == Document.id),
                                    bot_id, org_id, ids).filter(Chunk.embedding_provider == profile.provider,
                                    Chunk.embedding_model == profile.model, Chunk.embedding_version == profile.version)\
                    .order_by(Chunk.id).limit(limit).all()
            return FTSResult(tuple(C(cid, did, .001, rank, "postgres_fts") for rank, (cid, did) in enumerate(rows, 1)), "indexable")
        self.fts = self.patches.enter_context(patch.object(rag, "fts_candidates", side_effect=lexical))
        self.legacy = self.patches.enter_context(patch.object(rag, "_lexical_candidate_ids", side_effect=AssertionError("Legacy fallback forbidden")))

    def test_sea_essence_price_followup_scope(self):
        _, state = self.contract("Tell me about Sea Essence Omega 3")
        c, _ = self.contract("price?", state=state)
        self.assertEqual(c.permitted_document_ids, [1])
        rows, _ = self.retrieve(c)
        self.assertEqual({r['document'].id for r in rows}, {1})

    def test_turmeric_followup_scope(self):
        _, state = self.contract("Tell me about Turmeric Boost")
        c, _ = self.contract("ingredients?", state=state)
        self.assertEqual(c.permitted_document_ids, [2])
        self.assertEqual({r['document'].id for r in self.retrieve(c)[0]}, {2})

    def test_comparison_fairness(self):
        c, _ = self.contract("Compare Sea Essence Omega 3 and Turmeric Boost prices and ingredients")
        rows, trace = self.retrieve(c)
        self.assertEqual({r['document'].id for r in rows}, {1, 2})
        self.assertLessEqual(len(rows), 48)
        self.assertTrue(any(r.get('required_fields') for r in rows))

    def test_price_roles_preserved(self):
        fixture.ScopedRagTests.test_structured_value_does_not_displace_supported_field_options(self)

    def test_explicit_entity_planner_failure(self):
        c, _ = self.contract("Tell me about Turmeric Boost", response=None)
        self.assertEqual(c.permitted_document_ids, [2])
        self.assertTrue(self.retrieve(c)[0])

    def test_fts_only_guarantee(self):
        c, _ = self.contract("Does Sea Essence Omega 3 have a money-back guarantee for repeat purchases?")
        self.fts.side_effect = None
        self.fts.return_value = FTSResult((candidate(15, backend="postgres_fts"),), "indexable")
        with patch.object(rag, "_vector_candidate_ids", return_value=[]):
            rows, trace = self.retrieve(c)
        self.assertIn(15, [r['chunk'].id for r in rows])
        self.assertEqual(trace.retrieval.candidates[(1, 15)].fts_rank, 1)

    def test_timeline_fts_evidence(self):
        c, _ = self.contract("When might I see results from Turmeric Boost?")
        rows, _ = self.retrieve(c)
        self.assertIn(26, [r['chunk'].id for r in rows])

    def test_lexical_only_identifier_and_low_score(self):
        c, _ = self.contract("Tell me about Sea Essence Omega 3")
        self.fts.side_effect = None
        self.fts.return_value = FTSResult((candidate(12, score=1e-30, backend="postgres_fts"),), "indexable")
        with patch.object(rag, "_vector_candidate_ids", return_value=[]):
            rows, trace = self.retrieve(c)
        self.assertIn(12, [r['chunk'].id for r in rows])
        self.assertEqual(trace.retrieval.candidates[(1, 12)].dense_rrf_contribution, 0)

    def test_dense_only_paraphrase(self):
        c, _ = self.contract("Tell me about Sea Essence Omega 3")
        self.fts.side_effect = TimeoutError("offline")
        rows, trace = self.retrieve(c)
        self.assertTrue(rows)
        self.assertEqual(trace.retrieval.hybrid['degradation'], 'dense_only')
        self.legacy.assert_not_called()

    def test_embedding_failure_still_retrieves_fts(self):
        c, _ = self.contract("Tell me about Turmeric Boost")
        with patch.object(rag, "generate_embedding", side_effect=TimeoutError("offline")):
            rows, trace = self.retrieve(c)
        self.assertTrue(rows)
        self.assertEqual(trace.retrieval.hybrid['degradation'], 'fts_only')

    def test_both_fail_no_legacy_or_field_only_success(self):
        c, _ = self.contract("Tell me about Turmeric Boost")
        self.fts.side_effect = TimeoutError("offline")
        with patch.object(rag, "generate_embedding", side_effect=TimeoutError("offline")):
            with self.assertRaises(HybridRetrievalError):
                self.retrieve(c)
        self.legacy.assert_not_called()

    def test_fts_raw_scores_and_contributions_traced(self):
        c, _ = self.contract("Tell me about Turmeric Boost")
        _, trace = self.retrieve(c)
        ct = trace.retrieval.candidates[(2, 20)]
        self.assertEqual(ct.fts_rank, 1)
        self.assertEqual(ct.fts_score, .001)
        self.assertIsNotNone(ct.vector_rank)
        self.assertEqual(ct.rrf_total, ct.dense_rrf_contribution + ct.fts_rrf_contribution)
        self.assertGreaterEqual(ct.rrf_rank, 1)
        serialized = json.dumps(trace.to_debug_dict())
        self.assertNotIn('Ingredient Alpha', serialized)
        self.assertIn('full_hybrid', serialized)

    def test_no_duplicate_lexical_context_boost(self):
        c, _ = self.contract("Sea Essence Omega 3 ingredients?")
        rows, trace = self.retrieve(c)
        rag.compress_and_rerank_chunks(rows, c.original_query, query_contract=c, trace=trace)
        for ct in trace.retrieval.candidates.values():
            for stage in ('fusion_ranking', 'context_ranking'):
                for signal in ('lexical_term_match', 'entity_exact_match', 'numeric_match'):
                    self.assertNotIn(signal, ct.signals.get(stage, {}))

    def test_original_message_and_single_embedding(self):
        question = 'Compare Sea Essence Omega 3 and Turmeric Boost prices and ingredients.'
        c, _ = self.contract(question)
        with patch.object(rag, 'generate_embedding', return_value=[0.0]*768) as embedding:
            self.retrieve(c)
        embedding.assert_called_once()
        self.assertEqual(c.original_query, question)

    def test_unauthorized_hydration_rejected(self):
        self.add_document(3, 'Foreign', bot_id=99, org_id=99)
        self.db.commit()
        c, _ = self.contract('Tell me about Turmeric Boost')
        self.fts.side_effect = None
        self.fts.return_value = FTSResult((candidate(30, doc=3, backend='postgres_fts'),), 'indexable')
        rows, trace = self.retrieve(c)
        self.assertNotIn(3, {r['document'].id for r in rows})
        self.assertIsNone(trace.retrieval.candidates[(3, 30)].rrf_total)

    def test_cache_backend_and_subject_isolation(self):
        c1, _ = self.contract('Tell me about Turmeric Boost')
        c2, _ = self.contract('Tell me about Sea Essence Omega 3')
        fts_key = rag.semantic_cache_identity(self.bot, 'price?', [], c1)
        self.assertNotEqual(fts_key, rag.semantic_cache_identity(self.bot, 'price?', [], c2))
        with patch.dict(os.environ, {'RAG_LEXICAL_BACKEND': 'legacy'}):
            self.assertNotEqual(fts_key, rag.semantic_cache_identity(self.bot, 'price?', [], c1))

    def test_retrieval_cache_retains_fts_trace_and_backend(self):
        c, _ = self.contract('Tell me about Turmeric Boost')
        traces = [ChatTrace(1, 'offline'), ChatTrace(1, 'offline')]
        for trace in traces:
            rows = rag.retrieve_relevant_chunks_cached(self.db, 1, c.retrieval_query, trace=trace, query_contract=c)
        self.assertEqual(traces[1].retrieval.cache, 'retrieval_hit')
        self.assertTrue(all(r['lexical_backend'] == 'postgres_fts' for r in rows))
        self.assertTrue(any(c.fts_rank for c in traces[1].retrieval.candidates.values()))

    def test_empty_query_leg_not_error(self):
        c, _ = self.contract('Tell me about Turmeric Boost')
        self.fts.side_effect = None
        self.fts.return_value = FTSResult((), 'empty')
        rows, trace = self.retrieve(c)
        self.assertTrue(rows)
        self.assertIn('fts_empty_query', trace.retrieval.fallback_events)
        self.assertEqual(trace.retrieval.hybrid['query_status'], 'empty')

    def test_live_inventory_still_requires_live_data(self):
        phase16.PostLiveCorrectnessTests.test_33_live_quantity_safe_no_cards(self)
        self.fts.assert_not_called()

    def test_generation_provider_failure_is_not_absent_evidence(self):
        phase16.PostLiveCorrectnessTests.test_04_provider_failure_is_not_missing_knowledge_or_credential_advice(self)

    def test_actual_final_prompt_preserves_original_message(self):
        phase16.PostLiveCorrectnessTests.test_56_original_question_unmodified(self)

    def test_all_model_boundaries_have_original_call_counts(self):
        phase16.PostLiveCorrectnessTests.test_57_call_counts_bounded(self)

    def test_both_failure_returns_explicit_service_failure(self):
        self.fts.side_effect = TimeoutError('offline')
        with patch.object(rag, 'generate_embedding', side_effect=TimeoutError('offline')):
            (answer, sources, chunks), trace, generation = self.answer('ingredients of Turmeric Boost')
        self.assertEqual(trace.retrieval.terminal_response_category, 'temporary_service_failure')
        self.assertEqual((sources, chunks), ([], []))
        generation.assert_not_called()
        self.legacy.assert_not_called()

    def test_retrieval_cache_switch_cannot_hit_other_backend(self):
        c, _ = self.contract('Tell me about Turmeric Boost')
        rag.retrieve_relevant_chunks_cached(self.db, 1, c.retrieval_query, query_contract=c)
        self.assertEqual(len(rag._RETRIEVAL_CACHE), 1)
        with patch.dict(os.environ, {'RAG_LEXICAL_BACKEND': 'legacy'}), \
             patch.object(rag, '_lexical_candidate_ids', return_value=[]):
            trace = ChatTrace(1, 'offline')
            rag.retrieve_relevant_chunks_cached(self.db, 1, c.retrieval_query, trace=trace, query_contract=c)
        self.assertNotEqual(trace.retrieval.cache, 'retrieval_hit')
        self.assertEqual(len(rag._RETRIEVAL_CACHE), 2)


if __name__ == '__main__':
    unittest.main()
