"""Offline fresh-process recovery fixture; never constructs a real SDK client.

Explicit SQLite file under a test-owned temporary directory only. Mock receipts
are not real-provider acceptance; the PostgreSQL harness separately proves the
same persistence/guard boundary with mocked responses.
"""
import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
from sqlalchemy import create_engine,event,insert,select,update
from database import canary_schema as s
from scripts.canary_stage_a import approval,fixture_batch,make_manifest,NOW
from scripts.canary_gemini_embeddings import real_profile,configuration
from scripts.canary_provider_recovery import RecoverableGemini,ProviderHold
from scripts.canary_real_repository import RealAuthorization
from scripts.canary_recovery_repository import RecoveryRepository
from scripts.canary_recovery_state import initialize,validate,record_attempt,authorize_unknown,mark
from services.canary_contracts import Manifest,Lane,State,CanaryError
from services.canary_representation import exact_input_hash
from services.canary_repository import run_values,where
from services.structural_chunking import digest
from google.genai import errors


def engine_for(path):
    engine=create_engine('sqlite+pysqlite:///'+str(path),hide_parameters=True)
    @event.listens_for(engine,'connect')
    def fk(dbapi,_):dbapi.execute('PRAGMA foreign_keys=ON')
    return engine


def auth(a):return RealAuthorization(a.operator_reference,a.organization_id,a.bot_id,real_profile().configuration_hash)


def fixture_init(engine,count=100):
    s.metadata.create_all(engine)
    a=approval().model_copy(update={'environment':'disposable_test','created_at':NOW,'expires_at':NOW+86400})
    chunks=[dict(id=i,text=f'Exact mock work unit {i}.') for i in range(1,count+1)]
    with engine.begin() as conn:
        conn.execute(insert(s.marker).values(database_identity=a.database_identity,marker=a.ownership_marker,environment=a.environment))
        repo=RecoveryRepository(conn,a,authorization=auth(a),clock=lambda:NOW)
        batch=fixture_batch('# Guide\n\nA bounded source statement.')
        p=repo.register_fixture_source(batch,source_id=1).model_copy(update={'entries':(),
            'legacy_members':tuple(c['id'] for c in chunks),'batch_hash':digest(chunks)})
        mf=Manifest(**(make_manifest((p,),approved=a,lane=Lane.LEGACY_CONTROL).model_dump()|
            {'profile':real_profile(),'embedding_configuration':configuration()}))
        repo.create(mf,now=NOW);repo.stage_legacy_work(mf,p,chunks,now=NOW)
        ident=initialize(repo,(mf,),frozen_identity={'fixture':digest(chunks)},owned={},query_hashes=[],now=NOW)
    return mf,digest(ident)


def fixture_step(engine,*,fail_at=None,approve=False,crash_after=None,crash_started=False,now=NOW,expected_hash=None):
    import uuid
    session=uuid.uuid4().hex
    with engine.begin() as conn:
        mf=Manifest.model_validate(conn.execute(select(s.manifests.c.payload)).scalar_one())
        a=mf.approval;pin=mf.documents[0]
        identity_hash=conn.execute(select(s.recovery.c.identity_hash)).scalar_one()
        chunks=[dict(id=i,text=f'Exact mock work unit {i}.') for i in pin.legacy_members]
        repo=RecoveryRepository(conn,a,authorization=auth(a),clock=lambda:now)
        validate(repo,(mf,),expected_hash=expected_hash or identity_hash,
            frozen_identity={'fixture':digest(chunks)},query_hashes=[],now=now)
        items=[(pin,c['id'],c) for c in chunks]
        states,done=repo.completed(mf,items)
    records=[]
    def sink(record):
        with engine.begin() as conn:
            record_attempt(RecoveryRepository(conn,a,authorization=auth(a),clock=lambda:now),mf,session,record)
        records.append(record)
    client=Mock()
    def response(**kw):
        if crash_started:os._exit(24)
        return NS(embeddings=[NS(values=[(int(digest(t)[:6],16)%1000+1)/1000]+[.125]*767,
            statistics=None) for t in kw['contents']])
    client.models.embed_content.side_effect=response
    provider=RecoverableGemini('offline-fake',organization_id=a.organization_id,bot_id=a.bot_id,
        approved=True,client_factory=Mock(return_value=client),on_attempt=sink,pause=lambda _:None)
    reused=len(done)
    try:
        for item in items:
            pin,key,value=item
            if (pin.scope.revision.source.document_id,key) in done:continue
            with engine.begin() as conn:
                repo=RecoveryRepository(conn,a,authorization=auth(a),clock=lambda:now)
                state=repo.work_state(mf,pin,key)
                if state['state']=='unknown':
                    batch=digest([dict(lane=mf.lane.value,document=pin.scope.revision.source.document_id,
                        key=key,input_hash=exact_input_hash(value['text']))])
                    authorize_unknown(repo,mf,[item],approved_batches={batch} if approve else set(),
                        reference='fixture-'+session,session_id=session)
                else:repo.begin_attempt(mf,[item],now=now)
            if key==fail_at:client.models.embed_content.side_effect=errors.ServerError(503,{'message':'redacted'})
            before=len(provider.attempts)
            receipts=provider.embed([value['text']],purpose='evidence',retries=2)
            with engine.begin() as conn:
                repo=RecoveryRepository(conn,a,authorization=auth(a),clock=lambda:now)
                repo.persist(mf,[item],receipts,now=now,attempts=len(provider.attempts)-before)
            if key==crash_after:os._exit(23)
        with engine.begin() as conn:
            repo=RecoveryRepository(conn,a,authorization=auth(a),clock=lambda:now)
            repo.seal_generation(mf,expected_build_identity=repo.build_identity(mf),now=now)
            repo.transition(mf,State.CANARY_READ,now=now)
        return dict(result='SEALED',resumed_reuse=reused,new=provider.metrics['new_vectors'])
    except ProviderHold:
        with engine.begin() as conn:mark(RecoveryRepository(conn,a,authorization=auth(a),clock=lambda:now),mf,'PROVIDER_HOLD')
        return dict(result='HOLD',resumed_reuse=reused,new=provider.metrics['new_vectors'])
    finally:provider.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('path');p.add_argument('--fail-at',type=int)
    p.add_argument('--approve',action='store_true');p.add_argument('--crash-after',type=int)
    p.add_argument('--crash-started',action='store_true');args=p.parse_args()
    engine=engine_for(Path(args.path))
    try:
        result=fixture_step(engine,fail_at=args.fail_at,approve=args.approve,
            crash_after=args.crash_after,crash_started=args.crash_started)
        print(json.dumps(result));return 0
    except CanaryError as exc:
        print(json.dumps({'guard':str(exc)}));return 1
    finally:engine.dispose()


if __name__=='__main__':raise SystemExit(main())
