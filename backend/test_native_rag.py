"""Native SaaS integration with a real isolated DB and controlled service boundaries."""
import atexit
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import patch

_temp = TemporaryDirectory(prefix="native-rag-tests-")
os.environ["DATABASE_URL"] = "sqlite:///" + (Path(_temp.name) / "data.sqlite").as_posix()
os.environ["APP_ENV"] = "development"
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"
from database.connection import Base, engine, SessionLocal
from database.models import Organization, Customer, Bot, Document, Website, WebsiteCrawl
from database.native_rag_models import NativeRagDataset, NativeRagDocument, NativeRagChunk, NativeRagCleanup
from services.native_rag import knowledge, ingestion, cleanup, answer
from services.native_rag.client import NativeClient
from services.native_rag.config import NativeConfig, NativeRagError, SEARCH_POLICY, PROFILE
from services.observability_service import ChatTrace
from services.combined_rag import pipeline
import httpx
import fakeredis
from utils.redis_client import set_redis_override


def finish():
    from sqlalchemy.orm import close_all_sessions
    close_all_sessions()
    engine.dispose()
    _temp.cleanup()
atexit.register(finish)

TENANT, DATASET, NATIVE_DOC = "a" * 32, "b" * 32, "c" * 32
CONFIG = NativeConfig("http://native.test", "test-token", TENANT, PROFILE["model"] + "@HuggingFace")


def manifest(content="The desk is 120 cm wide. Final complete source."):
    rows = [{"id": "d" * 16, "content": content, "title": "Desk.md",
             "sha256": hashlib.sha256(content.encode()).hexdigest(), "metadata": {"available_int": 1}}]
    return {"policy": SEARCH_POLICY, "tenant_id": TENANT, "dataset_id": DATASET,
            "document_id": NATIVE_DOC, "chunks": rows,
            "manifest_sha256": hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}


class Client:
    config = CONFIG
    def __init__(self):
        self.calls = []
        self.hit = {"chunk_id": "d" * 16, "doc_id": NATIVE_DOC, "kb_id": DATASET,
                    "docnm_kwd": "Desk.md", "content_with_weight": manifest()["chunks"][0]["content"],
                    "similarity": .7, "term_similarity": .6, "vector_similarity": .8}
    def search(self, query, dataset, documents):
        self.calls.append((query, dataset, documents))
        return [dict(self.hit)]


class ParsingClient:
    """Only the remote parse boundary is doubled; staging/SQL/jobs remain real."""
    config = CONFIG
    def __init__(self): self.rows = {}; self.fail = False
    def request(self, method, path, **kwargs):
        if method == 'POST' and path.endswith('/documents'):
            native_id = format(len(self.rows) + 1000, '032x')
            name, data, _mime = kwargs['files']['file']
            self.rows[native_id] = (name, data.decode())
            return [{'id': native_id}]
        if method == 'POST' and path.endswith('/chunks'): return True
        if method == 'GET' and path.endswith('/documents'):
            return {'docs': [{'id':kwargs['params']['id'],'run':'FAIL' if self.fail else 'DONE'}]}
        raise AssertionError('Unexpected native endpoint')
    def manifest(self,dataset,native_id):
        title,text = self.rows[native_id]
        data = manifest(text); data['document_id'] = native_id
        data['chunks'][0]['title'] = title
        data['manifest_sha256'] = hashlib.sha256(json.dumps(data['chunks'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        return data


class NativeDatabaseTests(unittest.TestCase):
    def setUp(self):
        set_redis_override(fakeredis.FakeRedis(decode_responses=True))
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.db = SessionLocal()
        org = Organization(name="Native test", slug="native-test")
        customer = Customer(name="Native test", api_key="synthetic-native-test")
        self.db.add_all([org, customer]); self.db.flush()
        self.bot = Bot(name="Native bot", organization_id=org.id, customer_id=customer.id,
                       provider="gemini", model_name="unchanged-gemini-model")
        self.db.add(self.bot); self.db.flush()
        self.doc = Document(bot_id=self.bot.id, organization_id=org.id, filename="Desk.md",
            title="Desk", source_type="text", source_url="https://example.test/desk", raw_text="source",
            status="ready", processing_status="completed", version=1,
            content_hash=hashlib.sha256(b"source").hexdigest(), metadata_json={})
        self.db.add(self.doc); self.db.flush()
        self.dataset = NativeRagDataset(bot_id=self.bot.id, organization_id=org.id,
            tenant_id=TENANT, dataset_id=DATASET)
        self.db.add(self.dataset); self.db.flush()
        self.binding = knowledge.store_manifest(self.db, self.doc, self.dataset, manifest(), version=1,
            crawl_id=None, source_sha256=self.doc.content_hash, staging_id="unit-stage")
        knowledge.promote(self.db, self.doc, "unit-stage")
        self.db.commit()
        self.client = Client()

    def tearDown(self):
        self.db.rollback(); self.db.close()
        set_redis_override(None,None)

    def test_native_candidates_keep_content_ids_title_and_all_authorized_docs(self):
        scope = knowledge.NativeScope(self.db, self.bot, self.client)
        rows = scope.retrieve("How wide is the desk?", scope.contract, 128)
        self.assertEqual(rows[0]["chunk"].content, self.client.hit["content_with_weight"])
        self.assertEqual(rows[0]["document"].title, "Desk.md")
        self.assertEqual(rows[0]["chunk"].metadata_json["native_chunk_id"], "d" * 16)
        self.assertEqual(self.client.calls[0][1:], (DATASET, [NATIVE_DOC]))

    def test_unknown_chunk_foreign_document_dataset_and_changed_content_fail_closed(self):
        for key, value in (("chunk_id", "e" * 16), ("doc_id", "e" * 32), ("kb_id", "e" * 32),
                           ("content_with_weight", "changed"), ("docnm_kwd", "Changed title")):
            with self.subTest(key=key):
                client = Client(); client.hit[key] = value
                scope = knowledge.NativeScope(self.db, self.bot, client)
                with self.assertRaises(NativeRagError): scope.retrieve("q", scope.contract, 128)

    def test_revoke_during_request_is_observed_before_reply(self):
        scope = knowledge.NativeScope(self.db, self.bot, self.client)
        document_id = self.doc.id
        with SessionLocal() as other:
            other.query(Document).filter(Document.id == document_id).update({"status": "deleted"})
            other.commit()
        with self.assertRaisesRegex(NativeRagError, "authority_changed"): scope.check()

    def test_staging_and_version_drift_are_not_searchable(self):
        self.binding.status = "staging"; self.db.commit()
        with self.assertRaisesRegex(NativeRagError, "migration_required"):
            knowledge.NativeScope(self.db, self.bot, self.client)
        self.binding.status = "ready"; self.doc.version += 1; self.db.commit()
        with self.assertRaisesRegex(NativeRagError, "migration_required"):
            knowledge.NativeScope(self.db, self.bot, self.client)

    def test_partial_migration_cannot_silently_omit_ready_knowledge(self):
        scope = knowledge.NativeScope(self.db, self.bot, self.client)
        self.db.add(Document(bot_id=self.bot.id,organization_id=self.bot.organization_id,
            filename='Unbound.md',source_type='text',status='ready',processing_status='completed'))
        self.db.commit()
        with self.assertRaisesRegex(NativeRagError, 'authority_changed'): scope.check()
        with self.assertRaisesRegex(NativeRagError, 'migration_required'):
            knowledge.NativeScope(self.db,self.bot,self.client)

    def test_real_answer_path_uses_native_bge_and_existing_provider_once(self):
        from services import rag_service
        trace = ChatTrace(self.bot.id, "widget")
        with patch.object(knowledge, "NativeClient", return_value=self.client), \
                patch.object(pipeline, "focused_queries", return_value=["How wide is the desk?"]), \
                patch.object(pipeline.BGEClient, "score", return_value=[1.2]), \
                patch.object(answer, "generate", return_value="The desk is 120 cm wide.") as generate, \
                patch.object(answer, "get_last_generation_metadata", return_value={}), \
                patch.dict(os.environ, {"RAG_COMBINED_RERANKER_URL": "http://ranker.test/rerank", "RAG_COMBINED_RERANKER_TOKEN": "test-token"}):
            reply, sources, chunks = rag_service.answer_question(self.db, self.bot, "How wide is the desk?", trace=trace)
        self.assertEqual(reply, "The desk is 120 cm wide.")
        self.assertEqual(generate.call_count, 1)
        self.assertIs(generate.call_args.kwargs["bot"], self.bot)
        self.assertIn(self.client.hit["content_with_weight"], generate.call_args.kwargs["prompt"])
        self.assertEqual(sources[0]["source_url"], self.doc.source_url)
        self.assertEqual(chunks[0]["metadata"]["native_chunk_id"], "d" * 16)

    def test_outage_is_technical_not_missing_data_and_calls_no_generation(self):
        trace = ChatTrace(self.bot.id, "widget")
        with patch.object(knowledge, "NativeClient", side_effect=NativeRagError("native_service_unavailable")), \
                patch.object(answer, "generate") as generate:
            reply, sources, chunks = answer.answer_question(self.db, self.bot, "desk", trace=trace)
        self.assertEqual(reply, answer.TEMPORARY_SERVICE_REPLY)
        self.assertEqual((sources, chunks), ([], [])); generate.assert_not_called()

    def test_delete_source_persists_exact_native_cleanup_and_removes_mirrors(self):
        self.db.delete(self.doc); self.db.commit()
        tasks = self.db.query(NativeRagCleanup).all()
        self.assertEqual([(t.dataset_id, t.kind, t.resource_id) for t in tasks], [(DATASET, "document", NATIVE_DOC)])
        self.assertEqual(self.db.query(NativeRagChunk).count(), 0)

    def test_cleanup_refuses_active_source_and_retries_failure(self):
        cleanup.enqueue(self.db, self.dataset, "document", NATIVE_DOC); self.db.commit()
        client = Obj(config=CONFIG, request=lambda *args, **kwargs: self.fail("Must not delete active data"))
        self.assertEqual(cleanup.process_pending(self.db, client=client), 0)
        task = self.db.query(NativeRagCleanup).one()
        self.assertEqual(task.error_code, "native_cleanup_source_active")
        self.binding.status = "retired"; self.db.commit()
        client.request = lambda *args, **kwargs: []
        self.assertEqual(cleanup.process_pending(self.db, client=client), 1)
        self.assertEqual(self.db.query(NativeRagDocument).count(), 0)
        self.assertEqual(self.db.query(NativeRagChunk).count(), 0)

    def test_manifest_tamper_never_promotes(self):
        bad = manifest(); bad["chunks"][0]["content"] = "tampered"
        with self.assertRaises(NativeRagError):
            knowledge.store_manifest(self.db, self.doc, self.dataset, bad, version=2, crawl_id=None,
                                     source_sha256=self.doc.content_hash, staging_id="bad")
        self.assertEqual(self.db.query(NativeRagDocument).count(), 1)

    def test_failed_reindex_keeps_previous_ready_binding_and_queues_only_staging(self):
        newer = manifest(); newer['document_id'] = 'e' * 32
        staged = knowledge.store_manifest(self.db, self.doc, self.dataset, newer, version=2,
            crawl_id=None, source_sha256=self.doc.content_hash, staging_id='new-version')
        self.db.commit()
        cleanup.abort_staging(self.db, 'new-version'); self.db.commit()
        self.assertEqual(self.binding.status, 'ready')
        self.assertEqual(staged.status, 'retired')
        self.assertEqual(self.db.query(NativeRagCleanup).one().resource_id, 'e' * 32)
        self.assertEqual(len(knowledge.NativeScope(self.db, self.bot, self.client).rows), 1)

    def test_promotion_atomically_replaces_and_retires_old_source(self):
        newer = manifest(); newer['document_id'] = 'e' * 32
        staged = knowledge.store_manifest(self.db, self.doc, self.dataset, newer, version=2,
            crawl_id=None, source_sha256=self.doc.content_hash, staging_id='new-version')
        with self.assertRaisesRegex(NativeRagError, 'version_mismatch'):
            knowledge.promote(self.db, self.doc, 'new-version')
        self.doc.version = 2
        knowledge.promote(self.db, self.doc, 'new-version'); self.db.commit()
        self.assertEqual(self.binding.status, 'retired')
        self.assertEqual(staged.status, 'ready')
        self.assertEqual(knowledge.NativeScope(self.db, self.bot, self.client).rows[0][1].id, staged.id)

    def test_website_crawl_owner_must_match(self):
        site = Website(bot_id=self.bot.id, organization_id=self.bot.organization_id,
            root_url='https://example.test', domain='example.test', status='ready')
        self.db.add(site); self.db.flush()
        crawl = WebsiteCrawl(website_id=site.id,bot_id=self.bot.id+1,
            organization_id=self.bot.organization_id,version=1,status='ready')
        self.db.add(crawl); self.db.flush()
        site.active_crawl_id=crawl.id
        self.doc.source_type='website'; self.doc.website_id=site.id; self.doc.crawl_id=crawl.id
        self.binding.crawl_id=crawl.id; self.db.commit()
        self.assertEqual(knowledge.NativeScope(self.db,self.bot,self.client).rows,[])
        crawl.bot_id=self.bot.id; self.db.commit()
        self.assertEqual(len(knowledge.NativeScope(self.db,self.bot,self.client).rows),1)

    def test_native_ingestion_uses_official_parse_and_keeps_staging_invisible(self):
        new_id='e'*32
        calls=[]
        def request(method,path,**kwargs):
            calls.append((method,path,kwargs))
            if method=='POST' and path.endswith('/documents'): return [{'id':new_id}]
            if method=='POST' and path.endswith('/chunks'): return True
            if method=='GET' and path.endswith('/documents'): return {'docs':[{'id':new_id,'run':'DONE'}]}
            self.fail('Unexpected request')
        data=manifest(); data['document_id']=new_id
        client=Obj(config=CONFIG,request=request,manifest=lambda *a:data)
        result=ingestion.prepare(self.db,self.doc,text='new source',title='Desk',version=2,crawl_id=None,
            staging_id='ingestion-test',check_cancelled=lambda:None,client=client)
        self.assertEqual(result.binding.status,'staging')
        self.assertEqual(result.embeddings,1)
        self.assertEqual(len(knowledge.NativeScope(self.db,self.bot,self.client).rows),1)
        self.assertEqual(calls[1][2]['body'],{'document_ids':[new_id]})
        self.assertNotIn('embedding', calls[0][2])

    def test_native_parse_failure_preserves_exact_cleanup_identity(self):
        new_id='e'*32
        def request(method,path,**kwargs):
            if method=='POST' and path.endswith('/documents'): return [{'id':new_id}]
            if method=='POST': return True
            return {'docs':[{'id':new_id,'run':'FAIL'}]}
        client=Obj(config=CONFIG,request=request)
        with self.assertRaisesRegex(NativeRagError,'parse_failed'):
            ingestion.prepare(self.db,self.doc,text='new',title='Desk',version=2,crawl_id=None,
                staging_id='failed-test',check_cancelled=lambda:None,client=client)
        self.assertEqual(self.db.query(NativeRagDocument).filter_by(native_document_id=new_id).one().status,'failed')
        self.assertEqual(self.binding.status,'ready')
        cleanup.abort_staging(self.db,'failed-test'); self.db.commit()
        self.assertEqual(self.db.query(NativeRagCleanup).one().resource_id,new_id)

    def test_cleanup_retries_when_remote_delete_acknowledgement_is_lost(self):
        cleanup.retire(self.db,self.binding); self.db.commit()
        state={'deleted':False}
        def request(method,path,**kwargs):
            if path=='/api/v1/datasets': return [{'id':DATASET}]
            if method=='GET': return {'docs':[] if state['deleted'] else [{'id':NATIVE_DOC}]}
            state['deleted']=True
            raise NativeRagError('native_service_unavailable')
        client=Obj(config=CONFIG,request=request)
        self.assertEqual(cleanup.process_pending(self.db,client=client),0)
        self.assertEqual(cleanup.process_pending(self.db,client=client),1)
        self.assertEqual(self.db.query(NativeRagCleanup).one().status,'done')

    def test_bot_deletion_queues_dataset_and_its_documents(self):
        self.db.delete(self.bot); self.db.commit()
        self.assertEqual(self.db.query(NativeRagDataset).count(),0)
        self.assertEqual({x.kind for x in self.db.query(NativeRagCleanup)}, {'dataset','document'})

    def test_existing_text_job_replaces_index_without_old_embedding_calls(self):
        from services import document_processing_service as processing
        client=ParsingClient()
        self.doc.raw_text='The replacement source specifies a 140 cm wide desk.'; self.db.commit()
        with patch.object(ingestion,'NativeClient',return_value=client), \
             patch.object(processing,'generate_embeddings_batch',side_effect=AssertionError('Legacy embedding used')):
            result=processing.process_document(self.db,self.doc.id)
        self.assertEqual(result.status,'ready')
        self.assertEqual(result.version,2)
        self.assertEqual(result.embedding_provider,'ragflow')
        ready=self.db.query(NativeRagDocument).filter_by(status='ready').one()
        self.assertNotEqual(ready.native_document_id,NATIVE_DOC)
        self.assertEqual(self.db.query(NativeRagChunk).filter_by(binding_id=ready.id).one().content,self.doc.raw_text)
        self.assertEqual(self.db.query(NativeRagCleanup).one().resource_id,NATIVE_DOC)

    def test_existing_job_parse_failure_preserves_current_knowledge(self):
        from services import document_processing_service as processing
        client=ParsingClient(); client.fail=True
        with patch.object(ingestion,'NativeClient',return_value=client):
            result=processing.process_document(self.db,self.doc.id)
        self.assertEqual(result.status,'ready')
        self.assertEqual(result.version,1)
        self.assertEqual(self.db.query(NativeRagDocument).filter_by(status='ready').one().native_document_id,NATIVE_DOC)
        self.assertEqual(len(knowledge.NativeScope(self.db,self.bot,self.client).rows),1)

    def test_website_recrawl_promotes_all_pages_and_retires_removed_page(self):
        from services import document_processing_service as processing
        from services.firecrawl_service import Page, CrawlAuditReport
        self.doc.source_type='website'; self.doc.source_url='https://example.test'; self.db.commit()
        client=ParsingClient()
        text='Our desk is made from solid timber and measures 120 cm wide. Delivery is available within the local service area. Contact the store for delivery availability and use a soft dry cloth to care for its surface. '
        pages=[Page(url='https://example.test',title='Home',markdown=text*3),
               Page(url='https://example.test/other',title='Other',markdown=text*3+'Other item information.')]
        audit=CrawlAuditReport(seed_url='https://example.test',discovered_urls=2,eligible_urls=2,crawled_urls=2,stored_documents=2)
        with patch.object(ingestion,'NativeClient',return_value=client), \
             patch.object(processing,'crawl_website',return_value=(pages,audit)):
            result=processing.process_document(self.db,self.doc.id)
        self.assertEqual(result.status,'ready',result.processing_error)
        self.assertEqual(len(knowledge.NativeScope(self.db,self.bot,self.client).rows),2)
        site=self.db.query(Website).one(); previous=site.active_crawl_id
        audit=CrawlAuditReport(seed_url='https://example.test',discovered_urls=1,eligible_urls=1,crawled_urls=1,stored_documents=1)
        with patch.object(ingestion,'NativeClient',return_value=client), \
             patch.object(processing,'crawl_website',return_value=(pages[:1],audit)):
            result=processing.process_document(self.db,self.doc.id)
        self.assertEqual(result.status,'ready',result.processing_error)
        self.assertNotEqual(site.active_crawl_id,previous)
        self.assertEqual(len(knowledge.NativeScope(self.db,self.bot,self.client).rows),1)
        removed=self.db.query(Document).filter_by(source_url='https://example.test/other').one()
        self.assertEqual(removed.status,'stale')
        self.assertEqual(self.db.query(NativeRagDocument).filter_by(document_id=removed.id,status='ready').count(),0)


    def test_clone_queues_independent_knowledge_and_preserves_provider(self):
        from services import bot_service
        self.bot.provider_api_key='synthetic-custom-key'
        self.db.commit()
        with patch.object(bot_service,'get_bot_or_404',return_value=self.bot), \
             patch.object(bot_service,'ensure_can_create_bot'), \
             patch.object(bot_service,'ensure_can_promote_knowledge'), \
             patch.object(bot_service,'refresh_resource_usage'), \
             patch('services.queue_service.enqueue_ingestion_job') as enqueue:
            result=bot_service.clone_bot(self.db,self.bot.id,user=Obj(id=1))
        clone=self.db.get(Bot,result['bot_id'])
        doc=self.db.query(Document).filter_by(bot_id=clone.id).one()
        self.assertEqual((clone.provider,clone.model_name),(self.bot.provider,self.bot.model_name))
        self.assertEqual(doc.raw_text,self.doc.raw_text)
        self.assertEqual((doc.status,doc.processing_status,doc.chunk_count),('uploaded','pending',0))
        self.assertEqual(self.db.query(NativeRagDataset).filter_by(bot_id=clone.id).count(),0)
        self.assertEqual(self.db.query(NativeRagDocument).filter_by(document_id=doc.id).count(),0)
        self.assertEqual(enqueue.call_args.args[1:4],(clone.id,clone.organization_id,doc.id))


class NativeMigrationTests(unittest.TestCase):
    def test_upgrade_metadata_reentry_and_safe_downgrade(self):
        import importlib.util
        from sqlalchemy import create_engine, inspect, text
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        path=Path(__file__).parent/'migrations/versions/20260928_01_native_rag_bindings.py'
        spec=importlib.util.spec_from_file_location('native_migration',path)
        migration=importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
        local=create_engine('sqlite://')
        with local.begin() as connection:
            for table in ('bots','organizations','documents'):
                connection.execute(text('CREATE TABLE '+table+' (id INTEGER PRIMARY KEY)'))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade(); migration.upgrade()
                names=set(inspect(connection).get_table_names())
                self.assertTrue({'native_rag_datasets','native_rag_documents','native_rag_chunks','native_rag_cleanup'} <= names)
                connection.execute(text("INSERT INTO native_rag_datasets VALUES (1,1,1,:tenant,:dataset,CURRENT_TIMESTAMP)"),{'tenant':TENANT,'dataset':DATASET})
                with self.assertRaisesRegex(RuntimeError,'Native knowledge exists'): migration.downgrade()
                connection.execute(text('DELETE FROM native_rag_datasets'))
                migration.downgrade()
                self.assertEqual(set(inspect(connection).get_table_names()),{'bots','organizations','documents'})
                connection.execute(text('CREATE TABLE native_rag_datasets (id INTEGER)'))
                with self.assertRaisesRegex(RuntimeError,'Partial native schema'): migration.upgrade()
        local.dispose()


class ClientTests(unittest.TestCase):
    def test_native_http_contract_cannot_override_frozen_weights_or_scope(self):
        def handle(request):
            self.assertEqual(request.url.path, "/v1/saas_native/retrieve")
            self.assertEqual(json.loads(request.content), {"question": "q", "dataset_id": DATASET, "document_ids": [NATIVE_DOC]})
            return httpx.Response(200, json={"code": 0, "data": {
                "policy": SEARCH_POLICY, "tenant_id": TENANT, "dataset_id": DATASET, "chunks": []}})
        client = NativeClient(CONFIG, transport=httpx.MockTransport(handle))
        self.assertEqual(client.search("q", DATASET, [NATIVE_DOC]), [])

    def test_changed_server_policy_or_redirect_fails(self):
        for response in (httpx.Response(302, headers={"Location": "http://outside.invalid"}),
                         httpx.Response(200, json={"code": 0, "data": {"policy": {"candidates": 64}}})):
            client = NativeClient(CONFIG, transport=httpx.MockTransport(lambda _: response))
            with self.assertRaises(NativeRagError): client.search("q", DATASET, [NATIVE_DOC])


if __name__ == "__main__": unittest.main()
