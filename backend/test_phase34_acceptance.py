"""Offline guards for Phase 3.4 orchestration; no network/provider calls."""
from collections import Counter
from contextlib import ExitStack, contextmanager, nullcontext
from dataclasses import replace
import os
from unittest.mock import patch
import unittest

from scripts import phase34_acceptance as run, phase31_remote
from test_resource_discovery import ResourceFixture
from test_candidate_free_semantic_gaps import empty_service
from test_resource_semantic_gaps import populate


class HarnessTests(unittest.TestCase):
    def test_frozen_dimensions_and_old_dataset_preserved(self):
        cases = run.natural_cases()
        self.assertEqual(len(cases), 49)
        self.assertEqual(len({(c.question, c.bot) for c in cases}), 49)
        self.assertEqual(Counter(c.family for c in cases),
                         dict(candidate_free=12, fuzzy=12, short=10, category=5, relation=5, ambiguous=5))
        self.assertEqual(len(run.fuzzy_probes()), 60)
        self.assertEqual(len(run.previous.augmented_documents()), 6000)
        self.assertIs(run.core.disposable_database, phase31_remote.disposable_database)
        old = {r['id']: r for r in run.previous.augmented_documents()}
        new = run.system_documents()
        self.assertEqual(len(new), 6000)
        self.assertEqual(sum(r['bot_id'] == run.ZERO_BOT for r in new), 2)
        for row in new:
            if old[row['id']]['organization_id'] != run.ZERO_ORG:
                self.assertEqual(row, old[row['id']])

    def test_failure_prevents_benchmark(self):
        result = {}
        def setup(*_): result['fixture'] = dict(documents=6000, isolated_bot_resources=2)
        with patch.object(run, 'setup_system_fixture', side_effect=setup), \
             patch.object(run, 'natural_gates', side_effect=run.GateFailure('unrelated_semantic_gap')), \
             patch.object(run.core, 'benchmarks') as benchmark, patch.object(run.previous, 'handoffs') as handoffs:
            with self.assertRaises(run.GateFailure): run.run(None, None, result)
            benchmark.assert_not_called(); handoffs.assert_not_called()

    def test_fixture_gate_requires_controlled_tiny_bot(self):
        result = {}
        def setup(*_): result['fixture'] = dict(documents=6000, isolated_bot_resources=218)
        with patch.object(run, 'setup_system_fixture', side_effect=setup), \
             patch.object(run, 'natural_gates') as natural:
            with self.assertRaises(run.GateFailure): run.run(None, None, result)
            natural.assert_not_called()

    def test_complete_order_preserves_system_gates_without_repeated_infrastructure(self):
        result = {}; order = []
        def setup(*_): order.append('seed'); result['fixture'] = dict(documents=6000, isolated_bot_resources=2)
        def benchmark(*_): order.append('612'); result['benchmark'] = {s: {'gates': {'all': True}} for s in ('development', 'heldout')}
        def historical(*_): order.append('historical'); result['historical'] = {'pass': True}
        with ExitStack() as stack:
            stack.enter_context(patch.object(run, 'setup_system_fixture', side_effect=setup))
            for name in ('sql_and_security', 'cycle', 'concurrency_and_plans', 'setup'):
                stack.enter_context(patch.object(run.core, name, side_effect=AssertionError('Repeated infrastructure forbidden')))
            stack.enter_context(patch.object(run, 'performance', side_effect=AssertionError('Plans forbidden')))
            for name, callback in (('benchmarks', benchmark), ('historical', historical)):
                stack.enter_context(patch.object(run.core, name, side_effect=callback))
            for name in ('natural_gates', 'candidate_free_handoffs', 'non_exact_handoffs', 'surrogate_audit', 'light_concurrency'):
                stack.enter_context(patch.object(run, name, side_effect=lambda *_, n=name: order.append(n)))
            stack.enter_context(patch.object(run.previous, 'handoffs', side_effect=lambda *_: order.append('48')))
            stack.enter_context(patch.object(run.core, 'emit'))
            run.run(None, None, result)
        self.assertEqual(order, ['seed', 'natural_gates', '48', 'candidate_free_handoffs', 'non_exact_handoffs',
                                 '612', 'surrogate_audit', 'light_concurrency', 'historical'])

    def test_main_redacts_errors_cleans_environment_and_requires_cleanup(self):
        @contextmanager
        def disposable():
            yield None, None, {'cleanup': {'schema_absent': True}}  # incomplete cleanup proof must fail
        captured = []
        with patch.object(run.core, 'isolated_application_imports', return_value=nullcontext()), \
             patch.object(run.core, 'disposable_database', disposable), patch.object(run, 'run'), \
             patch.object(run.core, 'emit', side_effect=lambda stage, data: captured.append(data)), \
             patch.dict(os.environ, {'PHASE3_TEST_DATABASE_URL': 'synthetic-test-value', 'PHASE3_ALLOW_REMOTE_DISPOSABLE': '1'}):
            self.assertEqual(run.main(), 1)
            self.assertNotIn('PHASE3_TEST_DATABASE_URL', os.environ)
            self.assertNotIn('PHASE3_ALLOW_REMOTE_DISPOSABLE', os.environ)
        self.assertNotIn('synthetic-test-value', str(captured))
        self.assertEqual(captured[-1]['failure']['gate'], 'cleanup')


class NaturalGateTests(ResourceFixture):
    def test_controlled_zero_catalog_runs_actual_offline_discovery_not_injected_zeros(self):
        self.add(1, 'ZXQJ 78124', kind='custom'); self.add(2, 'VKMZ 95367', kind='custom'); self.project(1, 2)
        for case in run.natural_cases():
            if case.family == 'candidate_free':
                local = replace(case, organization=1, bot=1)
                row = run.natural_record(local, self.contract(case.question))
                self.assertTrue(row['passed'], row)
                self.assertTrue(row['safe_members'])
                self.assertEqual(row['candidate_count'], 0)

    def test_real_fuzzy_outcome_must_not_be_forced_to_zero(self):
        # Recorded shape, not a PostgreSQL surrogate: actual runtime policy,
        # hydration, assessment and scope adapter still execute below.
        from services.resource_channels import ChannelBatch, CandidateSignal
        from services.resource_discovery import ResourceDiscoveryService
        from test_candidate_free_semantic_gaps import EmptyChannel
        from database.resource_models import KnowledgeResource
        self.add(1, 'Reference Code 713'); self.project(1)
        rid = self.db.query(KnowledgeResource.id).scalar()
        class Fuzzy:
            name = 'trigram'
            def search(self, *args):
                return ChannelBatch((CandidateSignal(rid, 'trigram', 1, .34, 1,
                    'alias', 'reference code 713', 'document_metadata'),), overflow=True)
        self.service = ResourceDiscoveryService([EmptyChannel('exact'), Fuzzy()])
        case = run.NaturalCase('recorded', 'reserve conference rooms', 'fuzzy', 1, 1)
        contract = self.contract(case.question)
        self.assertEqual(contract.execution.soft_scope.state.value, 'ambiguous')
        self.assertTrue(run.natural_record(case, contract)['passed'])

    def test_all_oracles_offline_without_claiming_pg_candidate_presence(self):
        populate(self)
        original = self.service
        for case in run.natural_cases():
            local = replace(case, organization=1, bot=1)
            # Only candidate-free/short oracle testing uses injected zeros;
            # phase34_acceptance.natural_gates always uses real SQL channels.
            self.service = empty_service() if case.family in ('candidate_free', 'short') else original
            row = run.natural_record(local, self.contract(case.question))
            self.assertTrue(row['passed'], row)
            self.assertTrue(row['safe_members'], row)

    def test_twelve_fuzzy_natural_queries_against_normal_catalog_surrogate(self):
        for n, name, kind, aliases in run.data.NATURAL:
            self.add(n, name, kind=kind, aliases=aliases)
        self.project(*[r[0] for r in run.data.NATURAL])
        for case in run.natural_cases():
            if case.family == 'fuzzy':
                row = run.natural_record(replace(case, organization=1, bot=1), self.contract(case.question))
                self.assertTrue(row['passed'] and row['safe_members'], row)

    def test_fuzzy_candidates_not_candidate_free_and_no_arbitrary_winner(self):
        self.add(1, 'Amber devices Choice Extended'); self.add(2, 'Amber devices Choice Compact'); self.project(1, 2)
        case = run.NaturalCase('weak', 'Show me Amber devices Choice.', 'fuzzy', 1, 1)
        c = self.contract(case.question)
        row = run.natural_record(case, c)
        self.assertTrue(row['passed'], row)
        self.assertGreater(row['candidate_count'], 0)
        self.assertFalse(row['selected'])
        self.assertNotEqual(row['trace']['resolutions'][0]['semantic_gap']['basis'], 'candidate_free_informative')

    def test_shared_exact_identity_remains_ambiguous(self):
        self.add(1, 'Silver Cedar Extended', aliases=['Silver Cedar']); self.add(2, 'Silver Cedar Compact', aliases=['Silver Cedar'])
        self.project(1, 2)
        row = run.natural_record(run.NaturalCase('shared', 'Silver Cedar', 'fuzzy', 1, 1), self.contract('Silver Cedar'))
        self.assertTrue(row['passed'], row)
        self.assertEqual(row['state'], 'ambiguous')

    def test_strong_identity_can_resolve_and_forged_proof_cannot(self):
        from copy import deepcopy
        self.add(1, 'Cedar Tax Advisory'); self.project(1)
        case = run.NaturalCase('strong', 'Cedar Tax Advisory', 'fuzzy', 1, 1)
        row = run.natural_record(case, self.contract(case.question))
        self.assertTrue(row['passed'], row)
        self.assertEqual(row['selected'], [1])
        forged = deepcopy(row['trace']['resolutions'][0])
        forged['candidates'][0]['channels'] = ['trigram']
        self.assertFalse(run.member_safe(forged))
        forged = deepcopy(row['trace']['resolutions'][0])
        forged['selected_resource_id'] = 'made-up-identity'
        self.assertFalse(run.member_safe(forged))

    def test_candidate_count_cannot_be_relabelled_candidate_free(self):
        from copy import deepcopy
        self.add(1, 'Cedar Tax Advisory'); self.project(1)
        member = deepcopy(self.contract('Cedar Tax Advisory').execution.resource_discovery['resolutions'][0])
        member['semantic_gap']['basis'] = 'candidate_free_informative'
        self.assertFalse(run.member_safe(member))

    def test_empty_hard_scope_never_runs_channels_or_creates_access(self):
        from services.resource_channels import ResourceProbe
        with patch.object(self.service, '_discover', side_effect=AssertionError('No search allowed')):
            answer = self.service.discover(self.db, replace(self.hard, authorized_document_ids=()),
                                           [ResourceProbe('reserve conference rooms')])
        member = answer.trace()['resolutions'][0]
        self.assertTrue(run.member_safe(member))
        self.assertEqual(member['semantic_gap']['basis'], 'empty_hard_scope')
        self.assertFalse(answer.candidates)

    def test_technical_failure_never_becomes_a_successful_zero_search(self):
        self.add(1, 'Unrelated Catalog'); self.project(1)
        self.service = empty_service(failure=True)
        case = run.NaturalCase('technical', 'reserve conference rooms', 'fuzzy', 1, 1)
        row = run.natural_record(case, self.contract(case.question))
        self.assertFalse(row['passed'])
        member = row['trace']['resolutions'][0]
        self.assertEqual(member['semantic_gap']['basis'], 'technical_failure')
        self.assertTrue(run.member_safe(member))

    def test_positive_candidate_is_not_accepted_as_zero_candidate(self):
        self.add(1, 'Cedar Tax Advisory'); self.project(1)
        case = run.NaturalCase('guard', 'Cedar Tax Advisory', 'candidate_free', 1, 1)
        self.assertFalse(run.natural_record(case, self.contract(case.question))['passed'])


if __name__ == '__main__': unittest.main()
