"""Phase 4.1B synthetic PostgreSQL acceptance, using the unchanged owned harness.

Explicit PHASE3_ALLOW_REMOTE_DISPOSABLE=1 + PHASE3_TEST_DATABASE_URL required.
No application URL, providers, parser, saved corpus or live ingestion. Output
contains synthetic assertions/catalog plans only, never DSNs/raw DB exceptions.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import threading
import traceback
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import MetaData, Table, text, event
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from scripts.phase31_remote import disposable_database, register
from scripts.test_phase3_postgres import isolated_application_imports
from database import structural_schema_v1 as schema
from services.structural_document import StructuralEdge, RevisionState, StructuralNode, NodeIdentity, Disposition, make_node_key
from services.structural_repository import StructuralRepository, StorageScope, RevisionCounts, StructuralConflict, StructuralScopeError
from test_structural_repository import bundle


class Checks:
    def __init__(self):
        self.passed = []
        self.stage = "preflight"

    def check(self, name, condition):
        self.stage = name
        if not condition:
            raise AssertionError(name)
        self.passed.append(name)
        print("PASS " + name, flush=True)

    def rejects(self, conn, name, call, kinds=(DBAPIError,)):
        self.stage = name
        with conn.begin_nested() as savepoint:
            try:
                call()
                conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            except kinds:
                savepoint.rollback()
                self.check(name, True)
                return
            savepoint.rollback()
        self.check(name, False)


def migrate(conn, direction):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path=Path(__file__).resolve().parents[1]/"migrations/versions/20260916_01_structural_sidecar.py"
    spec=importlib.util.spec_from_file_location("structural_migration_test",path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module,direction)()


def register_sidecars(conn):
    # Only fixture metadata registration, never application runtime registration.
    # Existing harness refuses any table not registered in its Base allow-list.
    from database.connection import Base
    for name in schema.TABLES:
        if name not in Base.metadata.tables:
            Table(name,Base.metadata,autoload_with=conn)
    register(conn)


def repo(conn, docs, org=1, bot=1):
    return StructuralRepository(conn,StorageScope(org,bot,frozenset(docs)))


def seed_document(conn, doc, org=1, bot=1, version=1):
    from database.models import Document
    conn.execute(Document.__table__.insert().values(id=doc,organization_id=org,bot_id=bot,
        filename="synthetic.txt",source_type="txt",version=version,status="ready",processing_status="completed"))


def stage(conn, value, content, *, mappings=True):
    source=value.revision.identity.source
    store=repo(conn,[source.document_id],source.organization_id,source.bot_id)
    store.create_document_version(source,source_identity=f"owned:{source.document_id}",source_format=value.revision.source_format,
        fidelity=value.revision.fidelity,source_text=content)
    store.create_structure_revision(value.revision,RevisionCounts(len(value.nodes),len(value.edges),len(value.mappings)))
    store.stage_nodes(value.revision.identity,value.nodes)
    if value.edges:
        store.stage_edges(value.revision.identity,value.edges)
    if value.mappings and mappings:
        store.stage_chunk_mappings(value.revision.identity,value.mappings)
    return store


def insert_row(conn, table, values):
    json_keys={"provenance","quality","attributes"}
    columns=", ".join(values)
    binds=", ".join(f"CAST(:{k} AS jsonb)" if k in json_keys else f":{k}" for k in values)
    conn.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({binds})"),
        {k:json.dumps(v) if k in json_keys and v is not None else v for k,v in values.items()})


def setup(conn, checks, facts):
    from database.connection import Base
    from database import models
    old=MetaData()
    for table in Base.metadata.tables.values():
        clone=table.to_metadata(old)
        for column in tuple(clone.columns):
            if (clone.name=="documents" and column.name=="active_structure_revision_id") or (
                    clone.name=="chunks" and column.name in {"document_version_id","structure_revision_id"}):
                clone._columns.remove(column)
    checks.stage="legacy_fixture_schema"
    old.create_all(conn)
    register(conn)
    conn.execute(old.tables["organizations"].insert(),[
        {"id":i,"name":"Synthetic", "slug":f"fixture-{i}"} for i in (1,2,70001)])
    conn.execute(old.tables["customers"].insert().values(id=1,name="Synthetic",api_key="fixture-not-a-credential"))
    conn.execute(old.tables["bots"].insert(),[
        {"id":bot,"organization_id":org,"customer_id":1,"name":"Synthetic"}
        for org,bot in ((1,1),(1,2),(2,3),(2,4),(70001,70002))])
    conn.execute(old.tables["documents"].insert().values(id=9,organization_id=1,bot_id=1,
        filename="legacy.txt",source_type="txt",status="ready",processing_status="completed"))
    conn.execute(old.tables["chunks"].insert().values(id=9,organization_id=1,bot_id=1,document_id=9,
        content="legacy remains unchanged",embedding=[0.0]*models.EMBEDDING_DIMENSIONS))
    conn.commit()
    checks.stage="migration_upgrade"
    migrate(conn,"upgrade")
    register_sidecars(conn)
    conn.commit()
    checks.check("migration_upgrade_all_five_tables",all(conn.dialect.has_table(conn,n) for n in schema.TABLES))
    checks.check("legacy_null_structural_columns",conn.execute(text("SELECT active_structure_revision_id IS NULL FROM documents WHERE id=9")).scalar() and
        conn.execute(text("SELECT document_version_id IS NULL AND structure_revision_id IS NULL FROM chunks WHERE id=9")).scalar())
    conn.commit()
    checks.stage="migration_empty_downgrade"
    migrate(conn,"downgrade")
    register(conn)
    conn.commit()
    checks.check("downgrade_removes_only_sidecar",not any(conn.dialect.has_table(conn,n) for n in schema.TABLES))
    checks.check("downgrade_preserves_legacy_content",conn.execute(text("SELECT content FROM chunks WHERE id=9")).scalar()=="legacy remains unchanged")
    conn.commit()
    checks.stage="migration_reupgrade"
    # The historical baseline uses current model metadata on empty databases.
    # Exercise pre-created compatibility columns as well as legacy absent ones.
    for statement in schema.DDL[:3]: conn.execute(text(statement))
    migrate(conn,"upgrade")
    register_sidecars(conn)
    conn.commit()
    checks.check("migration_reupgrade",conn.dialect.has_table(conn,"structural_nodes"))
    facts["indexes"]=dict(conn.execute(text("SELECT c.relname,i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND (c.relname LIKE :a OR c.relname LIKE :b)"),{"a":"ix_structural%","b":"uq_structural%"}).all())
    facts["fixture_extensions"]=dict(conn.execute(text("SELECT extname,extversion FROM pg_extension WHERE extname IN ('vector','pg_trgm')")).all())
    checks.check("all_structural_indexes_valid",len(facts["indexes"])>=10 and all(facts["indexes"].values()))
    for doc,org,bot in ((10,1,1),(11,1,1),(12,1,2),(13,2,3),(14,2,4),(15,1,1),(16,1,1),(17,1,1),(18,1,1),(19,1,1),(20,1,1),(21,1,1),(22,1,1)):
        seed_document(conn,doc,org,bot)
    for doc,org,bot in ((10,1,1),(11,1,1),(12,1,2),(13,2,3),(14,2,4)):
        content,value=bundle(doc=doc,org=org,bot=bot)
        stage(conn,value,content)
    conn.commit()


def constraints(conn, checks):
    node=dict(conn.execute(text("SELECT * FROM structural_nodes WHERE document_id=10 AND preorder=2")).mappings().one())
    root=dict(conn.execute(text("SELECT * FROM structural_nodes WHERE document_id=10 AND preorder=0")).mappings().one())
    def new_node(**changes):
        return dict(node,node_key="f"*64,preorder=10,leaf_order=10,**changes)
    # Direct SQL, not repository/Pydantic: ownership and ordering must hold in DB.
    for name,target in (("cross_document_parent",11),("cross_bot_parent",12),("cross_org_parent",13)):
        foreign=conn.execute(text("SELECT node_key FROM structural_nodes WHERE document_id=:d AND preorder=0"),{"d":target}).scalar_one()
        checks.rejects(conn,name,lambda foreign=foreign:insert_row(conn,"structural_nodes",new_node(parent_key=foreign)))
    for name,values in (
        ("duplicate_node_key",dict(node)),
        ("duplicate_preorder",dict(node,node_key="f"*64,leaf_order=10)),
        ("duplicate_leaf_order",dict(node,node_key="f"*64,preorder=10)),
        ("self_parent",new_node(parent_key="f"*64)),
        ("parent_same_order",dict(new_node(),preorder=0)),
        ("parent_later_order",new_node(parent_preorder=11)),
        ("forged_parent_order",new_node(parent_preorder=1)),
        ("forged_parent_depth",new_node(parent_depth=1,depth=2)),
        ("second_root",dict(root,node_key="f"*64,preorder=10)),
        ("depth_bound",new_node(depth=33)),
        ("node_order_bound",dict(new_node(),preorder=10000)),
        ("unknown_node_type",new_node(node_type="invented")),
        ("wrong_source_version",new_node(document_version_id="missing")),
        ("wrong_revision",new_node(structure_revision_id="missing")),
    ):
        checks.rejects(conn,name,lambda values=values:insert_row(conn,"structural_nodes",values))
    for rev,version in (("r2",1),("r3",2)):
        if version==2: conn.execute(text("UPDATE documents SET version=2 WHERE id=10"))
        content,value=bundle(revision=rev,version=version,parser=rev)
        store=repo(conn,[10])
        store.create_document_version(value.revision.identity.source,source_identity="owned:10",source_format="text",fidelity="original",source_text=content)
        store.create_structure_revision(value.revision,RevisionCounts(4,1,0))
        # Child cannot point to a parent only present in another revision/version.
        checks.rejects(conn,"existing_cross_"+("revision" if version==1 else "version")+"_parent",
            lambda value=value:insert_row(conn,"structural_nodes",new_node(document_version_id=value.revision.identity.source.document_version_id,structure_revision_id=value.revision.identity.structure_revision_id)))
    conn.execute(text("UPDATE documents SET version=1 WHERE id=10"))
    edge=dict(conn.execute(text("SELECT * FROM structural_edges WHERE document_id=10")).mappings().one())
    for name,changes in (
        ("edge_org_mismatch",{"organization_id":2}), ("edge_bot_mismatch",{"bot_id":2}),
        ("edge_foreign_endpoint",{"to_document_id":13}), ("edge_invalid_endpoint_version",{"to_document_version_id":"missing"}),
        ("edge_invalid_endpoint_revision",{"to_structure_revision_id":"missing"}),
        ("edge_heading_type",{"from_node_key":node["node_key"]}),
        ("edge_qa_roles",{"relation":"QA_PAIR"}),
        ("edge_tree_duplicate",{"relation":"CONTAINS","from_node_key":root["node_key"]}),
        ("edge_logical_duplicate_despite_new_key",{}),
    ):
        values=dict(edge,edge_key="f"*64,ordinal=10);values.update(changes)
        checks.rejects(conn,name,lambda values=values:insert_row(conn,"structural_edges",values))
    version=dict(conn.execute(text("SELECT * FROM document_versions WHERE document_id=10 AND id='v1'")).mappings().one())
    checks.rejects(conn,"immutable_source_update",lambda:conn.execute(text("UPDATE document_versions SET source_sha256=:h WHERE document_id=10 AND id='v1'"),{"h":"a"*64}))
    checks.rejects(conn,"immutable_source_history_delete",lambda:conn.execute(text("DELETE FROM document_versions WHERE document_id=10 AND id='v1'")))
    checks.rejects(conn,"immutable_source_identity_collision",lambda:insert_row(conn,"document_versions",dict(version,id="different",source_sha256="a"*64)))
    checks.rejects(conn,"source_wrong_document_owner",lambda:insert_row(conn,"document_versions",dict(version,document_id=12)))
    checks.rejects(conn,"populated_downgrade_refused",lambda:migrate(conn,"downgrade"),(RuntimeError,))
    checks.rejects(conn,"pointer_foreign_document",lambda:conn.execute(text("UPDATE documents SET active_structure_revision_id='r1' WHERE id=15")))
    checks.rejects(conn,"pointer_staging_refused",lambda:conn.execute(text("UPDATE documents SET active_structure_revision_id='r1' WHERE id=10")))
    checks.rejects(conn,"direct_active_without_pointer",lambda:conn.execute(text("UPDATE document_structure_revisions SET state='active' WHERE document_id=10 AND id='r1'")))
    conn.commit()


def roundtrip_and_lifecycle(conn, checks, facts):
    from database.models import Chunk,EMBEDDING_DIMENSIONS
    content,value=bundle(doc=15,chunk=15)
    store=stage(conn,value,content,mappings=False)
    # Fixture ONLY, using existing chunks. Repository never creates/tags chunks.
    conn.execute(Chunk.__table__.insert().values(id=15,document_id=15,organization_id=1,bot_id=1,
        content="Repeated text",embedding=[0.0]*EMBEDDING_DIMENSIONS,document_version_id="v1",structure_revision_id="r1"))
    checks.rejects(conn,"validate_incomplete_mapping",lambda:store.mark_revision_validated(15,"r1"),(StructuralConflict,))
    store.stage_chunk_mappings(value.revision.identity,value.mappings)
    store.stage_nodes(value.revision.identity,value.nodes)
    store.stage_edges(value.revision.identity,value.edges)
    store.stage_chunk_mappings(value.revision.identity,value.mappings)
    checks.check("batch_idempotency",store.validate_revision_counts(15,"r1")==RevisionCounts(4,1,1))
    again=store.create_structure_revision(value.revision.model_copy(update={"identity":value.revision.identity.model_copy(update={"structure_revision_id":"alternate"})}),RevisionCounts(4,1,1))
    checks.check("build_fingerprint_idempotency",again.identity.structure_revision_id=="r1")
    store.create_document_version(value.revision.identity.source,source_identity="owned:15",source_format="text",fidelity="original",source_text=content)
    checks.check("source_idempotency",conn.execute(text("SELECT count(*) FROM document_versions WHERE document_id=15")).scalar()==1)
    original=value.edges[0]
    changed=original.model_copy(update={"provenance":original.provenance.model_copy(update={"confidence":.4})})
    checks.rejects(conn,"same_logical_edge_changed_confidence_conflicts",lambda:store.stage_edges(value.revision.identity,[changed]),(StructuralConflict,))
    mapped=dict(conn.execute(text("SELECT * FROM chunk_structural_nodes WHERE chunk_id=15")).mappings().one())
    with conn.begin_nested() as savepoint:
        conn.execute(text("UPDATE chunks SET content=:v WHERE id=15"),{"v":"\u00e9Repeated text"})
        checks.rejects(conn,"mapping_output_utf8_boundary",lambda:insert_row(conn,"chunk_structural_nodes",dict(mapped,ordinal=10,output_start=1)))
        savepoint.rollback()
    for name,change in (("mapping_foreign_tenant",{"organization_id":2}),
        ("mapping_wrong_version",{"document_version_id":"v2"}), ("mapping_wrong_revision",{"structure_revision_id":"r2"}),
        ("mapping_foreign_node",{"node_key":bundle(doc=13,org=2,bot=3)[1].nodes[2].identity.node_key}),
        ("mapping_source_overflow",{"node_end":1000}), ("mapping_output_overflow",{"output_end":1000}),
        ("mapping_negative_range",{"node_start":-1}), ("mapping_bad_bundle",{"bundle_key":"bundle"})):
        values=dict(mapped,ordinal=10);values.update(change)
        checks.rejects(conn,name,lambda values=values:insert_row(conn,"chunk_structural_nodes",values))
    store.mark_revision_validated(15,"r1")
    loaded=store.load_revision_bounded(15,"r1",node_limit=4,edge_limit=1,mapping_limit=1)
    checks.check("full_dto_mapping_roundtrip",loaded.canonical_json()==value.canonical_json())
    hashes=conn.execute(text("SELECT normalized_hash,serialization_hash FROM document_structure_revisions WHERE document_id=15")).one()
    checks.check("sealed_hashes_recorded",len(hashes[0])==64 and hashes[1]==value.canonical_hash())
    checks.rejects(conn,"sealed_nodes_immutable",lambda:conn.execute(text("UPDATE structural_nodes SET text='changed' WHERE document_id=15 AND preorder=2")))
    checks.rejects(conn,"sealed_edges_immutable",lambda:conn.execute(text("DELETE FROM structural_edges WHERE document_id=15")))
    checks.rejects(conn,"sealed_revision_recipe_immutable",lambda:conn.execute(text("UPDATE document_structure_revisions SET parser_version='changed' WHERE document_id=15")))
    checks.rejects(conn,"sealed_revision_history_delete",lambda:conn.execute(text("DELETE FROM document_structure_revisions WHERE document_id=15")))
    checks.rejects(conn,"stale_expected_source_activation",lambda:store.activate_revision(15,"r1",expected_source_version=2,expected_active_revision_id=None),(StructuralConflict,))
    store.activate_revision(15,"r1",expected_source_version=1,expected_active_revision_id=None)
    conn.commit()
    checks.check("validated_to_active_atomic",conn.execute(text("SELECT active_structure_revision_id FROM documents WHERE id=15")).scalar()=="r1" and store.get_structure_revision(15,"r1").state==RevisionState.ACTIVE)
    checks.check("activation_did_not_modify_chunks",conn.execute(text("SELECT content,status FROM chunks WHERE id=15")).one()==("Repeated text","ready"))
    # Source and processing versions are separate (Haystack / Docling adaptation).
    new_content,new_value=bundle(doc=15,revision="r2",parser="test-v2")
    next_store=stage(conn,new_value,new_content)
    checks.rejects(conn,"mapping_existing_foreign_revision",lambda:insert_row(conn,"chunk_structural_nodes",dict(mapped,ordinal=10,structure_revision_id="r2")))
    next_store.mark_revision_validated(15,"r2")
    conn.commit()
    with conn.begin_nested() as savepoint:
        conn.execute(text("UPDATE documents SET version=2 WHERE id=15"))
        body,newer=bundle(doc=15,version=2,revision="r3")
        stage(conn,newer,body)
        checks.rejects(conn,"mapping_existing_foreign_source_version",lambda:insert_row(conn,"chunk_structural_nodes",
            dict(mapped,ordinal=10,document_version_id="v2",structure_revision_id="r3",node_key=newer.nodes[2].identity.node_key)))
        savepoint.rollback()
    checks.rejects(conn,"validated_unreferenced_history_delete",lambda:conn.execute(text("DELETE FROM document_structure_revisions WHERE document_id=15 AND id='r2'")))
    with conn.begin_nested() as rollback:
        store.activate_revision(15,"r2",expected_source_version=1,expected_active_revision_id="r1")
        rollback.rollback()
    checks.check("activation_rollback_retains_previous",store.get_structure_revision(15,"r1").state==RevisionState.ACTIVE and store.get_structure_revision(15,"r2").state==RevisionState.VALIDATED and conn.execute(text("SELECT active_structure_revision_id FROM documents WHERE id=15")).scalar()=="r1")
    conn.commit()
    # Qualified management reads include staging; relationship targets are still ACL-intersected.
    source=repo(conn,[10,11]);_,a=bundle();_,b=bundle(doc=11)
    edge=StructuralEdge(from_node=a.nodes[2].identity,to_node=b.nodes[2].identity,relation="REFERS_TO",provenance=a.nodes[2].provenance,validation_state="validated")
    source.stage_edges(a.revision.identity,[edge])
    checks.check("valid_cross_document_edge",len(source.list_edges_bounded(10,"r1",node_key=a.nodes[2].identity.node_key,limit=10))==1)
    checks.check("relation_never_widens_document_access",repo(conn,[10]).list_edges_bounded(10,"r1",node_key=a.nodes[2].identity.node_key,limit=10)==())
    reverse=source.list_edges_bounded(11,"r1",node_key=b.nodes[2].identity.node_key,limit=10,reverse=True)
    checks.check("reverse_edges_scoped",{e.from_node.revision.source.document_id for e in reverse}=={10,11})
    reverse_restricted=repo(conn,[11]).list_edges_bounded(11,"r1",node_key=b.nodes[2].identity.node_key,limit=10,reverse=True)
    checks.check("reverse_edges_restrict_both_endpoints",{e.from_node.revision.source.document_id for e in reverse_restricted}=={11})
    checks.check("ordered_node_pagination",[n.preorder for n in source.list_nodes_bounded(10,"r1",limit=2,after_preorder=1)]==[2,3])
    checks.check("mapping_read_roundtrip",store.list_chunk_mappings_bounded(15,"r1",chunk_ids=[15],limit=2)==value.mappings)
    for doc,method in ((17,"mark_revision_failed"),(18,"mark_revision_cancelled")):
        body,record=bundle(doc=doc);target=stage(conn,record,body);getattr(target,method)(doc,"r1")
        checks.rejects(conn,"terminal_"+method+"_not_activatable",lambda target=target,doc=doc:target.activate_revision(doc,"r1",expected_source_version=1,expected_active_revision_id=None),(StructuralConflict,))
    conn.commit()
    # Frozen synthetic Phase 4.1A examples only, no real saved-source excerpts.
    from scripts.structural_gold_v1 import fixture_specs,build_fixture
    names=[]
    for spec in fixture_specs():
        if spec["category"]!="synthetic": continue
        record=build_fixture(spec);s=record.revision.identity.source
        seed_document(conn,s.document_id,s.organization_id,s.bot_id)
        target=stage(conn,record,spec["source_text"])
        target.mark_revision_validated(s.document_id,record.revision.identity.structure_revision_id)
        result=target.load_revision_bounded(s.document_id,record.revision.identity.structure_revision_id,node_limit=100,edge_limit=100,mapping_limit=1)
        checks.check("frozen_gold_roundtrip_"+spec["name"],record.canonical_json()==result.canonical_json())
        names.append(spec["name"])
    checks.check("all_eight_synthetic_domains_roundtripped",len(names)==8)
    facts["gold_roundtrip"]=names
    # Valid maximum-length UTF-8 IDs must not overflow the edge dedup index.
    seed_document(conn,23)
    wide="".join(chr(0x10000+(i*131)%60000) for i in range(256))
    body,record=bundle(doc=23,revision=wide[::-1],version_id=wide)
    target=stage(conn,record,body)
    target.mark_revision_validated(23,wide[::-1])
    wide_result=target.load_revision_bounded(23,wide[::-1],node_limit=4,edge_limit=1,mapping_limit=1)
    checks.check("maximum_utf8_revision_ids_roundtrip",record.canonical_json()==wide_result.canonical_json())
    conn.commit()


def serving(conn, checks):
    from services.retrieval_contracts import HardKnowledgeScope,ProfileIdentity
    store=repo(conn,[15])
    hard=HardKnowledgeScope(1,1,authorized_document_ids=(15,),embedding_profile=ProfileIdentity("gemini","gemini-embedding-001",1,768))
    checks.check("active_mapped_node_serving",len(store.list_active_nodes(hard,15,limit=10))==1)
    checks.check("empty_document_acl",store.list_active_nodes(replace(hard,authorized_document_ids=()),15,limit=10)==())
    checks.check("different_profile_denied",store.list_active_nodes(replace(hard,embedding_profile=ProfileIdentity("other","other",1,768)),15,limit=10)==())
    checks.check("stale_expected_version_denied",store.list_active_nodes(replace(hard,active_document_versions=((15,2,None),)),15,limit=10)==())
    from database.models import Chunk,EMBEDDING_DIMENSIONS
    for doc in (21,22):
        body,record=bundle(doc=doc,chunk=doc if doc==22 else None)
        blocked=record.revision.quality.model_copy(update={"disposition":Disposition.QUARANTINE})
        if doc==21:
            record=record.model_copy(update={"revision":record.revision.model_copy(update={"quality":blocked})})
        else:
            record=record.model_copy(update={"nodes":tuple(n.model_copy(update={"quality":blocked}) if n.preorder==2 else n for n in record.nodes)})
        target=stage(conn,record,body,mappings=False)
        if doc==22:
            conn.execute(Chunk.__table__.insert().values(id=22,document_id=22,organization_id=1,bot_id=1,
                content="Repeated text",embedding=[0.0]*EMBEDDING_DIMENSIONS,document_version_id="v1",structure_revision_id="r1"))
            target.stage_chunk_mappings(record.revision.identity,record.mappings)
        target.mark_revision_validated(doc,"r1")
        if doc==21:
            checks.rejects(conn,"quarantined_source_cannot_activate",lambda:target.activate_revision(doc,"r1",expected_source_version=1,expected_active_revision_id=None))
        else:
            target.activate_revision(doc,"r1",expected_source_version=1,expected_active_revision_id=None)
            checks.check("quarantined_node_not_served",target.list_active_nodes(replace(hard,authorized_document_ids=(22,)),22,limit=10)==())
    for table,column,values in (("documents","status",("processing","failed","deleted","superseded")),
        ("documents","processing_status",("pending",)),("chunks","status",("processing","failed","superseded")),
        ("documents","version",(2,)),("chunks","embedding_version",(2,))):
        for value in values:
            with conn.begin_nested() as savepoint:
                conn.execute(text(f"UPDATE {table} SET {column}=:v WHERE id=15"),{"v":value})
                checks.check(f"serving_denies_{table}_{column}_{value}",store.list_active_nodes(hard,15,limit=10)==())
                savepoint.rollback()
    from database.models import Website,WebsiteCrawl
    with conn.begin_nested() as savepoint:
        conn.execute(Website.__table__.insert().values(id=90,organization_id=1,bot_id=1,root_url="https://synthetic.test",domain="synthetic.test",status="ready",active_crawl_id=90))
        conn.execute(WebsiteCrawl.__table__.insert().values(id=90,organization_id=1,bot_id=1,website_id=90,version=1,status="ready"))
        # New independent source capture uses a real matching website/crawl fixture.
        conn.execute(text("UPDATE documents SET website_id=90,crawl_id=90,source_type='website' WHERE id=19"))
        from database.models import Chunk,EMBEDDING_DIMENSIONS
        body,value=bundle(doc=19,chunk=19)
        target=stage(conn,value,body,mappings=False)
        conn.execute(Chunk.__table__.insert().values(id=19,document_id=19,organization_id=1,bot_id=1,website_id=90,crawl_id=90,
            content="Repeated text",embedding=[0.0]*EMBEDDING_DIMENSIONS,document_version_id="v1",structure_revision_id="r1"))
        target.stage_chunk_mappings(value.revision.identity,value.mappings)
        target.mark_revision_validated(19,"r1")
        conn.execute(text("UPDATE websites SET active_crawl_id=91 WHERE id=90"))
        checks.rejects(conn,"stale_crawl_cannot_activate",lambda:target.activate_revision(19,"r1",expected_source_version=1,expected_active_revision_id=None))
        conn.execute(text("UPDATE websites SET active_crawl_id=90 WHERE id=90"))
        target.activate_revision(19,"r1",expected_source_version=1,expected_active_revision_id=None)
        web_hard=replace(hard,authorized_document_ids=(19,),authorized_source_ids=(90,))
        checks.check("active_crawl_serving",len(target.list_active_nodes(web_hard,19,limit=10))==1)
        conn.execute(text("UPDATE websites SET active_crawl_id=91 WHERE id=90"))
        checks.check("superseded_crawl_denied",target.list_active_nodes(web_hard,19,limit=10)==())
        savepoint.rollback()
    conn.commit()


def activation_race(engine, conn, checks):
    for revision in ("r1","r2"):
        body,value=bundle(doc=16,revision=revision,parser=revision)
        stage(conn,value,body).mark_revision_validated(16,revision)
    conn.commit()
    started=threading.Event();held=threading.Event()
    def worker(revision, winner):
        with engine.connect() as other:
            store=repo(other,[16])
            try:
                if winner:
                    store._document_lock(16)
                    held.set()
                    if not started.wait(15): raise AssertionError("race participant missing")
                else:
                    if not held.wait(15): raise AssertionError("race lock missing")
                    started.set()
                store.activate_revision(16,revision,expected_source_version=1,expected_active_revision_id=None)
                other.commit()
                return "active"
            except StructuralConflict:
                other.rollback()
                return "conflict"
    checks.stage="two_connection_activation_race"
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(worker,"r1",True);second=pool.submit(worker,"r2",False)
        outcomes=[first.result(timeout=45),second.result(timeout=45)]
    checks.check("race_one_success_one_deterministic_conflict",outcomes==["active","conflict"])
    checks.check("race_one_active_revision",conn.execute(text("SELECT count(*) FROM document_structure_revisions WHERE document_id=16 AND state='active'")).scalar()==1)
    checks.check("race_pointer_matches_winner",conn.execute(text("SELECT active_structure_revision_id FROM documents WHERE id=16")).scalar()=="r1")
    conn.commit()


def plans(conn, checks, facts):
    # A moderately-sized synthetic hierarchy; not a performance benchmark.
    body,record=bundle(doc=20)
    identity=record.revision.identity;root=record.nodes[0]
    nodes=[root]
    for i in range(1,1025):
        value=f"Synthetic row {i}"
        nodes.append(StructuralNode(identity=NodeIdentity(revision=identity,node_key=make_node_key(identity.source,f"/rows/{i}",0,value)),
            parser_path=f"/rows/{i}",occurrence=0,parent=root.identity,preorder=i,node_type="paragraph",text=value,provenance=root.provenance))
    store=repo(conn,[20])
    store.create_document_version(identity.source,source_identity="owned:20",source_format="text",fidelity="original",source_text=body)
    store.create_structure_revision(record.revision,RevisionCounts(1025,0,0))
    for start in range(0,len(nodes),500): store.stage_nodes(identity,nodes[start:start+500])
    conn.execute(text("ANALYZE structural_nodes"));conn.execute(text("ANALYZE structural_edges"));conn.execute(text("ANALYZE chunk_structural_nodes"))
    _,a=bundle();_,b=bundle(doc=11)
    queries={
        "children":("SELECT node_key,preorder FROM structural_nodes WHERE organization_id=1 AND bot_id=1 AND document_id=20 AND structure_revision_id='r1' AND parent_key=:key AND preorder>0 ORDER BY preorder LIMIT 20",{"key":root.identity.node_key}),
        "outgoing_edges":("SELECT edge_key FROM structural_edges WHERE organization_id=1 AND bot_id=1 AND structure_revision_id='r1' AND from_node_key=:key AND document_id=10 AND to_document_id=ANY(:allowed) ORDER BY edge_key LIMIT 20",{"key":a.nodes[2].identity.node_key,"allowed":[10,11]}),
        "incoming_edges":("SELECT edge_key FROM structural_edges WHERE organization_id=1 AND bot_id=1 AND to_structure_revision_id='r1' AND to_node_key=:key AND to_document_id=11 AND document_id=ANY(:allowed) ORDER BY edge_key LIMIT 20",{"key":b.nodes[2].identity.node_key,"allowed":[10,11]}),
        "chunk_mappings":("SELECT node_key FROM chunk_structural_nodes WHERE organization_id=1 AND bot_id=1 AND chunk_id=ANY(:chunks) ORDER BY chunk_id,ordinal LIMIT 20",{"chunks":[15]}),
        "active_revision":("SELECT r.id FROM documents d JOIN document_structure_revisions r ON (r.organization_id,r.bot_id,r.document_id,r.id)=(d.organization_id,d.bot_id,d.id,d.active_structure_revision_id) WHERE d.organization_id=1 AND d.bot_id=1 AND d.id=15 AND r.state='active' LIMIT 1",{}),
    }
    facts["plan_fixture_counts"]={table:conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() for table in schema.TABLES}
    facts["natural_plans"]={}
    for name,(sql,params) in queries.items():
        plan=conn.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "+sql),params).scalar_one()[0]
        facts["natural_plans"][name]={"query":sql,"plan":plan}
        checks.check("bounded_natural_plan_"+name,plan["Plan"]["Node Type"]=="Limit")
    conn.commit()


def identity_projection_checks(conn, checks):
    """Targeted PostgreSQL verification of the final metadata-only read change."""
    _,value=bundle()
    statements=[]
    def capture(connection,cursor,statement,parameters,context,many):
        statements.append(statement)
    event.listen(conn,"before_cursor_execute",capture)
    try:
        store=repo(conn,[10])
        checks.check("projected_source_identity",store.get_structure_revision(10,"r1").identity==value.revision.identity)
        checks.check("projected_node_roundtrip",store.get_node(10,"r1",value.nodes[2].identity.node_key)==value.nodes[2])
        checks.check("projected_edge_roundtrip",store.list_edges_bounded(10,"r1",node_key=value.nodes[1].identity.node_key,limit=10)==value.edges)
        checks.rejects(conn,"projected_read_foreign_scope_refused",lambda:repo(conn,[10],org=2,bot=3).get_structure_revision(10,"r1"),(StructuralScopeError,))
    finally:
        event.remove(conn,"before_cursor_execute",capture)
    source_reads=[s for s in statements if "FROM document_versions" in s]
    checks.check("identity_queries_omit_source_artifacts",bool(source_reads) and all(
        "source_text" not in s and "source_artifact_ref" not in s and "SELECT *" not in s and "SELECT v.*" not in s for s in source_reads))
    conn.commit()


def main(*, read_smoke=False):
    checks=Checks();facts={};start=perf_counter();failure=None
    print("PHASE41: explicit disposable target; application/provider access disabled",flush=True)
    try:
        with isolated_application_imports():
            with disposable_database() as (engine,conn,facts):
                try:
                    setup(conn,checks,facts)
                    if read_smoke:
                        identity_projection_checks(conn,checks)
                    else:
                        constraints(conn,checks)
                        roundtrip_and_lifecycle(conn,checks,facts)
                        serving(conn,checks)
                        activation_race(engine,conn,checks)
                        plans(conn,checks,facts)
                finally:
                    conn.rollback()
                    # Guarded outer harness owns schema + captured OIDs. Drop only
                    # our fixed trigger/function set inside that owned schema;
                    # outer RESTRICT cleanup removes tables and proves no outsiders.
                    functions=conn.execute(text("SELECT proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=current_schema() AND proname=ANY(:names)"),{"names":list(schema.FUNCTIONS)}).scalars().all()
                    if functions:
                        if set(functions)!=set(schema.FUNCTIONS): raise RuntimeError("partial structural cleanup requires inspection")
                        schema.remove_triggers(conn)
                        register(conn)
                        conn.commit()
    except Exception as exc:
        origin=getattr(exc,"orig",exc)
        failure={"stage":checks.stage,"class":type(exc).__name__,"sqlstate":getattr(origin,"pgcode",None),
            "constraint":getattr(getattr(origin,"diag",None),"constraint_name",None),
            "locations":[[Path(f.filename).name,f.lineno,f.name] for f in traceback.extract_tb(exc.__traceback__) if ".venv" not in f.filename]}
        print("SAFE_FAILURE "+json.dumps(failure),flush=True)
    facts.update(mode="metadata_read_smoke" if read_smoke else "full_acceptance",checks_passed=len(checks.passed),checks=checks.passed,failure=failure,total_seconds=round(perf_counter()-start,3))
    # Small lines avoid console truncation. No connection fields in facts.
    for key,value in facts.items():
        payload=json.dumps({key:value},sort_keys=True,default=str)
        for offset in range(0,len(payload),3000):
            print("RESULT "+json.dumps({"key":key,"part":offset//3000,"fragment":payload[offset:offset+3000]}),flush=True)
    return 1 if failure or not facts.get("cleanup",{}).get("schema_absent") else 0


if __name__ == "__main__":
    raise SystemExit(main())
