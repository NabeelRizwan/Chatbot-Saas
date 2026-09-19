import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock
from sqlalchemy import select,func,update,event
from database import canary_schema as s
from scripts.canary_recovery_fixture import engine_for,fixture_init,fixture_step,auth
from scripts.canary_recovery_repository import RecoveryRepository
from scripts.canary_real_repository import RealCanaryRepository
from scripts.canary_stage_a import NOW,hard_scope
from services.canary_contracts import CanaryError,State
from services.structural_chunking import digest


class Durable(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'owned-recovery.sqlite'
        self.engine=engine_for(self.path);self.addCleanup(self.engine.dispose)
        self.mf,self.identity=fixture_init(self.engine)

    def child(self,*args,code=0):
        result=subprocess.run([sys.executable,'-B','-m','scripts.canary_recovery_fixture',str(self.path),*map(str,args)],
            capture_output=True,text=True,timeout=90)
        self.assertEqual(result.returncode,code,result.stderr+result.stdout)
        return json.loads(result.stdout) if result.stdout else None

    def assert_inventory(self,succeeded,unknown=0):
        with self.engine.begin() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(s.legacy)).scalar_one(),succeeded)
            states=dict(conn.execute(select(s.legacy_work.c.state,func.count()).group_by(s.legacy_work.c.state)).all())
            self.assertEqual(states.get('succeeded',0),succeeded)
            self.assertEqual(states.get('unknown',0),unknown)
            self.assertEqual(sum(states.values()),100)

    def test_sixty_fail_then_fresh_process_forty(self):
        self.assertEqual(self.child('--fail-at',61)['new'],60)
        self.assert_inventory(60,1)
        result=self.child('--approve')
        self.assertEqual(result,dict(result='SEALED',resumed_reuse=60,new=40))
        self.assert_inventory(100)

    def test_ninety_nine_then_one(self):
        self.child('--fail-at',100);self.assert_inventory(99,1)
        self.assertEqual(self.child('--approve')['new'],1);self.assert_inventory(100)

    def test_first_batch_hold(self):
        self.child('--fail-at',1);self.assert_inventory(0,1)
        self.assertEqual(self.child('--approve')['new'],100)

    def test_multiple_resume_cycles(self):
        self.child('--fail-at',21)
        r=self.child('--approve','--fail-at',61)
        self.assertEqual((r['resumed_reuse'],r['new']),(20,40))
        self.assertEqual(self.child('--approve')['new'],40);self.assert_inventory(100)

    def test_commit_then_process_dies_before_artifact(self):
        self.child('--crash-after',60,code=23)
        self.assert_inventory(60)
        r=self.child();self.assertEqual((r['resumed_reuse'],r['new']),(60,40))

    def test_started_process_dies_no_automatic_spend(self):
        self.child('--crash-started',code=24);self.assert_inventory(0,1)
        result=self.child(code=1)
        self.assertEqual(result['guard'],'UNKNOWN_CONSUMPTION_EXPLICIT_BATCH_GRANT_REQUIRED')
        self.assert_inventory(0,1)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(s.attempts)).scalar_one(),1)

    def test_hold_no_partial_read_dense_fts_materialize_or_seal(self):
        self.child('--fail-at',61)
        with self.engine.begin() as conn:
            repo=RecoveryRepository(conn,self.mf.approval,authorization=auth(self.mf.approval),clock=lambda:NOW)
            for call in (lambda:repo.read_gate(self.mf,hard_scope(self.mf),now=NOW),
                    lambda:repo.dense(self.mf,hard_scope(self.mf),[.1]*768,now=NOW),
                    lambda:repo.fts(self.mf,hard_scope(self.mf),'test',now=NOW),
                    lambda:repo.transition(self.mf,State.CANARY_READ,now=NOW),
                    lambda:repo.transition(self.mf,State.COMPARATIVE_EVAL,now=NOW),
                    lambda:repo.seal_generation(self.mf,expected_build_identity=repo.build_identity(self.mf),now=NOW)):
                with self.assertRaises(CanaryError):call()

    def test_source_epoch_paused_refused(self):
        self.child('--fail-at',1)
        with self.engine.begin() as conn:conn.execute(update(s.lifecycle).values(epoch=1))
        self.assertEqual(self.child('--approve',code=1)['guard'],'STALE_SOURCE_EPOCH')

    def test_wrong_manifest_identity_refused(self):
        with self.assertRaisesRegex(CanaryError,'IDENTITY_MISMATCH'):
            fixture_step(self.engine,expected_hash='f'*64)

    def test_expired_run_refused(self):
        with self.assertRaisesRegex(CanaryError,'EXPIRED'):
            fixture_step(self.engine,now=NOW+86400)

    def test_corrupt_succeeded_readback_refused(self):
        self.child('--fail-at',2)
        with self.engine.begin() as conn:conn.execute(update(s.legacy).values(vector_hash='e'*64))
        self.assertEqual(self.child('--approve',code=1)['guard'],'PERSISTED_REAL_VECTOR_CORRUPTION')


class TransportEquivalence(unittest.TestCase):
    def test_all_structural_staging_rows_and_hashes_identical(self):
        from scripts.canary_stage_a import offline_repository,approval,fixture_batch,make_manifest
        from scripts.canary_real_repository import RealAuthorization
        from scripts.canary_gemini_embeddings import real_profile,configuration
        from services.canary_contracts import Manifest
        a=approval().model_copy(update={'environment':'disposable_test'})
        authorization=RealAuthorization(a.operator_reference,a.organization_id,a.bot_id,real_profile().configuration_hash)
        batch=fixture_batch('# Guide\n\n## Scope\n\n'+('A grounded statement with an exact qualification. '*120)+
            '\n\n## Directions\n\n1. Read the instructions.\n2. Follow the steps.\n\n| Item | Value |\n| --- | --- |\n| A | 12 |')
        hashes=[];counts=[]
        for cls in (RealCanaryRepository,RecoveryRepository):
            with offline_repository(a) as base:
                r=cls(base.conn,a,authorization=authorization,clock=lambda:NOW)
                calls=[]
                def counter(conn,cursor,statement,parameters,context,executemany):
                    calls.append(len(parameters) if executemany else 1)
                event.listen(base.conn,'before_cursor_execute',counter)
                pin=r.register_fixture_source(batch,source_id=1)
                mf=Manifest(**(make_manifest((pin,),approved=a).model_dump()|
                    {'profile':real_profile(),'embedding_configuration':configuration()}))
                r.create(mf,now=NOW);r.stage_structure(mf,batch,now=NOW)
                event.remove(base.conn,'before_cursor_execute',counter)
                inventory={t.name:[dict(row) for row in base.conn.execute(select(t).order_by(*t.primary_key.columns)).mappings()]
                    for t in (s.sources,s.nodes,s.lifecycle,s.entries,s.atoms,s.work,s.memberships,s.spans,s.documents,s.manifests)}
                hashes.append(digest(inventory));counts.append(sum(calls))
        self.assertEqual(hashes[0],hashes[1])
        self.assertLess(counts[1],counts[0])
        print('structural_transport_equivalence',{'old_parameter_sets':counts[0],'new_parameter_sets':counts[1],
            'inventory_hash':hashes[0]})

    def test_old_and_batched_rows_identical_fewer_statements(self):
        from test_canary_real_handoff import Handoff
        results=[]
        for cls in (RealCanaryRepository,RecoveryRepository):
            case=Handoff('test_actual_runner_eight_query_and_multiple_batches_preserve_bytes');case.setUp()
            try:
                case.repo=cls(case.repo.conn,case.approval,authorization=case.auth,clock=lambda:NOW)
                counter=[]
                event.listen(case.repo.conn,'before_cursor_execute',lambda *args:counter.append(1))
                case.test_actual_runner_eight_query_and_multiple_batches_preserve_bytes()
                inventory={table.name:[dict(r) for r in case.repo.conn.execute(select(table)).mappings()]
                    for table in (s.legacy,s.legacy_work,s.manifests,s.entries,s.atoms,s.memberships,s.spans)}
                results.append((digest(inventory),len(counter)))
            finally:case.doCleanups()
        self.assertEqual(results[0][0],results[1][0])
        self.assertLess(results[1][1],results[0][1])
        print('transport_equivalence',{'old_sql':results[0][1],'new_sql':results[1][1],'inventory_hash':results[0][0]})


class RunnerSafety(unittest.TestCase):
    def test_probe_receipt_persists_without_another_api_call(self):
        from contextlib import contextmanager
        from test_canary_real_handoff import Handoff
        from scripts.canary_recovery_runner import RecoveryRunner
        case=Handoff('test_real_roundtrip_seal_and_query');case.setUp()
        try:
            runner=RecoveryRunner(Path(__file__).resolve().parents[1],{})
            runner.provider=case.provider
            repo=RecoveryRepository(case.repo.conn,case.approval,authorization=case.auth,clock=lambda:NOW)
            @contextmanager
            def repository():yield repo
            runner.repository=repository
            item=case.items()[0]
            case.provider.embed([item[2].text],purpose='evidence')
            runner.store_batch(case.manifest,[item],retries=0)
            self.assertEqual(case.client.models.embed_content.call_count,1)
            self.assertIsNotNone(repo.persisted_receipt(case.manifest,item[0],item[1],item[2].text))
            self.assertNotIn('unknown_batch_hash',runner.result)
        finally:case.doCleanups()

    def test_failed_batch_records_exact_operator_grant_hash(self):
        from contextlib import contextmanager
        from test_canary_real_handoff import Handoff
        from scripts.canary_recovery_runner import RecoveryRunner
        from services.canary_representation import exact_input_hash
        case=Handoff('test_real_roundtrip_seal_and_query');case.setUp()
        try:
            runner=RecoveryRunner(Path(__file__).resolve().parents[1],{})
            runner.provider=case.provider
            repo=RecoveryRepository(case.repo.conn,case.approval,authorization=case.auth,clock=lambda:NOW)
            @contextmanager
            def repository():yield repo
            runner.repository=repository
            case.client.models.embed_content.side_effect=RuntimeError('not emitted')
            item=case.items()[0]
            with self.assertRaises(CanaryError):runner.store_batch(case.manifest,[item],retries=0)
            self.assertEqual(runner.result['unknown_batch_hash'],digest([dict(lane=case.manifest.lane.value,
                document=item[0].scope.revision.source.document_id,key=item[1],input_hash=exact_input_hash(item[2].text))]))
            self.assertEqual(repo.work_state(case.manifest,item[0],item[1])['state'],'unknown')
        finally:case.doCleanups()

    def test_pair_not_partially_published_when_second_incomplete(self):
        from contextlib import contextmanager
        from test_canary_real_handoff import Handoff
        from scripts.canary_recovery_runner import RecoveryRunner
        from services.canary_contracts import Lane
        case=Handoff('test_real_roundtrip_seal_and_query');case.setUp()
        try:
            case.persist()
            chunks=[dict(id=1,text='Unbuilt control')]
            pin=case.pin.model_copy(update={'entries':(),'legacy_members':(1,),'batch_hash':digest(chunks)})
            legacy=case.manifest.model_copy(update={'lane':Lane.LEGACY_CONTROL,'documents':(pin,)})
            case.repo.create(legacy,now=NOW);case.repo.stage_legacy_work(legacy,pin,chunks,now=NOW)
            runner=RecoveryRunner(Path(__file__).resolve().parents[1],{})
            runner.manifests=(case.manifest,legacy)
            @contextmanager
            def repository():
                with case.repo.conn.begin_nested():yield case.repo
            runner.repository=repository;runner.hard=hard_scope
            with self.assertRaises(CanaryError):runner.seal(case.manifest)
            self.assertEqual(case.repo._manifest(case.manifest)['state'],'EMBEDDING_STAGING')
            self.assertFalse(runner.pair_published)
        finally:case.doCleanups()

    def test_named_resume_rejects_broad_or_missing_identity_before_db(self):
        from scripts.canary_recovery_state import open_retained
        for name in (None,'public','canary_stagep_latest','canary_stagep_'+'g'*32):
            db=Mock()
            with self.assertRaises(CanaryError):open_retained(db,namespace=name,run_id='paired-real',
                expected_hash='a'*64,reference='authorized',now=NOW)
            db.open.assert_not_called()

    def test_invalid_resume_hash_no_db(self):
        from scripts.canary_recovery_state import open_retained
        db=Mock()
        with self.assertRaises(CanaryError):open_retained(db,namespace='canary_stagep_'+'a'*32,
            run_id='paired-real',expected_hash=None,reference='authorized',now=NOW)
        db.open.assert_not_called()

    def test_explicit_development_deadline_bound(self):
        from scripts.canary_recovery_runner import RecoveryRunner
        for minutes in (0,301):
            with self.assertRaises(CanaryError):RecoveryRunner(Path(__file__).resolve().parents[1],{},deadline_minutes=minutes)

    def test_real_generation_module_not_referenced(self):
        import ast
        for path in Path('scripts').glob('canary*recovery*.py'):
            tree=ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node,ast.ImportFrom):
                    self.assertNotIn(node.module,('database.connection','services.rag_service','services.embedding_service'))


if __name__=='__main__':unittest.main()
