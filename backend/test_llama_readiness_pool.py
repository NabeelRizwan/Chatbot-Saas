"""Serving readiness must cover the configured retrieval pool."""
import os
import threading
import time
import unittest
from unittest.mock import patch

import httpx

from services.knowledge_runtime import readiness
from services.llama_rag.client import RetrievalClient, RetrievalError
from services.llama_rag.client_runtime import (checkpoint, close_retrieval_clients,
    lifetime, retrieval_request_context)


READY = {"status": "ready", "engine": "llamaindex", "protocol": 1}


class RetrievalPoolReadinessTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            'PYTHON_DOTENV_DISABLED': '1', 'KNOWLEDGE_ENGINE': 'llamaindex',
            'LLAMA_RETRIEVAL_URL': 'http://old-primary:8900',
            'LLAMA_RETRIEVAL_TOKEN': 'local-readiness-test-token-0000000000',
            'LLAMA_RETRIEVAL_POOL_ENABLED': 'true'}, clear=True)
        self.env.start()

    def tearDown(self):
        close_retrieval_clients()
        self.env.stop()

    def client(self, handle, count=2):
        os.environ['LLAMA_RETRIEVAL_URLS'] = ','.join(
            f'http://worker-{index}:8900' for index in range(count))
        return RetrievalClient(transport=httpx.MockTransport(handle))

    def runtime_readiness(self, client):
        with patch('services.llama_rag.client.RetrievalClient', return_value=client):
            return readiness()

    def test_all_ready_uses_configured_pool_not_different_primary(self):
        barrier, requests = threading.Barrier(2), []
        def handle(request):
            requests.append((request.url.host, request.url.path, request.method))
            barrier.wait(timeout=2)
            return httpx.Response(200, json=READY)
        with patch('services.llama_rag.client.worker_slot', side_effect=AssertionError('Health must not reserve a slot')):
            self.assertEqual(self.runtime_readiness(self.client(handle)), 'ready')
        self.assertCountEqual(requests, [('worker-0', '/health/ready', 'GET'),
                                        ('worker-1', '/health/ready', 'GET')])

    def test_one_unavailable_worker_makes_whole_pool_unavailable(self):
        calls = []
        def handle(request):
            calls.append(request.url.host)
            if request.url.host == 'worker-1':
                raise httpx.ConnectError('Offline', request=request)
            return httpx.Response(200, json=READY)
        self.assertEqual(self.runtime_readiness(self.client(handle)), 'unavailable')
        self.assertCountEqual(calls, ['worker-0', 'worker-1'])

    def test_success_status_with_wrong_protocol_is_not_ready(self):
        for response in ({**READY, 'status': 'loading'}, {**READY, 'protocol': 2},
                         {**READY, 'engine': 'other'}, {}):
            with self.subTest(response=response):
                client = self.client(lambda request: httpx.Response(200,
                    json=response if request.url.host == 'worker-1' else READY))
                self.assertEqual(self.runtime_readiness(client), 'unavailable')

    def test_explicit_single_endpoint_does_not_probe_old_primary(self):
        calls = []
        def handle(request):
            calls.append(request.url.host)
            return httpx.Response(200, json=READY)
        self.assertEqual(self.runtime_readiness(self.client(handle, count=1)), 'ready')
        self.assertEqual(calls, ['worker-0'])

    def test_default_single_endpoint_retains_original_request_behavior(self):
        calls = []
        def handle(request):
            calls.append(request.url.host)
            return httpx.Response(200, json=READY)
        client = RetrievalClient(transport=httpx.MockTransport(handle))
        with patch('services.llama_rag.client.ThreadPoolExecutor', side_effect=AssertionError('Unexpected pool')):
            self.assertEqual(self.runtime_readiness(client), 'ready')
        self.assertEqual(calls, ['old-primary'])

    def test_fanout_has_four_request_bound_and_waits_for_started_probes(self):
        lock, barrier = threading.Lock(), threading.Barrier(4)
        counts = {'active': 0, 'peak': 0, 'started': 0, 'finished': 0}
        def handle(request):
            with lock:
                counts['active'] += 1
                counts['started'] += 1
                ordinal = counts['started']
                counts['peak'] = max(counts['peak'], counts['active'])
            if ordinal <= 4:
                barrier.wait(timeout=2)
            time.sleep(.02)
            with lock:
                counts['active'] -= 1
                counts['finished'] += 1
            return httpx.Response(503) if request.url.host == 'worker-0' else httpx.Response(200, json=READY)
        self.assertEqual(self.runtime_readiness(self.client(handle, count=6)), 'unavailable')
        self.assertEqual(counts, {'active': 0, 'peak': 4, 'started': 6, 'finished': 6})

    def test_pool_probes_inherit_outer_deadline_and_cancellation(self):
        observations, cancel = [], threading.Event()
        def handle(request):
            observations.append((checkpoint(), lifetime().cancel_event,
                                 request.extensions['timeout']['read']))
            return httpx.Response(200, json=READY)
        client = self.client(handle)
        with retrieval_request_context(timeout=.5, cancel_event=cancel):
            self.assertEqual(self.runtime_readiness(client), 'ready')
        self.assertEqual(len(observations), 2)
        self.assertTrue(all(0 < remaining <= .5 and event is cancel and 0 < timeout <= .5
                            for remaining, event, timeout in observations))
        with retrieval_request_context(cancel_event=cancel):
            cancel.set()
            with self.assertRaisesRegex(RetrievalError, 'retrieval_cancelled'):
                client.request('/health/ready', method='GET', timeout=3)
        self.assertEqual(len(observations), 2)


if __name__ == '__main__':
    unittest.main()
