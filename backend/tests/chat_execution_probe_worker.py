"""Deterministic workload used only by the opt-in real-engine scheduler test."""
import time

from services.chat_execution import get_broker
from services.chat_execution.workflow import build_task


def probe_runner(turn, broker, cancelled):
    started = time.time()
    if turn.message == "fail-once":
        if broker.redis.set(broker.key(turn.job_id, "probe-first-attempt"), "1", nx=True, ex=60):
            raise ValueError("Intentional local failure")
        delay = 0.1
    else:
        delay = float(turn.message)
    deadline = time.monotonic() + delay
    while time.monotonic() < deadline:
        if cancelled():
            raise InterruptedError("Probe cancelled")
        time.sleep(0.01)
    return {"reply": "Local scheduling probe completed.", "session_id": turn.session_id,
            "sources": [], "retrieved_chunks": [], "started": started, "finished": time.time()}


if __name__ == "__main__":
    broker = get_broker()
    broker.hatchet.worker("saas-chat-worker-integration-probe", slots=20,
        workflows=[build_task(broker.hatchet, runner=probe_runner)]).start()
