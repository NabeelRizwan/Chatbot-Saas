"""Serialize short queue/quota transitions without holding a lock during generation."""

import threading
import weakref
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import text
from sqlalchemy.orm import Session

from .models import ChatExecutionError

_held = ContextVar("chat_settlement_sessions", default=None)
_local_locks = weakref.WeakValueDictionary()
_local_mutex = threading.Lock()


@contextmanager
def turn_settlement(turn):
    if not turn.usage_key:
        yield None
        return
    held = _held.get() or {}
    if turn.job_id in held:
        yield held[turn.job_id]
        return
    from database.connection import engine

    # Session-level locks survive the commits in the existing quota helpers.
    # Binding their Session to this Connection keeps ownership on that session.
    with engine.connect() as connection:
        lock_id = int.from_bytes(bytes.fromhex(turn.job_id[:16]), "big", signed=True)
        postgres = connection.dialect.name == "postgresql"
        local_lock = None
        acquired = False
        try:
            if postgres:
                try:
                    connection.execute(text("SET LOCAL lock_timeout = '10s'"))
                    connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": lock_id})
                    acquired = True
                    connection.commit()
                except BaseException:
                    # A lost acknowledgement may leave ownership uncertain.
                    acquired = False
                    connection.invalidate()
                    raise
            elif connection.dialect.name == "sqlite":
                # SQLite is used only by local/unit tests; production uses PostgreSQL.
                with _local_mutex:
                    local_lock = _local_locks.setdefault(turn.job_id, threading.RLock())
                acquired = local_lock.acquire(timeout=10)
                if not acquired:
                    raise ChatExecutionError("Chat settlement is busy; please retry")
            else:
                raise ChatExecutionError("Queued chat requires PostgreSQL")
            with Session(bind=connection) as db:
                token = _held.set({**held, turn.job_id: db})
                try:
                    yield db
                finally:
                    _held.reset(token)
        finally:
            if acquired and postgres:
                try:
                    connection.rollback()
                    unlocked = connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_id}).scalar()
                    if not unlocked:
                        raise RuntimeError("Chat settlement lock ownership lost")
                    connection.commit()
                except BaseException:
                    # A pooled connection must never retain a session-level lock.
                    connection.invalidate()
                    raise
            elif acquired and local_lock is not None:
                local_lock.release()
