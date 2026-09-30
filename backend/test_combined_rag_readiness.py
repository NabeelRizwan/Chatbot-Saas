"""Readiness tests with local SQLite and an in-process HTTP transport."""
import atexit
import os
from pathlib import Path
from tempfile import TemporaryDirectory
_bootstrap = TemporaryDirectory(prefix="combined-rag-readiness-")
os.environ["DATABASE_URL"] = "sqlite:///" + (Path(_bootstrap.name) / "local.sqlite").as_posix()
import unittest
from unittest.mock import patch

import httpx

from services.combined_rag.config import MODEL, REVISION
from services.combined_rag.readiness import readiness
from services import health_service


def _close_database():
    from sqlalchemy.orm import close_all_sessions
    close_all_sessions()
    health_service.engine.dispose()
    _bootstrap.cleanup()


atexit.register(_close_database)


class ReadinessTests(unittest.TestCase):
    def probe(self, payload=None, *, status=200):
        payload = payload if payload is not None else {
            "ok": True, "loaded": True, "model": MODEL, "revision": REVISION,
            "dtype": "float32", "batch_size": 1,
        }
        def handle(request):
            self.assertEqual(str(request.url), "http://private.test:8080/ready")
            self.assertEqual(request.headers["Authorization"], "Bearer test-secret")
            self.assertEqual(request.method, "GET")
            return httpx.Response(status, json=payload)
        with patch.dict(os.environ, {
                "RAG_COMBINED_RERANKER_URL": "http://private.test:8080/rerank",
                "RAG_COMBINED_RERANKER_TOKEN": "test-secret"}):
            return readiness(transport=httpx.MockTransport(handle))

    def test_authenticated_identity_probe_without_inference(self):
        self.assertEqual(self.probe(), "ready")

    def test_missing_config_wrong_identity_auth_or_redirect_not_ready(self):
        with patch.dict(os.environ, {"RAG_COMBINED_RERANKER_URL": ""}):
            self.assertEqual(readiness(), "misconfigured")
        self.assertEqual(self.probe({"ok": True, "loaded": True, "model": "wrong"}), "identity_mismatch")
        self.assertEqual(self.probe(status=401), "unavailable")
        self.assertEqual(self.probe(status=302), "unavailable")

    def test_offline_tokenizer_failure_blocks_readiness(self):
        with patch("services.combined_rag.readiness.count_tokens", side_effect=RuntimeError("asset missing")):
            self.assertEqual(self.probe(), "tokenizer_unavailable")

    def test_api_requires_ranker_and_keeps_liveness_independent(self):
        with patch.dict(os.environ, {"APP_ENV": "development"}), \
                patch.object(health_service, "engine"), \
                patch.object(health_service, "migration_state", return_value=("same", "same")), \
                patch.object(health_service, "native_readiness", return_value="ready"), \
                patch.object(health_service, "rag_readiness", return_value="unavailable"):
            ready, payload = health_service.readiness_status()
        self.assertFalse(ready)
        self.assertEqual(payload["dependencies"]["retrieval"], "unavailable")
        self.assertEqual(health_service.liveness_status(), {"status": "alive"})
        with patch.dict(os.environ, {"APP_ENV": "development"}), \
                patch.object(health_service, "engine"), \
                patch.object(health_service, "migration_state", return_value=("same", "same")), \
                patch.object(health_service, "native_readiness", return_value="ready"), \
                patch.object(health_service, "rag_readiness", return_value="ready"):
            self.assertTrue(health_service.readiness_status()[0])


if __name__ == "__main__":
    unittest.main()
