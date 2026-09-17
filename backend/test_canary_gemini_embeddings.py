"""Offline Phase P provider/secret/budget contract, with no real calls."""
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from scripts.canary_gemini_embeddings import (GeminiCanary, MODEL, configuration,
    real_profile, bounded_batches)
from services.canary_contracts import CanaryError, canonical_vector_bytes
from services.canary_representation import exact_input_hash


def response(n=1, vector=None, truncated=False):
    return NS(embeddings=[NS(values=vector if vector is not None else [0.1] * 768,
        statistics=NS(token_count=3, truncated=truncated)) for _ in range(n)])


class Embeddings(unittest.TestCase):
    def setUp(self):
        self.factory = Mock()
        self.client = self.factory.return_value
        self.client.models.embed_content.return_value = response()
        self.canary = GeminiCanary('offline-test-only', organization_id=1, bot_id=2,
            approved=True, client_factory=self.factory, pause=Mock())
        self.addCleanup(self.canary.close)

    def test_explicit_approval(self):
        with self.assertRaisesRegex(CanaryError, 'AUTHORIZATION'):
            GeminiCanary('offline', organization_id=1, bot_id=2)

    def test_missing_key(self):
        with self.assertRaisesRegex(CanaryError, 'CREDENTIAL'):
            GeminiCanary('', organization_id=1, bot_id=2, approved=True)

    def test_transport_fixed_and_sdk_retry_disabled(self):
        args = self.factory.call_args.kwargs
        self.assertFalse(args['vertexai'])
        self.assertEqual(args['http_options'].retry_options.attempts, 1)
        self.assertEqual(args['http_options'].timeout, 45000)
        self.assertEqual(args['http_options'].base_url, 'https://generativelanguage.googleapis.com')

    def test_exact_request_and_no_new_normalization(self):
        self.canary.embed(['  Café\n'], purpose='evidence')
        args = self.client.models.embed_content.call_args.kwargs
        self.assertEqual(args['contents'], ['  Café\n'])
        self.assertEqual(args['model'], MODEL)
        self.assertEqual(args['config'].model_dump(exclude_none=True), {'output_dimensionality':768})

    def test_f32_and_receipt(self):
        receipt, = self.canary.embed(['sample'], purpose='evidence')
        self.assertEqual(len(canonical_vector_bytes(receipt.vector)), 3072)
        self.assertEqual(receipt.input_hash, exact_input_hash('sample'))
        self.assertEqual(receipt.profile_hash, self.canary.profile.canonical_hash())
        self.assertEqual((receipt.organization_id, receipt.bot_id), (1,2))
        self.assertEqual(receipt, self.canary.receipt('sample'))

    def test_missing_receipt(self):
        with self.assertRaisesRegex(CanaryError, 'ATTESTATION_REQUIRED'):
            self.canary.receipt('other')

    def test_ordering(self):
        self.client.models.embed_content.return_value = NS(embeddings=[
            NS(values=[x]*768, statistics=None) for x in (0.1,0.2)])
        result = self.canary.embed(['first','second'], purpose='evidence')
        self.assertLess(result[0].vector[0], result[1].vector[0])
        self.assertEqual(result[1].input_hash, exact_input_hash('second'))

    def test_cardinality_atomic(self):
        with self.assertRaisesRegex(CanaryError, 'CARDINALITY'):
            self.canary.embed(['one','two'], purpose='evidence')
        self.assertFalse(self.canary.ledger)

    def test_response_truncation_refused(self):
        self.client.models.embed_content.return_value = response(truncated=True)
        with self.assertRaisesRegex(CanaryError, 'TRUNCATED'):
            self.canary.embed(['one'], purpose='evidence')
        self.assertFalse(self.canary.ledger)

    def test_no_sanity_retry_or_secret_exception(self):
        self.client.models.embed_content.side_effect = RuntimeError('fake-secret-details')
        with self.assertRaisesRegex(CanaryError, '^GEMINI_EMBEDDING_PROVIDER_FAILURE$'):
            self.canary.embed(['one'], purpose='evidence')
        self.assertEqual(self.client.models.embed_content.call_count,1)
        self.assertNotIn('fake-secret',str(self.canary.attempts))
        self.assertFalse(self.canary.ledger)

    def test_auth_never_retried(self):
        error = RuntimeError('private'); error.code = 403
        self.client.models.embed_content.side_effect = error
        with self.assertRaises(CanaryError):
            self.canary.embed(['one'], purpose='evidence', retries=2)
        self.assertEqual(self.client.models.embed_content.call_count,1)

    def test_one_retry_owner_max_two(self):
        error = RuntimeError('private'); error.code = 503
        self.client.models.embed_content.side_effect = [error,error,response()]
        self.canary.embed(['one'], purpose='evidence', retries=2)
        self.assertEqual(self.client.models.embed_content.call_count,3)
        self.assertEqual(self.canary.metrics['retried'],2)

    def test_parallel_refused(self):
        self.canary.lock.acquire()
        try:
            with self.assertRaisesRegex(CanaryError,'PARALLEL'):
                self.canary.embed(['one'], purpose='evidence')
        finally:
            self.canary.lock.release()
        self.client.models.embed_content.assert_not_called()

    def test_deadline(self):
        self.canary.started -= 10801
        with self.assertRaisesRegex(CanaryError,'DEADLINE'):
            self.canary.embed(['one'], purpose='evidence')
        self.client.models.embed_content.assert_not_called()

    def test_reuse_exact_input_only(self):
        self.canary.embed(['one'],purpose='evidence')
        self.canary.embed(['one'],purpose='query')
        self.assertEqual(self.client.models.embed_content.call_count,1)
        self.canary.embed(['one '],purpose='query')
        self.assertEqual(self.client.models.embed_content.call_count,2)

    def test_no_cross_tenant_reuse(self):
        self.canary.embed(['one'],purpose='evidence')
        self.canary.scope=(2,2)
        self.canary.embed(['one'],purpose='evidence')
        self.assertEqual(self.client.models.embed_content.call_count,2)

    def test_no_unknown_profile_reuse(self):
        self.canary.embed(['one'],purpose='evidence')
        self.canary.profile=self.canary.profile.model_copy(update={'configuration_hash':'a'*64})
        with self.assertRaisesRegex(CanaryError,'ATTESTATION_REQUIRED'):
            self.canary.receipt('one')

    def test_no_synthetic_reuse(self):
        self.assertFalse(self.canary.ledger)
        self.assertEqual(self.canary.profile.source,'REAL_PROVIDER')

    def test_closes_and_clears(self):
        self.canary.embed(['one'],purpose='evidence')
        self.canary.close()
        self.assertFalse(self.canary.ledger)
        with self.assertRaises(CanaryError):
            self.canary.embed(['one'],purpose='evidence')

    def test_accounting(self):
        self.canary.embed(['one'],purpose='evidence')
        self.canary.embed(['other'],purpose='query')
        self.assertEqual(self.canary.metrics['new_vectors'],1)
        self.assertEqual(self.canary.metrics['query_embeddings'],1)
        self.assertEqual(self.canary.metrics['provider_tokens'],6)

    def test_unknown_usage_not_invented(self):
        self.client.models.embed_content.return_value=NS(embeddings=[NS(values=[.1]*768,statistics=None)])
        self.canary.embed(['one'],purpose='evidence')
        self.assertEqual(self.canary.metrics['unknown_usage_attempts'],1)
        self.assertEqual(self.canary.metrics['provider_tokens'],0)

    def test_caps(self):
        for field,value in (('new_vectors',2500),('local_input_tokens',500000)):
            with self.subTest(field=field):
                old=self.canary.metrics[field]; self.canary.metrics[field]=value
                with self.assertRaisesRegex(CanaryError,'BUDGET'):
                    self.canary.embed(['one'],purpose='evidence')
                self.canary.metrics[field]=old
        self.client.models.embed_content.assert_not_called()

    def test_no_duplicate_inputs(self):
        with self.assertRaisesRegex(CanaryError,'DUPLICATE'):
            self.canary.embed(['one','one'],purpose='evidence')

    def test_batch_count(self):
        self.assertEqual(list(map(len,bounded_batches(['x']*19))),[8,8,3])

    def test_batch_tokens_no_truncation(self):
        with patch('scripts.canary_gemini_embeddings.count_tokens',return_value=1500):
            self.assertEqual(list(bounded_batches(['a','b','c'])),[('a','b'),('c',)])

    def test_batch_oversize(self):
        with patch('scripts.canary_gemini_embeddings.count_tokens',return_value=4001):
            with self.assertRaisesRegex(CanaryError,'BUDGET'):
                list(bounded_batches(['exact']))

    def test_profile_freeze(self):
        p=real_profile(); c=configuration()
        self.assertEqual((p.provider,p.model,p.version,p.dimensions),('gemini',MODEL,1,768))
        self.assertEqual(c['request'],{'output_dimensionality':768})
        self.assertIn('sdk_version',c)


for label,vector in [('short',[.1]*767),('long',[.1]*769),('nan',[float('nan')]*768),
    ('inf',[float('inf')]*768),('zero',[0.0]*768),('bool',[True]*768),
    ('underflow',[1e-100]*768),('overflow',[1e100]*768)]:
    def test(self,vector=vector):
        self.client.models.embed_content.return_value=response(vector=vector)
        with self.assertRaises(CanaryError):
            self.canary.embed(['one'],purpose='evidence')
        self.assertFalse(self.canary.ledger)
    setattr(Embeddings,'test_invalid_vector_'+label,test)


if __name__=='__main__':
    unittest.main()
