"""Offline authorization/retry gates; never opens PostgreSQL or a provider."""
from contextlib import nullcontext, redirect_stdout
from hashlib import sha256
from io import StringIO
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from services.canary_contracts import CanaryError, Lane
from services.canary_representation import exact_input_hash
from scripts.canary_evaluation_resume import atomic_record, read_bounded
from scripts.canary_evaluation_transport import DatabaseTransportTimeout
from scripts.canary_post_atom_completion import PostAtomCompletion, AUTHORIZATION


class PostAtomCompletionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root = Path(temp.name); ns = 'canary_stagep_'+'f'*32
        (root/'.codex_phase4p'/ns).mkdir(parents=True)
        self.r = PostAtomCompletion(root, {'CANARY_EVALUATION_ONLY_AUTHORIZED': 'true'},
            namespace=ns, run_id='paired-real', identity_hash='a'*64,
            final_authorization=AUTHORIZATION, diagnostic_checkpoint='b'*40, diagnosis_artifact='diagnosis.json')
        self.r.wrapper_code = self.r.completion_code = {}
        atomic_record(self.r.diagnosis_path, {'fixture': True})
        self.r.diagnosis_sha = sha256(self.r.diagnosis_path.read_bytes()).hexdigest()
        self.r.split_transport_proof = {'result': 'PASS'}
        self.r.validate = Mock()
        self.r.telemetry = Mock()
        self.r.diagnosis = dict(source_scope={'document_id': 29, 'atom_id': 'original'})
        self.mf = NS(lane=Lane.STRUCTURAL_CANARY, canonical_hash=lambda: 'c'*64, generation='sealed')
        self.legacy = NS(lane=Lane.LEGACY_CONTROL)
        self.r.manifests = (self.mf, self.legacy)
        self.snapshot = dict(id=75, query='frozen', snapshot_hash='d'*64)
        self.hard = NS(identity=lambda: 'hard')
        self.r.queries = {exact_input_hash('frozen'): NS(vector_hash='e'*64)}
        atomic_record(self.r.folder/'case-75-LEGACY_CONTROL.json', {'immutable': True})
        self.addCleanup(patch.stopall)
        patch('scripts.canary_final_evaluation.wrapper_hashes', return_value={}).start()
        patch('scripts.canary_post_atom_completion.completion_hashes', return_value={}).start()

    def attempt(self, attempt=0):
        self.r.before_lane_attempt(self.snapshot, self.hard, self.mf, attempt)

    def probe(self, *, same=False, error=None):
        scope = self.r.diagnosis['source_scope'] if same else {'document_id': 30, 'atom_id': 'different'}
        record = dict(statement_started=True, result_category='DATABASE_TIMEOUT', source_scope=scope)
        self.r.telemetry = NS(summary=lambda: {}, set_context=Mock(), context={}, failed=dict(record=record, route=object(), key=scope['atom_id']),
            latest=dict(source_scope=scope, result_category='SUCCESS', payload_hash_validation='PASS'))
        self.r.exclusive = lambda: nullcontext()
        self.r.identity_gate = Mock()
        repo = NS(evidence=Mock(side_effect=error))
        self.r.repository = lambda: nullcontext(repo)
        return repo

    def retry(self):
        return self.r.authorize_lane_retry(self.snapshot, self.hard, self.mf, DatabaseTransportTimeout(), None)

    def test_separate_authorization_leaves_exhausted_historical_ledger_unchanged(self):
        old = self.r.folder/'evaluation-retry-75-STRUCTURAL_CANARY.json'
        atomic_record(old, {'exhausted': True}); before = old.read_bytes()
        self.attempt()
        self.assertEqual(before, old.read_bytes())
        self.r.validate.assert_called_once()
        record = read_bounded(self.r.folder/(self.r.attempt_name(75, self.mf.lane.value, 0)+'.json'))
        self.assertEqual(record['authorization'], AUTHORIZATION)
        with self.assertRaisesRegex(CanaryError, 'ALREADY_CONSUMED'): self.attempt()

    def test_old_cases_and_case75_legacy_cannot_run(self):
        self.snapshot['id'] = 74
        with self.assertRaisesRegex(CanaryError, 'HISTORICAL'): self.attempt()
        self.snapshot['id'] = 75
        self.mf.lane = Lane.LEGACY_CONTROL
        with self.assertRaises(CanaryError): self.attempt()

    def test_saved_lane_cannot_run(self):
        atomic_record(self.r.folder/'case-75-STRUCTURAL_CANARY.json', {'saved': True})
        with self.assertRaisesRegex(CanaryError, 'SAVED_LANE'): self.attempt()

    def test_same_atom_failure_stops_without_probe(self):
        repo = self.probe(same=True)
        with self.assertRaisesRegex(CanaryError, 'SAME_ATOM_FAILED_AGAIN_STOP'): self.retry()
        repo.evidence.assert_not_called()
        self.assertEqual(self.r.transport_retries, 0)

    def test_different_exact_scope_probe_permits_only_one_retry(self):
        repo = self.probe()
        with redirect_stdout(StringIO()): self.assertTrue(self.retry())
        repo.evidence.assert_called_once()
        self.assertEqual(self.r.identity_gate.call_count, 2)
        self.attempt(1)
        with self.assertRaisesRegex(CanaryError, 'ALREADY_CONSUMED'): self.attempt(1)
        with self.assertRaisesRegex(CanaryError, 'MEASURED_ATTEMPT_BOUND'): self.attempt(2)

    def test_probe_failure_does_not_authorize_retry(self):
        self.probe(error=DatabaseTransportTimeout())
        with self.assertRaises(DatabaseTransportTimeout): self.retry()
        self.assertEqual(self.r.transport_retries, 0)
        self.assertFalse(list(self.r.folder.glob('*fresh-scope-proof.json')))

    def test_later_case_also_requires_exact_probe(self):
        self.snapshot['id'] = 76
        self.probe()
        self.r.telemetry.failed = None
        with self.assertRaisesRegex(CanaryError, 'EXACT_FAILED_SCOPE_TELEMETRY_REQUIRED'): self.retry()
        with self.assertRaises(FileNotFoundError): self.attempt(1)

    def test_wrong_scope_probe_result_never_authorizes_retry(self):
        self.probe()
        self.r.telemetry.latest['source_scope'] = {'wrong': 'scope'}
        with self.assertRaisesRegex(CanaryError, 'EXACT_FRESH_SCOPE_PROOF_FAILED'): self.retry()


if __name__ == '__main__':
    unittest.main()
