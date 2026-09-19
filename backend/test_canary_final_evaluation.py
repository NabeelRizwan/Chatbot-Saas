"""Offline actual retrieval/event boundary tests for the final continuation."""
from contextlib import redirect_stdout, nullcontext
from hashlib import sha256
from io import StringIO
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import event, update
from database import canary_schema as s
from services.canary_contracts import CanaryError, Lane, State
from services.canary_repository import CanaryRepository
from services.canary_retrieval import run_query, LexicalResult
from services.canary_representation import exact_input_hash
from scripts.canary_stage_a import NOW, hard_scope
from scripts.canary_evaluation_resume import EvaluationRepository, EvaluationRunner, atomic_record, read_bounded
from scripts.canary_evaluation_transport import (DatabaseTransportTimeout, ChannelTransportFailure,
    CleanupOnlyFailure, transient_transport)
from scripts.canary_final_evaluation import FinalEvaluation, AUTHORIZATION
from scripts.canary_measured_telemetry import MeasuredEvidenceTelemetry
from scripts.canary_session_diagnostics import evidence_scope
import test_canary_real_handoff as fixtures


class ActualMeasuredRetrieval(unittest.TestCase):
    def setUp(self):
        b = self.base = fixtures.Handoff('test_real_roundtrip_seal_and_query')
        b.setUp(); self.addCleanup(b.doCleanups)
        self.vector = b.persist()[0].vector
        b.repo.seal_generation(b.manifest, expected_build_identity=b.repo.build_identity(b.manifest), now=NOW)
        b.repo.transition(b.manifest, State.CANARY_READ, now=NOW)
        self.mf, self.hard = b.manifest, hard_scope(b.manifest)
        self.repo = EvaluationRepository(b.repo.conn, b.approval, authorization=b.auth,
            lease_until=b.approval.expires_at, identities=[self.mf.canonical_hash()], clock=lambda: NOW)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.records = []
        def writer(record):
            atomic_record(self.folder/f"{record['operation_ordinal']}-{record['phase']}.json", record, immutable=True)
            self.records.append(copy.deepcopy(record))
        self.telemetry = MeasuredEvidenceTelemetry(b.repo.conn.engine, writer, session='offline')
        self.addCleanup(self.telemetry.close)
        self.telemetry.set_context(72, self.mf.lane.value, self.mf.canonical_hash(), self.mf.generation)

    def query(self, **kwargs):
        kwargs.setdefault('fts_call', lambda: LexicalResult((), 'offline-empty'))
        return run_query(self.repo, self.mf, self.hard, query='ordinary statement',
                         query_vector=self.vector, now=NOW, **kwargs)

    @staticmethod
    def logical(trace):
        trace = copy.deepcopy(trace)
        for channel in trace['channels'].values(): channel.pop('ms')
        for name in ('rrf_ms', 'materialization_ms', 'total_ms'): trace.pop(name)
        return trace

    def test_actual_materialization_on_off_identical_sql_parameters_order_budgets_rankings(self):
        statements = []
        def record(conn, cursor, sql, params, *unused): statements.append((sql, copy.deepcopy(params)))
        event.listen(self.base.repo.conn.engine, 'before_cursor_execute', record)
        self.addCleanup(event.remove, self.base.repo.conn.engine, 'before_cursor_execute', record)
        off = self.query(); off_sql = statements[:]; statements.clear()
        self.repo.observer = self.telemetry
        on = self.query()
        self.assertEqual(off_sql, statements)
        self.assertEqual(self.logical(off), self.logical(on))
        self.assertTrue(on['materialized']['units'])
        self.assertTrue(self.records)
        self.assertTrue(all(r['payload_hash_validation'] == 'PASS' for r in self.records if r['phase'] == 'AFTER_CALL'))

    def test_durable_exact_before_record_exists_at_actual_sql_boundary(self):
        self.repo.observer = self.telemetry
        checks = []
        def check(conn, cursor, sql, params, context, *unused):
            scope = evidence_scope(context)
            if scope is not None:
                records = [read_bounded(p) for p in self.folder.glob('*-BEFORE_SQL.json')]
                self.assertEqual(records[-1]['source_scope'], scope)
                self.assertTrue(records[-1]['statement_started'])
                checks.append(scope)
        event.listen(self.base.repo.conn.engine, 'before_cursor_execute', check)
        self.addCleanup(event.remove, self.base.repo.conn.engine, 'before_cursor_execute', check)
        self.query(); self.assertTrue(checks)

    def fail_atom(self):
        def fail(conn, cursor, sql, params, context, *unused):
            if evidence_scope(context) is not None: raise DatabaseTransportTimeout()
        event.listen(self.base.repo.conn.engine, 'before_cursor_execute', fail)
        self.addCleanup(event.remove, self.base.repo.conn.engine, 'before_cursor_execute', fail)

    def test_materialization_watchdog_keeps_exact_identity_and_transport_category(self):
        self.repo.observer = self.telemetry; self.fail_atom()
        with self.assertRaises(DatabaseTransportTimeout) as raised: self.query()
        self.assertTrue(transient_transport(raised.exception))
        failed = self.telemetry.failed['record']
        self.assertEqual(failed['source_scope']['atom_id'], self.telemetry.failed['key'])
        self.assertTrue(failed['statement_started'])
        self.assertEqual(failed['result_category'], 'DATABASE_TIMEOUT')
        self.assertEqual(failed['payload_hash_validation'], 'NOT_COMPLETED')
        self.assertEqual(failed['attempt_ordinal'], 1)
        self.assertEqual(len(failed['scope_digest']), 64)

    def test_dense_transport_survives_actual_run_query_channel_catch(self):
        with patch.object(CanaryRepository, 'dense', side_effect=DatabaseTransportTimeout()):
            with self.assertRaises(ChannelTransportFailure) as raised: self.query()
        self.assertTrue(transient_transport(raised.exception))

    def test_fts_transport_survives_actual_run_query_channel_catch(self):
        with patch.object(CanaryRepository, 'fts', side_effect=DatabaseTransportTimeout()):
            with self.assertRaises(ChannelTransportFailure) as raised: self.query(fts_call=None)
        self.assertTrue(transient_transport(raised.exception))

    def test_nontransport_channel_behavior_stays_frozen(self):
        with patch.object(CanaryRepository, 'fts', side_effect=RuntimeError('offline')):
            self.assertEqual(self.query(fts_call=None)['mode'], 'dense_only')

    def test_payload_corruption_records_validation_failure_not_success(self):
        self.repo.observer = self.telemetry
        self.repo.conn.execute(update(s.atoms).values(payload_hash='f'*64))
        with self.assertRaisesRegex(CanaryError, 'EVIDENCE_PAYLOAD_CORRUPTION'): self.query()
        self.assertEqual(self.telemetry.failed['record']['result_category'], 'VALIDATION_FAILURE')

    def test_telemetry_never_serializes_text_vectors_or_sql(self):
        self.repo.observer = self.telemetry; self.query()
        serialized = json.dumps(self.records)
        for forbidden in ('ordinary source-backed', 'SELECT ', '0.123456', 'query_vector', 'password'):
            self.assertNotIn(forbidden, serialized)

    def test_before_write_failure_prevents_evidence_sql(self):
        self.repo.observer = self.telemetry
        self.telemetry.writer = Mock(side_effect=OSError('offline'))
        with patch.object(CanaryRepository, 'evidence') as evidence:
            with self.assertRaises(OSError): self.query()
        evidence.assert_not_called()

    def test_secondary_telemetry_failure_does_not_mask_primary(self):
        self.repo.observer = self.telemetry; self.fail_atom()
        original = self.telemetry.writer
        def writer(record):
            if record['phase'] == 'AFTER_CALL': raise OSError('secondary')
            original(record)
        self.telemetry.writer = writer
        with self.assertRaises(DatabaseTransportTimeout): self.query()
        self.assertEqual(self.telemetry.persistence_errors, ['ERROR_TELEMETRY_WRITE_FAILED'])


class FinalAuthorizationAndCleanup(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.namespace = 'canary_stagep_'+'d'*32
        (self.root/'.codex_phase4p'/self.namespace).mkdir(parents=True)
        self.r = self.runner()

    def runner(self, auth=AUTHORIZATION):
        return FinalEvaluation(self.root, {'CANARY_EVALUATION_ONLY_AUTHORIZED': 'true'},
            namespace=self.namespace, run_id='paired-real', identity_hash='a'*64,
            final_authorization=auth, diagnostic_checkpoint='b'*40)

    def test_explicit_authorization_required(self):
        with self.assertRaisesRegex(CanaryError, 'FINAL_MEASURED_AUTHORIZATION_REQUIRED'): self.runner('old')

    def test_actual_exclusive_cleanup_only_has_no_primary_error_in_terminal(self):
        r = self.r; r.setup = Mock(); r.saved_progress = lambda: {}
        lock = NS(acquire=Mock(), close=Mock(return_value=[dict(category='UNLOCK_FAILED')]), connection_state='UNLOCK_FAILED')
        def evaluate():
            with r.exclusive(): pass
        r.evaluate = evaluate
        with patch('scripts.canary_evaluation_resume.ExclusiveRun', return_value=lock), redirect_stdout(StringIO()):
            self.assertEqual(r.run(), 1)
        self.assertIsNone(r.result['primary_error'])
        self.assertTrue(r.result['cleanup_errors'])
        self.assertEqual(read_bounded(r.folder/('evaluation-session-'+r.session+'.json'))['status'], 'SAFE_STOP')

    def test_actual_exclusive_primary_and_cleanup_keep_primary(self):
        r = self.r; r.setup = Mock(); r.saved_progress = lambda: {}
        lock = NS(acquire=Mock(), close=Mock(return_value=[dict(category='UNLOCK_FAILED')]), connection_state='UNLOCK_FAILED')
        def evaluate():
            with r.exclusive(): raise CanaryError('PRIMARY_FAILURE')
        r.evaluate = evaluate
        with patch('scripts.canary_evaluation_resume.ExclusiveRun', return_value=lock), redirect_stdout(StringIO()): r.run()
        self.assertEqual(r.result['primary_error']['guard'], 'PRIMARY_FAILURE')
        self.assertTrue(r.result['cleanup_errors'])

    def attempt_fixture(self):
        r = self.r; r.wrapper_code = {}; r.validate = Mock()
        mf = NS(lane=Lane.STRUCTURAL_CANARY, canonical_hash=lambda:'c'*64, generation='sealed')
        legacy = NS(lane=Lane.LEGACY_CONTROL)
        r.manifests = (mf, legacy)
        snapshot = dict(id=72, query='frozen', snapshot_hash='d'*64)
        r.queries = {exact_input_hash('frozen'): NS(vector_hash='e'*64)}
        atomic_record(r.folder/'case-72-LEGACY_CONTROL.json', {'immutable':True})
        r.telemetry = Mock()
        return r, snapshot, NS(identity=lambda:'hard'), mf

    def test_case72_attempt_cannot_reset_historical_or_new_ledger(self):
        r, snapshot, hard, mf = self.attempt_fixture()
        old = r.folder/'evaluation-retry-72-STRUCTURAL_CANARY.json'
        atomic_record(old, {'old':'exhausted'}); original = old.read_bytes()
        with patch('scripts.canary_final_evaluation.wrapper_hashes', return_value={}):
            r.before_lane_attempt(snapshot, hard, mf, 0)
            with self.assertRaisesRegex(CanaryError, 'ALREADY_CONSUMED'): r.before_lane_attempt(snapshot, hard, mf, 0)
        self.assertEqual(original, old.read_bytes())
        r.validate.assert_called()

    def test_case72_second_attempt_requires_exact_probe_proof(self):
        r, snapshot, hard, mf = self.attempt_fixture()
        with patch('scripts.canary_final_evaluation.wrapper_hashes', return_value={}):
            with self.assertRaises(FileNotFoundError): r.before_lane_attempt(snapshot, hard, mf, 1)

    def test_no_third_attempt(self):
        r, snapshot, hard, mf = self.attempt_fixture()
        with self.assertRaisesRegex(CanaryError, 'MEASURED_ATTEMPT_BOUND'):
            r.before_lane_attempt(snapshot, hard, mf, 2)

    def probe_fixture(self, error=None):
        r, snapshot, hard, mf = self.attempt_fixture()
        record = dict(statement_started=True, result_category='DATABASE_TIMEOUT', source_scope={'atom_id':'f'*64})
        r.telemetry = NS(summary=lambda:{}, context={}, failed=dict(record=record, route=object(), key='f'*64),
                         latest=dict(payload_hash_validation='PASS', source_scope=record['source_scope']))
        r.exclusive = lambda:nullcontext(); r.identity_gate = Mock()
        repo = NS(evidence=Mock(side_effect=error))
        r.repository = lambda:nullcontext(repo)
        return r, snapshot, hard, mf, repo

    def test_exact_fresh_probe_success_records_separate_retry_permission(self):
        r, snapshot, hard, mf, repo = self.probe_fixture()
        with redirect_stdout(StringIO()):
            self.assertTrue(r.authorize_lane_retry(snapshot, hard, mf, DatabaseTransportTimeout(), None))
        repo.evidence.assert_called_once()
        proof = read_bounded(r.folder/(AUTHORIZATION+'-fresh-atom-proof.json'))
        self.assertEqual(proof['payload_hash_validation'], 'PASS')
        self.assertEqual(r.transport_retries, 1)

    def test_exact_fresh_probe_failure_stops_without_whole_lane_retry(self):
        r, snapshot, hard, mf, repo = self.probe_fixture(DatabaseTransportTimeout())
        with self.assertRaisesRegex(CanaryError, 'EXACT_ATOM_READ_REPRODUCIBLE_FAILURE'):
            r.authorize_lane_retry(snapshot, hard, mf, DatabaseTransportTimeout(), None)
        self.assertEqual(r.transport_retries, 0); repo.evidence.assert_called_once()

    def test_probe_ownership_failure_not_claimed_as_atom_reproduction(self):
        r, snapshot, hard, mf, repo = self.probe_fixture()
        r.identity_gate.side_effect = CanaryError('OWNERSHIP_REFUSED')
        with self.assertRaisesRegex(CanaryError, 'EXACT_ATOM_PROBE_PREFLIGHT_FAILURE'):
            r.authorize_lane_retry(snapshot, hard, mf, DatabaseTransportTimeout(), None)
        repo.evidence.assert_not_called()

    def test_one_lease_interval_only(self):
        r = self.r; r.retained_until = 0
        atomic_record(r.folder/'evaluation-final-lease-0.json', {'authorized':True})
        with self.assertRaisesRegex(CanaryError, 'FINAL_AUTHORIZED_LEASE_ALREADY_CONSUMED'):
            r.ensure_lease()

    def test_case72_transport_without_exact_atom_never_probes_or_retries(self):
        r, snapshot, hard, mf = self.attempt_fixture()
        r.telemetry.summary.return_value = {}; r.telemetry.failed = None
        r.exclusive = Mock(side_effect=AssertionError('must not open'))
        with self.assertRaisesRegex(CanaryError, 'EXACT_FAILED_ATOM_TELEMETRY_REQUIRED'):
            r.authorize_lane_retry(snapshot, hard, mf, DatabaseTransportTimeout(), None)
        r.exclusive.assert_not_called()

    def test_saved_case72_is_reused_without_consuming_authorization(self):
        r, snapshot, hard, mf = self.attempt_fixture()
        atomic_record(r.folder/'case-72-STRUCTURAL_CANARY.json', {'immutable':True})
        r.exclusive = lambda: nullcontext(); r.identity_gate = Mock(); r.pair = Mock()
        r.before_lane_attempt = Mock(side_effect=AssertionError('must not consume'))
        r.evaluate_lane(snapshot, hard, mf)
        r.before_lane_attempt.assert_not_called()

    def paused_fixture(self):
        r, snapshot, hard, mf = self.attempt_fixture()
        snapshot['id'] = 73
        r.resume_paused_session = 'f'*32
        lane = dict(case=73, lane=mf.lane.value)
        pause = dict(status='PAUSED_BY_USER', pause_reason='USER_REQUESTED_PC_RESTART',
            process_stopped=True, primary_error=None, session=r.resume_paused_session,
            identity_hash=r.identity_hash, current_lane=lane, next_resumable_lane=lane, provider_calls=0)
        atomic_record(r.folder/f'evaluation-session-{r.resume_paused_session}.json', pause)
        old = dict(session=r.resume_paused_session, attempt_ordinal=1, identity_hash=r.identity_hash,
            case=73, lane=mf.lane.value, manifest=mf.canonical_hash(), generation=mf.generation,
            snapshot_hash=snapshot['snapshot_hash'], hard_scope=hard.identity(), query_vector_hash='e'*64)
        path = r.folder/(r.attempt_name(73, mf.lane.value, 0)+'.json')
        atomic_record(path, old)
        return r, snapshot, hard, mf, path

    def test_user_paused_attempt_resumes_once_without_changing_original(self):
        r, snapshot, hard, mf, path = self.paused_fixture(); before = path.read_bytes()
        with patch('scripts.canary_final_evaluation.wrapper_hashes', return_value={}):
            r.before_lane_attempt(snapshot, hard, mf, 0)
            with self.assertRaisesRegex(CanaryError, 'ALREADY_CONSUMED'):
                r.before_lane_attempt(snapshot, hard, mf, 0)
        self.assertEqual(path.read_bytes(), before)

    def test_user_pause_cannot_reset_transport_retry(self):
        r, snapshot, hard, mf, _ = self.paused_fixture()
        atomic_record(r.folder/'evaluation-retry-73-STRUCTURAL_CANARY.json', {'exhausted':True})
        with patch('scripts.canary_final_evaluation.wrapper_hashes', return_value={}):
            with self.assertRaisesRegex(CanaryError, 'TRANSPORT_RETRY_CANNOT_RESET'):
                r.before_lane_attempt(snapshot, hard, mf, 0)

    def test_user_pause_cannot_authorize_changed_query(self):
        r, snapshot, hard, mf, _ = self.paused_fixture(); snapshot['snapshot_hash'] = '0'*64
        with patch('scripts.canary_final_evaluation.wrapper_hashes', return_value={}):
            with self.assertRaisesRegex(CanaryError, 'IDENTITY_MISMATCH'):
                r.before_lane_attempt(snapshot, hard, mf, 0)

    def test_failure_session_not_user_pause(self):
        r, snapshot, hard, mf, _ = self.paused_fixture()
        path = r.folder/f'evaluation-session-{r.resume_paused_session}.json'
        pause = read_bounded(path); pause['status'] = 'SAFE_STOP'; atomic_record(path, pause)
        with patch('scripts.canary_final_evaluation.wrapper_hashes', return_value={}):
            with self.assertRaisesRegex(CanaryError, 'USER_PAUSED_RESUME_REFUSED'):
                r.before_lane_attempt(snapshot, hard, mf, 0)


if __name__ == '__main__': unittest.main()
