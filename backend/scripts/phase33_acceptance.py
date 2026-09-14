"""Phase 3.3 fail-fast acceptance using the unchanged Phase 3.1 remote guards.

One owned bulk fixture, real SQL channels/retrieval, synthetic vectors only.
Import application modules only inside isolated_application_imports in main.
No environment values or raw exception strings are emitted.
"""
import os
import re
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker
from scripts import phase31_acceptance as prior
from scripts import phase31_fixture as data

GAPS = (1, 2, 3, 10)
# Frozen offline states after unrelated development and held-out validation.
FROZEN_FOUR = {
    1: ('incomplete_comparison', 'discovery_required', [3002]),
    2: ('ambiguous', 'clarification_required', []),
    3: ('resolved_single', 'exact_scoped', [3004]),
    10: ('unresolved', 'discovery_required', []),
}


def augmented_documents():
    """Keep historical/612 fixtures intact; replace only late scale filler rows."""
    from test_resource_semantic_gaps import resource_rows
    rows = data.documents()
    additions = []
    for row in resource_rows():
        additions.append(dict(id=row['id'], organization_id=29, bot_id=30,
            title=row['title'], filename='source.txt', source_type='txt',
            canonical_url=f"https://synthetic.test/gap/{row['id']}", status='ready',
            processing_status='completed', version=1, crawl_id=None,
            metadata_json=row['metadata']))
    assert all(r['id'] > 100020 for r in rows[-len(additions):])
    return rows[:-len(additions)] + additions


def golden_record(f, number):
    question, expected, kind = data.GOLDEN[number-1]
    start = perf_counter()
    c = f.contract(question)
    soft = c.execution.soft_scope
    selected = sorted(soft.resolved_document_ids)
    candidates = sorted({d for a in soft.resource_candidates for d in a.resource.document_ids})
    exact = c.execution.scope_decision.exact_narrowing_applied
    original = (set(expected) <= set(candidates) and not exact if kind == 'category' else
                c.requires_clarification and not selected if kind == 'ambiguous' else
                not selected if kind == 'unresolved' else set(selected) == set(expected))
    # Do not erase the old oracle. Accept only candidate-backed semantic gaps or
    # explicit absence of an ordering contract, never a guessed middle resource.
    reviewed = original
    if number in (1, 2):
        reviewed = (not exact and not (set(selected) - set(expected)) and
                    'query_optimizer_eligible' in soft.reason_codes)
    elif number == 10:
        reviewed = not selected and not exact and 'structured_relation_required' in soft.reason_codes
    row = dict(id=number, question=question, original_expected=list(expected), original_kind=kind,
        original_ok=bool(original), reviewed_ok=bool(reviewed), selected=selected, candidates=candidates,
        state=soft.state.value, scope=c.execution.scope_decision.strategy.value,
        reasons=soft.reason_codes, ms=(perf_counter()-start)*1000,
        trace=c.execution.resource_discovery,
        leaks=sum(a.resource.organization_id!=f.hard.organization_id or a.resource.bot_id!=f.hard.bot_id
                  for a in soft.resource_candidates))
    row['frozen_match'] = number not in GAPS or (row['state'], row['scope'], selected) == FROZEN_FOUR[number]
    return row


def require(condition, name):
    if not condition:
        raise GateFailure(name)


class GateFailure(RuntimeError):
    pass


def natural_gates(engine, result):
    from test_resource_semantic_gaps import cases, record
    with Session(engine) as db:
        f = prior.fixture(db, 3, 4)
        former = []
        for number in GAPS:
            row = golden_record(f, number)
            former.append(row)
            prior.emit('former_four_case', row)
        result['former_four'] = former
        require(all(r['reviewed_ok'] and r['frozen_match'] and not r['leaks'] for r in former), 'former_four')
        # Both arbitrary JSON ordering and absent ordering remain relation-only.
        f = prior.fixture(db, 29, 30)
        unrelated = []
        for case in cases():
            if int(case.key.split('-')[1]) in (1, 2, 4, 9, 10):
                row = record(case, f.contract(case.question))
                unrelated.append(row)
                prior.emit('unrelated_case', row)
        result['unrelated'] = unrelated
        require(len(unrelated)==40 and all(r['pass_'] and not r['leaks'] and not r['false_confident'] for r in unrelated), 'unrelated_natural')
        f = prior.fixture(db, 3, 4)
        by_id = {r['id']:r for r in former}
        golden = []
        for number in range(1, 51):
            row = by_id.get(number)
            if row is None:
                row = golden_record(f, number)
                prior.emit('golden_case', row)
            golden.append(row)
        result['golden'] = golden
        require(all(r['reviewed_ok'] and not r['leaks'] for r in golden), 'reviewed_fifty')


def handoffs(engine, result):
    from services import rag_service as rag
    from services.observability_service import ChatTrace
    from database.resource_models import KnowledgeResource as Resource
    from test_resource_semantic_gaps import cases, resource_rows
    sessions = sessionmaker(bind=engine)
    sentinel = 'UNSUPPORTED SUMMARY: invented factual answer'
    # Synthetic fixture only, one transaction. No new schema or customer facts.
    with sessions() as db:
        db.query(Resource).filter(Resource.organization_id==29,Resource.bot_id==30,
            Resource.id.in_([r['id'] for r in resource_rows()])).update({Resource.summary:sentinel},synchronize_session=False)
        db.commit()
    rows = []
    with patch.object(rag,'SessionLocal',sessions), patch.object(rag,'generate_embedding',return_value=data.vector()), \
         patch.object(rag,'resolve_active_embedding_profile',return_value=SimpleNamespace(
             provider='gemini',model='gemini-embedding-001',version=1,dimensions=768)), \
         patch.dict(os.environ,{'RAG_LEXICAL_BACKEND':'postgres_fts','RAG_RESOURCE_DISCOVERY':'on'}):
        with sessions() as db:
            f = prior.fixture(db,29,30)
            for case in cases():
                if int(case.key.split('-')[1]) not in (3,4,5,6,7,14):
                    continue
                c = f.contract(case.question)
                require(not c.requires_clarification and set(c.permitted_document_ids or ())==set(case.expected), 'handoff_contract')
                trace = ChatTrace(30,'synthetic-phase33')
                chunks = rag.retrieve_relevant_chunks(db,30,c.retrieval_query,query_contract=c,trace=trace)
                evidence = prior.evidence_rows(chunks)
                ids = sorted({r['document_id'] for r in evidence})
                ok = set(ids)==set(case.expected) and sentinel not in str(evidence) and sentinel not in str(c.execution.resource_discovery)
                rows.append(dict(key=case.key,question=case.question,expected=case.expected,documents=ids,
                    passed=ok,evidence=evidence,trace=trace.to_debug_dict()))
                prior.emit('handoff_case',rows[-1])
                require(ok,'factual_handoff')
            # Existing historical fixture deliberately contradicts this summary.
            f = prior.fixture(db,3,4)
            c = f.contract('Show me Refund Policy.')
            require(not c.requires_clarification,'truth_contract')
            evidence = prior.evidence_rows(rag.retrieve_relevant_chunks(db,4,c.retrieval_query,query_contract=c))
            result['truth_separation'] = {'summary_not_fact':bool(evidence) and '90-day refund guarantee' not in str(evidence)}
            from services.resource_channels import ResourceProbe
            form=f.service.discover(db,f.hard,[ResourceProbe('Application Form')])
            result['truth_separation']['authorized_form_navigation']=bool(form.resolutions[0].candidate and
                form.resolutions[0].candidate.resource.url=='https://synthetic.test/3005')
    result['handoffs'] = rows
    require(len(rows)==48 and all(r['passed'] for r in rows) and all(result['truth_separation'].values()),'handoffs')


def performance(engine, result):
    """EXPLAIN execution is database time; service timing includes network/ORM."""
    from services.resource_channels import ResourceProbe, SQLResourceChannel
    from services.resource_scope_adapter import discovery_probes
    families = {
        'exact':['Laptop Repair Service'],
        'fts':['Repair Laptop Service'],
        'trigram':['Laptop Repiar Service'],
        'comparison':['Laptop Repair Service','Cobalt devices Advisory'],
        'natural_mixed':['Which service would I need if I want both website and database?'],
    }
    measured = {}
    with Session(engine) as db:
        f = prior.fixture(db,29,30)
        for name, questions in families.items():
            walls, executions, plans = [], [], []
            for _ in range(5):
                start = perf_counter()
                if name=='natural_mixed':
                    c=f.contract(questions[0]);probes=discovery_probes(c,{})
                else:
                    probes=tuple(ResourceProbe(q) for q in questions)
                    f.service.discover(db,f.hard,probes)
                walls.append((perf_counter()-start)*1000)
                sample=[]
                for p in probes:
                    # SQL channel plans only, not a claim of full service DB time.
                    for channel in ('exact','fts','trigram','metadata'):
                        variants=p.variants or (SimpleNamespace(text=p.text,provenance=p.provenance),)
                        for v in variants:
                            stmt=SQLResourceChannel(channel).statement(db,f.hard,ResourceProbe(v.text,v.provenance),32)
                            compiled=stmt.compile(dialect=engine.dialect,compile_kwargs={'render_postcompile':True})
                            plan=db.connection().exec_driver_sql('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+str(compiled),compiled.params).scalar()[0]
                            sample.append(plan)
                executions.append(sum(p['Execution Time'] for p in sample))
                if not plans: plans=sample
            measured[name]={'service_wall':prior.percentiles(walls),'channel_db_execution_sum':prior.percentiles(executions),'natural_plans':plans}
    result['performance']=measured
    prior.emit('performance',measured)


def run(engine, conn, result):
    # Construct once outside the patch to avoid recursion; the seed remains one
    # existing Core bulk insert pipeline, not a parallel projection architecture.
    docs=augmented_documents()
    result['stage']='migration_seed'
    with patch.object(data,'documents',return_value=docs): prior.setup(conn,result)
    require(result['migration_upgrade'],'migration_upgrade')
    result['stage']='sql_security';prior.sql_and_security(engine,result)
    require(len(result.get('sql_security_checks',{}))>=68 and all(result['sql_security_checks'].values()),'sql_security')
    result['stage']='natural_gates';natural_gates(engine,result)
    result['stage']='application_handoffs';handoffs(engine,result)
    result['stage']='generic_612';prior.benchmarks(engine,result)
    require(len(result.get('benchmark',{}))==2 and all(all(b['gates'].values()) for b in result['benchmark'].values()),'generic_612')
    result['stage']='concurrency_plans';prior.concurrency_and_plans(engine,conn,result)
    require(result['concurrency']['stable'] and result['concurrency']['leaks']==0 and result['concurrent_revision']['pass'],'concurrency')
    performance(engine,result)
    result['stage']='historical_last';prior.historical(engine,result)
    prior.emit('historical_last',result['historical'])
    require(result['historical']['pass'],'historical_last')
    result['stage']='migration_cycle';prior.cycle(conn,result)
    require(all(result.get(k) for k in ('migration_downgrade','migration_reupgrade','fixture_preserved_after_downgrade')),'migration_cycle')


def main():
    started=perf_counter();result={'stage':'preflight'};facts={};status=1
    try:
        with prior.isolated_application_imports(),prior.disposable_database() as (engine,conn,facts):
            prior.emit('preflight',facts)
            run(engine,conn,result)
        require(facts.get('cleanup',{}).get('schema_absent'),'cleanup')
        status=0
    except Exception as exc:
        result['failure']={'stage':result['stage'],'class':type(exc).__name__}
        if isinstance(exc,GateFailure) and re.fullmatch('[a-z_]+',str(exc)):
            result['failure']['gate']=str(exc)
        cause=getattr(exc,'orig',exc)
        result['failure']['sqlstate']=getattr(cause,'pgcode',None)
        status=2 if isinstance(exc,prior.DisposableUnavailable) else 1
    finally:
        os.environ.pop('PHASE3_TEST_DATABASE_URL',None)
        os.environ.pop('PHASE3_ALLOW_REMOTE_DISPOSABLE',None)
    summary={k:v for k,v in result.items() if k not in {'former_four','unrelated','golden','handoffs','benchmark','performance','natural_plans'}}
    summary.update(facts=facts,total_seconds=perf_counter()-started,status=status)
    summary['natural_summary']={key:{'total':len(result.get(key,[])),
        'passed':sum(r.get('reviewed_ok',r.get('pass_',r.get('passed',False))) for r in result.get(key,[]))}
        for key in ('former_four','unrelated','golden','handoffs')}
    summary['original_oracle']=sum(r['original_ok'] for r in result.get('golden',[]))
    summary['verdict']='PHASE 3 FULLY ACCEPTED — READY FOR PHASE 4' if status==0 else 'PHASE 3 NOT YET ACCEPTED'
    prior.emit('phase33_final',summary)
    return status


if __name__=='__main__':
    raise SystemExit(main())
