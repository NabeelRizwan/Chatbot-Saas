"""Scope-only Q3 regression tests; SQLite identity lookup, no providers."""
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from test_resource_discovery import ResourceFixture
from services import rag_planning, rag_service
from services.retrieval_contracts import (ScopeStrategy, HardKnowledgeScope, KnowledgeResourceRef,
    ResourceCandidate, SoftSemanticScope, SemanticScopeState, QueryExecutionContract, choose_scope_strategy)
from services.discovery_scope import preserve_discovery_scope


class DiscoveryHandoffTests(ResourceFixture):
    def setUp(self):
        super().setUp()
        self.add(1, "Evening Courses", kind="collection")
        self.add(2, "Silver Writing Course", kind="course")
        self.project(1, 2)

    def runtime(self, question, history=(), state=None):
        with patch.object(rag_planning, "plan_query", return_value=None), \
             patch.dict("os.environ", {"RAG_RESOURCE_DISCOVERY": "on"}), \
             patch("services.resource_scope_adapter.ResourceDiscoveryService", return_value=self.service):
            return rag_planning.prepare_query(self.db, self.bot, question, list(history), state or {},
                                             rag_service._build_turn_query_contract, hard_scope=self.hard)

    def test_discovery_collection_is_not_exclusive_evidence(self):
        contract = self.runtime("Are there any evening courses that are beginner friendly?")
        self.assertEqual(contract.execution.soft_scope.resolved_document_ids, (1,))
        self.assertEqual(contract.execution.scope_decision.strategy, ScopeStrategy.BROAD_AUTHORIZED)
        self.assertIsNone(contract.permitted_document_ids)
        self.assertEqual(set(contract.execution.hard_scope.authorized_document_ids), {1, 2})

    def test_followup_retains_discovery_universe(self):
        question = "Are there any evening courses that are beginner friendly?"
        first = self.runtime(question)
        history = [{"role": "user", "content": question},
                   {"role": "assistant", "content": "Explore the Evening Courses collection."}]
        contract = self.runtime("Which one?", history, rag_planning.next_state(first, {}))
        self.assertEqual(contract.execution.scope_decision.strategy, ScopeStrategy.BROAD_AUTHORIZED)
        self.assertIsNone(contract.permitted_document_ids)

    def test_explicit_collection_page_preserves_existing_resolution(self):
        q = "What does the Evening Courses collection page say?"
        with patch("services.discovery_scope.preserve_discovery_scope", side_effect=lambda c, h: c):
            before = self.runtime(q)
        after = self.runtime(q)
        self.assertEqual(after.execution.scope_decision, before.execution.scope_decision)

    def test_proven_exact_collection_lookup_stays_exact(self):
        candidate = self.discover("Evening Courses").resolutions[0].candidate
        self.assertIsNotNone(candidate)
        soft = SoftSemanticScope(resolved_resources=(candidate.resource,), resource_candidates=(candidate,),
                                 state=SemanticScopeState.RESOLVED_SINGLE)
        c = ScopePolicyTests().contract("Tell me about Evening Courses", soft=soft)
        preserve_discovery_scope(c, [])
        self.assertEqual(c.execution.scope_decision.effective_document_ids, (1,))

    def test_similarly_named_concrete_resource_still_narrows(self):
        self.add(3, "Evening Courses Workbook", kind="product")
        self.project(3)
        c = self.runtime("Tell me about Evening Courses Workbook")
        self.assertEqual(c.permitted_document_ids, [3])

    def test_exact_followup_stays_exact(self):
        q = "Tell me about Silver Writing Course"
        first = self.runtime(q)
        c = self.runtime("What are its benefits?", [{"role": "user", "content": q}],
                         rag_planning.next_state(first, {}))
        self.assertEqual(c.permitted_document_ids, [2])

    def test_same_name_foreign_bot_cannot_enter_identity_or_authorization(self):
        from database.models import Bot, Organization
        self.db.add(Organization(id=2, name="Other", slug="other"))
        self.db.add(Bot(id=2, organization_id=1, customer_id=1, name="Other bot"))
        self.db.add(Bot(id=3, organization_id=2, customer_id=1, name="Foreign bot"))
        self.db.flush()
        self.add(3, "Evening Courses", bot=2, kind="collection")
        self.add(4, "Evening Courses", org=2, bot=3, kind="collection")
        self.db.commit()
        c = self.runtime("Are there any evening courses that are beginner friendly?")
        self.assertEqual(set(c.execution.hard_scope.authorized_document_ids), {1, 2})
        self.assertEqual(c.execution.soft_scope.resolved_document_ids, (1,))

    def test_stale_catalog_link_revalidated(self):
        from database.models import Document
        self.db.get(Document, 1).status = "superseded"
        self.db.commit()
        c = self.runtime("Are there any evening courses that are beginner friendly?")
        self.assertNotIn(1, c.execution.hard_scope.authorized_document_ids)
        self.assertNotIn(1, c.execution.soft_scope.resolved_document_ids)


class ScopePolicyTests(unittest.TestCase):
    question = "Are there any evening courses that are beginner friendly?"

    def contract(self, question=None, *, hard=None, resource=None, soft=None):
        hard = hard or HardKnowledgeScope(1, 1, (1, 2))
        resource = resource or KnowledgeResourceRef("r1", 1, 1, "Evening Courses", document_ids=(1,))
        soft = soft or SoftSemanticScope(resolved_resources=(resource,),
            resource_candidates=(ResourceCandidate(resource, confidence=1., canonical_exact=True),),
            state=SemanticScopeState.RESOLVED_SINGLE)
        question = question or self.question
        execution = QueryExecutionContract(question, "unchanged frozen query", hard, soft, choose_scope_strategy(hard, soft))
        return SimpleNamespace(original_query=question, execution=execution, permitted_document_ids=[1],
                               scope_mode="single_entity", entity_resolution={})

    def test_query_identities_and_hard_scope_not_modified(self):
        c = self.contract(); old = c.execution
        preserve_discovery_scope(c, [])
        self.assertIs(c.execution.hard_scope, old.hard_scope)
        self.assertIs(c.execution.soft_scope, old.soft_scope)
        self.assertEqual(c.execution.retrieval_query, old.retrieval_query)
        self.assertNotEqual(c.execution.cache_identity(), old.cache_identity())

    def test_positive_discovery_grammar_across_domains(self):
        for name, q in [("Flexible Plans", "Are there any flexible plans with extra storage?"),
                        ("City Hotels", "Which city hotels are near transit?"),
                        ("Evening Courses", "Do you offer any evening courses for beginners?")]:
            with self.subTest(q=q):
                c = self.contract(q, resource=KnowledgeResourceRef("r1", 1, 1, name, document_ids=(1,)))
                preserve_discovery_scope(c, [])
                self.assertEqual(c.execution.scope_decision.strategy, ScopeStrategy.BROAD_AUTHORIZED)

    def test_deictic_followups_inherit_user_discovery(self):
        for q in ("Which one?", "What about the other?", "Which is cheaper?", "Which tastes better?"):
            with self.subTest(q=q):
                c = self.contract(q)
                preserve_discovery_scope(c, [{"role": "user", "content": self.question}])
                self.assertEqual(c.execution.scope_decision.reason, "discovery_set_followup")

    def test_empty_history_never_invents_discovery(self):
        c = self.contract("Which one?")
        old = c.execution
        preserve_discovery_scope(c, [])
        self.assertIs(c.execution, old)

    def test_assistant_text_does_not_establish_discovery(self):
        c = self.contract("Which one?"); old = c.execution
        preserve_discovery_scope(c, [{"role": "assistant", "content": self.question}])
        self.assertIs(c.execution, old)

    def test_explicit_switch_and_intervening_exact_turn_stop_inheritance(self):
        for q, history in [("Tell me about Silver Writing Course", [{"role": "user", "content": self.question}]),
                           ("Which one?", [{"role": "user", "content": self.question},
                                           {"role": "user", "content": "Tell me about Silver Writing Course"}])]:
            c = self.contract(q); old = c.execution
            preserve_discovery_scope(c, history)
            self.assertIs(c.execution, old)

    def test_short_followup_chain_preserves_discovery(self):
        c = self.contract("Which is cheaper?")
        preserve_discovery_scope(c, [{"role": "user", "content": self.question},
                                    {"role": "user", "content": "Which one?"}])
        self.assertEqual(c.execution.scope_decision.reason, "discovery_set_followup")

    def test_field_or_explicit_page_request_is_not_category_discovery(self):
        for q in ("Are there any reviews of Evening Courses?", "Are there any discounts for Evening Courses?",
                  "Tell me what the Evening Courses collection page says", "Evening courses?",
                  'Explain the sentence "Are there any evening courses that are beginner friendly?"'):
            c = self.contract(q); old = c.execution
            preserve_discovery_scope(c, [])
            self.assertIs(c.execution, old)

    def test_followup_after_field_question_keeps_exact_resource(self):
        for q in ("Are there any discounts for Evening Courses?", "Are there any benefits for Evening Courses?"):
            c = self.contract("Which one?"); old = c.execution
            preserve_discovery_scope(c, [{"role": "user", "content": q}])
            self.assertIs(c.execution, old)

    def test_empty_and_restricted_authorization_never_widen(self):
        for ids in ((), (1,)):
            c = self.contract(hard=HardKnowledgeScope(1, 1, ids)); old = c.execution.hard_scope
            preserve_discovery_scope(c, [])
            self.assertIs(c.execution.hard_scope, old)
            self.assertEqual(old.intersect(c.execution.scope_decision.effective_document_ids), ids)

    def test_foreign_and_unready_resources_cannot_promote(self):
        ref = KnowledgeResourceRef("r1", 1, 1, "Evening Courses", document_ids=(1,))
        for resource in (replace(ref, organization_id=2), replace(ref, bot_id=2),
                         replace(ref, document_ids=(99,)), replace(ref, status="superseded")):
            c = self.contract(resource=resource); old = c.execution
            preserve_discovery_scope(c, [])
            self.assertIs(c.execution, old)
            self.assertEqual(c.execution.scope_decision.effective_document_ids, ())

    def test_ambiguous_unknown_and_malformed_proofs_not_promoted(self):
        good = self.contract().execution.soft_scope
        for soft in (replace(good, ambiguity=True), replace(good, state=SemanticScopeState.UNRESOLVED),
                     replace(good, resource_candidates=()), replace(good, unresolved_mentions=("unknown",)),
                     replace(good, state="invalid-state")):
            c = self.contract(soft=soft); old = c.execution
            preserve_discovery_scope(c, [])
            self.assertIs(c.execution, old)

    def test_long_or_malformed_history_is_not_truncated_to_a_topic(self):
        for history in (None, {}, [{"role": "user", "content": None}],
                        [{"role": "user", "content": self.question + "x" * 2000}]):
            c = self.contract("Which one?"); old = c.execution
            preserve_discovery_scope(c, history)
            self.assertIs(c.execution, old)

    def test_empty_alias_is_not_history_discovery_evidence(self):
        ref = KnowledgeResourceRef("r1", 1, 1, "Evening Courses", aliases=("",), document_ids=(1,))
        c = self.contract("Which one?", resource=ref); old = c.execution
        preserve_discovery_scope(c, [{"role": "user", "content": None}])
        self.assertIs(c.execution, old)


class TargetedHarnessTests(unittest.TestCase):
    def test_inherits_q1_read_only_repository_and_expiry_guard(self):
        from scripts.validate_discovery_scope import ScopeCanary
        from scripts.run_compact_evidence_canary import CompactCanary
        from services.canary_contracts import CanaryError
        runner = object.__new__(ScopeCanary)
        self.assertIs(ScopeCanary.repository, CompactCanary.repository)
        self.assertIs(ScopeCanary.ensure_lease, CompactCanary.ensure_lease)
        runner.retained_until = 0
        with self.assertRaisesRegex(CanaryError, "LEASE_EXPIRED"):
            runner.ensure_lease()
        with self.assertRaisesRegex(CanaryError, "WRITES_FORBIDDEN"):
            with runner.repository(writable=True):
                self.fail("Writable connection entered")

    def test_targeted_wrapper_keeps_real_retrieval_and_q1_packer(self):
        from scripts import validate_discovery_scope as wrapper
        from services.compact_evidence_pack import materialize_compact
        from scripts.run_compact_evidence_canary import query_with_materializer
        self.assertIs(wrapper.materialize_compact, materialize_compact)
        self.assertIs(wrapper.query_with_materializer, query_with_materializer)

    def test_fresh_output_cannot_write_baseline(self):
        from scripts.validate_discovery_scope import ScopeCanary
        from services.canary_contracts import CanaryError
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            runner = object.__new__(ScopeCanary)
            runner.output = Path(folder)
            with self.assertRaises(CanaryError):
                runner.save("../accepted/case", {})


if __name__ == "__main__":
    unittest.main()
