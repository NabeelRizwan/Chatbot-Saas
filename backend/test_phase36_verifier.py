"""Prose verification shares existing staged deadlines; no live provider."""
import contextlib
import time
import unittest
from threading import Event
from types import SimpleNamespace as NS
from unittest.mock import patch
from services import llm_router as router, conversational_engine as engine
from services.providers.base_provider import auxiliary_budget, ProviderError, ProviderErrorKind


class Verification(unittest.TestCase):
    def run_case(self,*,setup=.04,provider=.002,cleanup=.04,error=None):
        done=Event();seen=[]
        @contextlib.contextmanager
        def guard(*a,**kw):
            time.sleep(setup)
            try:yield True
            finally:time.sleep(cleanup)
        def response(**kw):
            seen.append(dict(budget=auxiliary_budget.get(),model=kw['model_name']))
            time.sleep(provider)
            if error:raise error
            return NS(text='A qualified supported answer.',provider='fixture',model='fixture',usage=NS(total_tokens=10,input_tokens=8,output_tokens=2))
        def account(*a):done.set()
        original=router.generate_auxiliary
        bot=NS(id=1,organization_id=1,provider='fixture',model_name='fixture',provider_api_key=None,capabilities={})
        with patch.dict(router.PROVIDERS,fixture=NS(generate_with_metadata=response)),patch.dict('os.environ',RAG_AUX_MODEL_FIXTURE='other-model'), \
             patch.object(router,'_resolve_api_key',return_value=('synthetic-placeholder',True)), \
             patch.object(router,'_track_usage',side_effect=account) as usage, \
             patch('services.llm_client.distributed_concurrency_guard',guard),patch('services.llm_client.global_circuit_breaker'), \
             patch.object(router,'generate_auxiliary',side_effect=lambda *a,**kw:original(*a,**(kw|{'timeout':.025}))) as aux:
            result=engine.verify_answer(bot,'How should it be used?','Original draft.','Use as directed.','Be accurate.')
            if error is None:self.assertTrue(done.wait(2))
            else:time.sleep(setup+cleanup+provider+.02)
            self.assertEqual(aux.call_count,1)
            self.assertEqual(len(seen),1)
            self.assertEqual(seen[0]['model'],'fixture')
            self.assertFalse(seen[0]['budget']['json_mode'])
            self.assertEqual(usage.call_count,0 if error else 1)
            return result,router.get_last_auxiliary_metadata()

    def test_setup_overhead_does_not_consume_inference_budget(self):
        result,meta=self.run_case()
        self.assertEqual(result,'A qualified supported answer.')
        self.assertEqual(meta['provider_status'],'success')
        self.assertIsNone(meta['timeout_stage'])

    def test_real_provider_timeout_retains_draft(self):
        result,meta=self.run_case(setup=0,provider=.08,cleanup=0)
        self.assertEqual(result,'Original draft.')
        self.assertEqual(meta['timeout_stage'],'provider')

    def test_quota_failure_not_wrapper_timeout(self):
        error=ProviderError('synthetic quota',status_code=429,kind=ProviderErrorKind.RATE_LIMIT)
        result,meta=self.run_case(setup=0,cleanup=0,error=error)
        self.assertEqual(result,'Original draft.')
        self.assertEqual(meta['provider_status'],'error')
        self.assertIsNone(meta['timeout_stage'])

    def test_accounting_cleanup_not_provider_timeout(self):
        result,meta=self.run_case(setup=0,cleanup=.08)
        self.assertEqual(result,'A qualified supported answer.')
        self.assertGreater(meta['cleanup_ms'],50)
        self.assertIsNone(meta['timeout_stage'])

    def test_empty_or_failed_provider_retains_draft(self):
        result,meta=self.run_case(setup=0,cleanup=0,error=ValueError('synthetic invalid response'))
        self.assertEqual(result,'Original draft.')
        self.assertEqual(meta['provider_status'],'error')

if __name__=='__main__':unittest.main()
