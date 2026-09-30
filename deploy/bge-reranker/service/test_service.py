"""Boundary and full-input tests; no model downloads or external providers."""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from .scorer import (BGEScorer, InputError, PairTooLong, MAX_BODY_BYTES,
                     MAX_TOKENS, MODEL, REVISION, PROCESSING, validate_request,
                     verify_artifacts)
from .server import RankingServer


class FakeScorer:
    loaded = True
    device = "cpu"

    def __init__(self):
        self.calls = []
        self.error = None

    def score(self, query, documents):
        self.calls.append((query, documents))
        if self.error:
            raise self.error
        return {"model": MODEL, "revision": REVISION,
                "scores": [float(n) for n in range(len(documents))],
                "token_counts": [12] * len(documents)}


@contextmanager
def server_for(scorer, *, queue_wait_seconds=60):
    server = RankingServer(("127.0.0.1", 0), scorer, "test-private-token",
                           queue_wait_seconds=queue_wait_seconds)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(server, method="POST", body=None, headers=None, path="/rerank"):
    connection = http.client.HTTPConnection(*server.server_address, timeout=3)
    effective = {"Authorization": "Bearer test-private-token", "Content-Type": "application/json"}
    if headers is not None:
        effective.update(headers)
    payload = json.dumps(body or {"query": "Café?", "documents": ["Title: Test\nContent:\nExact Unicode café."]})
    connection.request(method, path, body=payload, headers=effective)
    response = connection.getresponse()
    result = response.status, json.loads(response.read())
    connection.close()
    return result


class HTTPTests(unittest.TestCase):
    def test_authenticated_readiness_never_runs_inference(self):
        scorer = FakeScorer()
        with server_for(scorer) as server:
            self.assertEqual(request(server, method="GET", path="/ready",
                                     headers={"Authorization": "Bearer wrong"})[0], 401)
            status, body = request(server, method="GET", path="/ready")
            self.assertEqual(status, 200)
            self.assertEqual(body["revision"], REVISION)
            scorer.loaded = False
            self.assertEqual(request(server, method="GET", path="/ready")[0], 503)
        self.assertEqual(scorer.calls, [])

    def test_missing_auth_rejected_before_scoring(self):
        scorer = FakeScorer()
        with server_for(scorer) as server:
            status, body = request(server, headers={"Authorization": "Bearer wrong"})
        self.assertEqual(status, 401)
        self.assertEqual(body, {"error": "UNAUTHORIZED"})
        self.assertEqual(scorer.calls, [])

    def test_identity_order_and_complete_unicode_inputs(self):
        scorer = FakeScorer()
        value = {"query": "Original question?", "documents": ["a\n\u00e9", "z\nFINAL WARNING"]}
        with server_for(scorer) as server:
            status, body = request(server, body=value)
            health_status, health = request(server, method="GET", path="/health")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"model": MODEL, "revision": REVISION,
                               "scores": [0.0, 1.0], "token_counts": [12, 12]})
        self.assertEqual(scorer.calls, [(value["query"], value["documents"])])
        self.assertEqual(health_status, 200)
        self.assertTrue(health["loaded"])
        self.assertNotIn("token", health)

    def test_limits_invalid_json_fields_and_content_type(self):
        scorer = FakeScorer()
        with server_for(scorer) as server:
            for value in ({"query": "q", "documents": []},
                          {"query": "q", "documents": ["d"] * 33},
                          {"query": "q", "documents": ["d"], "model": "other"},
                          {"query": "q", "documents": [None]}):
                self.assertEqual(request(server, body=value)[0], 400)
            self.assertEqual(request(server, headers={"Content-Length": str(MAX_BODY_BYTES + 1)})[0], 413)
            self.assertEqual(request(server, headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(scorer.calls, [])

    def test_queued_request_expires_without_scoring_and_releases_capacity(self):
        scorer = FakeScorer()
        with server_for(scorer, queue_wait_seconds=.02) as server:
            with server.scoring:
                status, body = request(server)
            self.assertEqual((status, body), (503, {"error": "RANKER_QUEUE_TIMEOUT"}))
            self.assertEqual(scorer.calls, [])
            self.assertEqual(request(server)[0], 200)

    def test_three_concurrent_requests_serialize_fourth_busy_health_auth_responsive(self):
        class BlockingScorer(FakeScorer):
            def __init__(self):
                super().__init__()
                self.started = threading.Event()
                self.release = threading.Semaphore(0)
                self.active = self.max_active = 0

            def score(self, query, documents):
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                self.started.set()
                try:
                    if not self.release.acquire(timeout=3):
                        raise RuntimeError("TEST_INFERENCE_TIMED_OUT")
                    return super().score(query, documents)
                finally:
                    self.active -= 1

        scorer = BlockingScorer()
        with server_for(scorer, queue_wait_seconds=2) as server, ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(request, server)]
            self.assertTrue(scorer.started.wait(timeout=1))
            futures.extend(executor.submit(request, server) for _ in range(2))
            deadline = time.monotonic() + 1
            while server.ranking_slots._value != 0 and time.monotonic() < deadline:
                time.sleep(.005)
            self.assertEqual(server.ranking_slots._value, 0, "Three requests were not admitted")
            self.assertEqual(request(server), (503, {"error": "RANKER_BUSY"}))
            self.assertEqual(request(server, method="GET", path="/health")[0], 200)
            self.assertEqual(request(server, headers={"Authorization": "Bearer wrong"})[0], 401)
            self.assertEqual(len(scorer.calls), 0)
            scorer.release.release(3)
            self.assertEqual([future.result(timeout=2)[0] for future in futures], [200, 200, 200])
        self.assertEqual(scorer.max_active, 1)
        self.assertEqual(len(scorer.calls), 3)

    def test_failures_expose_only_safe_category(self):
        scorer = FakeScorer()
        with server_for(scorer) as server:
            scorer.error = PairTooLong("private original input")
            self.assertEqual(request(server), (422, {"error": "PAIR_TOKEN_LIMIT_EXCEEDED"}))
            scorer.error = RuntimeError("private model path or query")
            self.assertEqual(request(server), (503, {"error": "SCORING_UNAVAILABLE"}))
            scorer.loaded = False
            self.assertEqual(request(server), (503, {"error": "MODEL_UNAVAILABLE"}))
            self.assertEqual(request(server, method="GET", path="/health")[0], 503)

    def test_token_is_mandatory(self):
        for token in (None, "", "   ", "secret\nheader"):
            with self.assertRaises(ValueError):
                RankingServer(("127.0.0.1", 0), FakeScorer(), token)

    def test_queue_wait_is_bounded_and_finite(self):
        for timeout in (0, -1, True, 91, math.inf, math.nan):
            with self.assertRaises(ValueError):
                RankingServer(("127.0.0.1", 0), FakeScorer(), "test-token", queue_wait_seconds=timeout)


class Vector:
    def __init__(self, values):
        self.values = values

    def tolist(self):
        return self.values

    def reshape(self, *args):
        return self


class Tensor:
    ndim = 2

    def __init__(self, length):
        self.shape = (1, length)
        self.length = length

    def sum(self, dim):
        return Vector([self.length])


class ModelDouble:
    def __init__(self, lengths, values=None):
        self.lengths = iter(lengths)
        self.values = iter(values if values is not None else [0.4] * len(lengths))
        self.preprocessing, self.predictions = [], []

    def preprocess(self, pairs, **kwargs):
        self.preprocessing.append((pairs, kwargs))
        length = next(self.lengths)
        return {"input_ids": Tensor(length), "attention_mask": Tensor(length)}

    def predict(self, pairs, **kwargs):
        self.predictions.append((pairs, kwargs))
        return Vector([next(self.values)])


class ScoringTests(unittest.TestCase):
    def make_scorer(self, model):
        scorer = BGEScorer("unused", device="cpu")
        scorer.model = model
        return scorer

    def test_later_oversize_pair_stops_all_inference_without_truncation(self):
        model = ModelDouble([100, MAX_TOKENS + 1])
        scorer = self.make_scorer(model)
        with self.assertRaises(PairTooLong):
            scorer.score("query", ["valid", "long ending clause"])
        self.assertEqual(model.predictions, [])
        self.assertEqual(model.preprocessing[1][0], [("query", "long ending clause")])
        for _, kwargs in model.preprocessing:
            self.assertEqual(kwargs, {"prompt": None, "processing_kwargs": PROCESSING})

    def test_full_boundary_pair_allowed_and_raw_logits_retained(self):
        model = ModelDouble([MAX_TOKENS, 8], values=[-2.3, 8.4])
        result = self.make_scorer(model).score("query", ["first", "second"])
        self.assertEqual(result["scores"], [-2.3, 8.4])
        self.assertEqual(result["token_counts"], [MAX_TOKENS, 8])
        for pairs, kwargs in model.predictions:
            self.assertEqual(len(pairs), 1)
            self.assertEqual(kwargs["batch_size"], 1)
            self.assertEqual(kwargs["processing_kwargs"], PROCESSING)

    def test_nonfinite_model_score_rejected(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.assertRaises(RuntimeError):
                self.make_scorer(ModelDouble([5], [value])).score("query", ["document"])

    def test_missing_artifact_or_invalid_device_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError):
                verify_artifacts(directory)
        with self.assertRaises(ValueError):
            BGEScorer("unused", device="auto")

    def test_no_experiment_imports(self):
        import ast
        for name in ("scorer.py", "server.py", "prefetch.py"):
            tree = ast.parse(Path(__file__).with_name(name).read_text())
            modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            self.assertFalse(any("validation" in module or "bge_local" in module for module in modules))


@unittest.skipUnless(os.environ.get("BGE_TEST_MODEL_DIR"), "Explicit local model path required")
class RealModelTests(unittest.TestCase):
    def test_local_offline_classifier_and_long_pair_gate(self):
        scorer = BGEScorer(os.environ["BGE_TEST_MODEL_DIR"], device=os.environ.get("BGE_TEST_DEVICE", "cpu"))
        scorer.load()
        result = scorer.score("How many seats does the table have?", [
            "Title: Table details\nContent:\nThe table has four seats.",
            "Title: Laundry guide\nContent:\nWash clothes using a gentle cycle."])
        self.assertEqual(len(result["scores"]), 2)
        self.assertGreater(result["scores"][0], result["scores"][1])
        with self.assertRaises(PairTooLong):
            scorer.score("query", ["evidence " * 10000])


if __name__ == "__main__":
    unittest.main()
