"""Explicit snapshot fanout and request-local cache diagnostics."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import json
import os
import threading
import time
import unittest
from unittest.mock import patch

import fakeredis
import httpx

from services.llama_rag.client import RetrievalClient, RetrievalError
from services.llama_rag.client_runtime import (checkpoint, close_retrieval_clients,
    get_last_retrieval_metadata, lifetime, retrieval_request_context)
from utils.redis_client import set_redis_override

from test_llama_client_runtime import SCOPE, TOKEN, evidence_response


class SnapshotFanoutTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'PYTHON_DOTENV_DISABLED': '1',
            'LLAMA_RETRIEVAL_URL': 'http://worker-a:8900', 'LLAMA_RETRIEVAL_TOKEN': TOKEN,
            'LLAMA_RETRIEVAL_POOL_ENABLED': 'true'}, clear=True)
        self.env.start()
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        set_redis_override(self.redis)

    def tearDown(self):
        close_retrieval_clients()
        set_redis_override(None)
        self.env.stop()

    def client(self, handle, count=2):
        urls = tuple(f'http://worker-{chr(97 + i)}:8900' for i in range(count))
        return RetrievalClient(urls=urls, transport=httpx.MockTransport(handle))

    def success(self, request):
        body = json.loads(request.content)
        return httpx.Response(200, json={'fingerprint': body['fingerprint'],
            'status': {'ready': True}, 'worker': request.url.host})

    def test_single_url_default_still_uses_one_request_without_routing(self):
        calls = []
        def handle(request):
            calls.append(request)
            return self.success(request)
        client = RetrievalClient(transport=httpx.MockTransport(handle))
        with patch('services.llama_rag.client.worker_slot', side_effect=AssertionError('Unexpected routing')):
            client.snapshot(SCOPE, [])
        self.assertEqual(len(calls), 1)

    def test_explicit_snapshot_warms_every_endpoint_in_parallel(self):
        barrier, calls = threading.Barrier(2), []
        def handle(request):
            calls.append((request.url.host, request.url.path))
            barrier.wait(timeout=2)
            return self.success(request)
        result = self.client(handle).snapshot(SCOPE, [])
        self.assertEqual(result['worker'], 'worker-a')
        self.assertCountEqual(calls, [('worker-a', '/v1/snapshots'), ('worker-b', '/v1/snapshots')])
        self.assertFalse(list(self.redis.scan_iter('llama:routing:*')))

    def test_fanout_never_exceeds_four_active_requests(self):
        lock, first_four = threading.Lock(), threading.Barrier(4)
        counts = {'active': 0, 'peak': 0, 'started': 0, 'finished': 0}
        def handle(request):
            with lock:
                counts['active'] += 1
                counts['started'] += 1
                ordinal = counts['started']
                counts['peak'] = max(counts['peak'], counts['active'])
            if ordinal <= 4:
                first_four.wait(timeout=2)
            time.sleep(.01)
            with lock:
                counts['active'] -= 1
                counts['finished'] += 1
            return self.success(request)
        self.client(handle, count=6).snapshot(SCOPE, [])
        self.assertEqual(counts, {'active': 0, 'peak': 4, 'started': 6, 'finished': 6})

    def test_failure_is_not_masked_and_other_started_work_is_drained(self):
        barrier, second_finished = threading.Barrier(2), threading.Event()
        def handle(request):
            barrier.wait(timeout=2)
            if request.url.host == 'worker-a':
                return httpx.Response(503)
            time.sleep(.04)
            second_finished.set()
            return self.success(request)
        with self.assertRaisesRegex(RetrievalError, 'retrieval_service_503'):
            self.client(handle).snapshot(SCOPE, [])
        self.assertTrue(second_finished.is_set())
        self.assertFalse(list(self.redis.scan_iter('llama:routing:*')))

    def test_any_invalid_replica_snapshot_prevents_success(self):
        for broken in ({'fingerprint': 'wrong', 'status': {'ready': True}},
                       {'fingerprint': SCOPE['fingerprint'], 'status': {'ready': False}}):
            def handle(request):
                return httpx.Response(200, json=broken) if request.url.host == 'worker-b' else self.success(request)
            with self.subTest(broken=broken), self.assertRaisesRegex(RetrievalError, 'retrieval_snapshot_invalid'):
                self.client(handle).snapshot(SCOPE, [])

    def test_each_fanout_inherits_deadline_and_cancel_event(self):
        observations, cancel = [], threading.Event()
        def handle(request):
            observations.append((checkpoint(), lifetime().cancel_event))
            return self.success(request)
        with retrieval_request_context(timeout=.5, cancel_event=cancel):
            self.client(handle).snapshot(SCOPE, [])
        self.assertEqual(len(observations), 2)
        self.assertTrue(all(0 < remaining <= .5 and event is cancel for remaining, event in observations))
        cancel.set()
        with self.assertRaisesRegex(RetrievalError, 'retrieval_cancelled'):
            with retrieval_request_context(cancel_event=cancel):
                self.client(lambda request: self.fail('Unexpected request')).snapshot(SCOPE, [])

    def test_two_fanouts_share_the_existing_per_endpoint_capacity(self):
        active, peaks, lock = {}, {}, threading.Lock()
        def handle(request):
            host = request.url.host
            with lock:
                active[host] = active.get(host, 0) + 1
                peaks[host] = max(peaks.get(host, 0), active[host])
            time.sleep(.02)
            with lock:
                active[host] -= 1
            return self.success(request)
        client = self.client(handle)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(client.snapshot, SCOPE, []) for _ in range(2)]
            for future in futures:
                self.assertTrue(future.result()['status']['ready'])
        self.assertEqual(peaks, {'worker-a': 1, 'worker-b': 1})

    def test_cache_metadata_is_context_local_and_does_not_modify_payload(self):
        os.environ.update(LLAMA_RETRIEVAL_CACHE_ENABLED='true', LLAMA_RETRIEVAL_PIPELINE_REVISION='fixture-v1')
        calls = []
        def handle(request):
            body = json.loads(request.content)
            calls.append(body['question'])
            return httpx.Response(200, json=evidence_response(body))
        client = RetrievalClient(transport=httpx.MockTransport(handle))
        original = client.retrieve(SCOPE, [], 'Cached?')
        self.assertFalse(get_last_retrieval_metadata()['cache_hit'])
        copied_contexts = [copy_context(), copy_context()]
        def request(question):
            result = client.retrieve(SCOPE, [], question)
            return result, get_last_retrieval_metadata()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(copied_contexts[0].run, request, 'Cached?')
            second = pool.submit(copied_contexts[1].run, request, 'Fresh?')
            cached, hit = first.result()
            fresh, miss = second.result()
        self.assertEqual(cached, original)
        self.assertTrue(hit['cache_hit'])
        self.assertFalse(miss['cache_hit'])
        self.assertFalse(get_last_retrieval_metadata()['cache_hit'])
        self.assertGreaterEqual(hit['client_elapsed_ms'], 0)
        self.assertNotIn('cache_hit', fresh)
        hit['cache_hit'] = False
        self.assertTrue(copied_contexts[0].run(get_last_retrieval_metadata)['cache_hit'])
        self.assertEqual(calls, ['Cached?', 'Fresh?'])

    def test_metadata_resets_on_cache_miss_and_failed_request(self):
        os.environ.update(LLAMA_RETRIEVAL_CACHE_ENABLED='true', LLAMA_RETRIEVAL_PIPELINE_REVISION='fixture-v1')
        client = RetrievalClient(transport=httpx.MockTransport(lambda request:
            httpx.Response(200, json=evidence_response(json.loads(request.content)))))
        client.retrieve(SCOPE, [], 'Question?')
        client.retrieve(SCOPE, [], 'Question?')
        self.assertTrue(get_last_retrieval_metadata()['cache_hit'])
        cancel = threading.Event()
        cancel.set()
        # Enter the valid outer lifetime first, then cancel before retrieve().
        cancel.clear()
        with retrieval_request_context(cancel_event=cancel):
            cancel.set()
            with self.assertRaisesRegex(RetrievalError, 'retrieval_cancelled'):
                client.retrieve(SCOPE, [], 'Question?')
        metadata = get_last_retrieval_metadata()
        self.assertFalse(metadata['cache_hit'])
        self.assertGreaterEqual(metadata['client_elapsed_ms'], 0)
