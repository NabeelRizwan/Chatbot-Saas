import unittest
from unittest.mock import Mock
from types import SimpleNamespace as NS
import httpx
from google.genai import errors
from scripts.canary_provider_recovery import classify,RecoverableGemini,ProviderHold
from scripts.canary_bounded_output import bounded_json
from scripts.canary_gemini_embeddings import configuration,real_profile


class Diagnostics(unittest.TestCase):
    def test_http_classes(self):
        for code,category in [(400,'INVALID_INPUT'),(401,'AUTH'),(403,'PERMISSION'),
                (429,'RATE_LIMIT'),(500,'SERVER_500'),(502,'SERVER_502'),(503,'SERVER_503'),(504,'SERVER_504')]:
            with self.subTest(code=code):
                value=classify(errors.APIError(code,{'error':{'status':'RESOURCE_EXHAUSTED','message':'SECRET'}}))
                self.assertEqual(value['category'],category)
                self.assertNotIn('SECRET',bounded_json(value))

    def test_generic_429_not_quota(self):
        self.assertEqual(classify(errors.ClientError(429,{'error':{'status':'RESOURCE_EXHAUSTED'}}))['category'],'RATE_LIMIT')

    def test_structured_quota_only(self):
        exc=errors.ClientError(429,{'error':{'details':[{'@type':'type.googleapis.com/google.rpc.QuotaFailure',
            'violations':[{'subject':'not emitted','description':'not emitted'}]}]}})
        self.assertEqual(classify(exc)['category'],'QUOTA_EXHAUSTED')
        self.assertNotIn('not emitted',bounded_json(classify(exc)))

    def test_unknown_status_not_message_parsed(self):
        self.assertEqual(classify(RuntimeError('429 quota reached SECRET'))['category'],'UNKNOWN_PROVIDER_FAILURE')

    def test_transport_and_timeout(self):
        for exc,category in [(httpx.ReadTimeout('SECRET'), 'TIMEOUT'),(httpx.ConnectError('SECRET'),'TRANSPORT')]:
            self.assertEqual(classify(exc)['category'],category)
            self.assertEqual(classify(exc)['consumption'],'UNKNOWN')

    def test_retry_after_bounded(self):
        for raw,expected in [('12',12.0),('18001',None),('-1',None),('SECRET',None),('NaN',None)]:
            response=httpx.Response(429,headers={'Retry-After':raw})
            self.assertEqual(classify(errors.ClientError(429,{},response))['retry_after_seconds'],expected)

    def test_arbitrary_enum_never_persisted(self):
        self.assertIsNone(classify(errors.ClientError(400,{'status':'SECRET'}))['provider_status'])


class Transport(unittest.TestCase):
    def setUp(self):
        self.factory=Mock();self.records=[];self.pauses=[]
        self.client=self.factory.return_value
        self.client.models.embed_content.return_value=NS(embeddings=[NS(values=[.1]*768,statistics=None)])
        self.provider=RecoverableGemini('fake',organization_id=1,bot_id=2,approved=True,
            client_factory=self.factory,on_attempt=self.records.append,pause=self.pauses.append)
        self.addCleanup(self.provider.close)

    def test_success_profile_f32_and_attempt_sink(self):
        r=self.provider.embed(['an input'],purpose='evidence')[0]
        self.assertEqual(r.profile_hash,real_profile().canonical_hash())
        self.assertEqual(len(r.vector),768)
        self.assertEqual([v['result'] for v in self.records],['STARTED','SUCCEEDED'])
        for v in self.records:bounded_json(v)
        self.assertEqual(self.factory.call_args.kwargs['http_options'].retry_options.attempts,1)
        self.assertEqual(self.client.models.embed_content.call_args.kwargs['config'].output_dimensionality,768)

    def test_only_three_attempts_and_safe_hold(self):
        self.client.models.embed_content.side_effect=errors.ServerError(503,{'message':'SECRET'})
        with self.assertRaises(ProviderHold) as caught:self.provider.embed(['a'],purpose='evidence',retries=2)
        self.assertEqual(self.client.models.embed_content.call_count,3)
        self.assertEqual(caught.exception.diagnostic['category'],'SERVER_503')
        self.assertEqual(self.pauses,[2,4])
        self.assertNotIn('SECRET',str(self.records))

    def test_no_auth_invalid_retry(self):
        for code in (400,401,403):
            self.client.models.embed_content.reset_mock()
            self.client.models.embed_content.side_effect=errors.ClientError(code,{})
            with self.assertRaises(ProviderHold):self.provider.embed(['a'],purpose='evidence',retries=2)
            self.assertEqual(self.client.models.embed_content.call_count,1)

    def test_retry_after_honored(self):
        ok=self.client.models.embed_content.return_value
        self.client.models.embed_content.side_effect=[errors.ClientError(429,{},httpx.Response(429,headers={'Retry-After':'7'})),ok]
        self.provider.embed(['a'],purpose='evidence',retries=2)
        self.assertEqual(self.pauses,[7.0])

    def test_deadline_no_spend(self):
        self.provider.deadline=self.provider.clock()+1
        with self.assertRaisesRegex(ValueError,'WALL_DEADLINE'):self.provider.embed(['a'],purpose='evidence')
        self.client.models.embed_content.assert_not_called()

    def test_invalid_dimension_no_retry(self):
        self.client.models.embed_content.return_value=NS(embeddings=[NS(values=[1.0]*3)])
        with self.assertRaises(ProviderHold):self.provider.embed(['a'],purpose='evidence',retries=2)
        self.assertEqual(self.client.models.embed_content.call_count,1)
        self.assertEqual(self.records[-1]['category'],'INVALID_RESPONSE')

    def test_durable_sink_failure_stops_before_http(self):
        self.provider.on_attempt=Mock(side_effect=RuntimeError('local sink failure'))
        with self.assertRaises(RuntimeError):self.provider.embed(['a'],purpose='evidence')
        self.client.models.embed_content.assert_not_called()

    def test_frozen_configuration_hash_preserved(self):
        self.assertEqual(real_profile().canonical_hash(),'bd524bb94626d8d5f5282b286beffeb5fc806011685d18af16fa24619cc7e407')
        self.assertEqual(configuration()['request'],{'output_dimensionality':768})


if __name__=='__main__':unittest.main()
