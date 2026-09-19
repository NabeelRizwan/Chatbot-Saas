"""New authorization cannot replay saved lanes or reset exhausted attempts."""
from unittest.mock import patch
import unittest

from services.canary_contracts import CanaryError, Lane
from scripts.canary_evaluation_resume import atomic_record, read_bounded
from scripts.canary_case82_completion import Case82Completion, AUTHORIZATION
from test_canary_post_atom_completion import PostAtomCompletionTests as ParentTests


class Case82CompletionTests(ParentTests):
    def setUp(self):
        super().setUp()
        old = self.r
        new = Case82Completion(old.root, old.env, namespace=old.namespace, run_id=old.run_id,
            identity_hash=old.identity_hash, final_authorization=AUTHORIZATION,
            diagnostic_checkpoint='b'*40, diagnosis_artifact='diagnosis.json')
        for key in ('wrapper_code','completion_code','diagnosis_sha','split_transport_proof','validate',
                    'telemetry','diagnosis','manifests','queries'):
            setattr(new,key,getattr(old,key))
        self.r = new
        self.snapshot['id'] = 82
        atomic_record(new.folder/'case-82-LEGACY_CONTROL.json', {'immutable':True})
        patch('scripts.canary_case82_completion.wrapper_hashes',return_value={}).start()
        patch('scripts.canary_case82_completion.case82_hashes',return_value={}).start()

    def test_separate_authorization_leaves_exhausted_historical_ledger_unchanged(self):
        old=self.r.folder/'CASE75_STRUCTURAL_POST_ATOM_DIAGNOSIS_20260919-82-STRUCTURAL_CANARY-attempt-2.json'
        atomic_record(old,{'exhausted':True});before=old.read_bytes()
        self.attempt()
        self.assertEqual(old.read_bytes(),before)
        record=read_bounded(self.r.folder/(self.r.attempt_name(82,self.mf.lane.value,0)+'.json'))
        self.assertEqual(record['authorization'],AUTHORIZATION)
        self.r.validate.assert_called_once()
        with self.assertRaisesRegex(CanaryError,'ALREADY_CONSUMED'):self.attempt()

    def test_old_cases_and_case75_legacy_cannot_run(self):
        for case in (1,75,81):
            self.snapshot['id']=case
            with self.assertRaisesRegex(CanaryError,'HISTORICAL'):self.attempt()
        self.snapshot['id']=82;self.mf.lane=Lane.LEGACY_CONTROL
        with self.assertRaises(CanaryError):self.attempt()

    def test_saved_lane_cannot_run(self):
        atomic_record(self.r.folder/'case-82-STRUCTURAL_CANARY.json',{'saved':True})
        with self.assertRaisesRegex(CanaryError,'SAVED_LANE'):self.attempt()

    def test_later_case_also_requires_exact_probe(self):
        self.snapshot['id']=83;self.probe();self.r.telemetry.failed=None
        with self.assertRaisesRegex(CanaryError,'EXACT_FAILED_SCOPE_TELEMETRY_REQUIRED'):self.retry()
        with self.assertRaises(FileNotFoundError):self.attempt(1)

    def test_missing_real_row_proof_blocks_measurement(self):
        self.r.split_transport_proof=None
        with self.assertRaisesRegex(CanaryError,'REAL_SPLIT_ROW_EQUIVALENCE_REQUIRED'):self.attempt()

    def test_altered_diagnosis_blocks_measurement(self):
        atomic_record(self.r.diagnosis_path,{'changed':True})
        with self.assertRaisesRegex(CanaryError,'DIAGNOSTIC_EVIDENCE_CHANGED'):self.attempt()


# Do not discover the imported historical TestCase a second time.
del ParentTests

if __name__=='__main__':unittest.main()
