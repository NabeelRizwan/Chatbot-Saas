"""Phase 3.4 application handoff; synthetic SQL and offline vectors only.

Existing Phase 3.2 48-case actual-retrieval suite remains independently intact.
The new 12+restricted cases use explicitly EMPTY resource search outcomes.
"""
from dataclasses import replace
import unittest

from test_resource_discovery import ResourceFixture, SQLiteTestChannel
import test_resource_probe_handoff as pooled_fixture
from services import rag_service as rag
from services.observability_service import ChatTrace
from test_candidate_free_semantic_gaps import DOMAINS, empty_service
from services.resource_channels import ChannelBatch
from services.resource_discovery import ResourceDiscoveryService
from scripts import phase31_fixture as data, phase33_acceptance as prior


class CandidateFreeHandoffTests(ResourceFixture):
    # Reuse ONLY the existing safe file-backed/pooled setup, not its test method.
    setUp = pooled_fixture.ProbeHandoffTests.setUp

    def test_twelve_candidate_free_actual_retrieval_handoffs(self):
        self.service = empty_service()
        for domain, action, *_ in DOMAINS:
            with self.subTest(domain=domain):
                question = f"Can you {action}?"
                c = self.contract(question)
                self.assertFalse(c.requires_clarification)
                self.assertIsNone(c.permitted_document_ids)
                self.assertFalse(c.execution.scope_decision.exact_narrowing_applied)
                self.assertEqual(c.execution.soft_scope.resolved_document_ids, ())
                self.assertEqual(c.execution.soft_scope.resource_candidates, ())
                rows = c.execution.resource_discovery['resolutions']
                self.assertTrue(any(r['semantic_gap']['basis'] == 'candidate_free_informative' for r in rows))
                self.assertEqual(c.original_query, question)
                result = rag.retrieve_relevant_chunks(self.db, 1, c.retrieval_query, query_contract=c, trace=ChatTrace(1, 'offline'))
                ids = {rag._document_id(r) for r in result}
                self.assertTrue(ids)
                self.assertTrue(ids <= {i*10+o for i in range(1, 13) for o in (0, 1)})
                self.assertNotIn('UNSUPPORTED SUMMARY', str(result))
                self.assertNotIn('UNSUPPORTED SUMMARY', str(rows))

    def test_candidate_free_retrieval_keeps_restricted_documents(self):
        self.service = empty_service()
        c = self.contract('Can you repair gaming laptops?')
        c.execution = replace(c.execution, hard_scope=replace(c.execution.hard_scope, authorized_document_ids=(10, 11)))
        result = rag.retrieve_relevant_chunks(self.db, 1, c.retrieval_query, query_contract=c, trace=ChatTrace(1, 'offline'))
        ids = {rag._document_id(r) for r in result}
        self.assertTrue(ids)
        self.assertTrue(ids <= {10, 11})
        self.assertFalse(c.execution.scope_decision.exact_narrowing_applied)


def recorded_q1(f):
    class RecordedFirstMember:
        def __init__(self, name): self.name = name
        def search(self, db, hard, probe, limit):
            if probe.comparison_member_index == 0:
                return ChannelBatch()  # Actual Phase 3.3 PostgreSQL recorded zero.
            return SQLiteTestChannel(self.name).search(db, hard, probe, limit)
    previous = f.service
    try:
        f.service = ResourceDiscoveryService([RecordedFirstMember(n) for n in ('exact', 'fts', 'trigram', 'metadata')])
        return prior.golden_record(f, 1)
    finally:
        f.service = previous


class RecordedPostgresHistoryTests(ResourceFixture):
    def test_zero_candidate_q1_then_preserved_q2_q3_q10(self):
        for number, name, kind, aliases in data.NATURAL:
            self.add(number, name, kind=kind, aliases=aliases)
        self.project(*[r[0] for r in data.NATURAL])
        row = recorded_q1(self)
        first, second = row['trace']['resolutions']
        self.assertEqual(first['candidate_count'], 0)
        self.assertEqual(first['state'], 'unresolved')
        self.assertEqual(first['semantic_gap']['basis'], 'candidate_free_informative')
        self.assertTrue(first['semantic_gap']['eligible_for_optimizer'])
        self.assertIsNone(first['selected_resource_id'])
        self.assertEqual(second['state'], 'resolved')
        self.assertEqual(row['selected'], [3002])
        self.assertEqual(row['state'], 'incomplete_comparison')
        self.assertEqual(row['scope'], 'discovery_required')
        self.assertTrue(row['reviewed_ok'])
        self.assertFalse(row['original_ok'])
        for number in (2, 3, 10):
            other = prior.golden_record(self, number)
            self.assertTrue(other['reviewed_ok'])
            self.assertTrue(other['frozen_match'])
            self.assertEqual(other['leaks'], 0)
            if number == 2:
                self.assertEqual(other['trace']['resolutions'][0]['semantic_gap']['basis'], 'candidate_backed_insufficient')
            if number == 10:
                self.assertEqual(other['trace']['resolutions'][0]['semantic_gap']['basis'], 'structured_relation_required')


if __name__ == '__main__':
    unittest.main()
