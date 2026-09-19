"""Process-local canary I/O bounds and advisory cleanup, not application policy."""
from contextlib import contextmanager
import select
from time import monotonic

from psycopg2 import extensions
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from scripts.canary_postgres_validation import safe_failure
from scripts.canary_recovery_state import ExclusiveRun as OriginalExclusiveRun


class DatabaseTransportTimeout(TimeoutError):
    """No transport address or driver message is retained."""


def wait_bounded(conn, *, seconds=30, clock=monotonic, wait=select.select):
    deadline = clock() + seconds
    while True:
        state = conn.poll()
        if state == extensions.POLL_OK:
            return
        if state not in (extensions.POLL_READ, extensions.POLL_WRITE):
            raise DatabaseTransportTimeout('DATABASE_POLL_STATE_FAILURE')
        remaining = deadline - clock()
        if remaining <= 0:
            raise DatabaseTransportTimeout('DATABASE_OPERATION_RESPONSE_TIMEOUT')
        descriptor = conn.fileno()
        ready = wait([descriptor] if state == extensions.POLL_READ else [],
                     [descriptor] if state == extensions.POLL_WRITE else [], [], remaining)
        if not any(ready):
            raise DatabaseTransportTimeout('DATABASE_OPERATION_RESPONSE_TIMEOUT')


@contextmanager
def bounded_database_io():
    previous = extensions.get_wait_callback()
    extensions.set_wait_callback(wait_bounded)
    try:
        yield
    finally:
        extensions.set_wait_callback(previous)


def transient_transport(exc):
    """No message heuristics: timeout, invalidation, or SQLSTATE connection class."""
    original = getattr(exc, 'orig', None)
    return (isinstance(exc, DatabaseTransportTimeout)
            or isinstance(original, DatabaseTransportTimeout)
            or isinstance(exc, DBAPIError) and (
                exc.connection_invalidated or
                str(getattr(original, 'pgcode', '') or '').startswith('08')))


def safe_error(exc):
    record = safe_failure(exc)
    record['category'] = ('DATABASE_TRANSPORT_FAILURE' if transient_transport(exc)
                          else 'NON_TRANSPORT_FAILURE')
    return record


class ExclusiveRun(OriginalExclusiveRun):
    """Evaluation-only repair; original sealed builder implementation stays pinned.

    The lock connection also performs the lane's read transaction. It is not an
    idle second connection held for hours. close() returns safe diagnostics and
    never replaces the caller's primary exception.
    """
    def __init__(self, db):
        super().__init__(db)
        self.cleanup_errors = []
        self.connection_state = 'NOT_OPEN'

    def acquire(self):
        try:
            super().acquire()
            self.connection_state = 'HEALTHY'
        except BaseException:
            self.close()
            raise

    def close(self):
        conn, self.conn = self.conn, None
        if conn is None:
            return self.cleanup_errors
        try:
            if conn.closed or conn.invalidated:
                self.connection_state = 'INVALID_OR_CLOSED'
                self.cleanup_errors.append(dict(exception_class='InvalidConnection',
                                                category='UNLOCK_SKIPPED_INVALID_CONNECTION'))
            else:
                # End a failed read transaction before attempting healthy unlock.
                if conn.in_transaction():
                    conn.rollback()
                conn.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': self.key})
                conn.commit()
                self.connection_state = 'RELEASED'
        except BaseException as exc:
            self.connection_state = 'UNLOCK_FAILED'
            self.cleanup_errors.append(safe_error(exc))
        finally:
            try:
                conn.close()
            except BaseException as exc:
                self.cleanup_errors.append(safe_error(exc))
        return self.cleanup_errors
