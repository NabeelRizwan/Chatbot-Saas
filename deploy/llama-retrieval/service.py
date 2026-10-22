"""Private retrieval API. The SaaS database remains the source of authority."""
from __future__ import annotations

from contextlib import contextmanager, asynccontextmanager
import asyncio
from collections import OrderedDict
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sys
import threading
import time

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Literal
from starlette.concurrency import run_in_threadpool

from retrieval_engine.config import RetrievalConfig
from retrieval_engine.retrieval import LocalRetrievalEngine
from retrieval_engine.model_runtime import ModelRuntime
from rag2_engine.config import RetrievalConfig as RAG2Config
from rag2.pipeline import PlannedRetrievalEngine, validate_queries
from rag2.voyage import VoyagePredictor
from rag2.request_budget import RequestBudget, VoyageError

logger = logging.getLogger(__name__)
MAX_BODY = 50 * 1024 * 1024
RAG2_BUILD_REVISION = 'rag2-voyage-v1'


class PipelineProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    pipeline: Literal['og', 'rag2_improved'] = 'og'
    pipeline_build_revision: str | None = None

    @model_validator(mode='after')
    def supported_profile(self):
        expected = RAG2_BUILD_REVISION if self.pipeline == 'rag2_improved' else 'og-v1'
        if self.pipeline_build_revision not in (None, expected):
            raise ValueError('unsupported_pipeline_build_revision')
        if self.pipeline == 'rag2_improved' and self.pipeline_build_revision != expected:
            raise ValueError('pipeline_build_revision_required')
        return self


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    source_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    title: str = Field(min_length=1, max_length=4096)
    url: str = Field(min_length=1, max_length=8192)
    text: str = Field(min_length=1, max_length=5_000_000)
    version: int = Field(ge=1)
    crawl_id: int | None = Field(default=None, ge=1)


class Scope(PipelineProfile):
    model_config = ConfigDict(extra="forbid", strict=True)
    organization_id: int = Field(ge=1)
    bot_id: int = Field(ge=1)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class Snapshot(Scope):
    documents: list[Record] = Field(min_length=1, max_length=10000)


class Search(Scope):
    question: str = Field(min_length=1, max_length=2000)
    queries: list[str] = Field(default_factory=list, max_length=6)
    timeout_seconds: float = Field(default=1440, gt=0, le=1440, allow_inf_nan=False)

    @field_validator('queries')
    @classmethod
    def focused_queries(cls, value):
        return validate_queries(value)

    @model_validator(mode='after')
    def query_profile(self):
        if self.pipeline == 'og' and self.queries:
            raise ValueError('focused_queries_require_rag2')
        return self


class PrepareRecord(Record, PipelineProfile):
    pass


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
    """One inference lane, persistent models, bounded isolated corpus snapshots.

    All cache operations run inside admitted(). The lane pins its current index
    for the complete operation, so maintenance cannot evict an in-flight corpus.
    More CPU lanes use separate processes and separate cache directories.
    """

    def __init__(self, root=None, model_root=None, engine_factory=LocalRetrievalEngine,
                 runtime_factory=ModelRuntime, *, config_factory=RetrievalConfig,
                 shared_runtime=None, planned=False):
        self.root = Path(root or os.getenv("LLAMA_DATA_DIR", "/data/retrieval")).resolve()
        self.model_root = Path(model_root or os.getenv("LLAMA_MODEL_ROOT", Path(__file__).parent)).resolve()
        self.engine_factory = engine_factory
        self.config_factory = config_factory
        # Freeze the opt-in selection preference for this process. Model and
        # corpus snapshots remain reusable because this changes no embeddings.
        self.evidence_role_weight = float(os.getenv("LLAMA_EVIDENCE_ROLE_WEIGHT", "0"))
        question_coverage = os.getenv('LLAMA_INDEPENDENT_QUESTION_COVERAGE', 'false').strip().casefold()
        if question_coverage not in {'true', 'false', '1', '0'}:
            raise ValueError('LLAMA_INDEPENDENT_QUESTION_COVERAGE must be true or false.')
        self.independent_question_coverage = question_coverage in {'true', '1'}
        if planned:
            self.independent_question_coverage = True
            self.evidence_role_weight = 0.0
        RetrievalConfig(root=self.model_root, evidence_role_weight=self.evidence_role_weight)
        self.runtime = shared_runtime or (runtime_factory(RetrievalConfig(root=self.model_root))
            if engine_factory is LocalRetrievalEngine else None)
        self.lock = threading.Lock()
        self.active_key = None
        self.entries = OrderedDict()
        self.max_bytes = int(os.getenv("LLAMA_CACHE_MAX_BYTES", str(2 * 1024**3)))
        self.max_entries = int(os.getenv("LLAMA_CACHE_MAX_ENTRIES", "32"))
        self.ttl = int(os.getenv("LLAMA_CACHE_TTL_SECONDS", "86400"))
        self.memory_max_bytes = int(os.getenv("LLAMA_MEMORY_CACHE_MAX_BYTES", str(512 * 1024**2)))
        self.memory_max_entries = int(os.getenv("LLAMA_MEMORY_CACHE_MAX_ENTRIES", "4"))
        self.startup_warm_max_entries = int(os.getenv("LLAMA_STARTUP_WARM_MAX_ENTRIES", str(self.memory_max_entries)))
        self.startup_ready = False
        self.queue_limit = int(os.getenv("LLAMA_MAX_PENDING_REQUESTS", "16"))
        self.wait_seconds = float(os.getenv("LLAMA_QUEUE_WAIT_SECONDS", "60"))
        if min(self.max_bytes, self.max_entries, self.ttl, self.memory_max_bytes,
               self.memory_max_entries, self.wait_seconds) <= 0 or self.queue_limit < 0 or self.startup_warm_max_entries < 0:
            raise ValueError("Retrieval cache and admission limits must be positive")
        self.admission_slots = threading.BoundedSemaphore(self.queue_limit + 1)

    @property
    def engine(self):
        entry = self.entries.get(self.active_key)
        return entry[0] if entry else None

    @engine.setter
    def engine(self, value):
        if value is not None:
            raise ValueError('Install engines through load()')
        self.entries.pop(self.active_key, None)

    @contextmanager
    def admitted(self, budget=None):
        if not self.admission_slots.acquire(blocking=False):
            raise HTTPException(503, "retrieval_queue_full", headers={"Retry-After": "2"})
        acquired = False
        try:
            if budget is None:
                acquired = self.lock.acquire(timeout=self.wait_seconds)
            else:
                end = time.monotonic() + self.wait_seconds
                while not acquired and time.monotonic() < end:
                    acquired = self.lock.acquire(timeout=min(.1, budget.remaining(),
                        max(.001, end-time.monotonic())))
            if not acquired:
                raise HTTPException(503, "retrieval_busy", headers={"Retry-After": "2"})
            yield
        finally:
            if acquired:
                self.lock.release()
            self.admission_slots.release()

    def warm(self):
        self.startup_ready = False
        with self.admitted():
            if self.runtime is not None and not self.runtime.ready:
                self.runtime.load()
            self.root.mkdir(parents=True, exist_ok=True)
            self.prune(None)
            candidates = []
            for path in self.root.glob('*/*'):
                # Persisted caches are performance hints, never bot authority.
                # Accept only the canonical paths written by snapshot ingestion.
                if (not path.is_dir() or path.is_symlink() or path.resolve() != path
                        or not re.fullmatch(r'[1-9][0-9]{0,18}-[1-9][0-9]{0,18}', path.parent.name)
                        or not re.fullmatch(r'[a-f0-9]{64}', path.name)
                        or not (path / 'corpus.jsonl').is_file()):
                    continue
                candidates.append((path.stat().st_mtime, path))
            scopes, tenants = [], set()
            limit = min(self.startup_warm_max_entries, self.memory_max_entries, self.max_entries)
            for _, path in sorted(candidates, reverse=True):
                if len(scopes) >= limit:
                    break
                if path.parent.name in tenants:
                    continue
                tenants.add(path.parent.name)
                organization_id, bot_id = map(int, path.parent.name.split('-'))
                scopes.append(Scope(organization_id=organization_id, bot_id=bot_id, fingerprint=path.name))
            # Warm oldest first so retained entries favour the most recently used
            # snapshots if their combined resident size exceeds the memory budget.
            for scope in reversed(scopes):
                self.load(scope)
            self.startup_ready = True
            logger.info('Retrieval startup ready with %s retained corpus indexes', len(self.entries))

    def path(self, scope):
        return self.root / f"{scope.organization_id}-{scope.bot_id}" / scope.fingerprint

    def _drop(self, path):
        self.entries.pop(path, None)
        if self.active_key == path:
            self.active_key = None

    def prune(self, keep):
        entries = []
        now = time.time()
        for path in self.root.glob("*/*"):
            if not path.is_dir() or path.is_symlink():
                continue
            # Only canonical corpus directories belong to this store. In
            # particular, OG must never prune the separate pipeline namespace.
            if (not re.fullmatch(r'[1-9][0-9]{0,18}-[1-9][0-9]{0,18}', path.parent.name)
                    or not re.fullmatch(r'[a-f0-9]{64}', path.name)):
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
                self._drop(path)
                shutil.rmtree(path)
                total -= size
                remaining -= 1
        if total > self.max_bytes:
            raise HTTPException(507, "retrieval_cache_capacity_exceeded")

    def _resident_bytes(self, engine):
        # Account Python index graphs and array buffers, excluding shared models.
        # This bounds retained cache objects; allocator RSS is a separate OS limit.
        seen = self.runtime.shared_object_ids() if self.runtime else set()
        def size(value):
            if id(value) in seen:
                return 0
            seen.add(id(value))
            result = sys.getsizeof(value)
            if isinstance(value, dict):
                result += sum(size(key) + size(item) for key, item in value.items())
            elif isinstance(value, (list, tuple, set, frozenset, OrderedDict)):
                result += sum(size(item) for item in value)
            elif hasattr(value, 'nbytes') and type(value).__module__.startswith('numpy'):
                result += int(value.nbytes)
            elif hasattr(value, '__dict__') and not isinstance(value, type):
                result += size(vars(value))
            return result
        return size(engine)

    def _retain(self, path, engine):
        size = self._resident_bytes(engine)
        if size > self.memory_max_bytes:
            raise HTTPException(507, 'retrieval_memory_capacity_exceeded')
        while self.entries and (len(self.entries) >= self.memory_max_entries or
                sum(entry[1] for entry in self.entries.values()) + size > self.memory_max_bytes):
            oldest = next(iter(self.entries))
            self._drop(oldest)
        self.entries[path] = (engine, size)
        self.active_key = path

    def load(self, scope, documents=None):
        path = self.path(scope)
        corpus = path / "corpus.jsonl"
        if documents is not None:
            if fingerprint(documents) != scope.fingerprint:
                raise HTTPException(422, "snapshot_fingerprint_mismatch")
            if len({row['id'] for row in documents}) != len(documents) or any(
                    row['id'] != row['source_id'] for row in documents):
                raise HTTPException(422, "snapshot_identity_invalid")
        if path in self.entries:
            self.entries.move_to_end(path)
            self.active_key = path
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
        config = self.config_factory(root=self.model_root, corpus_file=corpus, index_directory=path / "indexes",
                                 evidence_role_weight=self.evidence_role_weight,
                                 independent_question_coverage=self.independent_question_coverage)
        engine = self.engine_factory(config, runtime=self.runtime) if self.runtime else self.engine_factory(config)
        engine.build_or_load()
        self.prune(path)
        self._retain(path, engine)
        os.utime(path, None)
        return engine

    def sweep(self):
        if not self.lock.acquire(blocking=False):
            return
        try:
            if self.active_key is not None and (not self.active_key.exists() or
                    time.time() - self.active_key.stat().st_mtime > self.ttl):
                self._drop(self.active_key)
            self.prune(self.active_key)
            while len(self.entries) > self.memory_max_entries or sum(entry[1] for entry in self.entries.values()) > self.memory_max_bytes:
                self._drop(next(iter(self.entries)))
        finally:
            self.lock.release()


store = IndexStore()
_rag2_store = None
_rag2_owner = None


def get_rag2_store():
    # Constructed during lifespan before serving. OG's legacy disk path stays
    # intact; switching policies never changes the immutable build namespace.
    global _rag2_store, _rag2_owner
    if _rag2_owner is not store:
        _rag2_store = IndexStore(store.root / 'pipelines' / RAG2_BUILD_REVISION,
            store.model_root, PlannedRetrievalEngine, config_factory=RAG2Config,
            shared_runtime=store.runtime, planned=True)
        _rag2_owner = store
    return _rag2_store


def selected_store(profile):
    return get_rag2_store() if profile.pipeline == 'rag2_improved' else store


def profile_result(profile):
    return ({'pipeline': 'rag2_improved', 'pipeline_build_revision': RAG2_BUILD_REVISION}
            if profile.pipeline == 'rag2_improved' else {})


@asynccontextmanager
async def lifespan(app):
    await asyncio.to_thread(store.warm)
    try:
        await asyncio.to_thread(get_rag2_store().warm)
    except Exception:
        # A broken RAG2 cache must not make the preserved OG service unavailable.
        logger.exception('RAG2 startup warmup failed')
    async def cleanup():
        while True:
            await asyncio.sleep(60)
            try:
                await asyncio.to_thread(store.sweep)
                await asyncio.to_thread(get_rag2_store().sweep)
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
    if not store.startup_ready or store.runtime is None or not store.runtime.ready:
        raise HTTPException(503, 'model_runtime_not_ready')
    store.root.mkdir(parents=True, exist_ok=True)
    return {"status": "ready", "engine": "llamaindex", "protocol": 1}


@app.get('/health/rag2', dependencies=[Depends(authorize)])
def rag2_ready():
    selected = get_rag2_store()
    if not selected.startup_ready or selected.runtime is None or not selected.runtime.ready:
        raise HTTPException(503, 'rag2_model_runtime_not_ready')
    try:
        predictor = VoyagePredictor.from_environment(selected.model_root)
        predictor.ledger.ready()
    except (VoyageError, OSError, ValueError) as error:
        reason = str(error) if isinstance(error, VoyageError) else 'rag2_configuration_invalid'
        raise HTTPException(503, reason) from None
    return {'status': 'ready', 'engine': 'llamaindex', 'protocol': 1,
            'pipeline': 'rag2_improved', 'pipeline_build_revision': RAG2_BUILD_REVISION,
            'quota_store': 'ready', 'provider_validation': 'not_probed'}


@app.post("/v1/snapshots", dependencies=[Depends(authorize)])
def snapshot(body: Snapshot):
    selected = selected_store(body)
    with selected.admitted():
        engine = selected.load(body, [record.model_dump() for record in body.documents])
        return {"fingerprint": body.fingerprint, "status": engine.status(), **profile_result(body)}


def execute_search(body: Search, budget=None):
    selected = selected_store(body)
    with selected.admitted(budget):
        engine = selected.load(body)
        try:
            if body.pipeline == 'rag2_improved':
                budget.remaining()
                result = engine.retrieve_planned(body.question, body.queries, budget=budget)
                budget.remaining()
            else:
                result = engine.retrieve(body.question)
        except VoyageError as error:
            raise HTTPException(503, str(error), headers={'Retry-After': '62'}) from None
        except ValueError as error:
            # Oversized questions and invalid source spans fail closed; no
            # silent truncation, provider fallback or unscoped retry.
            logger.warning('Retrieval rejected input: %s', type(error).__name__)
            if str(error).startswith(('This question has ', 'This question exceeds ', 'Questions are limited to ')):
                raise HTTPException(422, 'question_too_long') from error
            raise HTTPException(422, 'retrieval_input_rejected') from error
        return {"fingerprint": body.fingerprint, **result, **profile_result(body)}


@app.post("/v1/retrieve", dependencies=[Depends(authorize)])
async def retrieve(body: Search, request: Request):
    if body.pipeline == 'og':
        return await run_in_threadpool(execute_search, body)
    budget = RequestBudget(body.timeout_seconds)
    task = asyncio.create_task(asyncio.to_thread(execute_search, body, budget))
    try:
        while not task.done():
            if await request.is_disconnected():
                budget.cancel_event.set()
                break
            await asyncio.wait({task}, timeout=.1)
        return await asyncio.shield(task)
    except VoyageError as error:
        raise HTTPException(503, str(error), headers={'Retry-After': '62'}) from None
    finally:
        # The async provider transport observes this signal within its polling
        # interval, aborts an in-flight attempt and never retries after cancel.
        budget.cancel_event.set()


@app.post("/v1/prepare", dependencies=[Depends(authorize)])
def prepare(body: PrepareRecord):
    """Validate source parsing before atomic SaaS promotion; vectors warm after it."""
    selected = selected_store(body)
    with selected.admitted():
        config = selected.config_factory(root=selected.model_root)
        config.apply_runtime_environment()
        from tokenizers import Tokenizer
        from llama_index.core import Document
        if body.pipeline == 'rag2_improved':
            from rag2_engine.document_nodes import build_nodes, has_textual_evidence
        else:
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
