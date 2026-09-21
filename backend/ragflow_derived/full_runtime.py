"""Request-local dependency injection for the pinned advanced runtime.

No application ORM, default credentials, process-global tenant or network client
is discoverable here. Every operation carries an explicit capability bundle.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from types import SimpleNamespace
from .contracts import EngineError
from .upstream.timeouts import timeout
from uuid import uuid4


def get_uuid():
    return uuid4().hex


class _OperationCache:
    """Upstream cache interface with request/authority lifetime, no Redis discovery."""
    def get(self, key):
        value = current().cache.get(str(key))
        return value.decode('utf-8') if isinstance(value, bytes) else value

    def set(self, key, value, *args, **kwargs):
        current().cache[str(key)] = value
        return True

    def mget(self, keys):
        return [self.get(key) for key in keys]

    def delete(self, key):
        return current().cache.pop(str(key), None) is not None

    def exist(self, key):
        return str(key) in current().cache

    @property
    def REDIS(self):
        return self

    def sscan_iter(self, key, **kwargs):
        return iter(tuple(current().cache.get(str(key), set())))

    def pipeline(self, **kwargs):
        return _CachePipeline(self)


class _CachePipeline:
    # Checkpoints have operation lifetime only; no durable-resume claim.
    def __init__(self, cache):
        self.cache, self.operations = cache, []

    def set(self, key, value, **kwargs):
        self.operations.append(('set', key, value))
        return self

    def sadd(self, key, value):
        self.operations.append(('sadd', key, value))
        return self

    def expire(self, key, seconds):
        return self  # operation teardown is stricter than upstream's seven-day TTL

    def execute(self):
        state = current().cache
        for operation, key, value in self.operations:
            if operation == 'set':
                state[str(key)] = value
            else:
                state.setdefault(str(key), set()).add(value)
        self.operations.clear()
        return True


REDIS_CONN = _OperationCache()

_operation = ContextVar('ragflow_full_operation', default=None)


@dataclass
class FullOperation:
    scope: object
    store: object
    retriever: object
    catalog: object
    lock_factory: object = None
    canceled: object = None
    tools: object = None
    fatal: object = None
    cache: dict = field(default_factory=dict)

    def check(self):
        if self.fatal is not None:
            raise self.fatal
        try:
            self.store.check()
        except EngineError as exc:
            self.fatal = exc
            raise

    def refuse(self, code='UNAUTHORIZED_SCOPE', stage='advanced capability'):
        self.fatal = EngineError(code, stage)
        raise self.fatal


def current():
    value = _operation.get()
    if value is None:
        raise EngineError('UNAUTHORIZED_SCOPE', 'missing explicit advanced operation')
    value.check()
    return value


@contextmanager
def full_operation(value):
    value.check()
    token = _operation.set(value)
    try:
        yield value
        value.check()  # upstream recoverable exceptions cannot swallow a scope violation
    finally:
        value.tools = None
        value.cache.clear()
        _operation.reset(token)


class _Settings:
    def __getattr__(self, name):
        op = current()
        if name == 'docStoreConn':
            return op.store
        if name == 'retriever':
            return op.retriever
        if name == 'DOC_ENGINE':
            return 'elasticsearch'
        if name.startswith('DOC_ENGINE_'):
            return False
        raise AttributeError(name)


settings = _Settings()


class RequestTools:
    """Mapping-shaped replacement of upstream's shared navigation singleton."""
    def get(self, key, default=None):
        return current().tools if key == 'tools' else default

    def __setitem__(self, key, tools):
        op = current()
        if key != 'tools' or tools.tenant_ids != [op.scope.key] or tools.kb_ids != [op.scope.bot_id]:
            op.refuse(stage='navigation binding')
        op.tools = tools


def scoped_documents(requested=None):
    op = current()
    allowed = {s.document_id for s in op.scope.sources}
    if op.store.document_ids is not None:
        allowed &= op.store.document_ids
    if requested is None:
        return sorted(allowed)
    requested = list(requested)
    if not set(requested).issubset(allowed):
        op.refuse(stage='model document ID')
    return requested


Knowledgebase = SimpleNamespace


class KnowledgebaseService:
    @staticmethod
    def accessible(kb_id, tenant_id):
        op = current()
        if kb_id != op.scope.bot_id or tenant_id != op.scope.key:
            op.refuse(stage='dataset ownership')
        return True

    @staticmethod
    def get_by_id(kb_id):
        rows = KnowledgebaseService.get_by_ids([kb_id])
        return True, rows[0]

    @staticmethod
    def get_by_ids(ids):
        op = current()
        if list(ids) != [op.scope.bot_id]:
            op.refuse(stage='dataset ID')
        return op.catalog.knowledgebases()


class DocumentService:
    @staticmethod
    def query(*, kb_id):
        op = current()
        KnowledgebaseService.get_by_ids([kb_id])
        return op.catalog.documents()

    @staticmethod
    def get_disabled_doc_ids_by_kb_id(kb_id):
        op = current()
        KnowledgebaseService.get_by_ids([kb_id])
        return op.catalog.disabled_documents()

    @staticmethod
    def get_by_id(doc_id):
        scoped_documents([doc_id])
        docs = [d for d in current().catalog.documents() if d.id == doc_id]
        return bool(docs), docs[0] if docs else None


class DocMetadataService:
    @staticmethod
    def get_flatted_meta_by_kbs(kb_ids):
        KnowledgebaseService.get_by_ids(kb_ids)
        return current().catalog.flattened_metadata()

    @staticmethod
    def filter_doc_ids_by_meta_pushdown(kb_ids, conditions, logic):
        KnowledgebaseService.get_by_ids(kb_ids)
        return scoped_documents(current().catalog.filter_metadata(conditions, logic))


class _UnavailableHistory(type):
    def __getattr__(cls, name):
        current().refuse('MODE_UNAVAILABLE', 'versioned wiki history')


class FileCommitService(metaclass=_UnavailableHistory):
    """Versioned wiki compilation requires an explicitly installed history store."""


async def use_sql(*args, **kwargs):
    current().refuse('MODE_UNAVAILABLE', 'SQL dataset backend not configured')


class TaskCanceledException(EngineError):
    def __init__(self, *args):
        super().__init__('OPERATION_CANCELED')


def has_canceled(task_id):
    op = current()
    return bool(op.canceled and op.canceled(task_id))


class OwnedCompileLock:
    def __init__(self, key, **kwargs):
        op = current()
        if op.lock_factory is None:
            op.refuse('MODE_UNAVAILABLE', 'owned distributed compilation lock required')
        self.lock = op.lock_factory(op.scope, key, **kwargs)

    async def spin_acquire(self):
        try:
            return await self.lock.spin_acquire()
        except Exception:
            current().refuse('INDEX_FAILED', 'compilation lock')

    def acquire(self):
        current().check()
        return self.lock.acquire()

    def release(self):
        return self.lock.release()
