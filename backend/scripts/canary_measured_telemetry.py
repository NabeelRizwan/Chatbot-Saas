"""Observation-only evidence call/event records for the frozen paired evaluation."""
from hashlib import sha256
from time import monotonic
import uuid

from sqlalchemy import select
from database import canary_schema as s
from services.canary_contracts import CanaryError, Lane
from services.canary_repository import document_values, where
from services.structural_chunking import digest
from scripts.canary_session_diagnostics import EvidenceTelemetry, evidence_scope, _safe_identity
from scripts.canary_evaluation_transport import DatabaseTransportTimeout, transient_transport


class MeasuredEvidenceTelemetry(EvidenceTelemetry):
    def __init__(self, engine, writer, *, session, clock=monotonic):
        self.session = session
        self.pending = self.failed = None
        self.sql_count = self.evidence_count = 0
        super().__init__(engine, writer, clock=clock)

    def set_context(self, *args, **kwargs):
        super().set_context(*args, **kwargs)
        self.sql_count = self.evidence_count = 0
        self.failed = None

    def _connected(self, conn):
        super()._connected(conn)
        conn.info['_canary_measured_token'] = uuid.uuid4().hex

    def _before(self, conn, cursor, statement, parameters, context, executemany):
        if self.context is None:
            return
        self.sql_count += 1
        if self.pending is None or executemany:
            return
        record = self.pending['record']
        scope = evidence_scope(context, legacy=record['lane'] == 'LEGACY_CONTROL')
        if scope is None:
            return
        if scope != record['source_scope']:
            raise CanaryError('MEASURED_EVIDENCE_SCOPE_MISMATCH')
        record = dict(record, phase='BEFORE_SQL', statement_started=True,
                      query_shape_sha256=sha256(statement.encode()).hexdigest())
        self.pending['record'] = record
        self.writer(record)  # fsync/replace must finish before DBAPI execution

    def _after(self, *args):
        pass  # success is recorded only AFTER row fetch AND repository validation

    def _error(self, *args):
        pass  # wrapper catches fetch-time/non-DBAPI watchdog errors as well

    @staticmethod
    def connection_state(conn):
        return 'INVALID_OR_CLOSED' if conn.closed or conn.invalidated else 'OPEN'

    def observe(self, callback, conn, manifest, hard, route, key, *, now):
        if self.context is None or self.pending is not None:
            raise CanaryError('MEASURED_EVIDENCE_CONTEXT_REQUIRED')
        pin = next((p for p in manifest.documents if p.scope == route.source), None)
        if pin is None:
            # Original authorization boundary remains authoritative.
            return callback(manifest, hard, route, key, now=now)
        legacy = manifest.lane == Lane.LEGACY_CONTROL
        scope = document_values(manifest, pin)
        if any(not _safe_identity(k, v) for k, v in scope.items()):
            raise CanaryError('UNSAFE_DIAGNOSTIC_IDENTITY')
        scope = dict(scope, **({'chunk_id': int(key)} if legacy else {'atom_id': key}))
        table = s.legacy if legacy else s.atoms
        stmt = select(table.c.payload) if legacy else select(table)
        stmt = stmt.where(where(table, scope))
        self.ordinal += 1
        self.evidence_count += 1
        started = self.clock()
        record = dict(self.context, phase='BEFORE_CALL', source_scope=scope,
            evaluation_session=self.session, operation_ordinal=self.ordinal,
            attempt_ordinal=self.context['retry_ordinal'] + 1,
            connection_token=conn.info.setdefault('_canary_measured_token', uuid.uuid4().hex),
            monotonic_start=started, scope_digest=digest(dict(source=scope, hard=hard.identity())),
            query_shape_sha256=sha256(str(stmt.compile(dialect=conn.dialect)).encode()).hexdigest(),
            statement_started=False, result_category='STARTED')
        self.writer(record)
        self.pending = dict(record=record, route=route, key=key)
        try:
            result = callback(manifest, hard, route, key, now=now)
        except BaseException as exc:
            category = ('DATABASE_TIMEOUT' if isinstance(exc, DatabaseTransportTimeout)
                        or isinstance(getattr(exc, 'orig', None), DatabaseTransportTimeout)
                        else 'TRANSPORT_FAILURE' if transient_transport(exc) else 'VALIDATION_FAILURE')
            finished = dict(self.pending['record'], phase='AFTER_CALL', result_category=category,
                elapsed_ms=(self.clock()-started)*1000, row_count=None,
                payload_hash_validation='NOT_COMPLETED', connection_state=self.connection_state(conn))
            self.failed = dict(record=finished, route=route, key=key)
            self.latest = finished
            try:
                self.writer(finished)
            except BaseException:
                self.persistence_errors.append('ERROR_TELEMETRY_WRITE_FAILED')
            raise
        else:
            finished = dict(self.pending['record'], phase='AFTER_CALL', result_category='SUCCESS',
                elapsed_ms=(self.clock()-started)*1000, row_count=1,
                payload_hash_validation='NOT_PERFORMED_BY_LEGACY_METHOD' if legacy else 'PASS',
                connection_state=self.connection_state(conn))
            self.latest = finished
            self.writer(finished)
            return result
        finally:
            self.pending = None

    def summary(self):
        return dict(self.context or {}, evaluation_session=self.session,
            sql_execution_count=self.sql_count, evidence_calls=self.evidence_count,
            persistence_errors=list(self.persistence_errors), provider_calls=0)
