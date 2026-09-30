"""Public HTTP/session delivery using native evidence and an isolated SQLite database."""
from contextlib import ExitStack
import json
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import patch
import test_native_rag as fixture
from database.connection import SessionLocal, get_db
from database.models import ConversationMessage, MessageUsageReservation
from services.native_rag import knowledge, answer
from services.combined_rag import pipeline
from services import rag_service
from utils.redis_client import set_redis_override
from routes import public_routes
from fastapi import FastAPI
from fastapi.testclient import TestClient
import fakeredis


class PublicNativeIntegrationTests(unittest.TestCase):
    def setUp(self):
        fixture.NativeDatabaseTests.setUp(self)
        self.bot.allowed_origins=['http://testserver']; self.db.commit()
        set_redis_override(fakeredis.FakeRedis(decode_responses=True))
        self.stack=ExitStack()
        self.stack.enter_context(patch('services.native_rag.knowledge.NativeClient',return_value=fixture.Client()))
        self.stack.enter_context(patch.object(pipeline,'focused_queries',side_effect=lambda b,q,c,t:[q]))
        self.stack.enter_context(patch.object(pipeline,'BGEClient',return_value=Obj(score=lambda q,docs:[.8]*len(docs))))
        self.stack.enter_context(patch.object(pipeline.Config,'from_env',return_value=Obj()))
        self.generate=self.stack.enter_context(patch.object(answer,'generate',return_value='The desk is 120 cm wide.'))
        self.stack.enter_context(patch.object(answer,'get_last_generation_metadata',return_value={'provider':'gemini'}))
        app=FastAPI(); app.include_router(public_routes.router,prefix='/public')
        def db_dependency():
            with SessionLocal() as db: yield db
        app.dependency_overrides[get_db]=db_dependency
        self.http=TestClient(app,headers={'Origin':'http://testserver'})
        self.credential=self.http.post(f'/public/widget/{self.bot.id}/session').json()

    def tearDown(self):
        self.http.close(); self.stack.close(); set_redis_override(None,None)
        fixture.NativeDatabaseTests.tearDown(self)

    def submit(self,question='How wide is the desk?',turn='native-http-one',**extra):
        return self.http.post(f'/public/chat/{self.bot.id}/stream',json={
            **self.credential,'message':question,'turn_id':turn,**extra})

    def test_widget_sse_delivers_and_persists_once_under_existing_provider(self):
        result=self.submit(); self.assertEqual(result.status_code,200)
        frames=[json.loads(line[6:]) for line in result.text.splitlines() if line.startswith('data: ')]
        self.assertEqual(''.join(f.get('token','') for f in frames),'The desk is 120 cm wide.')
        self.assertTrue(any(f.get('type')=='done' for f in frames))
        self.assertNotIn('content_with_weight',result.text)
        self.assertEqual(self.generate.call_args.kwargs['bot'].provider,'gemini')
        self.assertIn('Final complete source.',self.generate.call_args.kwargs['prompt'])
        self.assertEqual(self.db.query(ConversationMessage).count(),1)
        self.assertEqual(self.db.query(MessageUsageReservation).one().status,'consumed')
        again=self.submit(); self.assertEqual(again.status_code,200)
        self.assertEqual(self.generate.call_count,1)
        self.assertEqual(self.db.query(ConversationMessage).count(),1)

    def test_bad_session_and_origin_never_reach_native_or_generation(self):
        bad=self.http.post(f'/public/chat/{self.bot.id}/stream',json={
            **self.credential,'session_token':'wrong','message':'q','turn_id':'bad'})
        self.assertIn(bad.status_code,(401,403))
        bad=self.http.post(f'/public/chat/{self.bot.id}/stream',headers={'Origin':'https://foreign.test'},
            json={**self.credential,'message':'q','turn_id':'bad-origin'})
        self.assertEqual(bad.status_code,403)
        self.generate.assert_not_called()

    def test_followup_uses_stored_session_history_at_existing_ai_boundary(self):
        self.submit()
        with patch.object(answer,'generate_auxiliary',return_value='What is the width of the desk?') as rewrite:
            result=self.submit('And its width?',turn='native-http-two')
        self.assertEqual(result.status_code,200)
        self.assertIn('120 cm',result.text)
        self.assertIn('How wide is the desk?',rewrite.call_args.args[1])
        self.assertIn('120 cm',rewrite.call_args.args[1])
        self.assertFalse(rewrite.call_args.kwargs['use_auxiliary_model'])

    def test_revoked_source_during_generation_is_not_delivered(self):
        def revoke(**kwargs):
            with SessionLocal() as db:
                from database.models import Document
                db.query(Document).filter_by(id=self.doc.id).update({'status':'deleted'}); db.commit()
            return 'The desk is 120 cm wide.'
        self.generate.side_effect=revoke
        result=self.submit()
        self.assertNotIn('120 cm',result.text)
        self.assertNotIn('"type": "sources"',result.text)
        self.assertIn('"type": "error"',result.text)
        self.assertEqual(self.db.query(MessageUsageReservation).one().status,'released')

    def test_native_failure_does_not_call_retired_postgres_retriever(self):
        with patch.object(knowledge.NativeScope,'retrieve',side_effect=RuntimeError('offline')), \
             patch.object(rag_service,'retrieve_relevant_chunks',side_effect=AssertionError('Old route used')):
            result=self.submit()
        self.assertEqual(result.status_code,200)
        self.generate.assert_not_called()
        self.assertNotIn('120 cm',result.text)
        self.assertIn('"type": "error"',result.text)
        self.assertEqual(self.db.query(MessageUsageReservation).one().status,'released')
        self.assertEqual(self.db.query(ConversationMessage).one().status,'error')
        retry=self.submit(retry=True)
        self.assertIn('120 cm',retry.text)
        self.db.expire_all()
        self.assertEqual(self.db.query(MessageUsageReservation).one().status,'consumed')
        self.assertEqual(self.db.query(ConversationMessage).count(),1)

    def test_nonstream_native_failure_releases_existing_quota(self):
        with patch.object(knowledge.NativeScope,'retrieve',side_effect=RuntimeError('offline')):
            response=self.http.post(f'/public/chat/{self.bot.id}',json={
                **self.credential,'message':'How wide is the desk?','turn_id':'native-http-failure'})
        self.assertEqual(response.status_code,503)
        self.assertEqual(self.db.query(MessageUsageReservation).one().status,'released')
        self.generate.assert_not_called()


if __name__=='__main__': unittest.main()
