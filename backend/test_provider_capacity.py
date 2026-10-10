"""Shared provider limits queue safely without changing any provider calls."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import threading
import time
import unittest
from unittest.mock import patch

import fakeredis
from redis.exceptions import ConnectionError as RedisConnectionError

from services import provider_capacity as capacity
from utils.redis_client import set_redis_override


class ProviderCapacityTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"PROVIDER_CAPACITY_ENABLED": "true"}, clear=True)
        self.env.start()
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        set_redis_override(self.redis)

    def tearDown(self):
        set_redis_override(None)
        self.env.stop()

    def guard(self, *, key="credential-a", org="org-a", provider="gemini", model="model-a"):
        return capacity.provider_capacity_guard(provider, model, key, org)

    def test_disabled_mode_does_not_consult_redis_or_modify_call(self):
        os.environ["PROVIDER_CAPACITY_ENABLED"] = "false"
        with patch.object(capacity, "get_redis", side_effect=AssertionError("Redis should not be used")):
            with self.guard() as lease:
                self.assertIsNone(lease)

    def test_remaining_turn_budget_and_cancel_event_propagate_to_nested_context(self):
        self.assertIsNone(capacity.provider_capacity_remaining())
        cancelled = threading.Event()
        with capacity.provider_capacity_context(timeout=0.5, cancel_event=cancelled):
            with capacity.provider_capacity_context(timeout=30):
                self.assertLessEqual(capacity.provider_capacity_remaining(), 0.5)
                self.assertIs(capacity.provider_capacity_cancel_event(), cancelled)
                cancelled.set()
                with self.assertRaisesRegex(capacity.ProviderCapacityError, "cancelled"):
                    capacity.provider_capacity_remaining()

    def test_same_key_across_organizations_shares_one_capacity_pool_and_queues(self):
        os.environ["PROVIDER_CAPACITY_CREDENTIAL_LIMIT"] = "1"
        lock = threading.Lock()
        active, maximum = 0, 0
        def invoke(org):
            nonlocal active, maximum
            with capacity.provider_capacity_context(timeout=2), self.guard(org=org):
                with lock:
                    active += 1
                    maximum = max(maximum, active)
                time.sleep(0.025)
                with lock:
                    active -= 1
            return org
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(invoke, [f"org-{i}" for i in range(5)]))
        self.assertEqual(len(results), 5)
        self.assertEqual(maximum, 1)

    def test_distinct_keys_can_run_together_but_global_limit_is_shared(self):
        os.environ["PROVIDER_CAPACITY_GLOBAL_LIMIT"] = "2"
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        active, maximum = 0, 0
        def invoke(i):
            nonlocal active, maximum
            with capacity.provider_capacity_context(timeout=2), self.guard(key=f"key-{i}", org=f"org-{i}"):
                with lock:
                    active += 1
                    maximum = max(maximum, active)
                barrier.wait(timeout=1)
                time.sleep(0.01)
                with lock:
                    active -= 1
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(invoke, range(4)))
        self.assertEqual(maximum, 2)

    def test_organization_limit_spans_different_keys_and_providers(self):
        os.environ["PROVIDER_CAPACITY_ORG_LIMIT"] = "1"
        with self.guard(key="key-a", provider="gemini"):
            with self.assertRaisesRegex(capacity.ProviderCapacityError, "deadline_exceeded"):
                with capacity.provider_capacity_context(timeout=0.03), self.guard(key="key-b", provider="openai"):
                    self.fail("Organization capacity exceeded")

    def test_explicit_provider_project_groups_different_keys(self):
        mapping = {capacity.credential_fingerprint("gemini", key): "shared-project" for key in ("key-a", "key-b")}
        os.environ["PROVIDER_CAPACITY_QUOTA_GROUPS_JSON"] = json.dumps(mapping)
        os.environ["PROVIDER_CAPACITY_GROUP_LIMIT"] = "1"
        with self.guard(key="key-a", org="org-a"):
            with self.assertRaisesRegex(capacity.ProviderCapacityError, "deadline_exceeded"):
                with capacity.provider_capacity_context(timeout=0.03), self.guard(key="key-b", org="org-b"):
                    self.fail("Shared project capacity exceeded")

    def test_configured_rpm_counts_failed_attempts_and_retries_separately(self):
        os.environ["PROVIDER_CAPACITY_RPM"] = "2"
        with self.assertRaisesRegex(ValueError, "provider failed"):
            with self.guard():
                raise ValueError("provider failed")
        with self.guard():
            pass
        with self.assertRaisesRegex(capacity.ProviderCapacityError, "deadline_exceeded"):
            with capacity.provider_capacity_context(timeout=0.03), self.guard():
                self.fail("RPM exceeded")
        identity = capacity.scope_identity("gemini", "model-a", "credential-a", "org-a")
        self.assertEqual(self.redis.zcard(identity["keys"][4]), 2)
        self.assertTrue(all(self.redis.zcard(key) == 0 for key in identity["keys"][:4]))

    def test_project_rpm_override_can_span_models(self):
        fingerprint = capacity.credential_fingerprint("gemini", "credential-a")
        os.environ["PROVIDER_CAPACITY_QUOTA_GROUPS_JSON"] = json.dumps({fingerprint: "shared-project"})
        os.environ["PROVIDER_CAPACITY_RPM_LIMITS_JSON"] = json.dumps({"gemini:shared-project": 1})
        with self.guard(model="model-a"):
            pass
        with self.assertRaisesRegex(capacity.ProviderCapacityError, "deadline_exceeded"):
            with capacity.provider_capacity_context(timeout=0.03), self.guard(model="model-b"):
                self.fail("Cross-model RPM exceeded")

    def test_unconfigured_rpm_is_not_invented(self):
        for _ in range(5):
            with self.guard():
                pass
        self.assertFalse(list(self.redis.scan_iter("*:rpm:*")))

    def test_queue_cancellation_avoids_provider_admission(self):
        os.environ["PROVIDER_CAPACITY_CREDENTIAL_LIMIT"] = "1"
        cancelled = threading.Event()
        outcome = []
        def wait_for_capacity():
            try:
                with capacity.provider_capacity_context(timeout=2, cancel_event=cancelled), self.guard():
                    outcome.append("unexpected-admission")
            except capacity.ProviderCapacityError as error:
                outcome.append(str(error))
        with self.guard():
            worker = threading.Thread(target=wait_for_capacity)
            worker.start()
            time.sleep(0.02)
            cancelled.set()
            worker.join(timeout=0.5)
        self.assertEqual(outcome, ["provider_capacity_cancelled"])

    def test_retry_after_is_shared_and_shorter_retry_after_cannot_clear_it(self):
        mapping = {capacity.credential_fingerprint("gemini", key): "shared-project" for key in ("key-a", "key-b")}
        os.environ["PROVIDER_CAPACITY_QUOTA_GROUPS_JSON"] = json.dumps(mapping)
        capacity.record_provider_cooldown("gemini", "model-a", "key-a", 10)
        capacity.record_provider_cooldown("gemini", "model-a", "key-b", 1)
        with self.assertRaisesRegex(capacity.ProviderCapacityError, "deadline_exceeded"):
            with capacity.provider_capacity_context(timeout=0.03), self.guard(key="key-b"):
                self.fail("Cooldown ignored")
        identity = capacity.scope_identity("gemini", "model-a", "key-b", "org-a")
        self.assertGreater(self.redis.pttl(identity["keys"][5]), 9000)

    def test_lease_is_renewed_until_actual_call_finishes(self):
        os.environ["PROVIDER_CAPACITY_LEASE_SECONDS"] = "1"
        with self.guard() as lease:
            identity = capacity.scope_identity("gemini", "model-a", "credential-a", "org-a")
            original = self.redis.zscore(identity["keys"][0], lease.token)
            time.sleep(0.4)
            renewed = self.redis.zscore(identity["keys"][0], lease.token)
            self.assertGreater(renewed, original)
            lease.check()
        self.assertTrue(all(self.redis.zcard(key) == 0 for key in identity["keys"][:4]))

    def test_redis_failure_fails_closed_without_leaking_error_detail(self):
        with patch.object(self.redis, "eval", side_effect=RedisConnectionError("secret URL")):
            with self.assertRaisesRegex(capacity.ProviderCapacityError, "^provider_capacity_unavailable$"):
                with self.guard():
                    self.fail("Redis failure admitted provider call")

    def test_lost_lease_cannot_return_success(self):
        os.environ["PROVIDER_CAPACITY_LEASE_SECONDS"] = "1"
        with self.assertRaisesRegex(capacity.ProviderCapacityError, "provider_capacity_lease_lost"):
            with self.guard() as lease:
                self.redis.delete(lease.keys[0])
                time.sleep(0.4)
                lease.check()

    def test_final_ownership_check_detects_loss_before_heartbeat(self):
        with self.assertRaisesRegex(capacity.ProviderCapacityError, "provider_capacity_lease_lost"):
            with self.guard() as lease:
                self.redis.delete(lease.keys[0])

    def test_fractional_limits_and_nonfinite_deadlines_fail_configuration(self):
        os.environ["PROVIDER_CAPACITY_RPM"] = "0.5"
        with self.assertRaisesRegex(capacity.ProviderCapacityError, "configuration_invalid"):
            with self.guard():
                self.fail("Invalid RPM accepted")
        with self.assertRaisesRegex(capacity.ProviderCapacityError, "configuration_invalid"):
            with capacity.provider_capacity_context(timeout=float("nan")):
                self.fail("Invalid deadline accepted")

    def test_credentials_are_absent_from_redis_keys_and_values(self):
        credential = "private-credential-that-must-not-be-persisted"
        os.environ["PROVIDER_CAPACITY_RPM"] = "10"
        with self.guard(key=credential):
            for key in self.redis.scan_iter("provider-capacity:*"):
                self.assertNotIn(credential, key)
                if self.redis.type(key) == "zset":
                    self.assertNotIn(credential, json.dumps(self.redis.zrange(key, 0, -1, withscores=True)))


if __name__ == "__main__":
    unittest.main()
