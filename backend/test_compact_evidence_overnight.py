"""Execution policy only: no network, providers, or retrieval changes."""
from contextlib import nullcontext
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from sqlalchemy.exc import DBAPIError
from services.canary_contracts import CanaryError, Lane
from scripts.canary_bounded_output import bounded_json
from scripts.canary_evaluation_resume import atomic_record, read_bounded
from scripts.canary_evaluation_transport import ChannelTransportFailure
from scripts.run_compact_evidence_canary import CompactCanary
from scripts.run_compact_evidence_overnight import (OvernightCanary, execution_only,
    renewal_update, OLD_EXPIRY, NEW_EXPIRY)


class OvernightPolicy(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.r = object.__new__(OvernightCanary)
        self.r.root = Path(tmp.name)
        self.r.output = self.r.root / 'q1'; self.r.output.mkdir()
        self.r.folder = self.r.root / 'p'; self.r.folder.mkdir()
        self.r.session = 'session'; self.r.identity_hash = 'identity'
        self.r.preflight = False; self.r.rows = {}; self.r.deferred = {}
        self.r.manifests = [SimpleNamespace(lane=lane) for lane in Lane]
        self.r.common = [({'id': i}, None) for i in range(1, 91)]

    def test_inherited_lane_is_byte_identical(self):
        self.assertIs(OvernightCanary.evaluate_lane, CompactCanary.evaluate_lane)
        self.assertIs(OvernightCanary.repository, CompactCanary.repository)

    def test_execution_timeouts_and_transport_defer(self):
        for exc in (TimeoutError(), ChannelTransportFailure('DATABASE_TRANSPORT_FAILURE'),
                    CanaryError('READ_RECOVERY_CYCLES_EXHAUSTED')):
            self.assertTrue(execution_only(exc))

    def test_all_integrity_guards_hard_stop(self):
        for guard in ('UPSTREAM_RETRIEVAL_PARITY_FAILURE', 'Q1_UPSTREAM_IDENTITY_CHANGED',
            'Q1_LEGACY_CHANGED', 'RESUME_IDENTITY_MISMATCH', 'FOREIGN_EVALUATION_ROUTE',
            'Q1_REAL_REPLAY_PACK_MISMATCH', 'UNEXPECTED_PROVIDER_ACCESS',
            'SAVED_QUERY_RECEIPT_CORRUPTION', 'PHASE_P_BASELINE_CHANGED'):
            self.assertFalse(execution_only(CanaryError(guard)))

    def test_unclassified_failures_hard_stop(self):
        self.assertFalse(execution_only(ValueError('unknown')))
        self.assertFalse(execution_only(DBAPIError(None, None, Exception())))

    def test_database_permission_integrity_faults_hard_stop(self):
        for code in ('42501', '23505', 'XX001'):
            error = Exception(); error.pgcode = code
            self.assertFalse(execution_only(DBAPIError(None, None, error)))

    def test_database_execution_faults_defer(self):
        for code in ('08006', '57014', '40001', '53300'):
            error = Exception(); error.pgcode = code
            self.assertTrue(execution_only(DBAPIError(None, None, error)))

    def test_success_and_deferred_not_reselected(self):
        for mf in self.r.manifests:
            self.r.rows[1, mf.lane.value] = {}
            self.r.deferred[2, mf.lane.value] = {}
        self.assertEqual(self.r.next_unsaved()['case'], 3)

    def test_all_attempted_returns_none_even_if_deferred(self):
        for snapshot, _ in self.r.common:
            for mf in self.r.manifests:
                self.r.deferred[snapshot['id'], mf.lane.value] = {}
        self.assertIsNone(self.r.next_unsaved())
        self.assertEqual(self.r.completed(), 0)
        bounded_json(self.r.deferred_index())

    def test_attempt_ledgers_are_immutable_and_unique(self):
        self.r.attempt_ordinal = 1
        self.r.save('attempt-01-STRUCTURAL_CANARY', {'case': 1}, immutable=True)
        self.r.attempt_ordinal = 2
        self.r.save('attempt-01-STRUCTURAL_CANARY', {'case': 1}, immutable=True)
        self.assertEqual(len(list(self.r.output.glob('*attempt*'))), 2)
        self.assertEqual(list(self.r.folder.iterdir()), [])

    def test_cannot_escape_existing_family(self):
        with self.assertRaises(CanaryError):
            self.r.save('../p/overwrite', {})

    def test_saved_packing_checksum_detects_mutation(self):
        mf = self.r.manifests[0]
        self.r.save(self.r.case_name(1, mf), {'case': 1}, immutable=True)
        self.r.save(f'packing-01-{mf.lane.value}', {'case': 1}, immutable=True)
        self.r.attest_saved_lane(1, mf)
        self.r.attest_saved_lane(1, mf)
        self.r.save(f'packing-01-{mf.lane.value}', {'case': 2})
        with self.assertRaises(CanaryError): self.r.attest_saved_lane(1, mf)

    def test_incomplete_pair_has_no_success_checksum(self):
        mf = self.r.manifests[0]
        self.r.rows[1, mf.lane.value] = {}
        self.r.pair(1)
        self.assertFalse((self.r.output / 'evaluation-pair-01.json').exists())

    def test_existing_pair_cannot_mask_changed_lane(self):
        for mf in self.r.manifests:
            self.r.rows[1, mf.lane.value] = {}
            self.r.save(self.r.case_name(1, mf), {'case': 1}, immutable=True)
        self.r.pair(1); self.r.pair(1)
        self.r.save(self.r.case_name(1, self.r.manifests[0]), {'case': 2})
        with self.assertRaises(CanaryError): self.r.pair(1)

    def test_only_one_exact_lease_increment(self):
        with self.assertRaises(CanaryError):
            renewal_update(Mock(), None, 'identity', NEW_EXPIRY, NEW_EXPIRY + 86400)

    def test_renewal_updates_only_two_expiry_columns(self):
        from scripts.canary_stage_a import fixture_batch, make_manifest
        from services.canary_representation import source_pin
        mf = make_manifest((source_pin(fixture_batch(), source_id=1),))
        conn = Mock()
        c = Mock(); c.mappings.return_value.one.return_value = dict(
            identity_hash='identity', retained_until=OLD_EXPIRY, condition='COMPLETE')
        r = Mock(); r.mappings.return_value.one.return_value = dict(
            expires_at=OLD_EXPIRY, state='CANARY_READ')
        conn.execute.side_effect = [c, r, SimpleNamespace(rowcount=1), SimpleNamespace(rowcount=1)]
        renewal_update(conn, mf, 'identity', OLD_EXPIRY, NEW_EXPIRY)
        updates = [call.args[0] for call in conn.execute.call_args_list[2:]]
        self.assertEqual([list(stmt.compile().params)[0] for stmt in updates],
                         ['retained_until', 'expires_at'])
        self.assertTrue(all('FOR UPDATE' in str(call.args[0])
                            for call in conn.execute.call_args_list[:2]))

    def test_renewal_concurrent_change_refused(self):
        from scripts.canary_stage_a import fixture_batch, make_manifest
        from services.canary_representation import source_pin
        mf = make_manifest((source_pin(fixture_batch(), source_id=1),))
        conn = Mock()
        a = Mock(); a.mappings.return_value.one.return_value = dict(
            identity_hash='wrong', retained_until=OLD_EXPIRY, condition='COMPLETE')
        b = Mock(); b.mappings.return_value.one.return_value = dict(
            expires_at=OLD_EXPIRY, state='CANARY_READ')
        conn.execute.side_effect = [a, b]
        with self.assertRaises(CanaryError):
            renewal_update(conn, mf, 'identity', OLD_EXPIRY, NEW_EXPIRY)
        self.assertEqual(conn.execute.call_count, 2)

    def run_fixture(self, failure=None):
        from scripts.canary_read_recovery import ReadTelemetry
        r = self.r
        (r.root / 'docs').mkdir()
        r.events = []; r.lock = r.db = None; r.env = {}; r.result = {}
        r.cleanup_errors = []; r.reads = ReadTelemetry(lambda record: None)
        r.wrapper_hash = sha256(Path(__import__('scripts.run_compact_evidence_overnight',
            fromlist=['__file__']).__file__).read_bytes()).hexdigest()
        r.common = [({'id': 1}, SimpleNamespace(identity=lambda: {'org': 1}))]
        r.setup = Mock(); r.verify_phase_p = Mock(); r.load_q1 = Mock()
        r.aggregate = Mock(); r.attest_saved_lane = Mock()
        calls = []
        def evaluate(snapshot, hard, mf):
            calls.append(mf.lane.value)
            if len(calls) == 1 and failure: raise failure
            r.rows[1, mf.lane.value] = {}
        r.evaluate_lane = evaluate
        with patch('scripts.run_compact_evidence_overnight.provider_free', nullcontext), \
             patch('scripts.run_compact_evidence_overnight.bounded_database_io', nullcontext), \
             patch('scripts.run_compact_evidence_overnight.emit'):
            result = r.run()
        return calls, result

    def test_loop_defers_exhaustion_then_attempts_independent_lane(self):
        calls, result = self.run_fixture(CanaryError('READ_RECOVERY_CYCLES_EXHAUSTED'))
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['status'], 'PARTIAL_DEFERRED')
        self.assertEqual(result['successful_lanes'], 1)
        self.assertEqual(result['successful_pairs'], 0)
        events = list(self.r.output.glob('overnight-deferred-01-*.json'))
        self.assertEqual(len(events), 1)
        self.assertIs(read_bounded(events[0])['scored'], False)

    def test_loop_hard_stops_on_parity_without_next_lane(self):
        calls, result = self.run_fixture(CanaryError('Q1_UPSTREAM_IDENTITY_CHANGED'))
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['status'], 'HARD_STOP')
        self.assertEqual(result['deferred_lanes'], 0)

    def test_loop_never_reexecutes_saved_success(self):
        self.r.rows[1, self.r.manifests[0].lane.value] = {}
        calls, _ = self.run_fixture()
        self.assertEqual(calls, [self.r.manifests[1].lane.value])

    def test_loop_never_retries_deferred_tonight(self):
        self.r.deferred[1, self.r.manifests[0].lane.value] = {}
        calls, result = self.run_fixture()
        self.assertEqual(calls, [self.r.manifests[1].lane.value])
        self.assertEqual(result['status'], 'PARTIAL_DEFERRED')


if __name__ == '__main__': unittest.main()
