"""Evaluation-only SELECT transport: durable scope, buffered results, bounded recovery.

No application imports, query rewriting, result caching, ranking or provider calls.
Connection factories and fresh identity checks are supplied by the frozen runner.
"""
from hashlib import sha256
import inspect
from time import monotonic, sleep
import uuid

from sqlalchemy.sql import visitors, operators
from sqlalchemy.sql.elements import BinaryExpression, BindParameter, TextClause
from sqlalchemy.sql.functions import FunctionElement
from sqlalchemy.sql.selectable import Select

from database import canary_schema as s
from services.canary_contracts import CanaryError
from services.structural_chunking import digest
from scripts.canary_evaluation_resume import require
from scripts.canary_evaluation_transport import transient_transport, safe_error, ChannelTransportFailure
from scripts.canary_session_diagnostics import _safe_identity

BACKOFF = (1, 2, 5, 10, 20)
PURE_FUNCTIONS = frozenset(('coalesce', 'count', 'json_agg', 'row_to_json',
    'websearch_to_tsquery', 'to_tsvector', 'ts_rank_cd', 'numnode', 'querytree'))
READ_FRAGMENTS = frozenset(("'english'::regconfig", 'CAST(:query_vector AS vector(768))'))


class ReproducibleReadFailure(CanaryError):
    pass


class OwnershipTransportFailure(ChannelTransportFailure):
    """Read retry cannot replace the ownership connection; restart the unsaved lane."""


class ReadRecoveryExhausted(ChannelTransportFailure):
    """Probes can read the row, but bounded read cycles exhausted; try a fresh lane."""


def readonly(statement, allowed_text=()):
    if isinstance(statement, TextClause):
        return statement.text in allowed_text
    return (isinstance(statement, Select) and statement._for_update_arg is None
            and not any(getattr(node, 'is_dml', False)
                or isinstance(node, FunctionElement) and
                   (node.name not in PURE_FUNCTIONS or getattr(node, 'packagenames', ()))
                or isinstance(node, TextClause) and node.text not in READ_FRAGMENTS
                or getattr(node, 'is_literal', False) and getattr(node, 'name', None) != "''"
                for node in visitors.iterate(statement)))


def operation_identity(statement, parameters, dialect):
    compiled = statement.compile(dialect=dialect)
    binds = dict(compiled.params)
    binds.update(parameters or {})
    scope = {}
    for node in visitors.iterate(statement):
        if not isinstance(node, BinaryExpression) or node.operator is not operators.eq:
            continue
        column, bind = node.left, node.right
        key = getattr(column, 'name', None)
        if key not in (*s.DOC, 'atom_id', 'entry_id', 'chunk_id') or not isinstance(bind, BindParameter):
            continue
        value = binds.get(compiled.bind_names.get(bind))
        valid = type(value) is int and value >= 0 if key == 'chunk_id' else _safe_identity(key, value)
        if valid:
            if key in scope and scope[key] != value:
                scope.pop(key, None)  # compound multi-scope queries retain the complete bind digest
            else:
                scope[key] = value
    return dict(query_shape_digest=sha256(str(compiled).encode()).hexdigest(),
                bind_digest=digest(binds), source_scope=scope)


def caller_method():
    frame = inspect.currentframe()
    try:
        while frame:
            name = frame.f_code.co_filename.replace('\\', '/')
            if name.endswith(('canary_repository.py', 'canary_split_evidence.py',
                              'canary_evaluation_validation.py', 'canary_evaluation_resume.py')):
                return frame.f_code.co_name
            frame = frame.f_back
        return 'evaluation_read'
    finally:
        del frame


class ReadTelemetry:
    def __init__(self, writer, context=None, clock=monotonic):
        self.writer, self.context, self.clock = writer, context or {}, clock
        self.ordinal = 0
        self.retries = self.recoveries = 0
        self.failed_ms = self.success_ms = self.backoff_ms = 0.0
        self.latest = None

    def begin(self, identity, token, attempt, purpose):
        self.ordinal += 1
        record = dict(self.context, **identity, operation_ordinal=self.ordinal,
                      attempt_ordinal=attempt, connection_token=token,
                      purpose=purpose, phase='BEFORE_SQL', monotonic=self.clock(),
                      repository_method=caller_method())
        record['retrieval_stage'] = ('validation' if purpose == 'REVALIDATION' else
                                     record['repository_method'])
        self.writer(record)
        return record

    def end(self, record, started, result, conn, *, rows=None, error=None, hash_status='NOT_APPLICABLE'):
        elapsed = (self.clock() - started) * 1000
        after = dict(record, phase='AFTER_SQL', result=result, elapsed_ms=elapsed,
                     row_count=rows, connection_state='INVALID_OR_CLOSED' if
                     conn is None or conn.closed or conn.invalidated else 'HEALTHY',
                     hash_status=hash_status)
        if error is not None:
            after['failure'] = safe_error(error)
        self.writer(after)
        self.latest = after
        if result == 'SUCCESS':
            self.success_ms += elapsed
        else:
            self.failed_ms += elapsed

    def summary(self):
        return dict(sql_attempts=self.ordinal, retries=self.retries, recoveries=self.recoveries,
                    failed_read_ms=self.failed_ms, successful_read_ms=self.success_ms,
                    backoff_ms=self.backoff_ms)


class ObservedConnection:
    """Single attempt including fetch/decode; FrozenResult preserves SQLAlchemy rows.

    Eager buffering changes neither projection nor order. All repository SELECTs
    already consume bounded candidate/manifest/document rows; no rows are cut off.
    """
    def __init__(self, conn, telemetry, *, allowed_text=(), attempt=1, purpose='READ'):
        self.raw, self.telemetry = conn, telemetry
        self.allowed_text, self.attempt, self.purpose = allowed_text, attempt, purpose
        self.token = conn.info.setdefault('generic_read_token', uuid.uuid4().hex)

    @property
    def dialect(self):
        return self.raw.dialect

    def execute(self, statement, parameters=None, **kwargs):
        require(readonly(statement, self.allowed_text), 'RECOVERY_SELECT_ONLY')
        require(not kwargs and (parameters is None or isinstance(parameters, dict)), 'EXACT_SINGLE_EXECUTE_REQUIRED')
        identity = operation_identity(statement, parameters, self.dialect)
        record = self.telemetry.begin(identity, self.token, self.attempt, self.purpose)
        started = self.telemetry.clock()
        try:
            result = self.raw.execute(statement, parameters or {})
            frozen = result.freeze()  # Fetch-time transport failures stay inside this boundary.
            hashes = False
            for row in frozen.data:
                values = row._mapping
                if 'payload' in values and values.get('payload_hash') is not None:
                    require(digest(values['payload']) == values['payload_hash'], 'READ_PAYLOAD_HASH_MISMATCH')
                    hashes = True
            self.telemetry.end(record, started, 'SUCCESS', self.raw, rows=len(frozen.data),
                               hash_status='PASS' if hashes else 'DEFERRED_TO_REPOSITORY')
            return frozen()
        except Exception as exc:
            category = ('DATABASE_TIMEOUT' if transient_transport(exc) and
                        ('Timeout' in type(exc).__name__ or 'Timeout' in type(getattr(exc, 'orig', None)).__name__)
                        else 'TRANSPORT_FAILURE' if transient_transport(exc) else 'VALIDATION_FAILURE')
            self.telemetry.end(record, started, category, self.raw, error=exc, hash_status='NOT_COMPLETED')
            raise


class RecoveringConnection:
    """Same statement object/binds, new read-only transaction after transport loss.

    validate() must check frozen identity on every new physical connection. It is
    observed but not recursively retried: a failed gate consumes this attempt.
    No retry for validation failures, writes or artifact persistence errors.
    """
    def __init__(self, factory, validate, telemetry, diagnostic, *, dialect,
                 allowed_text=(), sleeper=sleep, max_reads=64, max_age=60):
        self.factory, self.validate, self.telemetry, self.diagnostic = factory, validate, telemetry, diagnostic
        self.dialect, self.allowed_text, self.sleeper = dialect, allowed_text, sleeper
        self.max_reads, self.max_age = max_reads, max_age
        self.raw = None
        self.reads = 0
        self.opened = 0

    def close(self, broken=False):
        conn, self.raw = self.raw, None
        if conn is not None:
            if broken:
                conn.invalidate()  # Never rollback/unlock by SQL on a known-broken socket.
            conn.close()

    def _connect(self, attempt):
        self.raw = self.factory()
        self.validate(ObservedConnection(self.raw, self.telemetry, allowed_text=self.allowed_text,
                                        attempt=attempt, purpose='REVALIDATION'))
        self.opened, self.reads = monotonic(), 0

    def execute(self, statement, parameters=None, **kwargs):
        require(readonly(statement, self.allowed_text), 'RECOVERY_SELECT_ONLY')
        require(not kwargs and (parameters is None or isinstance(parameters, dict)), 'EXACT_SINGLE_EXECUTE_REQUIRED')
        expected = operation_identity(statement, parameters, self.dialect)
        if self.raw is not None and (self.reads >= self.max_reads or monotonic()-self.opened >= self.max_age):
            self.close()
        failed = False
        failed_times = []
        attempt = 0
        for cycle in range(2):
            # Initial cycle: initial read + five retries. Second: five retries only.
            delays = (0, *BACKOFF) if cycle == 0 else BACKOFF
            for delay in delays:
                attempt += 1
                if delay:
                    self.telemetry.retries += 1
                    self.telemetry.backoff_ms += delay * 1000
                    self.sleeper(delay)
                require(operation_identity(statement, parameters, self.dialect) == expected,
                        'READ_SEMANTIC_IDENTITY_CHANGED')
                try:
                    if self.raw is None:
                        self._connect(attempt)
                    out = ObservedConnection(self.raw, self.telemetry, allowed_text=self.allowed_text,
                                             attempt=attempt).execute(statement, parameters)
                    self.reads += 1
                    if failed:
                        self.telemetry.recoveries += 1
                        self.telemetry.writer(dict(self.telemetry.context, **expected,
                            operation_ordinal=self.telemetry.ordinal, phase='TRANSPORT_RECOVERY_SUCCESS',
                            attempt_ordinal=attempt, failed_elapsed_ms=failed_times,
                            successful_elapsed_ms=self.telemetry.latest['elapsed_ms']))
                    return out
                except Exception as exc:
                    if isinstance(exc, OwnershipTransportFailure):
                        self.close(broken=True)
                        raise
                    if not transient_transport(exc):
                        raise
                    failed = True
                    failed_times.append(self.telemetry.latest['elapsed_ms'] if self.telemetry.latest else None)
                    self.close(broken=True)
            self.telemetry.writer(dict(self.telemetry.context, **expected,
                operation_ordinal=self.telemetry.ordinal, phase='TRANSPORT_RECOVERY_DIAGNOSTIC', cycle=cycle+1))
            # Diagnostic performs up to three independent exact probes and never scores them.
            if not self.diagnostic(statement, parameters, expected, cycle):
                raise ReproducibleReadFailure('REPRODUCIBLE_DATABASE_READ_FAILURE')
        raise ReadRecoveryExhausted('READ_RECOVERY_CYCLES_EXHAUSTED')
