"""Real Phase 3.1 acceptance; no live embeddings, final model, or customer data."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from itertools import count
import os
import re
from time import perf_counter
from types import SimpleNamespace, MethodType
from unittest.mock import patch

from sqlalchemy import MetaData, text, select, event
from sqlalchemy.orm import Session, sessionmaker
from scripts.phase31_remote import disposable_database, register, DisposableUnavailable
from scripts.test_phase3_postgres import isolated_application_imports, migrate
from scripts.phase31_fixture import bulk_seed, GOLDEN, NATURAL, vector


_OUTPUT_EVENTS=count()


def emit(stage, data):
    # Large WriteConsoleW/ConPTY writes can lose their tail. Small, numbered JSON
    # frames retain complete evidence without writing telemetry/secrets to disk.
    serialized=json.dumps({"stage":stage,"data":data},default=str,ensure_ascii=True)
    if len(serialized)<=1800:
        print(serialized,flush=True)
        return
    pieces=[serialized[i:i+1200] for i in range(0,len(serialized),1200)]
    event_id=next(_OUTPUT_EVENTS)
    for i,piece in enumerate(pieces):
        print(json.dumps({"stage":stage,"event":event_id,"part":i,"parts":len(pieces),"fragment":piece}),flush=True)


def percentiles(values):
    values=sorted(values)
    if not values:
        return None
    def percentile(p):
        position=(len(values)-1)*p
        a=int(position)
        return values[a]+(values[min(a+1,len(values)-1)]-values[a])*(position-a)
    return {"count":len(values),"p50_ms":percentile(.5),"p95_ms":percentile(.95),"max_ms":values[-1]}


def evidence_rows(retrieved):
    """Read the existing nested ORM retrieval contract; never invent a flat DTO."""
    from services import rag_service as rag
    return [{"id":getattr(item["chunk"],"id",None),"document_id":rag._document_id(item),
             "content":rag._chunk_text(item)} for item in retrieved]


def fixture(db, org=1, bot=1, service=None):
    from database.models import Bot
    from test_resource_discovery import ResourceFixture
    from services.retrieval_contracts import HardKnowledgeScope, ProfileIdentity
    from services.resource_discovery import ResourceDiscoveryService
    f=SimpleNamespace(db=db,bot=db.get(Bot,bot),hard=HardKnowledgeScope(org,bot,embedding_profile=ProfileIdentity("gemini","gemini-embedding-001",1,768)),
                      service=service or ResourceDiscoveryService())
    f.contract=MethodType(ResourceFixture.contract,f)
    return f


def setup(conn, result):
    from database.connection import Base
    from database import models
    from database.resource_schema_v1 import TABLE_NAMES
    old=MetaData()
    for table in Base.metadata.tables.values():
        if table.name not in TABLE_NAMES:
            clone=table.to_metadata(old)
            for constraint in tuple(clone.constraints):
                if constraint.name in {"uq_bots_resource_tenant","uq_documents_resource_tenant"}:
                    clone.constraints.remove(constraint)
    old.create_all(conn)
    register(conn)
    conn.commit()
    migrate(conn,"upgrade")
    register(conn)
    conn.commit()
    result["migration_upgrade"]=all(conn.dialect.has_table(conn,name) for name in TABLE_NAMES)
    result["extensions"]=dict(conn.execute(text("SELECT extname,extversion FROM pg_extension WHERE extname IN ('pg_trgm','vector')")).all())
    result["indexes"]=dict(conn.execute(text("SELECT c.relname,i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND c.relname LIKE :p"),{"p":"ix_resource%"}).all())
    result["constraints"]=conn.execute(text("SELECT conname FROM pg_constraint WHERE connamespace=(SELECT oid FROM pg_namespace WHERE nspname=current_schema()) AND (conname LIKE :p OR conname IN ('uq_bots_resource_tenant','uq_documents_resource_tenant')) ORDER BY conname"),{"p":"%resource%"}).scalars().all()
    result["revision_triggers"]=conn.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgrelid IN (SELECT oid FROM pg_class WHERE relnamespace=(SELECT oid FROM pg_namespace WHERE nspname=current_schema())) ORDER BY tgname")).scalars().all()
    conn.commit()
    emit("migration_schema",result)
    result["fixture"]=bulk_seed(conn)
    # Actual accepted Phase 2 content index, separate from resource FTS. No ANN changes.
    conn.exec_driver_sql("CREATE INDEX ix_chunks_content_fts_en_v1 ON chunks USING gin (to_tsvector('english'::regconfig, coalesce(content,'')))")
    conn.exec_driver_sql("ANALYZE")
    register(conn)
    conn.commit()
    emit("bulk_seed",result["fixture"])


def sql_and_security(engine, result):
    from database.models import Document,Chunk,Website,WebsiteCrawl
    from database.resource_models import KnowledgeResource as Resource,KnowledgeResourceTerm as Term,KnowledgeResourceDocument as Link
    from services.resource_channels import SQLResourceChannel,ResourceProbe
    from services.resource_discovery import ResolutionState
    from services.resource_catalog import catalog_revision,ResourceCatalogProjector
    checks={}
    def check(name, value):
        checks[name]=bool(value)
    with Session(engine) as db:
        f=fixture(db)
        def discover(q,hard=None):
            return f.service.discover(db,hard or f.hard,[ResourceProbe(q)])
        def selected(q,hard=None):
            return {d for r in discover(q,hard).resolutions if r.candidate for d in r.candidate.resource.document_ids}
        result["fts_trigram_facts"]=dict(db.execute(text("""SELECT
            NOT (to_tsvector('simple','running') @@ plainto_tsquery('simple','run')) AS simple_not_stemmed,
            to_tsvector('simple','Silver Package') @@ plainto_tsquery('simple','Package Silver') AS reordered_fts,
            ts_rank_cd(to_tsvector('simple','Silver Package'),plainto_tsquery('simple','Silver')) AS fts_rank,
            similarity('silver package','the silver package extended') AS similarity,
            word_similarity('silver package','the silver package extended') AS word_similarity,
            strict_word_similarity('silver package','the silver package extended') AS strict_word_similarity,
            ('the silver package extended' %>> 'silver package') AS correct_operator_direction""")).mappings().one())
        check("simple_fts",result["fts_trigram_facts"]["simple_not_stemmed"] and result["fts_trigram_facts"]["reordered_fts"])
        check("trigram_operator_direction",result["fts_trigram_facts"]["correct_operator_direction"])
        for label,query in (("canonical","Cedar Meridian product"),("alias","Cedar Meridian Desk"),("unicode","Café Cedar 東京"),("numeric","Cedar Unit 2021")):
            check(label,selected(query)=={10})
        for label,query,channel in (("fts","Meridian Cedar","fts"),("partial","Cedar Meridian","fts"),
              ("typo","Cedar Meridan product","trigram"),("multi_typo","Cedax Meridiax product","trigram"),
              ("url","Cedar-Meridian-portal","metadata"),("breadcrumb","Directory Cedar Meridian","metadata")):
            batch=SQLResourceChannel(channel).search(db,f.hard,ResourceProbe(query),32)
            check(label,any(s.resource_id==10 for s in batch.signals))
        for query in ("Pro","Shared Desk","Cedar Common"):
            check("ambiguity_"+query,discover(query).resolutions[0].state==ResolutionState.AMBIGUOUS)
        for query in ("AI","HR","PDF","Form","Plan"):
            check("short_no_confident_"+query,not selected(query))
        for label,query in (("injection","'; DROP TABLE knowledge_resources; --"),("percent","%_"),("quote","Cedar ' Meridian"),
                           ("apostrophe","Cedar’s Meridian"),("slash","Cedar/Meridian/product"),("parentheses","Cedar (Meridian) product")):
            value=discover(query)
            check("parameterized_"+label,all(c.resource.organization_id==1 and c.resource.bot_id==1 for c in value.candidates))
        check("table_survives_special_input",db.query(Resource).count()==6000)
        check("organization_filter",not discover("Cedar Meridian product",replace(f.hard,organization_id=2)).candidates)
        check("empty_doc_scope",not discover("Cedar Meridian product",replace(f.hard,authorized_document_ids=())).candidates)
        check("stronger_same_name_foreign_rows",selected("Cedar Meridian product")=={10})
        result["tenant_violations"]=sum(c.resource.bot_id!=1 or c.resource.organization_id!=1 for c in discover("Cedar Meridian product").candidates)
        check("foreign_bot_authorized_itself",selected("Cedar Meridian product",replace(f.hard,bot_id=2))=={10001})
        check("foreign_org_authorized_itself",selected("Cedar Meridian product",replace(f.hard,bot_id=3,organization_id=2))=={20001})
        with db.begin_nested() as savepoint:
            doc=db.get(Document,10); chunk=db.get(Chunk,10)
            for obj,field,value in [(doc,"status",v) for v in ("processing","error","failed","deleted","superseded")]+[
                    (doc,"processing_status","pending"),(doc,"version",2),(chunk,"status","failed"),(chunk,"embedding_version",7)]:
                prior=getattr(obj,field);setattr(obj,field,value);db.flush()
                check("lifecycle_"+field+"_"+str(value),not discover("Cedar Meridian product").resolutions[0].candidate)
                setattr(obj,field,prior);db.flush()
            resource=db.get(Resource,11)
            resource.canonical_name="Cedar Meridian product"
            resource.normalized_canonical_name="cedar meridian product"
            term=db.query(Term).filter_by(resource_id=11,term_kind="canonical").one()
            term.term_text="Cedar Meridian product";term.normalized_term="cedar meridian product";db.flush()
            check("canonical_collision",not selected("Cedar Meridian product"))
            savepoint.rollback()
        with db.begin_nested() as savepoint:
            # A shared resource may have another authorized or restricted anchor.
            db.add(Link(organization_id=1,bot_id=1,resource_id=10,document_id=11,document_version=1))
            db.add(Term(organization_id=1,bot_id=1,resource_id=10,source_document_id=11,source_version=1,
                        term_text="Cedar Meridian product",normalized_term="cedar meridian product",term_kind="canonical",term_source="explicit"))
            db.flush()
            restricted=replace(f.hard,authorized_document_ids=(10,))
            answer=discover("Cedar Meridian product",restricted)
            check("authorized_link_intersection",answer.resolutions[0].candidate.resource.document_ids==(10,))
            ids={d for r in answer.trace()["resolutions"] for c in r["candidates"] for d in c["document_ids"]}
            check("restricted_anchor_not_in_trace",ids=={10})
            check("cache_hard_scope_bound",answer.cache_identity(restricted)!=answer.cache_identity(f.hard))
            db.get(Document,10).status="failed";db.flush()
            check("one_valid_anchor",selected("Cedar Meridian product")=={11})
            db.get(Document,11).status="failed";db.flush()
            check("all_anchors_invalid",not selected("Cedar Meridian product"))
            savepoint.rollback()
        with db.begin_nested() as savepoint:
            db.add(Website(id=900,bot_id=1,organization_id=1,root_url="https://synthetic.test",domain="synthetic.test",status="ready",active_crawl_id=900))
            db.flush()
            db.add(WebsiteCrawl(id=900,website_id=900,bot_id=1,organization_id=1,status="ready",version=1));db.flush()
            d=db.get(Document,10);c=db.get(Chunk,10)
            d.source_type="website";d.website_id=900;d.crawl_id=900;c.website_id=900;c.crawl_id=900
            db.query(Link).filter_by(document_id=10).update({"document_crawl_id":900})
            db.query(Term).filter_by(source_document_id=10).update({"source_crawl_id":900});db.flush()
            check("active_crawl",selected("Cedar Meridian product")=={10})
            check("source_restriction",not discover("Cedar Meridian product",replace(f.hard,authorized_source_ids=(901,))).candidates)
            db.get(Website,900).active_crawl_id=901;db.flush()
            check("stale_crawl",not selected("Cedar Meridian product"));savepoint.rollback()
        before=catalog_revision(db,f.hard)
        with db.begin_nested() as savepoint:
            def revised(label, mutate):
                prior=catalog_revision(db,f.hard);mutate();db.flush()
                check(label,catalog_revision(db,f.hard)>prior)
            revised("revision_insert_resource",lambda:db.add(Resource(organization_id=1,bot_id=1,source_key="synthetic-revision",canonical_name="Revision Sentinel",normalized_canonical_name="revision sentinel")))
            alias=Term(organization_id=1,bot_id=1,resource_id=10,source_document_id=10,source_version=1,
                       term_text="Revision Alias",normalized_term="revision alias",term_kind="alias",term_source="explicit")
            revised("revision_add_alias",lambda:db.add(alias))
            revised("revision_canonical_update",lambda:setattr(db.get(Resource,10),"canonical_name","Revision Label"))
            revised("revision_link_update",lambda:setattr(db.query(Link).filter_by(resource_id=10,document_id=10).one(),"relation_type","secondary"))
            revised("revision_delete_term",lambda:db.delete(alias))
            savepoint.rollback()
        check("revision_rollback",catalog_revision(db,f.hard)==before)
        p=ResourceCatalogProjector()
        with db.begin_nested() as savepoint:
            revision=catalog_revision(db,f.hard)
            check("projector_idempotent",p.project(db,f.hard,[10]).changed==0 and catalog_revision(db,f.hard)==revision)
            doc=db.get(Document,10)
            doc.metadata_json={**doc.metadata_json,"aliases":doc.metadata_json["aliases"]+["Synthetic New Alias"]};db.flush()
            check("projector_metadata_update",p.project(db,f.hard,[10]).changed==1 and selected("Synthetic New Alias")=={10})
            check("projector_second_run",p.project(db,f.hard,[10]).changed==0)
            check("projector_no_fuzzy_merge",db.get(Resource,10).id!=db.get(Resource,11).id)
            doc.status="failed";db.flush()
            check("projector_failed_source_excluded",p.project(db,f.hard,[10]).changed==0)
            savepoint.rollback()
        with db.begin_nested() as savepoint:
            for number in (10,11):
                doc=db.get(Document,number)
                doc.metadata_json={**doc.metadata_json,"resource_id":"shared-synthetic-source"}
            db.flush();p.project(db,f.hard,[10,11])
            shared=db.query(Link).filter(Link.document_id.in_((10,11))).all()
            check("projector_multiple_anchors",len(shared)==2 and len({link.resource_id for link in shared})==1)
            resource=db.get(Resource,shared[0].resource_id)
            check("projector_stable_explicit_key",resource.source_key.startswith("explicit:"))
            check("projector_navigation_type",resource.url=="https://synthetic.test/Cedar-Meridian-portal" and resource.resource_type=="product")
            check("projector_breadcrumb",resource.breadcrumb==["Directory Cedar Meridian"])
            revision=catalog_revision(db,f.hard)
            check("projector_shared_rerun",p.project(db,f.hard,[10,11]).changed==0 and catalog_revision(db,f.hard)==revision)
            db.get(Chunk,10).content="Customer text cannot insert the Imaginary Secret Alias into identity metadata.";db.flush()
            check("projector_body_not_identity",p.project(db,f.hard,[10,11]).changed==0 and not db.query(Term).filter(Term.normalized_term=="imaginary secret alias").first())
            savepoint.rollback()
        from sqlalchemy.exc import IntegrityError
        refused=False
        try:
            with db.begin_nested():
                db.add(Link(organization_id=1,bot_id=1,resource_id=10,document_id=10001,document_version=1));db.flush()
        except IntegrityError as error:
            refused=getattr(error.orig,"pgcode",None)=="23503"
        check("composite_foreign_anchor_refused",refused)
        statements=[]
        def count_sql(_conn,_cursor,statement,_parameters,_context,_many):
            statements.append(statement)
        event.listen(engine,"before_cursor_execute",count_sql)
        try:
            f.service.discover(db,f.hard,[ResourceProbe("Cedar Meridian product"),ResourceProbe("Linden Summit service")])
        finally:
            event.remove(engine,"before_cursor_execute",count_sql)
        check("two_probe_batched_hydration_no_n_plus_one",len(statements)==10)
        result["two_probe_sql_statement_count"]=len(statements)
        db.rollback()
    result["sql_security_checks"]=checks
    emit("sql_security",checks)


def benchmarks(engine,result):
    from services.resource_discovery import ResourceDiscoveryService
    from test_resource_discovery_benchmark import evaluate
    records=[]
    class MeasuredService(ResourceDiscoveryService):
        def discover(self,*args,**kwargs):
            start=perf_counter();answer=super().discover(*args,**kwargs)
            records.append({"ms":(perf_counter()-start)*1000,"probes":len(answer.resolutions),
                            "channels":answer.diagnostics})
            if len(records) % 100 == 0:
                emit("benchmark_progress",{"discovery_calls":len(records)})
            return answer
    with Session(engine) as db:
        f=fixture(db,service=MeasuredService())
        result["benchmark"]={}
        for split in ("development","heldout"):
            start=perf_counter()
            result["benchmark"][split]=evaluate(f,split)
            result["benchmark"][split]["elapsed_seconds"]=perf_counter()-start
            emit("benchmark_"+split,result["benchmark"][split])
    result["benchmark_discovery_latency"]=percentiles([r["ms"] for r in records])


def golden_and_handoff(engine,result):
    from services import rag_service as rag
    from services.observability_service import ChatTrace
    from services.resource_scope_adapter import discovery_probes
    from services.resource_discovery import ResolutionState
    from services.retrieval_contracts import ScopeStrategy
    SessionLocal=sessionmaker(bind=engine)
    results=[]
    # No response generation/embedding calls. Both SQL recall channels, RRF and
    # evidence selection remain real; only the external vector generator is replaced.
    with patch.object(rag,"SessionLocal",SessionLocal), patch.object(rag,"generate_embedding",return_value=vector()), \
         patch.dict(os.environ,{"RAG_LEXICAL_BACKEND":"postgres_fts","RAG_RESOURCE_DISCOVERY":"on"}):
        with SessionLocal() as db:
            f=fixture(db,3,4)
            for i,(question,expected,expectation) in enumerate(GOLDEN,1):
                start=perf_counter();contract=f.contract(question)
                diagnostic=contract.execution.resource_discovery
                soft=contract.execution.soft_scope
                selected=set(soft.resolved_document_ids)
                candidates={d for c in soft.resource_candidates for d in c.resource.document_ids}
                if expectation=="positive":
                    passed=selected==set(expected)
                elif expectation=="category":
                    passed=set(expected)<=candidates and not contract.execution.scope_decision.exact_narrowing_applied
                elif expectation=="ambiguous":
                    passed=soft.ambiguity and not selected
                else:
                    passed=not selected
                row={"id":i,"question":question,"expected":expected,"expectation":expectation,"pass":passed,
                     "state":soft.state.value,"selected_documents":sorted(selected),"candidate_documents":sorted(candidates),
                     "scope":contract.execution.scope_decision.strategy.value,"ms":(perf_counter()-start)*1000,
                     "probes":[p.text for p in discovery_probes(contract,{})],"trace":diagnostic}
                # At least 25 fixed representative positive/category requests;
                # execute handoff even when discovery underperformed (never fix scope).
                if i<=30 and expectation in {"positive","category"}:
                    trace=ChatTrace(bot_id=4,channel="synthetic_phase31")
                    start=perf_counter()
                    chunks=rag.retrieve_relevant_chunks(db,4,contract.retrieval_query,query_contract=contract,trace=trace)
                    evidence=evidence_rows(chunks)
                    ids={c["document_id"] for c in evidence}
                    factual=all("90-day refund guarantee" not in c["content"] for c in evidence)
                    row["handoff"]={"pass":set(expected)<=ids and factual,"document_ids":sorted(ids),
                        "chunks":evidence,
                        "factual_metadata_isolation":factual,"ms":(perf_counter()-start)*1000,
                        "hybrid":trace.retrieval.hybrid,"timings":trace.timings_ms}
                results.append(row)
                emit("golden",row)
            # Explicit metadata/factual split and navigation test independent of prose.
            from services.resource_channels import ResourceProbe
            discovered=f.service.discover(db,f.hard,[ResourceProbe("Refund Policy")])
            contract=f.contract("Tell me about Refund Policy.")
            chunks=rag.retrieve_relevant_chunks(db,4,contract.retrieval_query,query_contract=contract)
            form=f.service.discover(db,f.hard,[ResourceProbe("Application Form")])
            result["truth_separation"]={"discovery_succeeds":bool(discovered.resolutions[0].candidate),
                "summary_not_factual":bool(chunks) and all("90-day" not in c["content"] for c in evidence_rows(chunks)),
                "authorized_form_navigation":bool(form.resolutions[0].candidate and form.resolutions[0].candidate.resource.url=="https://synthetic.test/3005")}
    result["golden"]=results


def concurrency_and_plans(engine,conn,result):
    from services.resource_channels import ResourceProbe,SQLResourceChannel
    from services.resource_discovery import ResourceDiscoveryService
    from services.retrieval_contracts import HardKnowledgeScope
    from services.resource_catalog import catalog_revision
    from database.resource_models import KnowledgeResource as Resource
    families={"exact":[],"fts":[],"trigram":[],"multi":[],"mixed":[]}
    def read_case(i):
        org=4+i%20;bot=org+1;number=i%20
        names={"exact":[f"Atlas Sector {number} Reference"],"fts":[f"Sector Atlas {number}"],
               "trigram":[f"Atlas Secto {number} Reference"],"category":["custom"],
               "multi":[f"Atlas Sector {number} Reference",f"Atlas Registry {number}"]}
        family=list(names)[i%5]
        def run():
            with Session(engine) as db:
                start=perf_counter()
                answer=ResourceDiscoveryService().discover(db,HardKnowledgeScope(org,bot),
                    [ResourceProbe(n,"category" if family=="category" else "explicit_user") for n in names[family]])
                return {"ids":sorted(c.resource.resource_id for c in answer.candidates),
                        "leaks":sum(c.resource.organization_id!=org or c.resource.bot_id!=bot for c in answer.candidates),
                        "ms":(perf_counter()-start)*1000}
        first=run();second=run()
        return {"family":family,"first":first,"stable":first["ids"]==second["ids"],"leaks":first["leaks"]+second["leaks"]}
    start=perf_counter()
    with ThreadPoolExecutor(max_workers=20) as pool:
        reads=list(pool.map(read_case,range(20)))
    result["concurrency"]={"requests":20,"repeated_identity_checks":20,"elapsed_seconds":perf_counter()-start,
                           "leaks":sum(r["leaks"] for r in reads),"stable":all(r["stable"] for r in reads),"results":reads}
    with Session(engine) as db:
        hard=HardKnowledgeScope(4,5)
        before=catalog_revision(db,hard)
    def write_case(i):
        with Session(engine) as db:
            db.query(Resource).filter(Resource.id==100000,Resource.organization_id==4,Resource.bot_id==5).update({"version":Resource.version+1})
            db.commit()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write_case,range(8)))
    with Session(engine) as db:
        after=catalog_revision(db,HardKnowledgeScope(4,5))
    result["concurrent_revision"]={"writes":8,"revision_delta":after-before,"pass":after-before==16}
    plans={}
    with Session(engine) as db:
        f=fixture(db)
        for channel,q in (("exact","Cedar Meridian product"),("fts","Meridian Cedar"),("trigram","Cedar Meridan product"),
                          ("metadata","product")):
            stmt=SQLResourceChannel(channel).statement(db,f.hard,ResourceProbe(q,"category" if channel=="metadata" else "explicit_user"),32)
            compiled=stmt.compile(dialect=conn.dialect,compile_kwargs={"render_postcompile":True})
            plan=db.connection().exec_driver_sql("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "+str(compiled),compiled.params).scalar()[0]
            plans[channel]=plan
        for name,query,hard in (("authorized_join","Cedar Meridian product",replace(f.hard,authorized_document_ids=(10,))),
                                ("multi_member_1","Cedar Meridian product",f.hard),
                                ("multi_member_2","Linden Summit service",f.hard)):
            stmt=SQLResourceChannel("exact").statement(db,hard,ResourceProbe(query),32)
            compiled=stmt.compile(dialect=conn.dialect,compile_kwargs={"render_postcompile":True})
            plans[name]=db.connection().exec_driver_sql("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "+str(compiled),compiled.params).scalar()[0]
        for family,probes in (("exact",["Cedar Meridian product"]),("fts",["Meridian Cedar"]),
                             ("trigram",["Cedar Meridan product"]),("multi",["Cedar Meridian product","Linden Summit service"])):
            for _ in range(5):
                start=perf_counter();f.service.discover(db,f.hard,[ResourceProbe(q) for q in probes])
                elapsed=(perf_counter()-start)*1000;families[family].append(elapsed);families["mixed"].append(elapsed)
    result["natural_plans"]=plans
    result["latencies"]={k:percentiles(v) for k,v in families.items()}
    emit("concurrency_and_plans",{k:result[k] for k in ("concurrency","concurrent_revision","natural_plans","latencies")})


def historical(engine,result):
    from database.models import Document,Chunk
    from services.resource_catalog import ResourceCatalogProjector
    with Session(engine) as db:
        f=fixture(db,30,31)
        with db.begin_nested() as savepoint:
            for number,name in ((5129,"Turmeric Boost"),(5134,"Grass Fed Collagen Peptides Powder Chocolate")):
                db.add(Document(id=number,bot_id=31,organization_id=30,title=name,filename="source.txt",source_type="txt",status="ready",processing_status="completed",version=1,metadata_json={},canonical_url=f"https://synthetic.test/{number}"))
            db.flush()
            for number in (5129,5134):
                db.add(Chunk(id=number,document_id=number,bot_id=31,organization_id=30,chunk_index=0,content="Synthetic historical source only.",status="ready",embedding=vector(number)))
            db.flush();ResourceCatalogProjector().project(db,f.hard,[5129,5134]);db.flush()
            question="For joint comfort, would Turmeric Boost or the chocolate collagen give me a fair trial before the money-back guarantee runs out?"
            contract=f.contract(question)
            result["historical"]={"pass":set(contract.permitted_document_ids or ())=={5129,5134},
                                  "state":contract.execution.soft_scope.state.value,"documents":contract.permitted_document_ids}
            savepoint.rollback()


def cycle(conn,result):
    count=conn.execute(text("SELECT count(*) FROM documents")).scalar();conn.commit()
    migrate(conn,"downgrade");register(conn);conn.commit()
    result["migration_downgrade"]=not conn.dialect.has_table(conn,"knowledge_resources")
    result["fixture_preserved_after_downgrade"]=conn.execute(text("SELECT count(*) FROM documents")).scalar()==count
    conn.commit();migrate(conn,"upgrade");register(conn);conn.commit()
    result["migration_reupgrade"]=conn.dialect.has_table(conn,"knowledge_resources")
    conn.commit()


def accepted(result):
    return (all(result.get("sql_security_checks",{}).values()) and
        all(all(b["gates"].values()) for b in result.get("benchmark",{}).values()) and
        len(result.get("golden",[]))==50 and all(r["pass"] for r in result["golden"]) and
        sum("handoff" in r for r in result["golden"])>=25 and all(r["handoff"]["pass"] for r in result["golden"] if "handoff" in r) and
        all(result.get("truth_separation",{}).values()) and result.get("historical",{}).get("pass",False) and
        result.get("concurrency",{}).get("stable",False) and result["concurrency"]["leaks"]==0 and
        result.get("concurrent_revision",{}).get("pass",False) and
        all(result.get(k,False) for k in ("migration_upgrade","migration_downgrade","migration_reupgrade","fixture_preserved_after_downgrade")))


def main():
    started=perf_counter();result={};stage="preflight";facts={};status=1
    try:
        with isolated_application_imports(), disposable_database() as (engine,conn,facts):
            emit("preflight",facts)
            stage="migration_seed";setup(conn,result)
            stage="sql_security";sql_and_security(engine,result)
            stage="generic_benchmark";benchmarks(engine,result)
            stage="golden_handoff";golden_and_handoff(engine,result)
            stage="concurrency_plans";concurrency_and_plans(engine,conn,result)
            if all(result["sql_security_checks"].values()) and all(all(b["gates"].values()) for b in result["benchmark"].values()) and all(r["pass"] for r in result["golden"]):
                stage="historical_last";historical(engine,result)
            else:
                result["historical"]={"status":"NOT RUN: general/golden prerequisite did not pass"}
            stage="migration_cycle";cycle(conn,result)
        status=0 if accepted(result) else 1
    except Exception as exc:
        # Never serialize exception values/SQL parameters or connection strings.
        cause=exc
        while getattr(cause,"__context__",None) is not None:
            cause=cause.__context__
        result["failure"]={"stage":stage,"class":type(exc).__name__,"cause_class":type(cause).__name__,
                           "sqlstate":getattr(getattr(cause,"orig",cause),"pgcode",None)}
        diagnostic=getattr(getattr(cause,"orig",cause),"diag",None)
        if diagnostic is not None:
            result["failure"]["sql_identifiers"]={name:getattr(diagnostic,name) for name in ("table_name","column_name","constraint_name")
                if isinstance(getattr(diagnostic,name,None),str) and re.fullmatch(r"[a-zA-Z_][a-zA-Z_0-9]*",getattr(diagnostic,name))}
        # Only these fixed harness guard messages may be displayed. Never raw DB errors.
        if isinstance(exc,DisposableUnavailable) and str(exc) in {
            "Phase 3.1 required extension package unavailable; no software installation permitted",
            "Phase 3.1 empty-database guard refused existing user objects",
            "Phase 3.1 stale owned-schema guard refused target",
            "Phase 3.1 configured application target refused",
            "Phase 3.1 cleanup ownership changed; deletion refused",
            "Phase 3.1 cleanup marker changed; deletion refused",
            "Phase 3.1 external objects changed; cleanup refused",
            "Phase 3.1 extension ownership changed; cleanup refused",
            "Phase 3.1 cleanup verification failed"}:
            result["failure"]["guard"]=str(exc)
        status=2 if isinstance(exc,DisposableUnavailable) else 1
    finally:
        os.environ.pop("PHASE3_TEST_DATABASE_URL",None)
        os.environ.pop("PHASE3_ALLOW_REMOTE_DISPOSABLE",None)
    result["facts"]=facts;result["total_seconds"]=perf_counter()-started
    result["verdict"]="PHASE 3 REAL POSTGRESQL ACCEPTED" if status==0 else "PHASE 3 NOT YET ACCEPTED"
    # Detailed evidence was emitted once per stage; avoid an enormous duplicate
    # final record that can be truncated by a terminal/output collector.
    summary={k:v for k,v in result.items() if k not in {"golden","benchmark","natural_plans"}}
    summary["golden_summary"]={"total":len(result.get("golden",[])),
        "passed":sum(r["pass"] for r in result.get("golden",[])),
        "handoff_total":sum("handoff" in r for r in result.get("golden",[])),
        "handoff_passed":sum(r.get("handoff",{}).get("pass",False) for r in result.get("golden",[]))}
    emit("final",summary)
    return status


def recover_telemetry():
    """Recover lost terminal telemetry, NOT a substitute/full acceptance verdict.

    Quality records already captured from the full run remain authoritative.
    This executes only the missing measured stages against an identical fresh
    owned scale fixture. It cannot print PHASE 3 REAL POSTGRESQL ACCEPTED.
    """
    started=perf_counter();result={};facts={};status=1;stage="preflight"
    try:
        with isolated_application_imports(),disposable_database() as (engine,conn,facts):
            emit("preflight",facts)
            stage="migration_seed";setup(conn,result)
            stage="concurrency_plans";concurrency_and_plans(engine,conn,result)
            stage="migration_cycle";cycle(conn,result)
        status=0 if (result["migration_upgrade"] and result["migration_downgrade"] and result["migration_reupgrade"]
                     and result["fixture_preserved_after_downgrade"] and result["concurrency"]["stable"]
                     and result["concurrency"]["leaks"]==0 and result["concurrent_revision"]["pass"]
                     and facts.get("cleanup",{}).get("schema_absent")) else 1
    except Exception as error:
        result["failure"]={"stage":stage,"class":type(error).__name__}
    finally:
        os.environ.pop("PHASE3_TEST_DATABASE_URL",None)
        os.environ.pop("PHASE3_ALLOW_REMOTE_DISPOSABLE",None)
    result["facts"]=facts;result["total_seconds"]=perf_counter()-started
    result["telemetry_recovery_only"]=True;result["telemetry_success"]=status==0
    emit("telemetry_final",result)
    return status


if __name__=="__main__":
    raise SystemExit(main())
