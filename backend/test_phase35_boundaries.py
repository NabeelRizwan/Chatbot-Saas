"""Actual selection handoff, field scope and shared-deadline safety boundaries."""
import contextlib
import time
import unittest
from threading import Event
from types import SimpleNamespace as NS
from unittest.mock import patch

from services import llm_router as router, rag_service as rag, rag_planning as planning
from services.query_contract import extract_requested_fields
from services.requested_propositions import annotate_candidates, update_support
from services.observability_service import ChatTrace, evidence_key
from services.retrieval_selection import POLICY
from services.semantic_scope import comparison_mentions
from test_phase35_live_repair import contract, item, VALUES
from test_required_evidence_retention import retrieve_fixture
from test_phase_l3_multi_entity_conversational_rag import document, chunk


class FieldAndSelectionBoundaries(unittest.TestCase):
    def test_meals_as_amenities_not_dosing(self):
        for q in ['Do rooms with meals cost more?', 'Which course is before lunch?', 'Show restaurants with food.']:
            with self.subTest(q=q): self.assertNotIn('directions',extract_requested_fields(q))

    def test_internal_conjunction_in_identity_preserved(self):
        self.assertEqual(comparison_mentions('Between Terms and Conditions and Privacy Notice, which has cancellation?',
            ['Terms and Conditions','Privacy Notice']),('terms and conditions','privacy notice'))

    def test_plain_take_non_usage(self):
        for q in ['What does this take into account?', 'Does it take over the server?', 'Will they take part?']:
            with self.subTest(q=q): self.assertNotIn('directions',extract_requested_fields(q))

    def test_required_pool_hard_cap_and_trace(self):
        c=contract(['directions','duration'])
        rows=annotate_candidates(c,[item(d,d*100+i,VALUES[f],[f],score=0.01)
            for d in (1,2) for i,f in enumerate(c.requested_fields)])
        tr=ChatTrace(1,'test')
        kept=POLICY.select(rows,2,1,[1,2],tr.retrieval)
        self.assertEqual(len(kept),2)
        self.assertEqual({evidence_key(r)[0] for r in kept},{1,2})
        decisions=[r.indicators['field_reservation'] for r in tr.retrieval.candidates.values()]
        self.assertEqual(sum(r['reserved'] for r in decisions),2)
        self.assertTrue(any(r['drop_reason']=='excluded_document_cap' for r in decisions))

    def test_foreign_resource_cannot_support_obligation(self):
        c=contract(['directions','duration'])
        rows=annotate_candidates(c,[item(99,99,VALUES['directions'],['directions'])])
        update_support(c,rows)
        self.assertFalse(any(p.supporting_candidate_ids for p in c.requested_propositions))

    def test_reviewer_foreign_field_reference_is_not_proof(self):
        c=contract(['directions','duration'])
        rows=annotate_candidates(c,[item(1,100,VALUES['directions'],['directions']),item(2,200,VALUES['directions'],['directions'])])
        tr=ChatTrace(1,'test')
        tr.retrieval.reviewer_outcome={'proposition_support':[dict(proposition_id='field:1:directions',support_state='supported',supporting_candidate_ids=[[2,200]],contradicting_candidate_ids=[])]}
        update_support(c,rows,tr)
        p=next(p for p in c.requested_propositions if p.id=='field:1:directions')
        self.assertNotEqual(p.support_state,'supported')
        self.assertEqual(p.supporting_candidate_ids,[[1,100]])

    def test_real_recall_field_scan_pool_context(self):
        docs=[document(1,'Cedar Liquid'),document(2,'Birch Tablets')]
        pairs=[]
        for d in docs:
            for i in range(35):
                c=chunk(d.id*100+i,i,f'Overview: extra optional detail {i}. ' * 12)
                c.document_id=d.id
                pairs.append((c,d))
            for i,f in enumerate(['directions','results_timeframe']):
                c=chunk(d.id*100+70+i,70+i,VALUES[f]);c.document_id=d.id;pairs.append((c,d))
        q='Compare Cedar Liquid and Birch Tablets on directions and results timeframe.'
        tr=ChatTrace(1,'test')
        with patch.object(rag,'ChatTrace',return_value=tr):
            rows,c,tr=retrieve_fixture(docs,pairs,q,with_trace=True)
        wanted={(d,100*d+70+i) for d in (1,2) for i in (0,1)}
        self.assertTrue(wanted<={evidence_key(r) for r in rows})
        self.assertLessEqual(len(rows),48)
        retained,ctx,_,_=rag._bounded_generation_context(rows,q,3500,'comparison',c,tr)
        self.assertTrue(wanted<={evidence_key(r) for r in retained})
        self.assertLessEqual(len(ctx),3500)

    def test_test_only_cache_bypass_restores_methods(self):
        from scripts.phase35_test_support import isolated_answer_caches
        old_get=rag.global_semantic_cache.get
        old_cache=rag._RETRIEVAL_CACHE
        with isolated_answer_caches():
            self.assertIsNone(rag.global_semantic_cache.get(1,'same exact question'))
            self.assertIsNot(rag._RETRIEVAL_CACHE,old_cache)
        self.assertEqual(rag.global_semantic_cache.get,old_get)
        self.assertIs(rag._RETRIEVAL_CACHE,old_cache)


class DeadlineSafety(unittest.TestCase):
    def fake(self, function):
        stack=contextlib.ExitStack()
        stack.enter_context(patch.dict(router.PROVIDERS,fixture=NS(generate_with_metadata=function)))
        stack.enter_context(patch.object(router,'_resolve_api_key',return_value=('synthetic',False)))
        stack.enter_context(patch.object(router,'execute_with_resilience',side_effect=lambda fn,*a,**k:fn()))
        return stack

    bot=NS(id=1,organization_id=1,provider='fixture',model_name='fixture',provider_api_key=None)

    def test_setup_deadline_never_launches_late_provider(self):
        finished=Event()
        def key(*a):
            try: time.sleep(0.08);return ('synthetic',False)
            finally: finished.set()
        with self.fake(lambda **k:NS(text='{}',usage=None)), \
             patch.object(router,'_resolve_api_key',side_effect=key), \
             patch.object(router,'AUXILIARY_SETUP_TIMEOUT',0.02):
            with self.assertRaises(router.AuxiliaryDeadlineExceeded) as error:
                router.generate_auxiliary(self.bot,'{}','schema')
            self.assertEqual(error.exception.stage,'setup')
            self.assertTrue(finished.wait(1))
            time.sleep(0.02)
        self.assertEqual(router.get_last_auxiliary_metadata()['timeout_stage'],'setup')

    def test_accounting_cleanup_pending_is_not_provider_failure(self):
        done=Event()
        def usage(*args): time.sleep(0.08);done.set()
        with self.fake(lambda **k:NS(text='{}',usage=None)), \
             patch.object(router,'_resolve_api_key',return_value=('synthetic',True)), \
             patch.object(router,'_track_usage',side_effect=usage), \
             patch.object(router,'AUXILIARY_CLEANUP_TIMEOUT',0.01):
            self.assertEqual(router.generate_auxiliary(self.bot,'{}','schema',timeout=0.04),'{}')
            timing=router.get_last_auxiliary_metadata()
            self.assertEqual(timing['provider_status'],'success')
            self.assertTrue(timing['cleanup_pending'])
            self.assertTrue(done.wait(1))
            time.sleep(0.02)

    def test_success_stage_times_reconcile(self):
        with self.fake(lambda **k:NS(text='{}',usage=None)):
            self.assertEqual(router.generate_auxiliary(self.bot,'{}','schema'),'{}')
        timing=router.get_last_auxiliary_metadata()
        total=sum(timing[k] for k in ['queue_ms','key_resolution_ms','concurrency_acquisition_ms','provider_ms','cleanup_ms','usage_accounting_ms'])
        self.assertAlmostEqual(total,timing['total_ms'],delta=15)
        self.assertIsNone(timing['timeout_stage'])

    def test_usage_error_does_not_lose_completion_or_slot(self):
        from services.providers.base_provider import auxiliary_budget
        with self.fake(lambda **k:NS(text='{}',usage=None)), \
             patch.object(router,'_resolve_api_key',return_value=('synthetic',True)), \
             patch.object(router,'_track_usage',side_effect=RuntimeError('synthetic accounting failure')):
            self.assertEqual(router.generate_auxiliary(self.bot,'{}','schema'),'{}')
        self.assertEqual(router.get_last_auxiliary_metadata()['usage_error'],'RuntimeError')
        self.assertIsNone(auxiliary_budget.get())

    def test_four_timed_out_calls_keep_slots_until_exit(self):
        from threading import BoundedSemaphore
        release=Event()
        exits=[]
        def provider(**kw):
            release.wait(2)
            exits.append(1)
            return NS(text='{}',usage=None)
        with self.fake(provider), patch.object(router,'_auxiliary_slots',BoundedSemaphore(4)):
            try:
                for _ in range(4):
                    with self.assertRaises(TimeoutError):
                        router.generate_auxiliary(self.bot,'{}','schema',timeout=0.01)
                with self.assertRaises(router.LLMRouterError):
                    router.generate_auxiliary(self.bot,'{}','schema',timeout=0.01)
            finally:
                release.set()
                deadline=time.monotonic()+2
                while len(exits)<4 and time.monotonic()<deadline: time.sleep(0.01)
                self.assertEqual(len(exits),4)
                time.sleep(0.03)


if __name__=='__main__': unittest.main()
