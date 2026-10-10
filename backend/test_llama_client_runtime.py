"""Isolation, failover and concurrency contracts for retrieval transport reuse."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import threading
import time
import unittest
from unittest.mock import patch

import fakeredis
import httpx
from redis.exceptions import ConnectionError as RedisConnectionError

from services.llama_rag.client import RetrievalClient, RetrievalError
from services.llama_rag import client_runtime
from services.llama_rag.client_runtime import close_retrieval_clients, retrieval_request_context
from services.llama_rag.retrieval_cache import EvidenceCache, _PREFIX
from services.llama_rag.worker_routing import worker_slot
from utils.redis_client import set_redis_override


TOKEN = "local-test-credential-" + "x" * 32
SCOPE = {"organization_id": "org-a", "bot_id": "bot-a", "fingerprint": "a" * 64}


def evidence_response(body):
    context = "[Source 1] Chair\nURL: https://example.test/chair\nThe chair is blue."
    return {"fingerprint": body["fingerprint"], "question": body["question"],
            "evidence": [{"text": "The chair is blue.", "source_id": "source-a"}],
            "context": context, "context_sha256": hashlib.sha256(context.encode()).hexdigest()}


class RetrievalRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "PYTHON_DOTENV_DISABLED": "1", "LLAMA_RETRIEVAL_URL": "http://worker-a:8900",
            "LLAMA_RETRIEVAL_TOKEN": TOKEN, "LLAMA_RETRIEVAL_POOL_ENABLED": "true",
        }, clear=True)
        self.env.start()
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        set_redis_override(self.redis)

    def tearDown(self):
        close_retrieval_clients()
        set_redis_override(None)
        self.env.stop()

    def client(self, handler):
        return RetrievalClient(transport=httpx.MockTransport(handler))

    def cache_on(self):
        os.environ["LLAMA_RETRIEVAL_CACHE_ENABLED"] = "true"
        os.environ["LLAMA_RETRIEVAL_PIPELINE_REVISION"] = "models-and-pipeline-v1"

    def workers_on(self):
        os.environ["LLAMA_RETRIEVAL_URLS"] = "http://worker-a:8900,http://worker-b:8900"

    def test_connections_are_reused_without_cookie_or_credential_state(self):
        requests = []
        def handle(request):
            requests.append(request)
            return httpx.Response(200, json={"ready": True}, headers={"Set-Cookie": "tenant=secret"})
        original = httpx.Client
        with patch.object(client_runtime.httpx, "Client", wraps=original) as constructor:
            client = self.client(handle)
            for _ in range(3):
                self.assertEqual(client.request("/health/ready", method="GET"), {"ready": True})
            constructor.assert_called_once()
        self.assertTrue(all("cookie" not in request.headers for request in requests))
        self.assertTrue(all(request.headers["Authorization"] == "Bearer " + TOKEN for request in requests))
        first = list(client_runtime._CLIENTS.values())[0]
        close_retrieval_clients()
        self.assertTrue(first.is_closed)

    def test_all_worker_urls_receive_original_safety_validation(self):
        for url in ("https://user:pass@worker.test", "http://worker.test/path", "http://worker.test?token=secret",
                    "http://worker.test#fragment", "http://worker.test:bad", "ftp://worker.test"):
            with self.subTest(url=url), self.assertRaisesRegex(RetrievalError, "configuration_invalid"):
                RetrievalClient(url="http://worker-a:8900", token=TOKEN, urls=(url,))
        with self.assertRaisesRegex(RetrievalError, "route_invalid"):
            self.client(lambda request: self.fail("Unexpected upstream call")).request("//untrusted.test/data")

    def test_bounded_response_and_safe_error_categories(self):
        cases = [(401, {"secret": "upstream-secret"}, "retrieval_service_401"),
                 (422, {"detail": "question_too_long"}, "question_too_long"),
                 (200, ["not an object"], "retrieval_response_invalid")]
        for status, value, category in cases:
            with self.subTest(category=category):
                client = self.client(lambda request: httpx.Response(status, json=value))
                with self.assertRaisesRegex(RetrievalError, "^" + category + "$"):
                    client.request("/v1/retrieve", {})
        client = self.client(lambda request: httpx.Response(200, content=b"x" * (5 * 1024 * 1024 + 1)))
        with self.assertRaisesRegex(RetrievalError, "retrieval_response_too_large"):
            client.request("/v1/retrieve", {})

    def test_document_preparation_contract_remains_available(self):
        self.workers_on()
        requests = []
        def handle(request):
            requests.append(request)
            return httpx.Response(200, json={"ready": True})
        result = self.client(handle).request("/v1/prepare", {"text": "A new document"}, timeout=300)
        self.assertTrue(result["ready"])
        self.assertEqual(requests[0].url.path, "/v1/prepare")
        self.assertEqual(json.loads(requests[0].content)["text"], "A new document")

    def test_snapshot_and_followup_stay_on_the_same_worker(self):
        self.workers_on()
        ready, calls = set(), []
        def handle(request):
            host, path = request.url.host, request.url.path
            body = json.loads(request.content)
            calls.append((host, path))
            if path == "/v1/snapshots":
                ready.add(host)
                return httpx.Response(200, json={"fingerprint": body["fingerprint"], "status": {"ready": True}})
            return httpx.Response(200, json=evidence_response(body)) if host in ready else httpx.Response(409)
        client = self.client(handle)
        for _ in range(2):
            self.assertEqual(client.retrieve(SCOPE, [], "Colour?")["question"], "Colour?")
        self.assertEqual(len(ready), 2)
        for offset in (0, 3):
            batch = calls[offset:offset + 3]
            self.assertEqual(len({host for host, path in batch}), 1)
            self.assertEqual([path for host, path in batch], ["/v1/retrieve", "/v1/snapshots", "/v1/retrieve"])
        self.assertFalse(list(self.redis.scan_iter("llama:routing:*")))

    def test_initial_connect_failure_can_fail_over_but_auth_cannot(self):
        self.workers_on()
        calls = []
        def handle(request):
            calls.append(request.url.host)
            if len(calls) == 1:
                raise httpx.ConnectError("sensitive upstream details", request=request)
            return httpx.Response(200, json=evidence_response(json.loads(request.content)))
        self.client(handle).retrieve(SCOPE, [], "Colour?")
        self.assertEqual(len(set(calls)), 2)
        calls.clear()
        def reject(request):
            calls.append(request.url.host)
            return httpx.Response(401)
        with self.assertRaisesRegex(RetrievalError, "retrieval_service_401"):
            self.client(reject).retrieve(SCOPE, [], "Colour?")
        self.assertEqual(len(calls), 1)

    def test_unknown_snapshot_outcome_is_not_replayed_elsewhere(self):
        self.workers_on()
        calls = []
        def handle(request):
            calls.append((request.url.host, request.url.path))
            if request.url.path == "/v1/retrieve":
                return httpx.Response(409)
            raise httpx.ReadTimeout("uncertain snapshot outcome", request=request)
        with self.assertRaisesRegex(RetrievalError, "retrieval_service_unavailable"):
            self.client(handle).retrieve(SCOPE, [], "Colour?")
        self.assertEqual(len(calls), 2)
        self.assertEqual(len({host for host, path in calls}), 1)

    def test_worker_capacity_is_shared_between_clients_and_wait_is_bounded(self):
        self.workers_on()
        os.environ["LLAMA_RETRIEVAL_QUEUE_TIMEOUT_SECONDS"] = "0.01"
        urls = ("http://worker-a:8900", "http://worker-b:8900")
        with retrieval_request_context(), worker_slot(urls), worker_slot(urls):
            start = time.monotonic()
            with self.assertRaisesRegex(RetrievalError, "retrieval_busy"):
                self.client(lambda request: self.fail("Capacity exceeded")).retrieve(SCOPE, [], "Colour?")
            self.assertLess(time.monotonic() - start, 0.5)

    def test_overlapping_worker_lists_share_capacity_during_rollout(self):
        os.environ["LLAMA_RETRIEVAL_QUEUE_TIMEOUT_SECONDS"] = "0.01"
        with retrieval_request_context(), worker_slot(("http://worker-a:8900",)):
            with worker_slot(("http://worker-a:8900", "http://worker-b:8900")) as url:
                self.assertEqual(url, "http://worker-b:8900")

    def test_default_queue_waits_for_capacity_beyond_five_seconds(self):
        urls = ("http://worker-a:8900",)
        occupied, release = threading.Event(), threading.Event()
        def occupy():
            with worker_slot(urls):
                occupied.set()
                release.wait(timeout=5.2)
        with ThreadPoolExecutor(max_workers=1) as pool:
            holder = pool.submit(occupy)
            self.assertTrue(occupied.wait(timeout=2))
            try:
                started = time.monotonic()
                with retrieval_request_context(timeout=10), worker_slot(urls) as url:
                    self.assertEqual(url, urls[0])
                self.assertGreater(time.monotonic() - started, 5)
            finally:
                release.set()
                holder.result(timeout=2)
        self.assertFalse(list(self.redis.scan_iter("llama:routing:*")))

    def test_default_queue_remains_bounded_by_shorter_turn_deadline(self):
        urls = ("http://worker-a:8900",)
        with worker_slot(urls):
            started = time.monotonic()
            with self.assertRaisesRegex(RetrievalError, "retrieval_deadline_exceeded"):
                with retrieval_request_context(timeout=.03), worker_slot(urls):
                    self.fail("Occupied worker was admitted")
            self.assertLess(time.monotonic() - started, .5)

    def test_parallel_requests_use_both_workers_without_exceeding_their_slots(self):
        self.workers_on()
        counts, peaks = {}, {}
        lock = threading.Lock()
        def handle(request):
            host = request.url.host
            with lock:
                counts[host] = counts.get(host, 0) + 1
                peaks[host] = max(peaks.get(host, 0), counts[host])
            time.sleep(0.04)
            with lock:
                counts[host] -= 1
            return httpx.Response(200, json=evidence_response(json.loads(request.content)))
        client = self.client(handle)
        with ThreadPoolExecutor(max_workers=8) as pool:
            answers = list(pool.map(lambda i: client.retrieve(SCOPE, [], f"Question {i}"), range(8)))
        self.assertEqual(len(answers), 8)
        self.assertEqual(peaks, {"worker-a": 1, "worker-b": 1})

    def test_cache_is_exact_and_isolated_by_bot_corpus_and_pipeline(self):
        self.cache_on()
        calls = []
        def handle(request):
            body = json.loads(request.content)
            calls.append(body)
            return httpx.Response(200, json=evidence_response(body))
        client = self.client(handle)
        original = client.retrieve(SCOPE, [], "Colour?")
        original["context"] = "caller mutation"
        self.assertNotEqual(client.retrieve(SCOPE, [], "Colour?")["context"], "caller mutation")
        self.assertEqual(len(calls), 1)
        for scope, question in ((SCOPE, "colour?"), (SCOPE, "Colour"),
                ({**SCOPE, "bot_id": "bot-b"}, "Colour?"),
                ({**SCOPE, "organization_id": "org-b"}, "Colour?"),
                ({**SCOPE, "fingerprint": "b" * 64}, "Colour?")):
            client.retrieve(scope, [], question)
        os.environ["LLAMA_RETRIEVAL_PIPELINE_REVISION"] = "models-and-pipeline-v2"
        client.retrieve(SCOPE, [], "Colour?")
        self.assertEqual(len(calls), 7)

    def test_identical_concurrent_misses_share_one_retrieval(self):
        self.cache_on()
        count = 0
        lock = threading.Lock()
        barrier = threading.Barrier(8)
        def handle(request):
            nonlocal count
            with lock:
                count += 1
            time.sleep(0.1)
            return httpx.Response(200, json=evidence_response(json.loads(request.content)))
        client = self.client(handle)
        def retrieve(_):
            barrier.wait(timeout=2)
            return client.retrieve(SCOPE, [], "Colour?")
        with ThreadPoolExecutor(max_workers=8) as pool:
            answers = list(pool.map(retrieve, range(8)))
        self.assertEqual(count, 1)
        self.assertTrue(all(answer == answers[0] for answer in answers))
        self.assertFalse(list(self.redis.scan_iter(_PREFIX + "*:flight")))

    def test_cache_has_ttl_byte_and_entry_limits_without_touching_other_redis_data(self):
        self.cache_on()
        os.environ["LLAMA_RETRIEVAL_CACHE_ENTRIES"] = "2"
        os.environ["LLAMA_RETRIEVAL_CACHE_BYTES"] = "1024"
        self.redis.set("queue:important-job", "preserve")
        client = self.client(lambda request: httpx.Response(200, json=evidence_response(json.loads(request.content))))
        for i in range(8):
            client.retrieve(SCOPE, [], f"Question {i}")
        keys = list(self.redis.scan_iter(_PREFIX + "item:*"))
        self.assertLessEqual(len(keys), 2)
        self.assertLessEqual(sum(len(self.redis.get(key).encode()) for key in keys), 1024)
        self.assertTrue(all(0 < self.redis.ttl(key) <= 300 for key in keys))
        self.assertEqual(self.redis.get("queue:important-job"), "preserve")
        self.assertEqual(int(self.redis.hget(_PREFIX + "sizes", "_bytes")),
                         sum(len(self.redis.get(key).encode()) for key in keys))

    def test_disabled_unversioned_or_unavailable_cache_uses_normal_retrieval(self):
        calls = []
        def handle(request):
            calls.append(request)
            return httpx.Response(200, json=evidence_response(json.loads(request.content)))
        client = self.client(handle)
        os.environ["LLAMA_RETRIEVAL_CACHE_ENABLED"] = "true"
        client.retrieve(SCOPE, [], "Colour?")
        client.retrieve(SCOPE, [], "Colour?")
        self.assertEqual(len(calls), 2)
        self.cache_on()
        with patch.object(self.redis, "get", side_effect=RedisConnectionError("offline")):
            client.retrieve(SCOPE, [], "Colour?")
        self.assertEqual(len(calls), 3)
        self.assertFalse(list(self.redis.scan_iter(_PREFIX + "item:*")))

    def test_cached_response_expiration_requires_a_fresh_search(self):
        self.cache_on()
        calls = []
        def handle(request):
            calls.append(request)
            return httpx.Response(200, json=evidence_response(json.loads(request.content)))
        client = self.client(handle)
        client.retrieve(SCOPE, [], "Colour?")
        cache = EvidenceCache.configured(SCOPE, "Colour?")
        self.redis.expire(cache.key, -1)
        client.retrieve(SCOPE, [], "Colour?")
        self.assertEqual(len(calls), 2)

    def test_cancellation_and_expired_deadline_do_not_issue_upstream_calls(self):
        client = self.client(lambda request: self.fail("Unexpected upstream call"))
        cancel = threading.Event()
        cancel.set()
        with self.assertRaisesRegex(RetrievalError, "retrieval_cancelled"):
            with retrieval_request_context(cancel_event=cancel):
                client.retrieve(SCOPE, [], "Colour?")
        with self.assertRaisesRegex(RetrievalError, "retrieval_deadline_exceeded"):
            with retrieval_request_context(timeout=0):
                client.retrieve(SCOPE, [], "Colour?")


if __name__ == "__main__":
    unittest.main()
