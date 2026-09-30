"""Private HTTP boundary. No request, credential, query or passage logging."""
from __future__ import annotations

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading

from .scorer import BGEScorer, InputError, PairTooLong, MODEL, REVISION, MAX_BODY_BYTES, validate_request


class RankingServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, address, scorer, token, *, queue_wait_seconds=60.0):
        if not isinstance(token, str) or not token.strip() or "\n" in token or "\r" in token:
            raise ValueError("COMBINED_RERANKER_TOKEN_REQUIRED")
        if (type(queue_wait_seconds) not in (int, float)
                or not 0 < queue_wait_seconds <= 90):
            raise ValueError("QUEUE_WAIT_MUST_BE_BETWEEN_ZERO_AND_90_SECONDS")
        self.scorer, self.token = scorer, token
        self.queue_wait_seconds = queue_wait_seconds
        self.scoring = threading.Lock()
        # One active operation and at most two waiting. Separate connection
        # capacity leaves room for health and fast auth/overload responses.
        self.ranking_slots = threading.BoundedSemaphore(3)
        self.connections = threading.BoundedSemaphore(8)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.connections.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.connections.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connections.release()

    def handle_error(self, request, client_address):
        # Socket failures never log request data or exception details.
        return


class Handler(BaseHTTPRequestHandler):
    server_version = "PrivateRanker"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        return

    def send_json(self, status, value):
        body = json.dumps(value, allow_nan=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def send_error(self, code, message=None, explain=None):
        self.send_json(code, {"error": "HTTP_REQUEST_REJECTED"})

    def do_GET(self):
        if self.path not in {"/health", "/ready"}:
            return self.send_json(404, {"error": "NOT_FOUND"})
        if self.path == "/ready" and not self.authorized():
            return self.send_json(401, {"error": "UNAUTHORIZED"})
        loaded = bool(self.server.scorer.loaded)
        self.send_json(200 if loaded else 503, {"ok": loaded, "loaded": loaded,
                       "model": MODEL, "revision": REVISION, "device": self.server.scorer.device,
                       "dtype": "float32", "batch_size": 1})

    def authorized(self):
        authorization = self.headers.get_all("Authorization", [])
        expected = "Bearer " + self.server.token
        return len(authorization) == 1 and hmac.compare_digest(
            authorization[0].encode(), expected.encode())

    def do_POST(self):
        if self.path != "/rerank":
            return self.send_json(404, {"error": "NOT_FOUND"})
        if not self.authorized():
            return self.send_json(401, {"error": "UNAUTHORIZED"})
        if self.headers.get("Transfer-Encoding"):
            return self.send_json(400, {"error": "TRANSFER_ENCODING_UNSUPPORTED"})
        sizes = self.headers.get_all("Content-Length", [])
        if len(sizes) != 1 or len(sizes[0]) > 10 or not sizes[0].isdigit():
            return self.send_json(411, {"error": "CONTENT_LENGTH_REQUIRED"})
        size = int(sizes[0])
        if not 0 < size <= MAX_BODY_BYTES:
            return self.send_json(413, {"error": "BODY_LIMIT_EXCEEDED"})
        if self.headers.get_content_type() != "application/json":
            return self.send_json(415, {"error": "JSON_REQUIRED"})
        try:
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise ValueError()
            query, documents = validate_request(json.loads(raw))
        except (ValueError, UnicodeError, OSError, RecursionError):
            return self.send_json(400, {"error": "INVALID_REQUEST"})
        if not self.server.scorer.loaded:
            return self.send_json(503, {"error": "MODEL_UNAVAILABLE"})
        if not self.server.ranking_slots.acquire(blocking=False):
            return self.send_json(503, {"error": "RANKER_BUSY"})
        acquired = False
        try:
            acquired = self.server.scoring.acquire(timeout=self.server.queue_wait_seconds)
            if not acquired:
                return self.send_json(503, {"error": "RANKER_QUEUE_TIMEOUT"})
            result = self.server.scorer.score(query, documents)
            self.send_json(200, result)
        except PairTooLong:
            self.send_json(422, {"error": "PAIR_TOKEN_LIMIT_EXCEEDED"})
        except InputError:
            self.send_json(400, {"error": "INVALID_REQUEST"})
        except Exception:
            self.send_json(503, {"error": "SCORING_UNAVAILABLE"})
        finally:
            if acquired:
                self.server.scoring.release()
            self.server.ranking_slots.release()


def main():
    token = os.environ.get("COMBINED_RERANKER_TOKEN", "")
    if not token.strip():
        raise SystemExit("COMBINED_RERANKER_TOKEN_REQUIRED")
    # Model directory/device are operator settings, never HTTP input. Offline
    # environment settings also constrain dependent libraries at startup.
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                      HF_HUB_DISABLE_TELEMETRY="1", TOKENIZERS_PARALLELISM="false")
    try:
        scorer = BGEScorer(os.environ.get("BGE_MODEL_DIR", "/model"),
                           device=os.environ.get("BGE_DEVICE", "cpu"),
                           threads=int(os.environ.get("BGE_THREADS", "2")))
        scorer.load()
        server = RankingServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), scorer, token,
                               queue_wait_seconds=float(os.environ.get("BGE_QUEUE_WAIT_SECONDS", "60")))
    except Exception:
        raise SystemExit("RERANKER_STARTUP_FAILED") from None
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
