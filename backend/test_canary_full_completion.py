"""New authorization, three UNSAVED attempts, reuse, and safe final durability."""
from contextlib import nullcontext, redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from services.canary_contracts import CanaryError, Lane
from services.canary_representation import exact_input_hash
from scripts.canary_full_completion import FullCompletion, AUTHORIZATION, CATALOG_SQL
from scripts.canary_evaluation_resume import atomic_record, read_bounded, EvaluationRunner
from scripts.canary_evaluation_transport import DatabaseTransportTimeout
from scripts.canary_read_recovery import ReproducibleReadFailure, ReadRecoveryExhausted
from scripts.canary_evaluation_transport import safe_error


class CompletionPolicy(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name); ns='canary_stagep_'+'c'*32
        (root/'.codex_phase4p'/ns).mkdir(parents=True)
        self.r=FullCompletion(root,{'CANARY_EVALUATION_ONLY_AUTHORIZED':'true'},
            namespace=ns,run_id='paired-real',identity_hash='a'*64,
            final_authorization=AUTHORIZATION,diagnostic_checkpoint='b'*40,
            diagnosis_artifact='diagnosis.json')
        self.snapshot=dict(id=82,query='frozen query',snapshot_hash='d'*64)
        self.hard=NS(organization_id=538,bot_id=674,identity=lambda:'hard')
        self.mf=NS(lane=Lane.STRUCTURAL_CANARY,generation='sealed',canonical_hash=lambda:'e'*64,
                   effective=lambda hard:(1,))
        self.r.queries={exact_input_hash(self.snapshot['query']):NS(vector=(1,),vector_hash='f'*64)}
        self.r.recovery_code=self.r.code={}
        for target in ('recovery_hashes','frozen_files'):
            p=patch('scripts.canary_full_completion.'+target,return_value={});p.start();self.addCleanup(p.stop)

    def test_new_auth_preserves_prior_ledgers_and_records_exact_identity(self):
        prior=self.r.folder/'old-attempt.json';atomic_record(prior,{'immutable':True});before=prior.read_bytes()
        self.r.before_lane_attempt(self.snapshot,self.hard,self.mf,0)
        self.assertEqual(prior.read_bytes(),before)
        record=read_bounded(next(self.r.folder.glob(AUTHORIZATION+'*.json')))
        self.assertEqual(record['query_vector_hash'],'f'*64)
        self.assertEqual(record['hard_scope'],'hard')
        with self.assertRaisesRegex(CanaryError,'ALREADY_CONSUMED'):
            self.r.before_lane_attempt(self.snapshot,self.hard,self.mf,0)

    def test_saved_historical_lanes_cannot_run(self):
        for case in (1,81):
            with self.assertRaisesRegex(CanaryError,'HISTORICAL'):
                self.r.before_lane_attempt(dict(self.snapshot,id=case),self.hard,self.mf,0)
        self.mf.lane=Lane.LEGACY_CONTROL
        with self.assertRaisesRegex(CanaryError,'HISTORICAL'):
            self.r.before_lane_attempt(self.snapshot,self.hard,self.mf,0)

    def test_saved_case82_and_later_success_cannot_reexecute(self):
        for case in (82,90):
            atomic_record(self.r.folder/f'case-{case}-STRUCTURAL_CANARY.json',{'saved':True})
            with self.assertRaisesRegex(CanaryError,'SAVED_LANE'):
                self.r.before_lane_attempt(dict(self.snapshot,id=case),self.hard,self.mf,0)

    def test_fourth_execution_refused(self):
        for attempt in range(3):self.r.before_lane_attempt(self.snapshot,self.hard,self.mf,attempt)
        with self.assertRaisesRegex(CanaryError,'THREE_LANE'):
            self.r.before_lane_attempt(self.snapshot,self.hard,self.mf,3)

    def lane_fixture(self):
        r=self.r
        r.exclusive=lambda:nullcontext();r.identity_gate=Mock();r.repository=lambda:nullcontext(object())
        r.before_lane_attempt=Mock();r.validate=Mock(return_value={'validated':True})
        r.gold={82:{}};r.entry_atoms={};r.pair=Mock();r.aggregate=Mock();r.completed=lambda:82;r.next_lane=lambda:None
        trace={'mode':'full_hybrid'}
        for name,result in (('score_case',{}),('safe_trace',{}),('vector_summary',{})):
            p=patch('scripts.canary_full_completion.'+name,return_value=result);p.start();self.addCleanup(p.stop)
        p=patch('scripts.canary_full_completion.sleep');p.start();self.addCleanup(p.stop)
        return trace

    def test_two_escaped_transport_errors_then_success_scores_only_success(self):
        trace=self.lane_fixture()
        with patch('scripts.canary_full_completion.run_query',side_effect=[DatabaseTransportTimeout(),
                DatabaseTransportTimeout(),trace]) as query,redirect_stdout(StringIO()):
            self.r.evaluate_lane(self.snapshot,self.hard,self.mf)
        self.assertEqual(query.call_count,3)
        self.assertEqual(self.r.validate.call_count,1)
        self.assertEqual(self.r.new_lanes,1)
        self.assertEqual(len(list(self.r.folder.glob('lane-failure*'))),2)
        self.assertTrue((self.r.folder/'case-82-STRUCTURAL_CANARY.json').exists())

    def test_nontransport_and_reproducible_failure_never_lane_retry(self):
        self.lane_fixture()
        for error in (CanaryError('SOURCE_CHANGED'),ReproducibleReadFailure('REPRODUCIBLE_DATABASE_READ_FAILURE')):
            # separate session avoids mutating an immutable diagnostic record
            self.r.session+='a'
            with patch('scripts.canary_full_completion.run_query',side_effect=error) as query,redirect_stdout(StringIO()):
                with self.assertRaises(CanaryError):self.r.evaluate_lane(self.snapshot,self.hard,self.mf)
            self.assertEqual(query.call_count,1)
        self.r.validate.assert_not_called()

    def test_saved_artifact_is_validated_reused_without_query(self):
        self.lane_fixture();atomic_record(self.r.folder/'case-82-STRUCTURAL_CANARY.json',{'saved':True})
        with patch('scripts.canary_full_completion.run_query') as query:
            self.r.evaluate_lane(self.snapshot,self.hard,self.mf)
        query.assert_not_called();self.r.validate.assert_called_once()

    def test_retry_attempt_does_not_score_failure(self):
        self.lane_fixture()
        with patch('scripts.canary_full_completion.run_query',side_effect=DatabaseTransportTimeout()) as query,redirect_stdout(StringIO()):
            with self.assertRaises(DatabaseTransportTimeout):self.r.evaluate_lane(self.snapshot,self.hard,self.mf)
        self.assertEqual(query.call_count,3);self.r.validate.assert_not_called()
        self.assertFalse((self.r.folder/'case-82-STRUCTURAL_CANARY.json').exists())

    def test_repeated_lease_uses_original_full_validation_and_cas(self):
        self.r.retained_until=0;self.r.load_cases=Mock()
        with patch.object(EvaluationRunner,'ensure_lease') as original:
            self.r.ensure_lease();self.r.ensure_lease()
        self.assertEqual(original.call_count,2)
        self.assertEqual(self.r.load_cases.call_count,2)

    def test_catalog_allowlist_is_read_only_and_not_arbitrary(self):
        self.assertTrue(CATALOG_SQL)
        self.assertTrue(all(s.lstrip().startswith('SELECT') for s in CATALOG_SQL))
        self.assertNotIn('SELECT pg_advisory_lock(1)',CATALOG_SQL)

    def test_interrupted_session_resumes_next_unused_attempt_without_reset(self):
        self.r.before_lane_attempt(self.snapshot,self.hard,self.mf,0)
        path=next(self.r.folder.glob(AUTHORIZATION+'*.json'));old=path.read_bytes()
        self.r.session='c'*32
        self.assertEqual(self.r.next_unused_attempt(self.snapshot,self.hard,self.mf),1)
        before=self.r.before_lane_attempt
        trace=self.lane_fixture();self.r.before_lane_attempt=before
        with patch('scripts.canary_full_completion.run_query',return_value=trace) as query,redirect_stdout(StringIO()):
            self.r.evaluate_lane(self.snapshot,self.hard,self.mf)
        self.assertEqual(query.call_count,1);self.assertEqual(path.read_bytes(),old)
        self.assertEqual(len(list(self.r.folder.glob(AUTHORIZATION+'*.json'))),2)

    def test_three_global_attempts_survive_process_restart(self):
        for attempt in range(3):self.r.before_lane_attempt(self.snapshot,self.hard,self.mf,attempt)
        self.r.session='c'*32
        with self.assertRaisesRegex(CanaryError,'THREE_LANE'):
            self.r.next_unused_attempt(self.snapshot,self.hard,self.mf)

    def test_resumption_refuses_changed_vector_identity(self):
        self.r.before_lane_attempt(self.snapshot,self.hard,self.mf,0)
        self.r.queries[exact_input_hash(self.snapshot['query'])].vector_hash='0'*64
        with self.assertRaisesRegex(CanaryError,'IDENTITY_MISMATCH'):
            self.r.next_unused_attempt(self.snapshot,self.hard,self.mf)

    def test_resumption_refuses_attempt_gap(self):
        self.r.before_lane_attempt(self.snapshot,self.hard,self.mf,1)
        with self.assertRaisesRegex(CanaryError,'LEDGER_GAP'):
            self.r.next_unused_attempt(self.snapshot,self.hard,self.mf)

    def test_resumption_requires_transport_or_interruption_not_integrity_failure(self):
        self.r.before_lane_attempt(self.snapshot,self.hard,self.mf,0)
        path=self.r.folder/f'lane-failure-{self.r.session}-82-STRUCTURAL_CANARY-1.json'
        failure=dict(case=82,lane='STRUCTURAL_CANARY',attempt=1,saved=False,
                     failure=safe_error(CanaryError('HASH_MISMATCH')))
        atomic_record(path,failure)
        with self.assertRaisesRegex(CanaryError,'NON_TRANSPORT'):
            self.r.next_unused_attempt(self.snapshot,self.hard,self.mf)
        # An independent fixture transport failure is eligible, without reset.
        with tempfile.TemporaryDirectory() as tmp:
            other=Path(tmp)
            for src in self.r.folder.glob(AUTHORIZATION+'*.json'):
                atomic_record(other/src.name,read_bounded(src))
            atomic_record(other/path.name,dict(failure,failure=safe_error(DatabaseTransportTimeout())))
            self.r.folder=other
            self.assertEqual(self.r.next_unused_attempt(self.snapshot,self.hard,self.mf),1)

    def test_read_cycle_exhaustion_uses_bounded_unsaved_lane_recovery(self):
        trace=self.lane_fixture()
        with patch('scripts.canary_full_completion.run_query',side_effect=[
                ReadRecoveryExhausted('READ_RECOVERY_CYCLES_EXHAUSTED'),trace]) as query,redirect_stdout(StringIO()):
            self.r.evaluate_lane(self.snapshot,self.hard,self.mf)
        self.assertEqual(query.call_count,2);self.assertEqual(self.r.new_lanes,1)


if __name__=='__main__':unittest.main()
