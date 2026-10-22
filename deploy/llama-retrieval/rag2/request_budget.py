"""Request-local deadline and disconnect signal; no process-global selection."""
from contextlib import contextmanager
import threading
import time


class VoyageError(RuntimeError):
    pass


class RequestBudget:
    def __init__(self, seconds=1440, cancel_event=None):
        self.deadline = time.monotonic() + seconds
        self.cancel_event = cancel_event or threading.Event()

    def remaining(self):
        if self.cancel_event.is_set():
            raise VoyageError('voyage_request_cancelled')
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise VoyageError('voyage_request_deadline_exceeded')
        return remaining

    def pause(self, seconds):
        if seconds >= self.remaining():
            raise VoyageError('voyage_quota_deadline_exceeded')
        self.cancel_event.wait(max(0, seconds))
        self.remaining()


@contextmanager
def yield_cpu(lock):
    """Suspend the variant engine's single runtime-lock hold during remote work.

    Its private corpus lock stays held. No shared model/tokenizer is touched
    until the CPU lock is reacquired, including on cancellation or failure.
    """
    lock.release()
    try:
        yield
    finally:
        lock.acquire()
