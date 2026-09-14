"""48 natural-query handoffs through actual retrieval, synthetic local SQL only.

Independent file-backed pooled connections retain Phase 2.4.1 semantics.
Only vectors/SQLite unsupported search operators use labeled test substitutes.
Ambiguous requests terminate at clarification, never bypass that gate.
"""
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from sqlalchemy import URL, create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from database.connection import Base
from database.models import Customer, Organization, Bot, Chunk, Document
from database.resource_models import KnowledgeResource
from services import rag_service as rag, rag_planning
from services.knowledge_scope import ready_chunks
from services.observability_service import ChatTrace
from services.retrieval_contracts import HardKnowledgeScope,ProfileIdentity
from test_resource_discovery import ResourceFixture, similarity,service
from test_resource_probe_benchmark import SEEDS
from services.resource_catalog import ResourceCatalogProjector

class ProbeHandoffTests(ResourceFixture):
    def setUp(self):
        temp=TemporaryDirectory(prefix="phase32-handoff-")
        self.addCleanup(temp.cleanup)
        self.engine=create_engine(URL.create("sqlite",database=str(Path(temp.name)/"fixture.sqlite3")),
            poolclass=QueuePool,connect_args={"check_same_thread":False})
        self.addCleanup(self.engine.dispose)
        @event.listens_for(self.engine,"connect")
        def functions(conn,_):
            conn.execute("PRAGMA foreign_keys=ON")
            conn.create_function("fixture_tokens",2,lambda value,probe:float(bool(probe) and set(probe.split())<=set(value.split())))
            conn.create_function("fixture_trigram",2,similarity)
        Base.metadata.create_all(self.engine)
        self.sessions=sessionmaker(bind=self.engine)
        self.db=self.sessions();self.addCleanup(self.db.close)
        self.db.add(Customer(id=1,name="Synthetic",api_key="not-a-secret"))
        self.db.add(Organization(id=1,name="Synthetic",slug="handoff"));self.db.flush()
        self.bot=Bot(id=1,customer_id=1,organization_id=1,name="Fixture",capabilities={})
        self.db.add(self.bot);self.db.flush()
        self.hard=HardKnowledgeScope(1,1,embedding_profile=ProfileIdentity("gemini","gemini-embedding-001",1,768))
        self.service=service()
        for i,(stem,kind,_) in enumerate(SEEDS,1):
            self.add(i*10,stem+" "+kind,kind=kind,aliases=["Duo"])
            self.add(i*10+1,"Nimbus "+stem+" "+kind,kind=kind,aliases=["Duo"])
        self.project(*[i*10+o for i in range(1,13) for o in (0,1)])
        self.db.query(KnowledgeResource).update({KnowledgeResource.summary: "UNSUPPORTED SUMMARY: invented answer"})
        self.db.commit()
        self.patches=ExitStack();self.addCleanup(self.patches.close)
        self.patches.enter_context(patch.object(rag,"SessionLocal",self.sessions))
        self.patches.enter_context(patch.object(rag,"generate_embedding",return_value=[0.]*768))
        self.patches.enter_context(patch.object(rag,"resolve_active_embedding_profile",
            return_value=SimpleNamespace(provider="gemini",model="gemini-embedding-001",version=1,dimensions=768)))
        def vector(bot_id,org_id,embedding,limit,profile,document_ids=None):
            with self.sessions() as db:
                rows=ready_chunks(db.query(Chunk.id,Document.id).join(Document,Chunk.document_id==Document.id),
                    bot_id,org_id,document_ids).order_by(Chunk.id).limit(limit).all()
                return [(c,d,.02) for c,d in rows]
        self.patches.enter_context(patch.object(rag,"_vector_candidate_ids",side_effect=vector))

    def test_48_application_handoffs(self):
        count=0
        for i,(stem,kind,_) in enumerate(SEEDS,1):
            n=i*10; name=stem+" "+kind
            rows=[(f"Could you send me {name}?",{n},"exact"),
                  (f"{name} or Nimbus {stem} one",{n,n+1},"exact")]
            if i%3==0:
                rows += [(f"What {kind}s do you have?",set(),"broad"),("Show me Duo.",set(),"clarify")]
            elif i%3==1:
                rows += [(f"{name} or Unknown Cosmic one",set(),"broad"),
                         ("I need something to eliminate all work",set(),"broad")]
            else:
                rows += [(f"What is between {name} and Nimbus {stem} {kind}?",set(),"broad"),
                         (f"Tell me about {name} and its directions.",{n},"exact")]
            for q,expected,strategy in rows:
                with self.subTest(question=q):
                    c=self.contract(q)
                    self.assertEqual(c.original_query,q)
                    if strategy=="clarify":
                        self.assertTrue(c.requires_clarification)
                        count+=1
                        continue
                    self.assertFalse(c.requires_clarification,c.to_debug_dict())
                    if strategy=="exact":
                        self.assertEqual(set(c.permitted_document_ids or ()),expected,c.to_debug_dict())
                    else:
                        self.assertIsNone(c.permitted_document_ids,c.to_debug_dict())
                    trace=ChatTrace(1,"offline")
                    result=rag.retrieve_relevant_chunks(self.db,1,c.retrieval_query,query_contract=c,trace=trace)
                    ids={rag._document_id(r) for r in result}
                    if strategy=="exact":
                        self.assertEqual(ids,expected)
                    self.assertTrue(ids <= {i*10+o for i in range(1,13) for o in (0,1)})
                    self.assertNotIn("UNSUPPORTED SUMMARY",str(result))
                    self.assertNotIn("UNSUPPORTED SUMMARY",str(c.execution.resource_discovery))
                    count+=1
        self.assertEqual(count,48)

if __name__=="__main__":
    unittest.main()
