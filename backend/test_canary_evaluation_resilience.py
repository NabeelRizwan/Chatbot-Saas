"""Offline transport equivalence and the actual terminal/cleanup failure shape."""
from contextlib import contextmanager, redirect_stdout
import copy
from io import StringIO
from hashlib import sha256
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from psycopg2 import extensions
from sqlalchemy import select, update, delete
from sqlalchemy.dialects import postgresql
from database import canary_schema as s
from services.canary_contracts import CanaryError, Lane, State
from services.canary_repository import document_values, where
from services.canary_representation import exact_input_hash
from services.structural_chunking import digest
from scripts.canary_stage_a import NOW
from scripts.canary_evaluation_resume import EvaluationRunner, read_bounded, atomic_record, provider_free
from scripts.canary_evaluation_transport import (ExclusiveRun, DatabaseTransportTimeout, wait_bounded,
    bounded_database_io, transient_transport)
from scripts.canary_evaluation_validation import fetch_document, validate_document, validation_digest
import test_canary_real_handoff as fixtures


class ValidationEquivalence(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.Handoff('test_real_roundtrip_seal_and_query')
        self.base.setUp(); self.addCleanup(self.base.doCleanups)
        self.base.persist()
        self.repo, self.mf, self.pin = self.base.repo, self.base.manifest, self.base.pin

    def data(self, page_size=100):
        return fetch_document(self.repo.conn, self.mf, self.pin, page_size=page_size)

    def validate(self, data=None):
        return validate_document(self.repo, self.mf, self.pin, self.data() if data is None else data)

    def test_structural_old_and_new_exact_result_hash(self):
        self.repo._validate_generation(self.mf)
        old = {t.name:self.repo._rows(t,self.mf,self.pin) for t in
               (s.entries,s.vectors,s.atoms,s.work,s.memberships,s.spans)}
        old[s.sources.name] = [dict(self.repo.conn.execute(select(s.sources)).mappings().one())]
        self.assertEqual(validation_digest(self.mf,self.pin,old),self.validate())
        self.assertEqual(self.validate(),self.validate(self.data(page_size=1)))

    def test_legacy_old_and_new_exact_result_hash(self):
        b=self.base;chunks=[dict(id=i,text=f'Independent legacy input {i}.') for i in range(1,4)]
        pin=b.pin.model_copy(update={'entries':(),'legacy_members':(1,2,3),'batch_hash':digest(chunks)})
        mf=b.manifest.model_copy(update={'lane':Lane.LEGACY_CONTROL,'documents':(pin,)})
        b.repo.create(mf,now=NOW);b.repo.stage_legacy_work(mf,pin,chunks,now=NOW)
        items=[(pin,c['id'],c) for c in chunks];b.repo.begin_attempt(mf,items,now=NOW)
        b.repo.persist(mf,items,b.provider.embed([c['text'] for c in chunks],purpose='evidence'),now=NOW)
        b.repo._validate_generation(mf)
        old={t.name:b.repo._rows(t,mf,pin) for t in (s.legacy,s.legacy_work)}
        new=fetch_document(b.repo.conn,mf,pin,page_size=1)
        self.assertEqual(validation_digest(mf,pin,old),validate_document(b.repo,mf,pin,new))
        new[s.legacy.name][0]['input_hash']='f'*64
        with self.assertRaises(CanaryError):validate_document(b.repo,mf,pin,new)

    def test_missing_vector_both_reject(self):
        self.repo.conn.execute(delete(s.vectors))
        with self.assertRaises(CanaryError):self.repo._validate_generation(self.mf)
        with self.assertRaises(CanaryError):self.validate()

    def test_extra_vector_rejected(self):
        data=self.data();row=copy.deepcopy(data[s.vectors.name][0]);row['entry_id']='f'*64
        data[s.vectors.name].append(row)
        with self.assertRaises(CanaryError):self.validate(data)

    def test_wrong_input_hash_both_reject(self):
        data=self.data();data[s.vectors.name][0]['input_hash']='f'*64
        original=self.repo._rows
        def corrupt(table,*args):
            return data[table.name] if table is s.vectors else original(table,*args)
        with patch.object(self.repo,'_rows',side_effect=corrupt):
            with self.assertRaises(CanaryError):self.repo._validate_generation(self.mf)
        with self.assertRaises(CanaryError):self.validate(data)

    def test_wrong_profile_both_reject(self):
        proof=copy.deepcopy(self.data()[s.vectors.name][0]['provider_receipt']);proof['profile_hash']='f'*64
        self.repo.conn.execute(update(s.vectors).values(provider_receipt=proof))
        with self.assertRaises(CanaryError):self.repo._validate_generation(self.mf)
        with self.assertRaises(CanaryError):self.validate()

    def test_wrong_configuration_both_reject(self):
        proof=copy.deepcopy(self.data()[s.vectors.name][0]['provider_receipt']);proof['configuration']={}
        self.repo.conn.execute(update(s.vectors).values(provider_receipt=proof))
        with self.assertRaises(CanaryError):self.repo._validate_generation(self.mf)
        with self.assertRaises(CanaryError):self.validate()

    def test_corrupt_digest_both_reject(self):
        self.repo.conn.execute(update(s.vectors).values(vector_hash='f'*64))
        with self.assertRaises(CanaryError):self.repo._validate_generation(self.mf)
        with self.assertRaises(CanaryError):self.validate()

    def test_wrong_generation_rejected(self):
        data=self.data();data[s.vectors.name][0]['generation']='other'
        with self.assertRaisesRegex(CanaryError,'SCOPE'):self.validate(data)

    def test_wrong_document_or_source_rejected(self):
        for key,value in [('document_id',999),('source_hash','f'*64),('source_version',999),('crawl_id',1)]:
            data=self.data();data[s.vectors.name][0][key]=value
            with self.subTest(key=key),self.assertRaisesRegex(CanaryError,'SCOPE'):self.validate(data)

    def test_stale_epoch_still_rejected(self):
        self.repo.seal_generation(self.mf,expected_build_identity=self.repo.build_identity(self.mf),now=NOW)
        self.repo.conn.execute(update(s.lifecycle).values(epoch=1))
        with self.assertRaisesRegex(CanaryError,'STALE_SOURCE_EPOCH'):
            self.repo._snapshot(self.mf,self.repo._manifest(self.mf),NOW)

    def test_missing_work_receipt_both_reject(self):
        self.repo.conn.execute(delete(s.work))
        with self.assertRaises(CanaryError):self.repo._validate_generation(self.mf)
        with self.assertRaises(CanaryError):self.validate()

    def test_duplicate_row_rejected(self):
        data=self.data();data[s.vectors.name].append(copy.deepcopy(data[s.vectors.name][0]))
        with self.assertRaisesRegex(CanaryError,'DUPLICATE'):self.validate(data)

    def test_bounded_postgres_query_shapes(self):
        conn=Mock();conn.dialect=postgresql.dialect()
        groups={t:[] for t in self.data()}
        source=Mock();source.mappings.return_value=iter(self.data()[s.sources.name])
        page=Mock();page.mappings.return_value.one.return_value=groups
        conn.execute.side_effect=[source,page]
        fetch_document(conn,self.mf,self.pin,page_size=17)
        sql=conn.execute.call_args.args[0].compile(dialect=conn.dialect)
        self.assertEqual(conn.execute.call_count,2)
        self.assertEqual(str(sql).count('json_agg('),6)
        self.assertEqual(str(sql).count('LIMIT'),6)
        self.assertIn(17,sql.params.values())
        self.assertNotIn(self.pin.scope.revision.source.source_sha256,str(sql))

    def test_preflight_batch_disconnect_reconnects_with_identical_exact_proof(self):
        self.repo.seal_generation(self.mf,expected_build_identity=self.repo.build_identity(self.mf),now=NOW)
        self.repo.transition(self.mf,State.CANARY_READ,now=NOW)
        expected=self.validate(self.data(page_size=1))
        r=object.__new__(EvaluationRunner);r.transport_retries=0;r.identity_gate=Mock();r.save=Mock();r.session='offline'
        opens=[]
        @contextmanager
        def exclusive():opens.append(object());yield
        @contextmanager
        def repository(**kw):yield self.repo
        r.exclusive=exclusive;r.repository=repository
        original=self.repo.conn.execute;calls=[0]
        def lose_second_batch(statement,*args,**kwargs):
            calls[0]+=1
            if calls[0]==2:raise DatabaseTransportTimeout()
            return original(statement,*args,**kwargs)
        def fetch(conn,mf,pin):
            with patch.object(conn,'execute',side_effect=lose_second_batch):
                return fetch_document(conn,mf,pin,page_size=1)
        with patch('scripts.canary_evaluation_resume.fetch_document',side_effect=fetch), \
             patch('scripts.canary_evaluation_resume.time',return_value=NOW),redirect_stdout(StringIO()):
            _,actual=r.validated_document(self.mf,self.pin,dict(build_identity=self.repo.build_identity(self.mf)))
        self.assertEqual(actual,expected);self.assertEqual(len(opens),2)
        r.identity_gate.assert_called_once();self.assertEqual(r.transport_retries,1)

    def test_second_preflight_transport_failure_stops(self):
        r=object.__new__(EvaluationRunner);r.transport_retries=0;r.identity_gate=Mock();r.save=Mock();r.session='offline'
        @contextmanager
        def fail():raise DatabaseTransportTimeout();yield
        r.exclusive=fail
        with redirect_stdout(StringIO()),self.assertRaises(DatabaseTransportTimeout):
            r.validated_document(self.mf,self.pin,{})
        self.assertEqual(r.transport_retries,1)


class TransportSafety(unittest.TestCase):
    def test_wait_bound_times_out_without_secrets(self):
        conn=Mock();conn.poll.return_value=extensions.POLL_READ;conn.fileno.return_value=17
        with self.assertRaisesRegex(DatabaseTransportTimeout,'RESPONSE_TIMEOUT'):
            wait_bounded(conn,clock=lambda:0,wait=lambda *a:([],[],[]))

    def test_wait_success_and_callback_restoration(self):
        conn=Mock();conn.poll.side_effect=[extensions.POLL_READ,extensions.POLL_OK];conn.fileno.return_value=17
        wait_bounded(conn,clock=lambda:0,wait=lambda *a:([17],[],[]))
        before=extensions.get_wait_callback()
        with bounded_database_io():self.assertIs(extensions.get_wait_callback(),wait_bounded)
        self.assertIs(extensions.get_wait_callback(),before)

    def test_transport_classifier_does_not_retry_correctness(self):
        self.assertTrue(transient_transport(DatabaseTransportTimeout()))
        self.assertFalse(transient_transport(CanaryError('RESUME_IDENTITY_MISMATCH')))
        self.assertFalse(transient_transport(RuntimeError('random error')))

    def test_invalid_connection_does_not_unlock(self):
        lock=ExclusiveRun(Mock());conn=Mock(closed=False,invalidated=True);lock.conn=conn
        errors=lock.close()
        conn.execute.assert_not_called();conn.close.assert_called_once()
        self.assertEqual(errors[0]['category'],'UNLOCK_SKIPPED_INVALID_CONNECTION')

    def test_unlock_failure_still_closes(self):
        lock=ExclusiveRun(Mock());conn=Mock(closed=False,invalidated=False);lock.conn=conn;lock.key=1
        conn.execute.side_effect=DatabaseTransportTimeout()
        errors=lock.close()
        self.assertEqual(errors[0]['exception_class'],'DatabaseTransportTimeout')
        conn.close.assert_called_once();self.assertIsNone(lock.conn)


class ExecutionSafety(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);ns='canary_stagep_'+'a'*32
        (self.root/'.codex_phase4p'/ns).mkdir(parents=True)
        self.r=EvaluationRunner(self.root,{'CANARY_EVALUATION_ONLY_AUTHORIZED':'true'},namespace=ns,
            run_id='r',identity_hash='b'*64)
        self.r.common=[(dict(id=71,query='saved'),None)]
        self.mf=NS(lane=Lane.LEGACY_CONTROL)
        self.r.manifests=(self.mf,);self.r.identity_gate=Mock()
        self.r.rows={(case,lane.value):{} for case in range(1,71) for lane in Lane}
        self.r.queries={exact_input_hash('saved'):NS(vector=(.1,)*768)}

    def terminal(self,primary=None,cleanup=None,preflight=False):
        r=self.r;r.setup=Mock(side_effect=primary if preflight else None)
        r.evaluate=Mock(side_effect=None if preflight else primary)
        if primary is None:r.evaluate.side_effect=lambda:r.result.update(decision='B')
        r.lock=Mock();r.lock.close.return_value=[];r.lock.close.side_effect=cleanup
        r.db=Mock();r.db.close.return_value=None
        with redirect_stdout(StringIO()):code=r.run()
        result=read_bounded(r.folder/('evaluation-session-'+r.session+'.json'))
        self.assertNotEqual(result['status'],'RUNNING');self.assertEqual(result['provider_calls'],0)
        return code,result

    def test_success_unlock_success(self):
        code,result=self.terminal();self.assertEqual(code,0);self.assertIsNone(result['primary_error'])

    def test_failure_unlock_success(self):
        code,result=self.terminal(CanaryError('PRIMARY_FAILURE'))
        self.assertEqual(code,1);self.assertEqual(result['primary_error']['guard'],'PRIMARY_FAILURE')

    def test_success_unlock_failure(self):
        code,result=self.terminal(cleanup=DatabaseTransportTimeout())
        self.assertEqual(code,1);self.assertIsNone(result['primary_error']);self.assertTrue(result['cleanup_errors'])

    def test_failure_unlock_failure_primary_preserved(self):
        code,result=self.terminal(CanaryError('PRIMARY_FAILURE'),DatabaseTransportTimeout())
        self.assertEqual(result['failure']['guard'],'PRIMARY_FAILURE');self.assertTrue(result['cleanup_errors'])

    def test_disconnect_during_retrieval_and_unlock(self):
        _,result=self.terminal(DatabaseTransportTimeout(),RuntimeError('cleanup-private-details'))
        self.assertEqual(result['primary_error']['category'],'DATABASE_TRANSPORT_FAILURE')
        self.assertNotIn('private-details',str(result))

    def test_disconnect_during_preflight_terminal_written(self):
        _,result=self.terminal(DatabaseTransportTimeout(),preflight=True)
        self.r.evaluate.assert_not_called();self.assertEqual(result['next_resumable_lane']['case'],71)

    def test_terminal_write_failure_attempts_fallback(self):
        r=self.r;r.setup=Mock();r.evaluate=lambda:r.result.update(decision='B')
        r.save=Mock(side_effect=OSError('private path'))
        with redirect_stdout(StringIO()):self.assertEqual(r.run(),1)
        record=read_bounded(r.folder/('evaluation-terminal-'+r.session+'.json'))
        self.assertEqual(record['status'],'SAFE_STOP');self.assertIn('terminal_write_error',record)

    def prepare_lane(self):
        r=self.r
        @contextmanager
        def context():yield object()
        r.exclusive=context;r.repository=context
        return r.common[0][0]

    def test_unsaved_transport_retry_once_then_stop(self):
        snapshot=self.prepare_lane()
        with patch('scripts.canary_evaluation_resume.run_query',side_effect=DatabaseTransportTimeout()) as run,redirect_stdout(StringIO()):
            with self.assertRaises(DatabaseTransportTimeout):self.r.evaluate_lane(snapshot,None,self.mf)
        self.assertEqual(run.call_count,2);self.assertEqual(self.r.identity_gate.call_count,2)
        self.assertEqual(self.r.transport_retries,1)

    def test_retry_not_reset_across_process_resume(self):
        snapshot=self.prepare_lane()
        atomic_record(self.r.folder/'evaluation-retry-71-LEGACY_CONTROL.json',{'TRANSPORT_RETRY':1})
        with patch('scripts.canary_evaluation_resume.run_query',side_effect=DatabaseTransportTimeout()) as run,redirect_stdout(StringIO()):
            with self.assertRaises(DatabaseTransportTimeout):self.r.evaluate_lane(snapshot,None,self.mf)
        self.assertEqual(run.call_count,1)

    def test_completed_lane_never_rerun_or_modified(self):
        snapshot=self.prepare_lane();path=self.r.folder/'case-71-LEGACY_CONTROL.json'
        atomic_record(path,{'case':71});before=path.read_bytes()
        self.r.validate=Mock(return_value={});self.r.pair=Mock()
        with patch('scripts.canary_evaluation_resume.run_query',side_effect=AssertionError('rerun')):
            self.r.evaluate_lane(snapshot,None,self.mf)
        self.assertEqual(before,path.read_bytes())

    def test_provider_access_forbidden_during_run_and_cleanup(self):
        import httpx
        r=self.r;r.setup=lambda:httpx.get('https://example.invalid');r.evaluate=Mock()
        with redirect_stdout(StringIO()):self.assertEqual(r.run(),1)
        self.assertEqual(r.result['primary_error']['guard'],'UNEXPECTED_PROVIDER_ACCESS')
        r.evaluate.assert_not_called()

    def test_terminal_preflight_progress_uses_existing_pair_checksums(self):
        r=self.r;r.rows={}
        for case in range(1,71):
            lanes=[]
            for lane in Lane:
                path=r.folder/f'case-{case:02d}-{lane.value}.json'
                atomic_record(path,{'case':case,'lane':lane.value})
                lanes.append(dict(lane=lane.value,artifact_sha256=sha256(path.read_bytes()).hexdigest()))
            atomic_record(r.folder/f'evaluation-pair-{case:02d}.json',dict(case=case,identity_hash=r.identity_hash,status='COMPLETE',lanes=lanes))
        progress=r.saved_progress()
        self.assertEqual(progress['completed_pairs'],70)
        self.assertEqual(progress['next_resumable_lane'],dict(case=71,lane='LEGACY_CONTROL'))
        self.assertEqual(progress['last_completed_lane'],dict(case=70,lane='STRUCTURAL_CANARY'))

    def test_execution_revision_preserves_original_admission_and_rejects_retrieval_changes(self):
        r=self.r;path='backend/scripts/canary_evaluation_resume.py';source=b'original checkpoint'
        old=dict(identity_hash=r.identity_hash,frozen_files={path:sha256(source).hexdigest(),'retrieval.py':'a'*64})
        atomic_record(r.folder/'evaluation-admission.json',old);before=(r.folder/'evaluation-admission.json').read_bytes()
        r.execution_checkpoint='c'*40
        code={path:'b'*64,'retrieval.py':'a'*64,'backend/scripts/canary_evaluation_transport.py':'d'*64,
              'backend/scripts/canary_evaluation_validation.py':'e'*64}
        r.code=code
        with patch('scripts.canary_evaluation_resume.subprocess.check_output',return_value=source):
            r.admit_execution(dict(old,frozen_files=code))
            with self.assertRaisesRegex(CanaryError,'NON_EXECUTION'):
                r.admit_execution(dict(old,frozen_files=code|{'retrieval.py':'f'*64}))
        self.assertEqual(before,(r.folder/'evaluation-admission.json').read_bytes())


if __name__=='__main__':unittest.main()
