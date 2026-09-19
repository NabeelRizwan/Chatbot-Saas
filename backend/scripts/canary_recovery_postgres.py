"""Owned disposable PostgreSQL recovery proof. Mock vectors; ZERO provider calls."""
from contextlib import contextmanager
import os
from pathlib import Path
import sys
from time import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select,func,event,update
from database import canary_schema as s
from services.canary_contracts import Manifest,Lane,State,CanaryError,canonicalize_vector_f32,canonical_vector_digest
from services.canary_representation import exact_input_hash
from services.structural_chunking import digest
from scripts.canary_stage_a import fixture_batch,make_manifest,hard_scope
from scripts.canary_gemini_embeddings import Attestation,configuration,real_profile
from scripts.canary_real_repository import RealAuthorization,RealCanaryRepository
from scripts.canary_recovery_repository import RecoveryRepository
from scripts.canary_postgres_validation import DisposableCanary,settings,safe_failure
from scripts.canary_schema_migration import upgrade
from scripts.canary_recovery_state import initialize,ownership,open_retained,validate,authorize_unknown,ExclusiveRun
from scripts.canary_bounded_output import emit


def run(env):
    private={k:v for k,v in env.items() if k.startswith('CANARY_')}
    if private.get('CANARY_RECOVERY_TEST_AUTHORIZED')!='true':raise CanaryError('RECOVERY_DB_TEST_NOT_AUTHORIZED')
    cfg=settings(private,stage='p')
    cfg.approval=cfg.approval.model_copy(update={'expires_at':cfg.approval.created_at+86400})
    db=DisposableCanary(cfg);lease=None;report={'result':'FAIL','provider_calls':0}
    try:
        report['postgres']=db.open();db.bootstrap()
        with db.transaction() as conn:upgrade(conn,cfg.approval);db.record_owned(conn)
        auth=RealAuthorization(cfg.approval.operator_reference,cfg.approval.organization_id,cfg.approval.bot_id,real_profile().configuration_hash)
        def repo(conn,cls=RecoveryRepository):return cls(conn,db.config.approval,authorization=auth)
        chunks=[dict(id=i,text=f'Exact mock work unit {i}.') for i in range(1,101)]
        with db.transaction() as conn:
            r=repo(conn);batch=fixture_batch('# Guide\n\nA source-backed fixture statement.')
            pin=r.register_fixture_source(batch,source_id=1).model_copy(update={'entries':(),
                'legacy_members':tuple(c['id'] for c in chunks),'batch_hash':digest(chunks)})
            mf=Manifest(**(make_manifest((pin,),approved=cfg.approval,run='paired-real',lane=Lane.LEGACY_CONTROL).model_dump()|
                {'profile':real_profile(),'embedding_configuration':configuration()}))
            r.create(mf,now=int(time()));r.stage_legacy_work(mf,pin,chunks,now=int(time()))
            ident=initialize(r,(mf,),frozen_identity={'fixture':digest(chunks)},owned=ownership(db),query_hashes=[],now=int(time()))
        items=[(pin,c['id'],c) for c in chunks]
        def receipts(group):
            result=[]
            for p,key,value in group:
                v=canonicalize_vector_f32([key/100]+[.125]*767)
                result.append(Attestation(cfg.approval.organization_id,cfg.approval.bot_id,
                    exact_input_hash(value['text']),mf.profile.canonical_hash(),canonical_vector_digest(v),v,1))
            return result
        measures=[]
        # Same schema, manifest, PKs, payloads and receipts; rollback each branch.
        with db.transaction() as conn:
            for cls in (RealCanaryRepository,RecoveryRepository):
                point=conn.begin_nested();counts=[]
                def count(*args):counts.append(1)
                event.listen(conn,'before_cursor_execute',count)
                r=repo(conn,cls);r.begin_attempt(mf,items[:8],now=int(time()))
                r.persist(mf,items[:8],receipts(items[:8]),now=int(time()))
                event.remove(conn,'before_cursor_execute',count)
                inventory={t.name:[dict(row)|({'embedding':list(map(float,row['embedding']))} if 'embedding' in row else {})
                    for row in conn.execute(select(t).order_by(t.c.chunk_id)).mappings()]
                    for t in (s.legacy,s.legacy_work)}
                measures.append(dict(sql=len(counts),row_hash=digest(inventory)))
                point.rollback()
        assert measures[0]['row_hash']==measures[1]['row_hash']
        assert measures[1]['sql']<measures[0]['sql']
        report['transport_equivalence']=dict(old=measures[0],batched=measures[1],exact_rows='PASS')
        for start in range(0,60,4):
            with db.transaction() as conn:
                r=repo(conn);r.begin_attempt(mf,items[start:start+4],now=int(time()))
                r.persist(mf,items[start:start+4],receipts(items[start:start+4]),now=int(time()))
        with db.transaction() as conn:
            r=repo(conn);r.begin_attempt(mf,items[60:61],now=int(time()))
            try:r.read_gate(mf,hard_scope(mf),now=int(time()))
            except CanaryError:pass
            else:raise CanaryError('PARTIAL_READ_LEAK')
        # Dispose and explicitly re-open only the independently named identity.
        namespace=cfg.namespace;expected=digest(ident);db.close()
        db=DisposableCanary(settings(private,stage='p'))
        loaded,_=open_retained(db,namespace=namespace,run_id='paired-real',expected_hash=expected,
            reference=private['CANARY_APPROVAL_REFERENCE'],now=int(time()))
        lease=ExclusiveRun(db);lease.acquire()
        with db.transaction() as conn:
            r=repo(conn);validate(r,loaded,expected_hash=expected,frozen_identity={'fixture':digest(chunks)},query_hashes=[],now=int(time()))
            states,done=r.completed(mf,items);assert len(done)==60
            try:authorize_unknown(r,mf,items[60:61],approved_batches=set(),reference='db-test',session_id='resume-test')
            except CanaryError:pass
            else:raise CanaryError('UNKNOWN_WORK_RETRIED_WITHOUT_GRANT')
            grant=digest([dict(lane=mf.lane.value,document=pin.scope.revision.source.document_id,key=61,
                input_hash=exact_input_hash(chunks[60]['text']))])
            authorize_unknown(r,mf,items[60:61],approved_batches={grant},reference='explicit-db-test',session_id='resume-test')
            r.persist(mf,items[60:61],receipts(items[60:61]),now=int(time()))
        for start in range(61,100,4):
            with db.transaction() as conn:
                r=repo(conn);group=items[start:start+4]
                r.begin_attempt(mf,group,now=int(time()));r.persist(mf,group,receipts(group),now=int(time()))
        with db.transaction() as conn:
            r=repo(conn);r.seal_generation(mf,expected_build_identity=r.build_identity(mf),now=int(time()))
            r.transition(mf,State.CANARY_READ,now=int(time()))
            r.read_gate(mf,hard_scope(mf),now=int(time()))
            states,done=r.completed(mf,items)
            assert len(done)==100 and all(v['state']=='succeeded' for v in states.values())
            assert conn.execute(select(func.count()).select_from(s.legacy)).scalar_one()==100
            assert conn.execute(select(func.count()).select_from(s.legacy_work)).scalar_one()==100
        report.update(result='PASS',resumed_reuse=60,remaining_completed=40,unique_inventory=100,
            exact_readback='PASS',seal='PASS',partial_read='REFUSED',unknown_without_grant='REFUSED',named_reopen='PASS')
        # Same explicit identity remains eligible for owned cleanup after TTL,
        # but must not acquire a read/resume lease at expiry.
        expired=DisposableCanary(settings(private,stage='p'))
        try:
            try:open_retained(expired,namespace=namespace,run_id='paired-real',expected_hash=expected,
                reference=private['CANARY_APPROVAL_REFERENCE'],now=cfg.approval.expires_at)
            except CanaryError as exc:
                assert str(exc)=='RETAINED_RUN_EXPIRED'
                report['expired_resume']='REFUSED'
            else:raise CanaryError('EXPIRED_RESUME_ACCEPTED')
        finally:expired.close()
    except Exception as exc:report['failure']=safe_failure(exc)
    finally:
        try:report['cleanup']=db.cleanup()
        except Exception as exc:report.update(result='FAIL',cleanup=safe_failure(exc))
        finally:
            if lease is not None:lease.close()
            db.close();private.clear()
            for key in tuple(env):
                if key.startswith('CANARY_'):env.pop(key,None)
        emit(report)
    return report


if __name__=='__main__':raise SystemExit(0 if run(os.environ)['result']=='PASS' else 1)
