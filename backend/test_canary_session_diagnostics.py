"""Offline session-window and actual SQLAlchemy event-boundary checks."""
import copy
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
from time import monotonic
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine, event, or_, select, text

from database import canary_schema as s
from scripts.canary_session_diagnostics import EvidenceTelemetry, SessionWindow, SessionWindowEnded


class SessionDiagnostics(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.window = SessionWindow(100.0, clock=lambda: self.now)
        self.engine = create_engine('sqlite://')
        self.addCleanup(self.engine.dispose)
        self.records = []
        self.telemetry = EvidenceTelemetry(self.engine, lambda row: self.records.append(copy.deepcopy(row)),
                                            window=self.window, clock=lambda: self.now)
        self.addCleanup(self.telemetry.close)
        self.values = {key: 1 if key in s.INTS else 'fixture' for key in s.DOC}
        for key in ('source_hash', 'manifest_hash', 'profile_hash', 'policy_hash'):
            self.values[key] = 'a' * 64
        self.values.update(lane='STRUCTURAL_CANARY', generation='real-baseline-v1', atom_id='b' * 64)
        self.telemetry.set_context(72, 'STRUCTURAL_CANARY', 'a' * 64, 'real-baseline-v1')

    def query(self):
        return select(s.atoms).where(*(s.atoms.c[key] == value for key, value in self.values.items()))

    def test_boundaries_do_not_extend_operation_watchdog(self):
        self.now = 100 + 22 * 60
        self.assertFalse(self.window.may_start_case())
        self.assertTrue(self.window.may_start_case(20))
        self.now = 100 + 23 * 60
        self.assertTrue(self.window.shutdown_ready)
        self.assertFalse(self.window.may_start_case(1))
        self.window.require_database()
        self.now = 100 + 24 * 60
        with self.assertRaises(SessionWindowEnded): self.window.require_database()

    def test_error_has_durable_started_scope_before_actual_cursor_failure(self):
        with self.engine.connect() as conn:
            with self.assertRaises(Exception): conn.execute(self.query()).all()
        self.assertEqual([r['result_category'] for r in self.records], ['STARTED', 'DATABASE_ERROR'])
        self.assertEqual(self.records[0]['source_scope'], self.values)
        self.assertEqual(self.records[0]['case_id'], 72)
        self.assertEqual(len(self.records[0]['query_shape_sha256']), 64)
        self.assertNotIn('SELECT', json.dumps(self.records))

    def test_non_evidence_sql_is_not_recorded_or_modified(self):
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text('SELECT :payload'), {'payload':'secret://opaque'}).scalar_one(), 'secret://opaque')
        self.assertEqual(self.records, [])

    def test_disjunction_and_limited_shapes_are_not_mistaken_for_exact_evidence(self):
        for query in (select(s.atoms).where(or_(*(s.atoms.c[key] == value for key, value in self.values.items()))),
                      self.query().limit(1)):
            with self.engine.connect() as conn:
                with self.assertRaises(Exception): conn.execute(query).all()
        self.assertEqual(self.records, [])

    def test_payload_and_injection_shaped_identity_never_written(self):
        self.values['revision'] = 'secret://password@host'
        with self.engine.connect() as conn:
            with self.assertRaises(Exception): conn.execute(self.query()).all()
        self.assertEqual(self.records, [])

    def test_context_mismatch_fails_before_cursor(self):
        self.telemetry.set_context(72, 'STRUCTURAL_CANARY', 'c' * 64, 'real-baseline-v1')
        with self.engine.connect() as conn:
            with self.assertRaisesRegex(ValueError, 'DIAGNOSTIC_SCOPE_CONTEXT_MISMATCH'):
                conn.execute(self.query())
        self.assertEqual(self.records, [])

    def test_database_boundary_blocks_new_cursor_work(self):
        with self.engine.connect() as conn:
            self.now = 100 + 24 * 60
            with self.assertRaises(SessionWindowEnded): conn.execute(text('SELECT 1'))

    def test_start_record_survives_non_dbapi_watchdog_error(self):
        def fail(*args): raise TimeoutError('must-not-store-this-secret')
        event.listen(self.engine, 'before_cursor_execute', fail)
        with self.engine.connect() as conn:
            with self.assertRaises(TimeoutError): conn.execute(self.query())
        self.assertEqual(self.records[0]['result_category'], 'STARTED')
        self.assertEqual(self.records[0]['source_scope']['atom_id'], 'b' * 64)
        self.assertNotIn('must-not-store', json.dumps(self.records))

    def test_telemetry_context_invalid_fields_rejected(self):
        with self.assertRaises(ValueError): self.telemetry.set_context(72, 'secret', 'a'*64, 'safe')
        with self.assertRaises(ValueError): self.telemetry.set_context(72, 'STRUCTURAL_CANARY', 'a'*64, 'secret://key')
        with self.assertRaises(ValueError): self.telemetry.set_context(91, 'STRUCTURAL_CANARY', 'a'*64, 'safe')

    def test_success_reads_full_row_unchanged_and_records_no_payload(self):
        s.atoms.create(self.engine)
        values = dict(self.values, bundle_id='d'*64, kind='paragraph', canonical_text='private evidence',
                      payload={'secret':'never emit'}, payload_hash='e'*64, route_kind='ATOM_ONLY', route_entry=None)
        with self.engine.begin() as conn:
            conn.execute(s.atoms.insert().values(**values))
            self.now += 3
            row = conn.execute(self.query()).mappings().one()
            self.assertEqual(dict(row), values)
        self.assertEqual([r['result_category'] for r in self.records], ['STARTED', 'EXECUTED'])
        self.assertEqual(self.records[0]['connection_age_ms'], 3000)
        serialized = json.dumps(self.records)
        self.assertNotIn('private evidence', serialized)
        self.assertNotIn('never emit', serialized)
        self.assertEqual(set(self.records[0]['source_scope']), set(s.DOC) | {'atom_id'})

    def test_close_removes_deadline_hooks_for_cleanup_and_is_idempotent(self):
        self.now = 100 + 24 * 60
        self.telemetry.close()
        self.telemetry.close()
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text('SELECT 1')).scalar_one(), 1)

    def test_secondary_write_failure_does_not_replace_database_error(self):
        def writer(record):
            if record['result_category'] == 'DATABASE_ERROR':
                raise RuntimeError('secondary-secret-error')
            self.records.append(copy.deepcopy(record))
        self.telemetry.writer = writer
        with self.engine.connect() as conn:
            with self.assertRaises(Exception) as failure:
                conn.execute(self.query())
        self.assertNotIsInstance(failure.exception, RuntimeError)
        self.assertEqual(self.telemetry.persistence_errors, ['ERROR_TELEMETRY_WRITE_FAILED'])
        self.assertEqual(self.records[0]['result_category'], 'STARTED')


class Case72WrapperDiagnostics(unittest.TestCase):
    def runner(self):
        from scripts.canary_case72_diagnostic import Case72Diagnostic
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        namespace = 'canary_stagep_' + 'd' * 32
        (root / '.codex_phase4p' / namespace).mkdir(parents=True)
        started = monotonic() - 2
        runner = Case72Diagnostic(root, {'CANARY_EVALUATION_ONLY_AUTHORIZED': 'true'},
            namespace=namespace, run_id='paired-real', identity_hash='a' * 64,
            session_start=started)
        return runner, started

    def test_wrapper_init_keeps_supplied_original_session_start_without_db(self):
        runner, started = self.runner()
        self.assertEqual(runner.window.started_monotonic, started)
        self.assertEqual(runner.result['session_start_monotonic'], started)
        self.assertFalse(runner.result['case72_new_execution_authorized'])
        self.assertFalse(runner.result['case72_new_execution_used'])
        self.assertIsNone(runner.db)

    def test_wrapper_checkpoint_stops_at23_minutes(self):
        from services.canary_contracts import CanaryError
        runner, _ = self.runner()
        runner.window = SessionWindow(100, clock=lambda: 100 + 23 * 60)
        with self.assertRaisesRegex(CanaryError, 'SESSION_USAGE_WINDOW_ENDED'):
            runner.checkpoint()

    def test_ownership_failure_without_atom_event_is_not_atom_failure(self):
        from services.canary_contracts import CanaryError
        runner, _ = self.runner()
        runner.exclusive = lambda: nullcontext()
        runner.identity_gate = Mock(side_effect=CanaryError('DATABASE_OWNERSHIP_REFUSED'))
        runner.repository = Mock(side_effect=AssertionError('EVIDENCE_MUST_NOT_EXECUTE'))
        runner.telemetry = NS(latest=None)
        route = NS(source=NS(revision=NS(source=NS(document_id=12))))
        with self.assertRaisesRegex(CanaryError, 'DATABASE_OWNERSHIP_REFUSED'):
            runner.probe(None, None, route, 'a'*64)
        self.assertFalse(runner.observed_atom_failure(route, 'a'*64))
        runner.repository.assert_not_called()

    def test_only_matching_failed_atom_scope_is_proof_not_success_or_other_doc(self):
        runner, _ = self.runner()
        route = NS(source=NS(revision=NS(source=NS(document_id=12))))
        for category, document, atom in (('EXECUTED', 12, 'a'*64), ('STARTED', 12, 'a'*64),
                                         ('DATABASE_ERROR', 13, 'a'*64), ('DATABASE_ERROR', 12, 'b'*64)):
            runner.telemetry = NS(latest=dict(result_category=category,
                source_scope=dict(document_id=document, atom_id=atom)))
            self.assertFalse(runner.observed_atom_failure(route, 'a'*64))
        runner.telemetry = NS(latest=dict(result_category='DATABASE_ERROR',
            source_scope=dict(document_id=12, atom_id='a'*64)))
        self.assertTrue(runner.observed_atom_failure(route, 'a'*64))

    def test_authorized_execution_rejects_missing_fresh_proof_before_db_or_auth(self):
        from services.canary_contracts import CanaryError
        runner, _ = self.runner()
        runner.identity_gate = Mock(side_effect=AssertionError('NO_DB_ALLOWED'))
        runner.exclusive = Mock(side_effect=AssertionError('NO_DB_ALLOWED'))
        runner.save = Mock(side_effect=AssertionError('NO_AUTH_CONSUMPTION_ALLOWED'))
        runner.evaluate_lane = Mock(side_effect=AssertionError('NO_RETRIEVAL_ALLOWED'))
        mf = NS(canonical_hash=lambda:'a'*64, generation='real-baseline-v1')
        for proof in (None, {}, {'fresh_read_succeeded':False},
                      {'fresh_read_succeeded':True, 'atom':'b'*64, 'manifest':'c'*64,
                       'generation':'real-baseline-v1'}):
            runner.diagnostic_failure = proof
            with self.assertRaisesRegex(CanaryError, 'CASE72_FRESH_ATOM_PROOF_REQUIRED'):
                runner.authorized_execution({}, None, mf)
        runner.identity_gate.assert_not_called()
        runner.exclusive.assert_not_called()
        runner.save.assert_not_called()
        runner.evaluate_lane.assert_not_called()

    def test_unknown_historical_scope_never_authorizes_measured_retrieval(self):
        from services.canary_contracts import CanaryError, Lane
        from services.canary_representation import exact_input_hash
        runner, _ = self.runner()
        runner.save = Mock()
        runner.identity_gate = Mock()
        runner.exclusive = lambda: nullcontext()
        repo = NS(dense=Mock(return_value=[]), fts=Mock(return_value=NS(hits=[])), children=Mock())
        runner.repository = lambda: nullcontext(repo)
        runner.common = [({'id':72, 'query':'Frozen test query'}, object())]
        runner.queries = {exact_input_hash('Frozen test query'): NS(vector=[])}
        runner.rows = {(72, Lane.LEGACY_CONTROL.value): {}}
        runner.manifests = (NS(lane=Lane.STRUCTURAL_CANARY, canonical_hash=lambda: 'a'*64,
            generation='real-baseline-v1', effective=lambda hard: (),
            policy=NS(evidence_units=10, evidence_bytes=2000)),)
        runner.db = NS(engine=object())
        runner.evaluate_lane = Mock(side_effect=AssertionError('MEASURED_LANE_MUST_NOT_RUN'))
        with patch('scripts.canary_case72_diagnostic.EvidenceTelemetry'), \
                patch('scripts.canary_case72_diagnostic.normalize', return_value=[]), \
                patch('scripts.canary_case72_diagnostic.typed_rrf', return_value=[]), \
                patch('scripts.canary_case72_diagnostic.reserve_witnesses', return_value=[]), \
                patch('scripts.canary_case72_diagnostic.emit'), \
                patch('scripts.canary_case72_diagnostic.event.remove'):
            with self.assertRaisesRegex(CanaryError, 'HISTORICAL_FAILED_ATOM_NOT_RECOVERABLE'):
                runner.evaluate()
        runner.evaluate_lane.assert_not_called()
        self.assertFalse(runner.result['case72_new_execution_authorized'])
        self.assertFalse(runner.result['case72_new_execution_used'])
        self.assertEqual(runner.probes, 0)


if __name__ == '__main__':
    unittest.main()
