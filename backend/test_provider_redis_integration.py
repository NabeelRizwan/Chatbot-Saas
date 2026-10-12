"""Opt-in multiprocess checks against a dedicated disposable local Redis.

Set TEST_PROVIDER_REDIS_URL to a loopback Redis on port 56381. The selected
database must be empty. These tests never start services or invoke an AI API.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import multiprocessing
import os
from queue import Empty
import time
from urllib.parse import urlparse
import uuid

import pytest
import redis

from services import provider_capacity as capacity, provider_quotas as quotas
from services.providers.base_provider import ProviderFeedback, ProviderRateLimit, ProviderUsage
from utils.redis_client import set_redis_override


def _configure(values):
    for name in list(os.environ):
        if name.startswith("PROVIDER_CAPACITY_"):
            os.environ.pop(name)
    os.environ.update(values)
    os.environ["CHAT_EXECUTION_MODE"] = "inline"


def _worker(url, values, start_barrier, active_barrier, results, marker, mode):
    _configure(values)
    client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=3, socket_connect_timeout=3)
    set_redis_override(client)
    def record(phase):
        seconds, micros = client.time()
        client.rpush(marker, json.dumps({"phase": phase, "time": seconds + micros / 1_000_000}))
    def run_one(index):
        start_barrier.wait(timeout=10)
        try:
            with capacity.provider_capacity_context(timeout=0.5 if mode == "quota" else 10):
                with capacity.provider_capacity_guard("openai", "model", "test-key", "test-org",
                        reservation=quotas.TokenReservation(8, 2)):
                    record("start")
                    if active_barrier is not None:
                        active_barrier.wait(timeout=5)
                    time.sleep(0.15 if mode == "concurrency" else 0.01)
                    record("end")
            results.put({"outcome": "success", "pid": os.getpid()})
        except capacity.ProviderCapacityError as error:
            results.put({"outcome": str(error), "pid": os.getpid()})
        except Exception as error:
            results.put({"outcome": "unexpected", "type": type(error).__name__, "pid": os.getpid()})
    try:
        with ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(run_one, range(10)))
    finally:
        set_redis_override(None)
        client.close()


@pytest.fixture
def dedicated_redis(monkeypatch):
    url = os.getenv("TEST_PROVIDER_REDIS_URL")
    if not url:
        pytest.skip("Set TEST_PROVIDER_REDIS_URL for isolated Redis integration tests")
    parsed = urlparse(url)
    assert parsed.scheme == "redis" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    assert parsed.port == 56381, "Use the dedicated test port; production Redis is forbidden"
    assert parsed.path.lstrip("/").isdigit(), "Select an explicit isolated database"
    client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=3, socket_connect_timeout=3)
    client.ping()
    assert client.dbsize() == 0, "The dedicated test database must be empty; nothing was removed"
    for name in list(os.environ):
        if name.startswith("PROVIDER_CAPACITY_"):
            monkeypatch.delenv(name)
    values = {"PROVIDER_CAPACITY_ENABLED": "true", "PROVIDER_CAPACITY_GLOBAL_LIMIT": "10",
        "PROVIDER_CAPACITY_ORG_LIMIT": "10", "PROVIDER_CAPACITY_CREDENTIAL_LIMIT": "10",
        "PROVIDER_CAPACITY_GROUP_LIMIT": "10", "PROVIDER_CAPACITY_LEASE_SECONDS": "10"}
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("CHAT_EXECUTION_MODE", "inline")
    set_redis_override(client)
    try:
        yield url, client, values
    finally:
        set_redis_override(None)
        # Delete only this test's limiter/measurement keys, never FLUSHDB/FLUSHALL.
        for pattern in ("provider-capacity:{v1}:*", "provider-integration:*"):
            keys = list(client.scan_iter(match=pattern))
            if keys:
                client.delete(*keys)
        client.close()


def _burst(url, client, values, *, mode):
    context = multiprocessing.get_context("spawn")
    start_barrier = context.Barrier(20)
    active_barrier = context.Barrier(10) if mode == "concurrency" else None
    results = context.Queue()
    marker = "provider-integration:" + uuid.uuid4().hex
    workers = [context.Process(target=_worker,
        args=(url, values, start_barrier, active_barrier, results, marker, mode)) for _ in range(2)]
    try:
        for worker in workers:
            worker.start()
        rows = []
        for _ in range(20):
            try:
                rows.append(results.get(timeout=20))
            except Empty:
                pytest.fail("A Redis admission subprocess did not finish")
        for worker in workers:
            worker.join(timeout=5)
            assert worker.exitcode == 0
        assert len({row["pid"] for row in rows}) == 2
        assert not any(row["outcome"] == "unexpected" for row in rows), rows
        return rows, [json.loads(row) for row in client.lrange(marker, 0, -1)]
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
        results.close()
        results.join_thread()


def test_two_processes_share_atomic_request_and_token_budgets(dedicated_redis, monkeypatch):
    url, client, values = dedicated_redis
    credential = capacity.credential_fingerprint("openai", "test-key")
    scope = "openai:" + credential
    budgets = {scope: {"rpm": 12, "tpm": 100}, scope + ":model": {"input_tpm": 1000}}
    values["PROVIDER_CAPACITY_BUDGETS_JSON"] = json.dumps(budgets)
    monkeypatch.setenv("PROVIDER_CAPACITY_BUDGETS_JSON", values["PROVIDER_CAPACITY_BUDGETS_JSON"])
    rows, _ = _burst(url, client, values, mode="quota")
    assert sum(row["outcome"] == "success" for row in rows) == 10
    assert sum(row["outcome"] == "provider_capacity_deadline_exceeded" for row in rows) == 10
    identity = capacity.scope_identity("openai", "model", "test-key", "test-org")
    constraints = quotas.constraints(client, identity["group_scope"], identity["model_scope"], quotas.TokenReservation(8, 2))
    for budget in constraints:
        events, amounts = budget["keys"]
        assert client.zcard(events) == 10
        assert int(client.hget(amounts, "__total")) == budget["amount"] * 10
    assert all(client.zcard(key) == 0 for key in identity["keys"][:4])


def test_twenty_requests_really_overlap_at_ten_with_two_processes(dedicated_redis):
    url, client, values = dedicated_redis
    rows, events = _burst(url, client, values, mode="concurrency")
    assert all(row["outcome"] == "success" for row in rows)
    assert len(events) == 40
    active = maximum = 0
    for event in sorted(events, key=lambda event: (event["time"], event["phase"] == "start")):
        active += 1 if event["phase"] == "start" else -1
        maximum = max(maximum, active)
        assert 0 <= active <= 10
    assert maximum == 10 and active == 0
    elapsed = max(event["time"] for event in events) - min(event["time"] for event in events)
    assert elapsed >= 0.28  # At least two waves of 150ms provider work.
    assert elapsed < 2.5  # Serial execution of twenty attempts would require 3s.


def test_expired_window_is_pruned_using_redis_time(dedicated_redis, monkeypatch):
    _, client, _ = dedicated_redis
    monkeypatch.setenv("PROVIDER_CAPACITY_BUDGETS_JSON", json.dumps({"openai:*": {"rpm": 1, "tpm": 10}}))
    identity = capacity.scope_identity("openai", "model", "test-key", "test-org")
    reservation = quotas.TokenReservation(8, 2)
    with capacity.provider_capacity_guard("openai", "model", "test-key", "test-org", reservation=reservation) as lease:
        token = lease.token
        budgets = lease.budgets
    seconds, micros = client.time()
    expired_at = seconds * 1000 + micros // 1000 - 60001
    for budget in budgets:
        client.zadd(budget["keys"][0], {token: expired_at})
    # A late usage response must not resurrect or increase the expired entry.
    quotas.reconcile(client, budgets, token, ProviderUsage(100, 100))
    for budget in budgets:
        assert int(client.hget(budget["keys"][1], "__total")) == budget["amount"]
    with capacity.provider_capacity_context(timeout=0.5):
        with capacity.provider_capacity_guard("openai", "model", "test-key", "test-org", reservation=reservation):
            pass
    for budget in budgets:
        assert client.zcard(budget["keys"][0]) == 1
        assert client.zscore(budget["keys"][0], token) is None
        assert int(client.hget(budget["keys"][1], "__total")) == budget["amount"]
    assert all(client.zcard(key) == 0 for key in identity["keys"][:4])


def test_project_feedback_blocks_other_models_without_refreshing_old_limit(dedicated_redis):
    _, client, _ = dedicated_redis
    identity = capacity.scope_identity("openai", "model-a", "test-key", "test-org")
    original = ProviderFeedback(rate_limits=(ProviderRateLimit("total_tokens", limit=100, remaining=0,
        reset_after_seconds=5, window_seconds=60, scope="project"),), observed_at_unix=time.time())
    quotas.record_feedback(client, identity["group_scope"], identity["model_scope"], original)
    learned_key = next(client.scan_iter(match="provider-capacity:{v1}:quota:*:learned"))
    client.expire(learned_key, 10)
    newer = ProviderFeedback(rate_limits=(ProviderRateLimit("total_tokens", limit=200,
        window_seconds=60, scope="project"),), observed_at_unix=time.time())
    quotas.record_feedback(client, identity["group_scope"], identity["model_scope"], newer)
    assert client.ttl(learned_key) <= 10
    assert int(client.hget(learned_key, "tpm")) == 100
    with pytest.raises(capacity.ProviderCapacityError, match="deadline_exceeded"):
        with capacity.provider_capacity_context(timeout=0.08):
            with capacity.provider_capacity_guard("openai", "model-b", "test-key", "test-org",
                    reservation=quotas.TokenReservation(8, 2)):
                pytest.fail("Exhausted project tokens admitted another model")
