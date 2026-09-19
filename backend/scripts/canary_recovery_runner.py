"""Explicit fresh/resume/cleanup commands for the isolated real Phase-P canary.

No automatic stale-schema discovery, no automatic unknown-consumption re-spend.
No application DB, serving activation, generation, or provider fallback.
"""
import argparse
from contextlib import contextmanager
import logging
import os
from pathlib import Path
import sys
from time import time,perf_counter
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select,update,insert,func
from database import canary_schema as s
from services.canary_contracts import CanaryError,State,Lane,canonicalize_vector_f32,canonical_vector_digest
from services.canary_repository import where,run_values,manifest_values
from services.canary_representation import exact_input_hash,source_pin
from services.structural_chunking import digest
from scripts.canary_gemini_embeddings import Attestation,real_profile
from scripts.canary_provider_recovery import RecoverableGemini,ProviderHold
from scripts.canary_real_repository import RealAuthorization,receipt_payload
from scripts.canary_recovery_repository import RecoveryRepository
from scripts.canary_real_embedding_retrieval import Runner,item_text,require
from scripts.canary_postgres_validation import DisposableCanary,settings,safe_failure
from scripts.canary_schema_migration import upgrade
from scripts.canary_bounded_output import emit,vector_summary
from scripts.canary_recovery_state import (initialize,validate,mark,ownership,record_attempt,
    authorize_unknown,open_retained,ExclusiveRun,RETENTION_SECONDS)
from scripts.canary_timing import Timing


class RecoveryRunner(Runner):
    def __init__(self,root,env,*,mode='fresh',namespace=None,run_id='paired-real',identity_hash=None,
                 approved_batches=(),spend_reference=None,deadline_minutes=300):
        super().__init__(root,env)
        if not 1<=deadline_minutes<=300:raise CanaryError('INVALID_EXECUTION_DEADLINE')
        self.mode=mode;self.namespace=namespace;self.run_id=run_id;self.identity_hash=identity_hash
        self.approved_batches=set(approved_batches);self.spend_reference=spend_reference
        self.deadline=perf_counter()+deadline_minutes*60
        self.session_id=uuid.uuid4().hex;self.timing=Timing();self.lock=None
        self.manifests=();self.identity=None;self.control_ready=False;self.resume_reused=0
        self.pair_published=False
        self.result.update(p1='PREVIOUSLY_ACCEPTED_NOT_REPEATED',p2='NOT_RUN',mode=mode)

    def check_deadline(self):
        require(perf_counter()<self.deadline,'CANARY_EXECUTION_DEADLINE')

    @contextmanager
    def repository(self):
        self.check_deadline()
        with self.db.transaction() as conn:
            yield RecoveryRepository(conn,self.config.approval,authorization=self.authorization,timing=self.timing)

    def diagnostic(self,record):
        # One bounded file per attempt; STARTED survives process/provider death.
        self.save(f'attempt-{self.session_id}-{record["attempt"]:04d}',record)
        if self.control_ready:
            with self.timing.stage('work_ledger'),self.repository() as repo:
                record_attempt(repo,self.manifests[0],self.session_id,record)

    def provider_client(self):
        from dotenv import dotenv_values
        local=dotenv_values(self.root/'backend/.env',interpolate=False)
        key=local.get('GEMINI_API_KEY');local.clear()
        try:
            self.provider=RecoverableGemini(key,organization_id=self.config.approval.organization_id,
                bot_id=self.config.approval.bot_id,approved=True,on_attempt=self.diagnostic,
                deadline_seconds=min(18000,self.deadline-perf_counter()))
        finally:key=None

    def frozen_identity(self):
        return dict(m_digest=self.frozen['ordered_batch_digest'],snapshots=self.snapshot_hash,
            profile=real_profile().canonical_hash(),configuration=real_profile().configuration_hash,
            legacy=digest(self.legacy_chunks),plan=digest(self.plan))

    def query_hashes(self):return [exact_input_hash(v[0]['query']) for v in self.common]

    def setup(self):
        if self.mode=='cleanup':
            # Cleanup needs exact ownership, not the continued availability of
            # corpus reconstruction code or an embedding credential.
            require(self.env.get('CANARY_RESUME_AUTHORIZED')=='true','EXPLICIT_RESUME_AUTHORIZATION_REQUIRED')
            self.config=settings(self.env,stage='p')
            self.db=DisposableCanary(self.config)
            self.manifests,self.identity=open_retained(self.db,namespace=self.namespace,run_id=self.run_id,
                expected_hash=self.identity_hash,reference=self.env['CANARY_APPROVAL_REFERENCE'],
                now=int(time()),cleanup_only=True)
            self.lock=ExclusiveRun(self.db);self.lock.acquire()
            self.artifacts=self.root/'.codex_phase4p'/self.config.namespace
            self.artifacts.mkdir(parents=True,exist_ok=True)
            self.timing.attach(self.db.engine)
            return
        with self.timing.stage('source_reconstruction'):self.freeze_inputs()
        first=next(iter(self.batches.values())).scope.revision.source
        self.config=settings(self.env,stage='p',organization_id=first.organization_id,bot_id=first.bot_id)
        if self.mode not in ('fresh','resume','cleanup'):raise CanaryError('UNKNOWN_RECOVERY_MODE')
        if self.mode=='fresh':
            self.config.approval=self.config.approval.model_copy(update={
                'expires_at':self.config.approval.created_at+RETENTION_SECONDS})
            self.artifacts=self.root/'.codex_phase4p'/self.config.namespace
            self.artifacts.mkdir(parents=True,exist_ok=False)
            # Read-only target/stale-schema admission before even the probe.
            self.db=DisposableCanary(self.config)
            self.result['postgres']=self.db.open();self.timing.attach(self.db.engine)
            self.provider_client()
            first_entry=next(iter(self.batches.values())).entries[0]
            self.progress('ONE_AVAILABILITY_PROBE')
            with self.timing.stage('provider_wait'):
                probe=self.provider.embed([first_entry.text],purpose='evidence',retries=0)[0]
            self.result['probe']=dict(result='PASS',**vector_summary(probe))
            self.save('probe',self.result['probe'])
            # Only after the single successful exact-input probe create a schema.
            self.db.bootstrap();self.lock=ExclusiveRun(self.db);self.lock.acquire()
            with self.db.transaction() as conn:
                upgrade(conn,self.config.approval);self.db.record_owned(conn)
            self.authorization=RealAuthorization.from_environment(self.env,self.config.approval)
            with self.timing.stage('manifest_preparation'):
                structural,legacy,_,_=self.stage_paired()
                self.manifests=(structural,legacy)
                with self.repository() as repo:
                    self.identity=initialize(repo,self.manifests,frozen_identity=self.frozen_identity(),
                        owned=ownership(self.db),query_hashes=self.query_hashes(),now=int(time()))
            self.identity_hash=digest(self.identity);self.control_ready=True
            # Copy the already completed probe diagnostic into the owned ledger.
            for record in self.provider.attempts:
                with self.repository() as repo:
                    started=dict(record,result='STARTED',consumption='UNKNOWN')
                    record_attempt(repo,structural,self.session_id,started)
                    record_attempt(repo,structural,self.session_id,record)
            first_pin=next(p for p in structural.documents if first_entry.entry_key in p.entries)
            # Commit the probe alone before asking for any additional vectors.
            self.store_batch(structural,[(first_pin,first_entry.entry_key,first_entry)],retries=0)
            self.result['probe']['persisted_without_repeat']=True
            self.save('probe',self.result['probe'])
        else:
            require(self.env.get('CANARY_RESUME_AUTHORIZED')=='true','EXPLICIT_RESUME_AUTHORIZATION_REQUIRED')
            self.db=DisposableCanary(self.config)
            self.manifests,self.identity=open_retained(self.db,namespace=self.namespace,run_id=self.run_id,
                expected_hash=self.identity_hash,reference=self.env['CANARY_APPROVAL_REFERENCE'],
                now=int(time()),cleanup_only=self.mode=='cleanup')
            self.result['postgres']=self.db.facts;self.timing.attach(self.db.engine)
            self.lock=ExclusiveRun(self.db);self.lock.acquire()
            self.artifacts=self.root/'.codex_phase4p'/self.config.namespace
            self.artifacts.mkdir(parents=True,exist_ok=True)
            self.authorization=RealAuthorization.from_environment(self.env,self.config.approval)
            if self.mode=='cleanup':return
            # Independently reconstruct the exact manifests, not just trust rows.
            expected=[]
            for mf in self.manifests:
                pins=[]
                for doc,batch in self.batches.items():
                    pin=source_pin(batch,source_id=doc,website_id=self.websites[doc])
                    if mf.lane==Lane.LEGACY_CONTROL:
                        pin=pin.model_copy(update={'entries':(),'legacy_members':tuple(c['id'] for c in self.legacy_chunks[doc]),
                            'batch_hash':digest(self.legacy_chunks[doc])})
                    pins.append(pin)
                expected.append(self.manifest(pins,run=self.run_id,lane=mf.lane))
            self.manifests=tuple(expected)
            try:
                with self.repository() as repo:
                    validate(repo,self.manifests,expected_hash=self.identity_hash,frozen_identity=self.frozen_identity(),
                        query_hashes=self.query_hashes(),now=int(time()))
            except CanaryError as exc:
                if str(exc) in ('STALE_SOURCE_EPOCH','STALE_OR_INELIGIBLE_SOURCE','SOURCE_SNAPSHOT_MISMATCH'):
                    with self.repository() as repo:
                        mark(repo,self.manifests[0],'STALE')
                        repo.transition(self.manifests[0],State.STALE,now=int(time()))
                raise
            self.control_ready=True
            # Validate every successful persisted receipt BEFORE any new spend.
            self.reconcile()
            self.provider_client()
        self.save('resume',dict(namespace=self.config.namespace,run_id=self.run_id,
            identity_hash=self.identity_hash,target_fingerprint=self.config.approval.database_identity,
            approval_reference=self.config.approval.operator_reference,retained_until=self.config.approval.expires_at,
            resume_requires_explicit_authorization=True))

    def all_items(self,mf):
        pins={p.scope.revision.source.document_id:p for p in mf.documents}
        return ([(pins[d],e.entry_key,e) for d,b in self.batches.items() for e in b.entries]
                if mf.lane==Lane.STRUCTURAL_CANARY else
                [(pins[d],c['id'],c) for d,rows in self.legacy_chunks.items() for c in rows])

    def reconcile(self):
        for mf in self.manifests:
            items=self.all_items(mf)
            for offset in range(0,len(items),100):
                group=items[offset:offset+100]
                with self.timing.stage('vector_persistence_readback'),self.repository() as repo:
                    states,receipts=repo.completed(mf,group)
                self.resume_reused+=len(receipts)
                for pin,key,item in group:
                    if (pin.scope.revision.source.document_id,key) in receipts:
                        self.receipt_index[exact_input_hash(item_text((pin,key,item)))]=(mf,pin,key,item_text((pin,key,item)))
        self.result['resumed_reuse']=self.resume_reused
        with self.timing.stage('vector_persistence_readback'),self.repository() as repo:
            mf=self.manifests[0]
            for row in repo.conn.execute(select(s.query_work).where(where(s.query_work,run_values(mf)),
                    s.query_work.c.state=='succeeded')).mappings():
                r=Attestation(mf.approval.organization_id,mf.approval.bot_id,row['input_hash'],row['profile_hash'],
                    row['vector_hash'],canonicalize_vector_f32(row['embedding']),row['provider_receipt']['provider_attempt'])
                require(row['profile_hash']==mf.profile.canonical_hash() and canonical_vector_digest(r.vector)==r.vector_hash
                    and row['provider_receipt']==receipt_payload(r,self.authorization),'QUERY_RECEIPT_CORRUPTION')

    def store_batch(self,mf,items,*,retries):
        with self.timing.stage('work_ledger'),self.repository() as repo:
            states,completed=repo.completed(mf,items)
            pending=[v for v in items if states[(v[0].scope.revision.source.document_id,v[1])]['state']=='pending']
            unknown=[v for v in items if states[(v[0].scope.revision.source.document_id,v[1])]['state'] in ('unknown','failed')]
            if unknown:
                grant=digest([dict(lane=mf.lane.value,document=p.scope.revision.source.document_id,key=k,
                    input_hash=exact_input_hash(item_text((p,k,v)))) for p,k,v in unknown])
                self.result['unknown_batch_hash']=grant
                authorize_unknown(repo,mf,unknown,approved_batches=self.approved_batches,
                    reference=self.spend_reference,session_id=self.session_id)
                # Failed is not currently produced by this runner; do not reset it.
                require(all(states[(p.scope.revision.source.document_id,k)]['state']=='unknown'
                    for p,k,_ in unknown),'FAILED_WORK_REQUIRES_REVIEW')
            if pending:repo.begin_attempt(mf,pending,now=int(time()))
        todo=pending+unknown
        if not todo:return
        reusable=[];fresh=[]
        with self.timing.stage('vector_persistence_readback'),self.repository() as repo:
            for item in todo:
                ih=exact_input_hash(item_text(item));locator=self.receipt_index.get(ih)
                if locator:
                    old,pin,key,value=locator
                    receipt=repo.persisted_receipt(old,pin,key,value)
                    reusable.append((item,receipt));self.reused_persisted+=1
                else:fresh.append(item)
            if reusable:repo.persist(mf,[v[0] for v in reusable],[v[1] for v in reusable],now=int(time()))
        if fresh:
            # Publish the exact operator spend-grant identity before HTTP. Use
            # original work order, which the frozen build will replay on resume.
            fresh_keys={(p.scope.revision.source.document_id,k) for p,k,_ in fresh}
            failed_group=[v for v in items if (v[0].scope.revision.source.document_id,v[1]) in fresh_keys]
            self.result['unknown_batch_hash']=digest([dict(lane=mf.lane.value,
                document=p.scope.revision.source.document_id,key=k,input_hash=exact_input_hash(item_text((p,k,v))))
                for p,k,v in failed_group])
            self.result['unknown_batch_items']=len(failed_group)
            before=len(self.provider.attempts)
            with self.timing.stage('provider_wait'):
                receipts=self.provider.embed([item_text(v) for v in fresh],purpose='evidence',retries=retries)
            with self.timing.stage('vector_persistence_readback'),self.repository() as repo:
                repo.persist(mf,fresh,receipts,now=int(time()),attempts=max(1,len(self.provider.attempts)-before))
            self.save(f'batch-{self.session_id}-{len(self.provider.attempts):04d}',dict(result='PERSISTED',items=[vector_summary(v) for v in receipts]))
            self.result.pop('unknown_batch_hash',None);self.result.pop('unknown_batch_items',None)
        for pin,key,item in todo:
            ih=exact_input_hash(item_text((pin,key,item)))
            self.receipt_index[ih]=(mf,pin,key,item_text((pin,key,item)))
            self.provider.ledger.pop((*self.provider.scope,ih,self.provider.profile.canonical_hash()),None)

    def seal(self,mf):
        if self.pair_published:return 0
        start=perf_counter()
        # Publication of the paired build is atomic; a failed second seal rolls
        # back the first rather than leaving one readable partial pair.
        with self.timing.stage('seal'),self.repository() as repo:
            for lane in self.manifests:
                if repo._manifest(lane)['state']=='EMBEDDING_STAGING':
                    repo.seal_generation(lane,expected_build_identity=repo.build_identity(lane),now=int(time()))
            for lane in self.manifests:
                if repo._manifest(lane)['state']=='INDEX_READY':repo.transition(lane,State.CANARY_READ,now=int(time()))
                repo.read_gate(lane,self.hard(lane),now=int(time()))
        self.pair_published=True
        return (perf_counter()-start)*1000

    def embed_query(self,query):
        mf=self.manifests[0];ih=exact_input_hash(query)
        key=dict(**run_values(mf),input_hash=ih)
        with self.timing.stage('work_ledger'),self.repository() as repo:
            # Both lanes must be sealed before ANY query-provider work.
            for lane in self.manifests:repo.read_gate(lane,self.hard(lane),now=int(time()))
            row=repo.conn.execute(select(s.query_work).where(where(s.query_work,key)).with_for_update()).mappings().one()
            require(row['profile_hash']==mf.profile.canonical_hash(),'QUERY_PROFILE_MISMATCH')
            if row['state']=='succeeded':
                r=Attestation(mf.approval.organization_id,mf.approval.bot_id,ih,row['profile_hash'],row['vector_hash'],
                    canonicalize_vector_f32(row['embedding']),row['provider_receipt']['provider_attempt'])
                require(canonical_vector_digest(r.vector)==r.vector_hash and row['provider_receipt']==receipt_payload(r,self.authorization),
                    'QUERY_RECEIPT_CORRUPTION')
                return r
            if row['state']=='unknown':
                grant=digest(dict(purpose='query',input_hash=ih,profile=row['profile_hash']))
                self.result['unknown_batch_hash']=grant
                require(grant in self.approved_batches and self.spend_reference,'UNKNOWN_QUERY_EXPLICIT_GRANT_REQUIRED')
                repo.conn.execute(insert(s.spend_grants).values(**run_values(mf),batch_hash=grant,
                    approval_reference=self.spend_reference,session_id=self.session_id))
            else:repo.conn.execute(update(s.query_work).where(where(s.query_work,key)).values(state='unknown'))
        with self.timing.stage('provider_wait'):r=self.provider.embed([query],purpose='query',retries=2)[0]
        with self.timing.stage('vector_persistence_readback'),self.repository() as repo:
            repo.conn.execute(update(s.query_work).where(where(s.query_work,key),s.query_work.c.state=='unknown')
                .values(state='succeeded',embedding=list(r.vector),vector_hash=r.vector_hash,provider_receipt=receipt_payload(r,self.authorization)))
            row=repo.conn.execute(select(s.query_work).where(where(s.query_work,key))).mappings().one()
            require(canonicalize_vector_f32(row['embedding'])==r.vector and canonical_vector_digest(row['embedding'])==r.vector_hash,
                'QUERY_PGVECTOR_ROUNDTRIP_MISMATCH')
        self.provider.ledger.pop((*self.provider.scope,ih,self.provider.profile.canonical_hash()),None)
        return r

    def counts(self):
        with self.db.transaction() as conn:
            result={}
            for table in (s.work,s.legacy_work,s.query_work):
                result[table.name]={state:count for state,count in conn.execute(select(table.c.state,func.count())
                    .where(where(table,run_values(self.manifests[0]))).group_by(table.c.state))}
            return result

    def run(self):
        start=perf_counter();completed=False
        try:
            self.setup()
            if self.mode=='cleanup':
                self.result.update(decision='C',stage='EXPLICIT_OWNED_CLEANUP');completed=True
            else:
                self.result['p2']='BUILDING'
                for mf in self.manifests:self.build(mf,self.all_items(mf))
                self.result['p2']='BUILT'
                with self.timing.stage('query_evaluation'):
                    self.evaluate_paired(self.manifests[0],self.manifests[1],start)
                with self.repository() as repo:mark(repo,self.manifests[0],'COMPLETE')
                completed=True
        except Exception as exc:
            self.result.update(decision='C',failure=safe_failure(exc))
            if isinstance(exc,ProviderHold):self.result['provider_failure']=exc.diagnostic
            if self.control_ready:
                # Recovery/safety failures retain evidence for inspection too.
                # Never convert a terminal STALE run back into provider hold.
                try:
                    with self.db.transaction() as conn:
                        repo=RecoveryRepository(conn,self.config.approval,authorization=self.authorization)
                        old=conn.execute(select(s.recovery.c.condition).where(where(s.recovery,run_values(self.manifests[0])))).scalar_one()
                        if old!='STALE':mark(repo,self.manifests[0],'PROVIDER_HOLD' if isinstance(exc,ProviderHold) else 'PAUSED')
                except Exception as state_error:self.result['hold_record_failure']=safe_failure(state_error)
        finally:
            if self.provider is not None:
                self.result['provider']=dict(self.provider.metrics,requests=len(self.provider.attempts),
                    reused_persisted=self.reused_persisted,resumed_reuse=self.resume_reused,
                    elapsed_call_ms=sum(v.get('duration_ms',0) for v in self.provider.attempts),cost='UNKNOWN')
                try:self.provider.close()
                except Exception as close_error:self.result.update(decision='C',provider_close=safe_failure(close_error))
            if self.db is not None:
                try:
                    if self.control_ready:self.result['persisted_counts']=self.counts()
                    if completed or (self.mode=='fresh' and not self.control_ready):
                        with self.timing.stage('cleanup'):self.result['cleanup']=self.db.cleanup()
                    elif self.db.created:
                        self.result['retained']=dict(namespace=self.config.namespace,run_id=self.run_id,
                            identity_hash=self.identity_hash,retained_until=self.config.approval.expires_at,
                            automatic_resume=False,partial_read_allowed=False)
                except Exception as exc:self.result.update(decision='C',cleanup=safe_failure(exc))
                finally:
                    try:
                        if self.lock is not None:self.lock.close()
                    except Exception as close_error:self.result.update(decision='C',lock_close=safe_failure(close_error))
                    finally:self.db.close()
            for key in ('CANARY_DATABASE_URL','CANARY_REAL_EMBEDDING_AUTHORIZED','CANARY_APPROVAL_REFERENCE',
                    'CANARY_ENVIRONMENT','CANARY_TARGET_FINGERPRINT','CANARY_RESUME_AUTHORIZED'):
                self.env.pop(key,None)
            self.result['elapsed_ms']=(perf_counter()-start)*1000
            self.result['timing']=self.timing.summary()
            self.save('result-'+self.session_id,self.result);emit(self.result)
        return 0 if self.result['decision'] in ('A','B') or (self.mode=='cleanup' and completed) else 1


def main():
    logging.disable(logging.CRITICAL)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('fresh','resume','cleanup'))
    parser.add_argument('--namespace');parser.add_argument('--run-id',default='paired-real')
    parser.add_argument('--identity-hash');parser.add_argument('--retry-batch',action='append',default=[])
    parser.add_argument('--spend-reference');parser.add_argument('--deadline-minutes',type=int,default=300)
    args=parser.parse_args()
    try:
        return RecoveryRunner(Path(__file__).resolve().parents[2],os.environ,mode=args.mode,
            namespace=args.namespace,run_id=args.run_id,identity_hash=args.identity_hash,
            approved_batches=args.retry_batch,spend_reference=args.spend_reference,deadline_minutes=args.deadline_minutes).run()
    except Exception as exc:
        # Last-resort redaction even if a local artifact/cleanup sink itself fails.
        emit(dict(decision='C',failure=safe_failure(exc)))
        return 1
    finally:
        for key in ('CANARY_DATABASE_URL','CANARY_REAL_EMBEDDING_AUTHORIZED','CANARY_APPROVAL_REFERENCE',
                    'CANARY_ENVIRONMENT','CANARY_TARGET_FINGERPRINT','CANARY_RESUME_AUTHORIZED'):
            os.environ.pop(key,None)


if __name__=='__main__':raise SystemExit(main())
