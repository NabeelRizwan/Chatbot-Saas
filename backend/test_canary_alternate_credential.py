"""Offline exact-space and alternate-key continuation gates; zero real calls."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS
import tempfile
import unittest
from unittest.mock import Mock, patch
from sqlalchemy import select, func
from google.genai import errors
from database import canary_schema as s
from scripts.canary_alternate_credential import (AlternateCredentialRunner, compare_receipts,
    FinalCredentialRunner, SingleAttemptGemini, RetainedDatabase)
from scripts.canary_bounded_output import bounded_json
from scripts.canary_gemini_embeddings import Attestation, real_profile
from scripts.canary_provider_recovery import RecoverableGemini, ProviderHold
from scripts.canary_recovery_runner import RecoveryRunner
from scripts.canary_recovery_repository import RecoveryRepository
from scripts.canary_recovery_fixture import engine_for, fixture_init, auth
from scripts.canary_stage_a import NOW
from services.canary_contracts import CanaryError, canonicalize_vector_f32, canonical_vector_digest
from services.canary_representation import exact_input_hash
from services.structural_chunking import digest

ROOT = Path(__file__).resolve().parents[1]


def runner(env=None):
    obj = AlternateCredentialRunner(ROOT, env or {}, mode='resume',
        namespace='canary_stagep_'+'a'*32, run_id='paired-real', identity_hash='b'*64,
        approved_batches=('c'*64,), spend_reference='explicit-offline-approval')
    obj.save = Mock(); obj.progress = Mock()
    return obj


class ExactCompatibility(unittest.TestCase):
    def setUp(self):
        self.texts = ['First exact frozen input.', 'Second exact input.', 'Third input.']
        vector = canonicalize_vector_f32([.123456789]*768)
        self.receipts = [Attestation(1, 2, exact_input_hash(t), real_profile().canonical_hash(),
            canonical_vector_digest(vector), vector, i+1) for i, t in enumerate(self.texts)]

    def compare(self, new=None, old=None, texts=None):
        return compare_receipts(texts or self.texts, old or self.receipts, new or self.receipts,
            scope=(1, 2), profile=real_profile())

    def test_identical_f32_bytes_digest_and_profile_pass(self):
        result = self.compare()
        self.assertEqual(result['result'], 'PASS')
        self.assertEqual(result['canonical_bytes'], 3072)
        bounded_json(result)
        for text in self.texts: self.assertNotIn(text, str(result))

    def test_single_f32_change_fails_no_epsilon(self):
        value = list(self.receipts[0].vector); value[0] += 0.00000002
        value = canonicalize_vector_f32(value)
        changed = replace(self.receipts[0], vector=value, vector_hash=canonical_vector_digest(value))
        self.assertEqual(self.compare([changed, *self.receipts[1:]])['result'], 'FAIL')

    def test_wrong_new_input_profile_scope_or_digest_fails(self):
        for changes in ({'input_hash':'a'*64}, {'profile_hash':'a'*64},
                        {'organization_id':3}, {'bot_id':3}, {'vector_hash':'a'*64}):
            with self.subTest(changes=changes):
                self.assertEqual(self.compare([replace(self.receipts[0], **changes),
                                               *self.receipts[1:]])['result'], 'FAIL')

    def test_corrupt_old_receipt_refused(self):
        with self.assertRaisesRegex(CanaryError, 'INVALID_RETAINED'):
            self.compare(old=[replace(self.receipts[0], vector_hash='a'*64), *self.receipts[1:]])

    def test_invalid_dimensions_nonfinite_zero_refused(self):
        for vector in ((1.0,), (0.0,)*768, (float('nan'),)*768, (float('inf'),)*768):
            with self.subTest(kind=str(vector[0])):
                with self.assertRaises(CanaryError):
                    self.compare([replace(self.receipts[0], vector=vector), *self.receipts[1:]])

    def test_bounded_unique_sample(self):
        for n in (1, 2, 9):
            with self.assertRaises(CanaryError):
                compare_receipts(self.texts[:1]*n, self.receipts[:1]*n, self.receipts[:1]*n,
                    scope=(1,2), profile=real_profile())
        with self.assertRaisesRegex(CanaryError, 'DUPLICATE_COMPATIBILITY'):
            self.compare(texts=[self.texts[0]]*3)


class ContinuationGates(unittest.TestCase):
    def test_fresh_mode_refused(self):
        with self.assertRaisesRegex(CanaryError, 'EXPLICIT_RETAINED'):
            AlternateCredentialRunner(ROOT, {}, mode='fresh')

    def test_no_grant_before_both_probes(self):
        r = runner(); events = []
        def step(name):
            self.assertEqual(r.approved_batches, set()); events.append(name)
        r.compatibility_probe = lambda: step('compatibility')
        r.quota_probe = lambda: step('quota')
        with patch.object(RecoveryRunner, 'setup', lambda _: step('preflight')): r.setup()
        self.assertEqual(events, ['preflight','compatibility','quota'])
        self.assertEqual(r.approved_batches, {'c'*64})

    def test_mismatch_stops_before_quota_and_grant(self):
        r = runner(); r.compatibility_probe = Mock(side_effect=CanaryError('EMBEDDING_MISMATCH'))
        r.quota_probe = Mock()
        with patch.object(RecoveryRunner, 'setup'):
            with self.assertRaises(CanaryError): r.setup()
        r.quota_probe.assert_not_called(); self.assertEqual(r.approved_batches, set())

    def test_quota_failure_stops_before_grant(self):
        r = runner(); r.compatibility_probe = Mock()
        r.quota_probe = Mock(side_effect=ProviderHold({'category':'QUOTA_EXHAUSTED'}))
        with patch.object(RecoveryRunner, 'setup'):
            with self.assertRaises(ProviderHold): r.setup()
        self.assertEqual(r.approved_batches, set())

    def test_inventory_mismatch_before_client_creation(self):
        r = runner(); r.control_ready = True; r.resume_reused = 1078; r.counts = Mock(return_value={})
        with patch('scripts.canary_alternate_credential.RecoverableGemini') as factory:
            with self.assertRaisesRegex(CanaryError, 'INVENTORY_MISMATCH'): r.provider_client()
            factory.assert_not_called()

    def test_key_cleared_on_run_failure(self):
        env = {'CANARY_GEMINI_API_KEY':'offline-fake', 'GEMINI_API_KEY':'untouched-fake'}
        r = runner(env)
        with patch.object(RecoveryRunner, 'run', side_effect=CanaryError('stop')):
            with self.assertRaises(CanaryError): r.run()
        self.assertNotIn('CANARY_GEMINI_API_KEY', env)
        self.assertEqual(env['GEMINI_API_KEY'], 'untouched-fake')

    def test_only_process_alternate_key_used_and_removed(self):
        from scripts.canary_alternate_credential import EXPECTED_COUNTS
        env = {'CANARY_GEMINI_API_KEY':'alternate-offline-fake', 'GEMINI_API_KEY':'old-untouched-fake'}
        r = runner(env); r.control_ready = True; r.resume_reused = 1078
        r.counts = lambda: EXPECTED_COUNTS
        p = NS(scope=NS(revision=NS(source=NS(document_id=1))))
        items = [(p, i, {'text':f'Pending item {i}'}) for i in range(7)]
        mf = NS(lane=NS(value='LEGACY_CONTROL')); r.manifests = (mf, mf)
        r.all_items = lambda _: items
        r.requested_batches = {digest([dict(lane='LEGACY_CONTROL', document=1, key=k,
            input_hash=exact_input_hash(v['text'])) for _,k,v in items])}
        repo = Mock(); repo._run.return_value = repo._manifest.return_value = {'state':'EMBEDDING_STAGING'}
        repo.states.return_value = {(1,i):{'state':'unknown'} for i in range(7)}
        @contextmanager
        def repository(): yield repo
        r.repository = repository
        r.config = NS(approval=NS(organization_id=1, bot_id=2))
        with patch('scripts.canary_alternate_credential.RecoverableGemini') as factory, \
                patch('dotenv.dotenv_values', side_effect=AssertionError('No dotenv fallback')):
            r.provider_client()
        self.assertEqual(factory.call_args.args, ('alternate-offline-fake',))
        self.assertNotIn('CANARY_GEMINI_API_KEY', env)
        self.assertEqual(env['GEMINI_API_KEY'], 'old-untouched-fake')


class PersistedQuotaProbe(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.engine = engine_for(Path(temp.name)/'probe.sqlite'); self.addCleanup(self.engine.dispose)
        self.mf, _ = fixture_init(self.engine, count=8)
        self.r = runner(); self.r.manifests = (self.mf, self.mf)
        p = self.mf.documents[0]
        self.items = [(p, i, dict(id=i,text=f'Exact mock work unit {i}.')) for i in p.legacy_members]
        self.r.all_items = lambda _: self.items
        @contextmanager
        def repository():
            with self.engine.begin() as conn:
                yield RecoveryRepository(conn, self.mf.approval, authorization=auth(self.mf.approval), clock=lambda:NOW)
        self.r.repository = repository
        self.client = Mock()
        self.client.models.embed_content.side_effect = lambda **kw: NS(embeddings=[
            NS(values=[.125]*768,statistics=None) for _ in kw['contents']])
        self.r.provider = RecoverableGemini('offline-fake', organization_id=p.scope.revision.source.organization_id,
            bot_id=p.scope.revision.source.bot_id, approved=True, client_factory=Mock(return_value=self.client))
        self.addCleanup(self.r.provider.close)

    def test_quota_probe_persisted_and_not_repeated_by_build(self):
        self.r.quota_probe()
        self.assertEqual(self.client.models.embed_content.call_count, 1)
        self.r.store_batch(self.mf, self.items[:1], retries=0)
        self.assertEqual(self.client.models.embed_content.call_count, 1)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(s.legacy)).scalar_one(), 1)
        self.assertTrue(self.r.result['quota_probe']['persisted_without_repeat'])

    def test_429_quota_probe_one_call_no_retry_or_vector(self):
        self.client.models.embed_content.side_effect = errors.ClientError(429, {'error':{'status':'RESOURCE_EXHAUSTED'}})
        with self.assertRaises(ProviderHold): self.r.quota_probe()
        self.assertEqual(self.client.models.embed_content.call_count, 1)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(s.legacy)).scalar_one(), 0)
        self.assertEqual(self.r.approved_batches, set())


class FinalContinuation(unittest.TestCase):
    def runner(self):
        r = FinalCredentialRunner(ROOT, {}, mode='resume', namespace='canary_stagep_'+'a'*32,
            run_id='paired-real', identity_hash='b'*64,
            approved_batches=('c'*64,), spend_reference='new-exact-eight-item-approval')
        r.save = Mock(); r.progress = Mock()
        r.common = [({'query':f'Frozen query {i}'}, None) for i in range(90)]
        r.config = NS(namespace='canary_stagep_'+'a'*32, approval=NS(expires_at=123))
        return r

    def test_current_inventory_is_exact_and_previous_defaults_preserved(self):
        r = self.runner()
        self.assertEqual(r.expected_reuse, 2106)
        self.assertEqual(r.expected_unknown, 8)
        self.assertEqual(r.expected_counts['canary_legacy_embedding_work'],
                         {'succeeded':1076, 'unknown':8, 'pending':8})
        self.assertEqual(AlternateCredentialRunner.expected_reuse, 1078)
        self.assertEqual(AlternateCredentialRunner.expected_unknown, 7)
        self.assertEqual(r.mismatch_code, 'EMBEDDING_CREDENTIAL_COMPATIBILITY_FAILURE')

    def test_one_exact_unknown_spend_after_both_probes(self):
        r = self.runner(); events = []; database = Mock(); r.db = database
        r.manifests = ('structural', 'legacy'); r.authorized_unknown_items = tuple(range(8))
        def probe(name):
            self.assertEqual(r.approved_batches, set()); events.append(name)
        r.compatibility_probe = lambda: probe('compatibility')
        r.quota_probe = lambda: probe('quota')
        def store(mf, items, *, retries):
            self.assertEqual((mf, items, retries), ('legacy', tuple(range(8)), 0))
            self.assertEqual(r.approved_batches, {'c'*64}); events.append('unknown')
        r.store_batch = store
        with patch.object(RecoveryRunner, 'setup'): r.setup()
        self.assertEqual(events, ['compatibility', 'quota', 'unknown'])
        self.assertEqual(r.result['authorized_unknown_completed'], 8)
        self.assertIsInstance(r.db, RetainedDatabase)

    def test_quota_failure_does_not_spend_unknown(self):
        r = self.runner(); r.compatibility_probe = Mock()
        r.quota_probe = Mock(side_effect=ProviderHold({'category':'QUOTA_EXHAUSTED'}))
        r.store_batch = Mock()
        with patch.object(RecoveryRunner, 'setup'):
            with self.assertRaises(ProviderHold): r.setup()
        r.store_batch.assert_not_called(); self.assertFalse(r.approved_batches)

    def test_client_never_retries_even_if_base_requests_two(self):
        client = Mock(); client.models.embed_content.side_effect = errors.ClientError(
            429, {'error':{'status':'RESOURCE_EXHAUSTED'}})
        provider = SingleAttemptGemini('offline-fake', organization_id=1, bot_id=2,
            approved=True, client_factory=Mock(return_value=client), pause=Mock())
        self.addCleanup(provider.close)
        for purpose in ('evidence', 'query'):
            with self.assertRaises(ProviderHold):
                provider.embed(['Exact '+purpose+' input'], purpose=purpose, retries=2)
        self.assertEqual(client.models.embed_content.call_count, 2)
        self.assertEqual(provider.metrics['retried'], 0)
        provider.pause.assert_not_called()

    def test_seal_then_all_ninety_durable_queries_before_parent_evaluation(self):
        r = self.runner(); events = []
        r.seal = lambda mf: events.append('seal') or 1
        r.embed_query = lambda q: events.append(q)
        r.counts = lambda: {'canary_query_work':{'succeeded':90}}
        def evaluate(*args):
            self.assertEqual(events, ['seal']+[s['query'] for s,_ in r.common])
            events.append('evaluate')
        with patch.object(RecoveryRunner, 'evaluate_paired', evaluate):
            r.evaluate_paired('structural', 'legacy', 0)
        self.assertEqual(events[-1], 'evaluate')
        self.assertEqual(r.result['queries_durable_before_evaluation'], 90)
        self.assertTrue(r.result['retained']['completed'])

    def test_query_quota_failure_prevents_retrieval(self):
        r = self.runner(); r.seal = Mock()
        r.embed_query = Mock(side_effect=[object(), ProviderHold({'category':'QUOTA_EXHAUSTED'})])
        with patch.object(RecoveryRunner, 'evaluate_paired') as evaluate:
            with self.assertRaises(ProviderHold): r.evaluate_paired('s','l',0)
            evaluate.assert_not_called()
        self.assertEqual(r.embed_query.call_count, 2)

    def test_uncommitted_or_duplicate_query_inventory_prevents_evaluation(self):
        for duplicate in (False, True):
            r = self.runner(); r.seal = Mock(); r.embed_query = Mock()
            if duplicate: r.common[-1] = r.common[0]
            r.counts = lambda: {'canary_query_work':{'succeeded':89,'unknown':1}}
            with patch.object(RecoveryRunner, 'evaluate_paired') as evaluate:
                with self.assertRaises(CanaryError): r.evaluate_paired('s','l',0)
                evaluate.assert_not_called()
            if duplicate: r.embed_query.assert_not_called()

    def test_completed_database_retained_but_connection_still_closed(self):
        database = Mock(); retained = RetainedDatabase(database)
        self.assertIs(retained.engine, database.engine)
        self.assertEqual(retained.cleanup(),
                         {'schema_removed':False,'retained_by_operator_request':True})
        database.cleanup.assert_not_called()
        retained.close(); database.close.assert_called_once()


if __name__ == '__main__': unittest.main()
