"""Concurrent admission against provider project/model request and token windows."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
import threading
import time
import unittest
from unittest.mock import Mock, patch

import fakeredis

from services import provider_capacity as capacity, provider_quotas as quotas
from services import llm_client, llm_router
from services.providers.base_provider import ProviderFeedback, ProviderRateLimit, ProviderUsage
from utils.redis_client import set_redis_override


class ProviderTokenBudgetTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'PROVIDER_CAPACITY_ENABLED': 'true'}, clear=True)
        self.env.start()
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        set_redis_override(self.redis)
        self.group_keys({'key-a': 'project', 'key-b': 'project'})

    def tearDown(self):
        set_redis_override(None)
        self.env.stop()

    def group_keys(self, mapping, provider='gemini'):
        current = json.loads(os.getenv('PROVIDER_CAPACITY_QUOTA_GROUPS_JSON', '{}'))
        current.update({capacity.credential_fingerprint(provider, key): group for key, group in mapping.items()})
        os.environ['PROVIDER_CAPACITY_QUOTA_GROUPS_JSON'] = json.dumps(current)

    def configure(self, budgets):
        os.environ['PROVIDER_CAPACITY_BUDGETS_JSON'] = json.dumps(budgets)

    def identity(self, provider='gemini', model='model-a', key='key-a', org='org-a'):
        return capacity.scope_identity(provider, model, key, org)

    def guard(self, *, provider='gemini', model='model-a', key='key-a', org='org-a', input_tokens=100,
              output_tokens=20, on_admission=None):
        return capacity.provider_capacity_guard(provider, model, key, org,
            reservation=quotas.TokenReservation(input_tokens, output_tokens), on_admission=on_admission)

    def budget(self, label, *, scope='gemini:project:model-a', input_tokens=100, output_tokens=20):
        constraints = quotas.constraints(self.redis, 'gemini:project', scope,
                                         quotas.TokenReservation(input_tokens, output_tokens))
        return next(item for item in constraints if item['label'] == label and item['keys'][0].startswith(quotas._base(scope)))

    def snapshot(self):
        result = {}
        for key in sorted(self.redis.scan_iter('provider-capacity:*')):
            kind = self.redis.type(key)
            if kind == 'zset':
                result[key] = self.redis.zrange(key, 0, -1, withscores=True)
            elif kind == 'hash':
                result[key] = self.redis.hgetall(key)
            else:
                result[key] = self.redis.get(key)
        return result

    def denied(self, expected='deadline_exceeded', **kwargs):
        with self.assertRaisesRegex(capacity.ProviderCapacityError, expected):
            with capacity.provider_capacity_context(timeout=0.025), self.guard(**kwargs):
                self.fail('Exhausted budget admitted a provider request')

    def test_each_joint_dimension_limits_and_rejection_spends_no_other_budget(self):
        ceilings = {'rpm': 10, 'rpd': 100, 'input_tpm': 1000, 'output_tpm': 1000,
                    'tpm': 2000, 'tpd': 10000}
        first_request = {'rpm': 1, 'rpd': 1, 'input_tpm': 100, 'output_tpm': 20,
                         'tpm': 120, 'tpd': 120}
        for label, exhausted_limit in first_request.items():
            with self.subTest(label=label):
                self.redis.flushall()
                self.configure({'gemini:project:model-a': {**ceilings, label: exhausted_limit}})
                with self.guard():
                    pass
                before = self.snapshot()
                self.denied(expected='daily_quota_exhausted' if label in {'rpd', 'tpd'} else 'deadline_exceeded')
                self.assertEqual(self.snapshot(), before)
                identity = self.identity()
                self.assertTrue(all(self.redis.zcard(key) == 0 for key in identity['keys'][:4]))

    def test_daily_exhaustion_beyond_deadline_fails_without_waiting_or_spending(self):
        for label, limit in (('rpd', 1), ('tpd', 120)):
            with self.subTest(label=label):
                self.redis.flushall()
                self.configure({'gemini:project:model-a': {label: limit}})
                with self.guard():
                    pass
                before = self.snapshot()
                with patch.object(capacity.time, 'sleep', side_effect=AssertionError('Daily quota cannot fit')):
                    with self.assertRaisesRegex(capacity.ProviderCapacityError, 'daily_quota_exhausted'):
                        with capacity.provider_capacity_context(timeout=180), self.guard():
                            self.fail('Exhausted daily quota admitted a request')
                self.assertEqual(self.snapshot(), before)

    def test_daily_reset_inside_deadline_still_waits_and_admits(self):
        for label, limit in (('rpd', 1), ('tpd', 120)):
            with self.subTest(label=label):
                self.redis.flushall()
                self.configure({'gemini:project:model-a': {label: limit}})
                with self.guard() as previous:
                    previous_token = previous.token
                events, amounts = self.budget(label)['keys']
                now = self.redis.time()
                now_ms = now[0] * 1000 + now[1] // 1000
                self.redis.zadd(events, {previous_token: now_ms - 86400000 + 100})
                with patch.object(capacity.time, 'sleep', wraps=time.sleep) as wait:
                    with capacity.provider_capacity_context(timeout=2), self.guard() as lease:
                        self.assertGreater(lease.admission['wait_by_reason_ms'].get(label, 0), 0)
                self.assertTrue(wait.called)
                self.assertEqual(self.redis.zcard(events), 1)
                self.assertEqual(int(self.redis.hget(amounts, '__total')), limit)

    def test_daily_exhaustion_maps_to_terminal_safe_admission_diagnostics(self):
        self.configure({'gemini:project:model-a': {'rpd': 1}})
        with self.guard():
            pass
        events = []
        generate = Mock(return_value='Provider must not be called')
        with capacity.provider_capacity_context(timeout=180):
            with self.assertRaises(llm_client.CentralizedLLMError):
                llm_client.execute_with_resilience(generate, 'gemini', 'model-a',
                    skip_legacy_guard=True, on_event=events.append,
                    attempt_admission=lambda: llm_router._provider_admission(
                        'gemini', 'model-a', 'key-a', 'org-a', quotas.TokenReservation(100, 20)))
        generate.assert_not_called()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['event'], 'attempt_finished')
        self.assertEqual(events[0]['outcome'], 'error')
        self.assertFalse(events[0]['provider_started'])
        self.assertEqual(events[0]['provider_call_ms'], 0)
        self.assertEqual(events[0]['status_code'], 429)
        self.assertEqual(events[0]['error_kind'], 'quota_exhausted')
        self.assertEqual(events[0]['quota_category'], 'daily_quota')
        self.assertEqual(events[0]['error_code'], 'LLM_RATE_LIMITED')
        self.assertNotIn('key-a', json.dumps(events))

    def test_project_and_model_budgets_are_both_required_atomically(self):
        self.configure({'gemini:project': {'input_tpm': 150},
                        'gemini:project:model-a': {'input_tpm': 100},
                        'gemini:project:model-b': {'input_tpm': 100}})
        with self.guard():
            pass
        before = self.snapshot()
        self.denied(input_tokens=10)
        self.assertEqual(self.snapshot(), before, 'Model rejection charged the project budget')
        with self.guard(model='model-b', input_tokens=50):
            pass
        before = self.snapshot()
        self.denied(model='model-b', input_tokens=1)
        self.assertEqual(self.snapshot(), before, 'Project rejection charged the model budget')
        shared = self.budget('input_tpm', scope='gemini:project')
        self.assertEqual(int(self.redis.hget(shared['keys'][1], '__total')), 150)

    def test_gemini_resource_prefix_and_model_aliases_share_one_budget(self):
        os.environ['PROVIDER_CAPACITY_MODEL_GROUPS_JSON'] = json.dumps({
            'gemini:model-a': 'shared-flash', 'gemini:model-b': 'shared-flash'})
        self.configure({'gemini:project:shared-flash': {'rpm': 1, 'tpm': 500}})
        self.assertEqual(self.identity(model='models/model-a')['model_scope'], 'gemini:project:shared-flash')
        with self.guard(model='models/model-a'):
            pass
        self.denied(model='model-b')

    def test_different_keys_same_provider_project_share_budget_across_organizations(self):
        self.configure({'gemini:project:model-a': {'tpm': 120}})
        with self.guard(key='key-a', org='org-a'):
            pass
        self.denied(key='key-b', org='org-b')
        with self.guard(key='independent-key', org='org-b'):
            pass

    def test_switching_gemini_openai_claude_grok_keeps_quota_scopes_separate(self):
        providers = ('gemini', 'openai', 'claude', 'grok')
        for provider in providers:
            self.group_keys({'key-a': 'project'}, provider)
        self.configure({f'{provider}:*': {'rpm': 1, 'tpm': 120} for provider in providers})
        identities = []
        for provider in providers:
            with self.guard(provider=provider):
                pass
            identities.append(self.identity(provider=provider))
        self.assertEqual(len({item['model_scope'] for item in identities}), 4)
        self.assertEqual(len({item['credential'] for item in identities}), 4)
        for provider in providers:
            self.denied(provider=provider)

    def test_failed_provider_attempt_keeps_request_and_token_reservations(self):
        self.configure({'gemini:project:model-a': {'rpm': 2, 'tpm': 240}})
        with self.assertRaisesRegex(RuntimeError, 'provider failed'):
            with self.guard():
                raise RuntimeError('provider failed')
        with self.guard():
            pass
        self.denied()
        token_budget = self.budget('tpm')
        self.assertEqual(int(self.redis.hget(token_budget['keys'][1], '__total')), 240)
        self.assertEqual(self.redis.zcard(token_budget['keys'][0]), 2)

    def test_success_reconciles_upward_only_without_lowering_reserved_output(self):
        self.configure({'gemini:project:model-a': {'rpm': 10, 'input_tpm': 1000,
                        'output_tpm': 1000, 'tpm': 2000}})
        with self.guard() as lease:
            lease.observe(usage=ProviderUsage(150, 40))
            lease.observe(usage=ProviderUsage(10, 1))
        expected = {'rpm': 1, 'input_tpm': 150, 'output_tpm': 40, 'tpm': 190}
        for label, total in expected.items():
            budget = self.budget(label)
            self.assertEqual(int(self.redis.hget(budget['keys'][1], '__total')), total)

    def test_reconcile_never_recreates_expired_or_removed_window(self):
        self.configure({'gemini:project:model-a': {'tpm': 500}})
        with self.guard() as lease:
            budget = lease.budgets[0]
            self.redis.delete(*budget['keys'])
            lease.observe(usage=ProviderUsage(300, 200))
            self.assertFalse(self.redis.exists(*budget['keys']))

    def test_late_completion_does_not_increase_an_unpruned_expired_window(self):
        self.configure({'gemini:project:model-a': {'tpm': 500}})
        with self.guard() as lease:
            events, amounts = lease.budgets[0]['keys']
            now = self.redis.time()
            now_ms = int(now[0] * 1000 + now[1] // 1000)
            self.redis.zadd(events, {lease.token: now_ms - 61000})
            before = self.redis.hget(amounts, '__total')
            lease.observe(usage=ProviderUsage(300, 200))
            self.assertEqual(self.redis.hget(amounts, '__total'), before)

    def test_out_of_order_feedback_cannot_raise_learned_ceiling_or_refill_counters(self):
        identity = self.identity()
        def report(limit, remaining, stamp):
            return ProviderFeedback(rate_limits=(ProviderRateLimit('total_tokens', limit, remaining,
                1, 60, 'model'),), observed_at_unix=stamp)
        quotas.record_feedback(self.redis, identity['group_scope'], identity['model_scope'], report(240, 240, 20))
        with self.guard() as lease:
            lease.observe(feedback=report(120, 0, 30))
            before = self.snapshot()
            lease.observe(feedback=report(1000, 1000, 10))
            after = self.snapshot()
            self.assertEqual(before, after)
            budget = self.budget('tpm')
            self.assertEqual(budget['limit'], 120)
            self.assertEqual(int(self.redis.hget(budget['keys'][1], '__total')), 120)

    def test_exhausted_project_feedback_pauses_sibling_models_not_other_projects(self):
        with self.guard() as lease:
            lease.observe(feedback=ProviderFeedback(rate_limits=(
                ProviderRateLimit('requests', 1000, 0, 10, 60, 'project'),)))
        self.denied(model='model-b')
        with self.guard(model='model-b', key='other-project-key'):
            pass

    def test_configured_limit_cannot_be_relaxed_by_larger_observed_limit(self):
        self.configure({'gemini:project:model-a': {'tpm': 120}})
        with self.guard() as lease:
            lease.observe(feedback=ProviderFeedback(rate_limits=(
                ProviderRateLimit('total_tokens', 10000, 9999, 1, 60),)))
        self.assertEqual(self.budget('tpm')['limit'], 120)
        self.denied()

    def test_malformed_budget_configuration_is_rejected_without_admission(self):
        invalid = ['not-json', '[]', '{"gemini:*":{"unknown":10}}',
                   '{"gemini:*":{"rpm":true}}', '{"gemini:*":{"tpm":-1}}',
                   '{"gemini:*":{"tpm":1.5}}', '{"gemini:*":{"tpm":"100"}}',
                   '{"gemini:*":{"tpm":NaN}}', '{"gemini:*":null}']
        for raw in invalid:
            with self.subTest(raw=raw):
                os.environ['PROVIDER_CAPACITY_BUDGETS_JSON'] = raw
                with self.assertRaisesRegex(capacity.ProviderCapacityError, 'configuration_invalid'):
                    with self.guard():
                        self.fail('Malformed configuration admitted provider traffic')
                self.assertEqual(self.redis.dbsize(), 0)

    def test_invalid_model_alias_is_not_silently_ignored(self):
        for raw in ('[]', '{"gemini:model-a":false}', '{"gemini:model-a":""}', 'broken'):
            with self.subTest(raw=raw):
                os.environ['PROVIDER_CAPACITY_MODEL_GROUPS_JSON'] = raw
                with self.assertRaisesRegex(capacity.ProviderCapacityError, 'configuration_invalid'):
                    with self.guard():
                        self.fail('Invalid model alias admitted provider traffic')
                self.assertEqual(self.redis.dbsize(), 0)

    def test_intrinsically_oversized_request_fails_before_waiting_or_spending(self):
        self.configure({'gemini:project:model-a': {'tpm': 119}})
        with patch.object(capacity.time, 'sleep', side_effect=AssertionError('Impossible request waited')):
            with self.assertRaisesRegex(capacity.ProviderCapacityError, 'request_exceeds_quota'):
                with self.guard():
                    self.fail('Oversized request admitted')
        self.assertEqual(self.redis.dbsize(), 0)

    def test_oversized_request_fails_fast_even_while_other_call_occupies_capacity(self):
        os.environ['PROVIDER_CAPACITY_CREDENTIAL_LIMIT'] = '1'
        self.configure({'gemini:project:model-a': {'tpm': 200}})
        with self.guard():
            before = self.snapshot()
            with patch.object(capacity.time, 'sleep', side_effect=AssertionError('Impossible request waited')):
                with self.assertRaisesRegex(capacity.ProviderCapacityError, 'request_exceeds_quota'):
                    with self.guard(input_tokens=201):
                        self.fail('Oversized request admitted')
            self.assertEqual(self.snapshot(), before)

    def test_cancellation_before_admission_spends_no_budget(self):
        self.configure({'gemini:project:model-a': {'rpm': 1, 'tpm': 120}})
        cancel = threading.Event()
        cancel.set()
        with self.assertRaisesRegex(capacity.ProviderCapacityError, 'cancelled'):
            with capacity.provider_capacity_context(cancel_event=cancel), self.guard():
                self.fail('Cancelled request admitted')
        self.assertEqual(self.redis.dbsize(), 0)

    def test_cancellation_while_waiting_does_not_consume_quota(self):
        os.environ['PROVIDER_CAPACITY_CREDENTIAL_LIMIT'] = '1'
        self.configure({'gemini:project:model-a': {'rpm': 2, 'tpm': 240}})
        cancel = threading.Event()
        started = threading.Event()
        outcome = []
        def queued():
            started.set()
            try:
                with capacity.provider_capacity_context(timeout=2, cancel_event=cancel), self.guard():
                    outcome.append('admitted')
            except capacity.ProviderCapacityError as exc:
                outcome.append(str(exc))
        with self.guard():
            before = self.snapshot()
            thread = threading.Thread(target=queued)
            thread.start()
            self.assertTrue(started.wait(timeout=1))
            cancel.set()
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())
            self.assertEqual(outcome, ['provider_capacity_cancelled'])
            self.assertEqual(self.snapshot(), before)

    def test_ten_parallel_requests_all_admit_when_each_budget_permits(self):
        self.configure({'gemini:project': {'rpm': 10, 'tpm': 1200},
                        'gemini:project:model-a': {'rpm': 10, 'input_tpm': 1000,
                                                  'output_tpm': 200, 'tpm': 1200}})
        barrier = threading.Barrier(10)
        observed = []
        lock = threading.Lock()
        def request(index):
            with capacity.provider_capacity_context(timeout=5), self.guard(org='org-a') as lease:
                with lock:
                    observed.append(lease.admission)
                barrier.wait(timeout=4)
                self.assertEqual(self.redis.zcard(lease.keys[0]), 10)
                # Keep all leases alive until every thread observed the peak.
                barrier.wait(timeout=4)
            return index
        with ThreadPoolExecutor(max_workers=10) as pool:
            completed = list(pool.map(request, range(10)))
        self.assertEqual(completed, list(range(10)))
        self.assertTrue(all(item['token_budget_configured'] and item['request_budget_configured'] for item in observed))
        self.assertTrue(all(not item['wait_by_reason_ms'] for item in observed))
        self.denied()
        token_budget = self.budget('tpm')
        self.assertEqual(self.redis.zcard(token_budget['keys'][0]), 10)
        self.assertEqual(int(self.redis.hget(token_budget['keys'][1], '__total')), 1200)


if __name__ == '__main__':
    unittest.main()
