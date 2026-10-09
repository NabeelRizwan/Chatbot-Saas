"""Private retrieval API. The SaaS database remains the source of authority."""
from __future__ import annotations

from contextlib import contextmanager, asynccontextmanager
import asyncio
import gc
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import shutil
import threading
import time

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from retrieval_engine.config import RetrievalConfig
from retrieval_engine.retrieval import LocalRetrievalEngine

logger = logging.getLogger(__name__)
MAX_BODY = 50 * 1024 * 1024


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    source_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    title: str = Field(min_length=1, max_length=4096)
    url: str = Field(min_length=1, max_length=8192)
    text: str = Field(min_length=1, max_length=5_000_000)
    version: int = Field(ge=1)
    crawl_id: int | None = Field(default=None, ge=1)


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    organization_id: int = Field(ge=1)
    bot_id: int = Field(ge=1)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class Snapshot(Scope):
    documents: list[Record] = Field(min_length=1, max_length=10000)


class Search(Scope):
    question: str = Field(min_length=1, max_length=2000)


def fingerprint(documents):
    return hashlib.sha256(json.dumps(documents, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def authorize(authorization: str = Header(default="")):
    token = os.environ.get("LLAMA_RETRIEVAL_TOKEN", "")
    if len(token) < 32:
        raise HTTPException(503, "retrieval_auth_not_configured")
    if not hmac.compare_digest(authorization.encode(), ("Bearer " + token).encode()):
        raise HTTPException(401, "unauthorized")


class IndexStore:
    """One active engine; bounded immutable disk caches, no cross-bot search."""

    def __init__(self, root=None, model_root=None, engine_factory=LocalRetrievalEngine):
        self.root = Path(root or os.getenv("LLAMA_DATA_DIR", "/data/retrieval")).resolve()
        self.model_root = Path(model_root or os.getenv("LLAMA_MODEL_ROOT", Path(__file__).parent)).resolve()
        self.engine_factory = engine_factory
        self.lock = threading.Lock()
        self.active_key = None
        self.engine = None
        self.max_bytes = int(os.getenv("LLAMA_CACHE_MAX_BYTES", str(2 * 1024**3)))
        self.max_entries = int(os.getenv("LLAMA_CACHE_MAX_ENTRIES", "32"))
        self.ttl = int(os.getenv("LLAMA_CACHE_TTL_SECONDS", "86400"))
        if min(self.max_bytes, self.max_entries, self.ttl) < 1:
            raise ValueError("Retrieval cache limits must be positive")

    @contextmanager
    def admitted(self):
        if not self.lock.acquire(timeout=5):
            raise HTTPException(503, "retrieval_busy", headers={"Retry-After": "2"})
        try:
            yield
        finally:
            self.lock.release()

    def path(self, scope):
        return self.root / f"{scope.organization_id}-{scope.bot_id}" / scope.fingerprint

    def prune(self, keep):
        entries = []
        now = time.time()
        for path in self.root.glob("*/*"):
            if not path.is_dir() or path.is_symlink():
                continue
            if path.resolve().parent.parent != self.root:
                raise RuntimeError("Unsafe cache path")
            files = [file for file in path.rglob("*") if file.is_file()]
            entries.append((path, sum(file.stat().st_size for file in files), path.stat().st_mtime))
        total = sum(size for _, size, _ in entries)
        remaining = len(entries)
        for path, size, modified in sorted(entries, key=lambda entry: entry[2]):
            if path == keep:
                continue
            if now - modified > self.ttl or total > self.max_bytes or remaining > self.max_entries:
                shutil.rmtree(path)
                total -= size
                remaining -= 1
        if total > self.max_bytes:
            raise HTTPException(507, "retrieval_cache_capacity_exceeded")

    def load(self, scope, documents=None):
        path = self.path(scope)
        corpus = path / "corpus.jsonl"
        if documents is not None:
            if fingerprint(documents) != scope.fingerprint:
                raise HTTPException(422, "snapshot_fingerprint_mismatch")
            if len({row['id'] for row in documents}) != len(documents) or any(
                    row['id'] != row['source_id'] for row in documents):
                raise HTTPException(422, "snapshot_identity_invalid")
        if self.active_key == path and self.engine is not None:
            os.utime(path, None)
            return self.engine
        if documents is None and not corpus.is_file():
            raise HTTPException(409, "snapshot_required")
        if documents is None:
            documents = [json.loads(line) for line in corpus.read_text(encoding="utf-8").splitlines()]
            if fingerprint(documents) != scope.fingerprint:
                raise HTTPException(503, "snapshot_integrity_failed")
        path.mkdir(parents=True, exist_ok=True)
        if not corpus.exists():
            temporary = path / "corpus.pending"
            temporary.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in documents), encoding="utf-8")
            temporary.replace(corpus)
        self.prune(path)
        # Release the previous model/index before loading another bot. This is
        # deliberately a bounded single-worker service; replicas scale capacity.
        self.engine = None
        self.active_key = None
        gc.collect()
        engine = self.engine_factory(RetrievalConfig(root=self.model_root,
            corpus_file=corpus, index_directory=path / "indexes"))
        engine.build_or_load()
        self.prune(path)
        self.active_key, self.engine = path, engine
        os.utime(path, None)
        return engine

    def sweep(self):
        if not self.lock.acquire(blocking=False):
            return
        try:
            if self.active_key is not None and time.time() - self.active_key.stat().st_mtime > self.ttl:
                self.engine = None
                self.active_key = None
                gc.collect()
            self.prune(self.active_key)
        finally:
            self.lock.release()


store = IndexStore()


@asynccontextmanager
async def lifespan(app):
    async def cleanup():
        while True:
            await asyncio.sleep(60)
            try:
                await asyncio.to_thread(store.sweep)
            except Exception:
                logger.exception('Retrieval cache maintenance failed')
    task = asyncio.create_task(cleanup())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        messages, size = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            size += len(message.get('body', b''))
            if size > MAX_BODY:
                await send({'type': 'http.response.start', 'status': 413, 'headers': []})
                await send({'type': 'http.response.body', 'body': b'request_too_large'})
                return
            messages.append(message)
            if not message.get('more_body'):
                break
        async def buffered():
            return messages.pop(0) if messages else await receive()
        await self.app(scope, buffered, send)


app.add_middleware(BodyLimit)


@app.get("/health/live")
def live():
    return {"status": "alive"}


@app.get("/health/ready", dependencies=[Depends(authorize)])
def ready():
    models = store.model_root / 'models'
    required = ('embedding/model_optimized.onnx', 'embedding/tokenizer.json',
        'reranker/model.safetensors', 'reranker/config.json',
        'tiktoken/9b5ad71b2ce5302211f9c61530b329a4922fc6a4',
        'nltk_data/corpora/stopwords', 'nltk_data/tokenizers/punkt_tab')
    if not all((models / name).exists() for name in required):
        raise HTTPException(503, 'model_artifacts_missing')
    store.root.mkdir(parents=True, exist_ok=True)
    return {"status": "ready", "engine": "llamaindex", "protocol": 1}


@app.post("/v1/snapshots", dependencies=[Depends(authorize)])
def snapshot(body: Snapshot):
    with store.admitted():
        engine = store.load(body, [record.model_dump() for record in body.documents])
        return {"fingerprint": body.fingerprint, "status": engine.status()}


@app.post("/v1/retrieve", dependencies=[Depends(authorize)])
def retrieve(body: Search):
    with store.admitted():
        engine = store.load(body)
        try:
            result = engine.retrieve(body.question)
        except ValueError as error:
            # Oversized questions and invalid source spans fail closed; no
            # silent truncation, provider fallback or unscoped retry.
            logger.warning('Retrieval rejected input: %s', type(error).__name__)
            if str(error).startswith(('This question has ', 'This question exceeds ', 'Questions are limited to ')):
                raise HTTPException(422, 'question_too_long') from error
            raise HTTPException(422, 'retrieval_input_rejected') from error
        return {"fingerprint": body.fingerprint, **result}


@app.post("/v1/prepare", dependencies=[Depends(authorize)])
def prepare(body: Record):
    """Validate source parsing before atomic SaaS promotion; vectors warm after it."""
    with store.admitted():
        config = RetrievalConfig(root=store.model_root)
        config.apply_runtime_environment()
        from tokenizers import Tokenizer
        from llama_index.core import Document
        from retrieval_engine.document_nodes import build_nodes, has_textual_evidence
        tokenizer = Tokenizer.from_file(str(config.reranker_path / 'tokenizer.json'))
        tokenizer.no_truncation()
        tokenizer.no_padding()
        nodes = build_nodes([Document(id_=body.id, text=body.text,
            metadata={'source_id': body.source_id, 'title': body.title, 'url': body.url})],
            lambda text: tokenizer.encode(text, add_special_tokens=False).ids,
            config.chunk_tokens, config.chunk_overlap)
        count = sum(has_textual_evidence(node) for node in nodes)
        if not count:
            raise HTTPException(422, 'source_has_no_textual_evidence')
        return {'chunks': count, 'embeddings': 0}
