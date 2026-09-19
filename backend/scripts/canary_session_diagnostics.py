"""Evaluation-only session bounds and identity-only SQL diagnostics.

No query mutation, row consumption, provider access, or database writes. The
caller supplies an atomic bounded-record writer and the original session clock.
"""
from dataclasses import dataclass
from hashlib import sha256
import math
import re
from time import monotonic

from sqlalchemy import event
from sqlalchemy.sql import operators, visitors
from sqlalchemy.sql.elements import BindParameter, BinaryExpression, BooleanClauseList
from sqlalchemy.sql.selectable import Select

from database import canary_schema as s


class SessionWindowEnded(RuntimeError):
    pass


@dataclass(frozen=True)
class SessionWindow:
    started_monotonic: float
    clock: object = monotonic

    def __post_init__(self):
        if not math.isfinite(self.started_monotonic) or self.started_monotonic > self.clock():
            raise ValueError('INVALID_SESSION_MONOTONIC')

    @property
    def elapsed(self):
        return max(0.0, self.clock() - self.started_monotonic)

    @property
    def shutdown_ready(self):
        return self.elapsed >= 23 * 60

    @property
    def database_closed(self):
        return self.elapsed >= 24 * 60

    def require_database(self):
        if self.database_closed:
            raise SessionWindowEnded('SESSION_USAGE_WINDOW_ENDED')

    def may_start_case(self, estimated_seconds=0):
        if not math.isfinite(estimated_seconds) or estimated_seconds < 0:
            raise ValueError('INVALID_CASE_ESTIMATE')
        elapsed = self.elapsed
        return elapsed < 23 * 60 and (elapsed < 22 * 60 or (
            estimated_seconds > 0 and elapsed + estimated_seconds < 23 * 60))


_HASH = re.compile(r'[a-f0-9]{64}\Z')
_IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z')
_HASH_FIELDS = {'source_hash', 'manifest_hash', 'profile_hash', 'policy_hash', 'atom_id'}
_KEYS = frozenset((*s.DOC, 'atom_id'))


def _safe_identity(key, value):
    if key in s.INTS:
        return type(value) is int and 0 <= value < 2**63
    if key in _HASH_FIELDS:
        return isinstance(value, str) and bool(_HASH.fullmatch(value))
    if key == 'lane':
        return value in ('STRUCTURAL_CANARY', 'LEGACY_CONTROL')
    return isinstance(value, str) and bool(_IDENTIFIER.fullmatch(value))


def evidence_scope(context):
    """Recognize only the unchanged repository's exact scoped atom-row SELECT.

    Extraction uses compiled bind mappings, never parsing literal SQL or result
    data. Incomplete, duplicate, non-equality, or unrecognized shapes are ignored.
    """
    compiled = getattr(context, 'compiled', None)
    statement = getattr(compiled, 'statement', None)
    if not isinstance(statement, Select):
        return None
    columns = list(statement.selected_columns)
    if len(columns) != len(s.atoms.c) or any(a is not b for a, b in zip(columns, s.atoms.c)):
        return None
    if len(statement.get_final_froms()) != 1 or statement.get_final_froms()[0] is not s.atoms:
        return None
    if statement._limit_clause is not None or statement._offset_clause is not None:
        return None
    parameter_sets = getattr(context, 'compiled_parameters', ())
    if len(parameter_sets) != 1:
        return None
    parameters = parameter_sets[0]
    scope = {}
    for clause in statement._where_criteria:
        for expression in visitors.iterate(clause):
            if isinstance(expression, BooleanClauseList) and expression.operator is not operators.and_:
                return None
            if not isinstance(expression, BinaryExpression):
                continue
            column, bind = expression.left, expression.right
            if (getattr(column, 'table', None) is not s.atoms or column.name not in _KEYS
                    or expression.operator is not operators.eq or not isinstance(bind, BindParameter)):
                return None
            name = compiled.bind_names.get(bind)
            value = parameters.get(name)
            if column.name in scope or not _safe_identity(column.name, value):
                return None
            scope[column.name] = value
    return scope if set(scope) == _KEYS else None


class EvidenceTelemetry:
    """Per-engine hooks; latest-operation durability precedes cursor execution."""
    def __init__(self, engine, writer, *, window=None, clock=monotonic):
        self.engine, self.writer, self.window, self.clock = engine, writer, window, clock
        self.context = None
        self.ordinal = 0
        self.latest = None
        self.persistence_errors = []
        self._active = {}
        self._listeners = (('engine_connect', self._connected),
                           ('before_cursor_execute', self._before),
                           ('after_cursor_execute', self._after),
                           ('handle_error', self._error))
        for name, callback in self._listeners:
            event.listen(engine, name, callback)

    def set_context(self, case_id, lane, manifest_hash, generation, retry_ordinal=0):
        if (type(case_id) is not int or not 1 <= case_id <= 90
                or not _safe_identity('lane', lane)
                or not _safe_identity('manifest_hash', manifest_hash)
                or not _safe_identity('generation', generation)
                or type(retry_ordinal) is not int or retry_ordinal not in (0, 1)):
            raise ValueError('INVALID_DIAGNOSTIC_CONTEXT')
        self.context = dict(case_id=case_id, lane=lane, manifest_hash=manifest_hash,
                            generation=generation, retry_ordinal=retry_ordinal)

    def _connected(self, conn):
        conn.info['_canary_diagnostic_connected_at'] = self.clock()

    def _before(self, conn, cursor, statement, parameters, context, executemany):
        if self.window is not None:
            self.window.require_database()
        if self.context is None or executemany:
            return
        scope = evidence_scope(context)
        if scope is None:
            return
        if any(scope[key] != self.context[key] for key in ('lane', 'manifest_hash', 'generation')):
            raise ValueError('DIAGNOSTIC_SCOPE_CONTEXT_MISMATCH')
        now = self.clock()
        self.ordinal += 1
        record = dict(self.context, source_scope=scope, operation_ordinal=self.ordinal,
                      query_shape_sha256=sha256(statement.encode('utf-8')).hexdigest(),
                      connection_age_ms=max(0.0, now - conn.info.get(
                          '_canary_diagnostic_connected_at', now)) * 1000,
                      elapsed_ms=0.0, result_category='STARTED')
        self._active[id(context)] = (now, record)
        self.latest = record
        self.writer(dict(record))

    def _finish(self, context, category):
        active = self._active.pop(id(context), None)
        if active is None:
            return
        started, record = active
        result = dict(record, elapsed_ms=max(0.0, self.clock() - started) * 1000,
                      result_category=category)
        self.latest = result
        self.writer(dict(result))

    def _after(self, conn, cursor, statement, parameters, context, executemany):
        self._finish(context, 'EXECUTED')

    def _error(self, exception_context):
        # Never inspect/stringify the exception, driver SQL, or parameters.
        try:
            self._finish(exception_context.execution_context, 'DATABASE_ERROR')
        except Exception:
            # STARTED was durable before execution. A later diagnostic-write
            # failure must not replace the original database/transport error.
            self.persistence_errors.append('ERROR_TELEMETRY_WRITE_FAILED')

    def close(self):
        for name, callback in self._listeners:
            event.remove(self.engine, name, callback)
        self._listeners = ()
