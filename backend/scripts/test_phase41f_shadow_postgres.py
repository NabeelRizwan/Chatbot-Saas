"""Synthetic-only shadow lifecycle acceptance in the existing owned PG harness.

No application URL or providers. No snapshot/customer content. Secrets never enter
results. Reuses unchanged schema migration and ownership-checked RESTRICT cleanup.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import traceback
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from sqlalchemy.orm import Session
from scripts.phase31_remote import disposable_database, register
from scripts.test_phase3_postgres import isolated_application_imports
from scripts.test_phase41_structural_postgres import Checks, setup, seed_document
from database import structural_schema_v1 as schema
from services import structural_shadow as shadow
from services.structural_repository import StructuralScopeError, StructuralRepository, StorageScope

ROOT=Path(__file__).resolve().parents[2]


def run(engine, conn, checks, facts):
    from database.models import Document, IngestionJob
    def seed(doc,content='Useful synthetic instructions.',fmt='text'):
        seed_document(conn,doc)
        conn.execute(text('UPDATE documents SET source_type=:f,raw_text=:s WHERE id=:d'),{'f':fmt,'s':content,'d':doc})
        conn.execute(IngestionJob.__table__.insert().values(job_id=f'shadow-{doc}',organization_id=1,bot_id=1,document_id=doc,status='ready',audit_metadata={}))
        conn.commit()
        with Session(engine) as db:
            job=db.query(IngestionJob).filter(IngestionJob.job_id==f'shadow-{doc}').one()
            shadow.mark_pending(job,[{'document_id':doc,'version':1}]);db.commit()
    def result(doc):
        conn.rollback()
        row=conn.execute(text('SELECT audit_metadata FROM ingestion_jobs WHERE job_id=:j'),{'j':f'shadow-{doc}'}).scalar()
        conn.rollback()
        return row[shadow.AUDIT_KEY]['results'][str(doc)]
    def counts():
        data={t:conn.execute(text(f'SELECT count(*) FROM {t}')).scalar() for t in schema.TABLES}
        conn.rollback();return data
    def observe(doc): shadow.resume_shadow_job(engine,f'shadow-{doc}',1,1,doc)
    before=conn.execute(text('SELECT row_to_json(d) FROM documents d ORDER BY id')).scalars().all()
    chunks_before=conn.execute(text('SELECT row_to_json(c) FROM chunks c ORDER BY id')).scalars().all()
    catalog_before={t:conn.execute(text(f'SELECT count(*) FROM {t}')).scalar() for t in ('knowledge_resources','knowledge_resource_terms','resource_catalog_state')}
    conn.rollback()
    seed(101)
    observe(101)
    r=result(101)
    checks.check('real_shadow_success',r['status']=='validated')
    checks.check('real_source_capture',conn.execute(text('SELECT count(*) FROM document_versions WHERE document_id=101')).scalar()==1)
    checks.check('real_graph_staging',conn.execute(text('SELECT count(*) FROM structural_nodes WHERE document_id=101')).scalar()==r['nodes'])
    checks.check('validated_not_active',conn.execute(text("SELECT state FROM document_structure_revisions WHERE document_id=101")).scalar()=='validated')
    first_counts=counts();observe(101)
    checks.check('completed_event_idempotent',counts()==first_counts)
    with Session(engine) as db:
        job=db.query(IngestionJob).filter(IngestionJob.job_id=='shadow-101').one()
        shadow.mark_pending(job,[{'document_id':101,'version':1}]);db.commit()
    observe(101)
    checks.check('duplicate_build_no_graph_duplication',counts()==first_counts and result(101)['status']=='validated')
    checks.check('no_prospective_db_mappings',conn.execute(text('SELECT count(*) FROM chunk_structural_nodes WHERE document_id=101')).scalar()==0)
    checks.check('no_serving_pointer',conn.execute(text('SELECT active_structure_revision_id FROM documents WHERE id=101')).scalar() is None)
    conn.rollback()
    seed(102,'# Manual\n\n- First\n- Second','website')
    observe(102)
    checks.check('markdown_job_route',result(102)['parser_policy']=='markdown-structure-v1')
    seed(103)
    with patch.object(shadow,'build_shadow',side_effect=ValueError('private source details')):observe(103)
    checks.check('parser_failure_audited',result(103)['status']=='failed' and 'private' not in json.dumps(result(103)))
    checks.check('legacy_ready_after_shadow_failure',conn.execute(text("SELECT status FROM documents WHERE id=103")).scalar()=='ready')
    conn.rollback()
    seed(104)
    with patch.object(shadow,'build_shadow',side_effect=KeyboardInterrupt):
        try: observe(104)
        except KeyboardInterrupt: pass
    checks.check('crash_after_capture_pending',result(104)['status']=='running')
    observe(104);checks.check('restart_recovers',result(104)['status']=='validated')
    seed(105)
    # Race the actual production observer from two independent SQLAlchemy sessions.
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(observe,[105,105]))
    checks.check('duplicate_observer_race_success',result(105)['status']=='validated')
    checks.check('duplicate_observer_race_one_revision',conn.execute(text('SELECT count(*) FROM document_structure_revisions WHERE document_id=105')).scalar()==1)
    conn.rollback()
    seed(106)
    conn.execute(text("UPDATE ingestion_jobs SET cancellation_requested_at=now() WHERE job_id='shadow-106'"));conn.commit()
    observe(106);checks.check('cancelled_observer_not_active',result(106)['status']=='cancelled')
    seed(107)
    conn.execute(text("UPDATE documents SET version=2 WHERE id=107"));conn.commit()
    observe(107);checks.check('stale_source_refused',result(107)['failure_category']=='SOURCE_NOT_CURRENT_READY')
    # Repository checks remain authoritative even when a caller forges its DTO.
    s=shadow.ShadowSource(1,1,101,1,b'Useful synthetic instructions.','text','original')
    checks.rejects(conn,'foreign_org_capture_refused',lambda:shadow.capture_source(conn,replace(s,organization_id=2)),(StructuralScopeError,))
    checks.rejects(conn,'foreign_bot_capture_refused',lambda:shadow.capture_source(conn,replace(s,bot_id=2)),(StructuralScopeError,))
    conn.rollback()
    # New recipes create distinct builds without modifying the frozen recipe.
    s=replace(s,document_id=108);seed(108)
    b,_=shadow.build_shadow(s)
    shadow.persist_graph(conn,s,b);conn.commit()
    from services.structural_chunking import ChunkPolicy
    b2,_=shadow.build_shadow(s,chunk_policy=ChunkPolicy(max_chunks=9999))
    shadow.persist_graph(conn,s,b2);conn.commit()
    checks.check('changed_chunk_recipe_new_build',conn.execute(text('SELECT count(*) FROM document_structure_revisions WHERE document_id=108')).scalar()==2)
    conn.rollback()
    # Frozen repository-owned binary fixtures traverse the real isolated adapter.
    from scripts.evaluate_structural_docling_adapter import FIXTURES
    for doc,name in ((109,'workshop.docx'),(110,'workshop.pdf')):
        seed(doc)
        data=(FIXTURES/name).read_bytes()
        s=shadow.ShadowSource(1,1,doc,1,data,name.rsplit('.',1)[1],'original','synthetic-owned:'+name)
        b,t=shadow.build_shadow(s,model_cache=ROOT/'.codex_structural_4_1d/models')
        shadow.persist_graph(conn,s,b);conn.commit()
        checks.check('binary_'+name+'_validated',conn.execute(text('SELECT state FROM document_structure_revisions WHERE document_id=:d'),{'d':doc}).scalar()=='validated')
        facts[name]={'nodes':len(b.source_graph.nodes),'specs':len(b.chunks),'tokens':sum(c.token_count for c in b.chunks),**t}
        conn.rollback()
    checks.check('legacy_existing_documents_identical',conn.execute(text('SELECT row_to_json(d) FROM documents d WHERE id<100 ORDER BY id')).scalars().all()==before)
    checks.check('legacy_chunks_identical',conn.execute(text('SELECT row_to_json(c) FROM chunks c ORDER BY id')).scalars().all()==chunks_before)
    checks.check('catalog_unchanged',{t:conn.execute(text(f'SELECT count(*) FROM {t}')).scalar() for t in catalog_before}==catalog_before)
    checks.check('no_shadow_active_revisions',conn.execute(text("SELECT count(*) FROM document_structure_revisions WHERE document_id>=100 AND state='active'")).scalar()==0)
    conn.rollback()
    facts['shadow_results']=[result(d) for d in range(101,108)]


def closure(engine, conn, checks, facts):
    """Final-version lock/cancel/recipe closure, synthetic rows only."""
    from database.models import IngestionJob
    from services.structural_repository import StructuralScopeError
    seed_document(conn,201);seed_document(conn,202)
    for doc in (201,202):
        conn.execute(text("UPDATE documents SET source_type='text',raw_text='Synthetic final closure.' WHERE id=:d"),{'d':doc})
        conn.execute(IngestionJob.__table__.insert().values(job_id=f'closure-{doc}',organization_id=1,bot_id=1,document_id=doc,status='ready',audit_metadata={}))
    conn.commit()
    def pending(doc, version=1):
        with Session(engine) as db:
            job=db.query(IngestionJob).filter(IngestionJob.job_id==f'closure-{doc}').one()
            shadow.mark_pending(job,[{'document_id':doc,'version':version}]);db.commit()
    def observe(doc): shadow.resume_shadow_job(engine,f'closure-{doc}',1,1,doc)
    def result(doc):
        conn.rollback()
        audit=conn.execute(text('SELECT audit_metadata FROM ingestion_jobs WHERE job_id=:j'),{'j':f'closure-{doc}'}).scalar()
        conn.rollback();return audit[shadow.AUDIT_KEY]['results'][str(doc)]
    pending(201)
    actual=shadow.build_shadow
    def check_parse_locks(source, **kw):
        with engine.begin() as other:
            other.execute(text('SELECT id FROM documents WHERE id=:d FOR UPDATE NOWAIT'),{'d':source.document_id})
            other.execute(text('SELECT id FROM ingestion_jobs WHERE job_id=:j FOR UPDATE NOWAIT'),{'j':f'closure-{source.document_id}'})
        checks.check('parser_has_no_document_or_job_lock',True)
        return actual(source,**kw)
    with patch.object(shadow,'build_shadow',side_effect=check_parse_locks):observe(201)
    checks.check('final_runtime_validated',result(201)['status']=='validated')
    pending(201)
    with patch.object(shadow,'parser_signature',return_value='changed-parser-recipe'):observe(201)
    checks.check('changed_parser_recipe_new_build',conn.execute(text('SELECT count(*) FROM document_structure_revisions WHERE document_id=201')).scalar()==2)
    conn.execute(text("UPDATE documents SET version=2,raw_text='Changed synthetic final closure.' WHERE id=201"));conn.commit()
    pending(201,2);observe(201)
    checks.check('changed_source_version_new_capture',conn.execute(text('SELECT count(*) FROM document_versions WHERE document_id=201')).scalar()==2)
    checks.check('changed_source_version_new_revision',conn.execute(text('SELECT count(*) FROM document_structure_revisions WHERE document_id=201')).scalar()==3)
    conn.rollback()
    pending(202)
    audit=shadow._audit_result
    def race_cancel(db, job, org, bot, key, value):
        if value.get('status')=='validated':
            with engine.begin() as other:
                other.execute(text('UPDATE ingestion_jobs SET cancellation_requested_at=now() WHERE job_id=:j'),{'j':job})
        return audit(db,job,org,bot,key,value)
    with patch.object(shadow,'_audit_result',side_effect=race_cancel):observe(202)
    checks.check('cancel_at_commit_audited',result(202)['status']=='cancelled')
    checks.check('cancel_at_commit_graph_rolled_back',conn.execute(text('SELECT count(*) FROM document_structure_revisions WHERE document_id=202')).scalar()==0)
    checks.check('cancel_does_not_fail_legacy',conn.execute(text('SELECT status FROM documents WHERE id=202')).scalar()=='ready')
    checks.check('no_active_shadow_pointers',conn.execute(text('SELECT count(*) FROM documents WHERE id>=200 AND active_structure_revision_id IS NOT NULL')).scalar()==0)
    checks.check('no_shadow_chunk_rows',conn.execute(text('SELECT count(*) FROM chunks WHERE document_id>=200')).scalar()==0)
    conn.rollback()
    facts['closure_results']=[result(d) for d in (201,202)]


def main():
    checks=Checks();facts={};failure=None
    try:
        with isolated_application_imports(), patch.dict(os.environ,{'STRUCTURAL_INGESTION_MODE':'shadow','STRUCTURAL_SHADOW_ALLOWLIST':'1:1'}):
            with disposable_database() as (engine,conn,facts):
                try:
                    setup(conn,checks,facts)
                    if '--closure-only' in sys.argv:
                        closure(engine,conn,checks,facts)
                    else:
                        run(engine,conn,checks,facts)
                finally:
                    conn.rollback()
                    functions=conn.execute(text('SELECT proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=current_schema() AND proname=ANY(:names)'),{'names':list(schema.FUNCTIONS)}).scalars().all()
                    if functions:
                        if set(functions)!=set(schema.FUNCTIONS):raise RuntimeError('partial cleanup requires inspection')
                        schema.remove_triggers(conn);register(conn);conn.commit()
    except Exception as exc:
        origin=getattr(exc,'orig',exc)
        failure={'stage':checks.stage,'class':type(exc).__name__,'sqlstate':getattr(origin,'pgcode',None),
            'locations':[[Path(f.filename).name,f.lineno,f.name] for f in traceback.extract_tb(exc.__traceback__) if '.venv' not in f.filename]}
    print(json.dumps({'checks_passed':len(checks.passed),'checks':checks.passed,'failure':failure,'facts':facts},default=str),flush=True)
    return 1 if failure or not facts.get('cleanup',{}).get('schema_absent') else 0


if __name__=='__main__':raise SystemExit(main())
