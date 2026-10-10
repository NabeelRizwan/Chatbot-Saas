"""Opt-in tests against the real local Hatchet engine and isolated Redis."""
import os
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_HATCHET_INTEGRATION") != "1",
    reason="Requires explicitly configured local Hatchet and isolated Redis")


def _maximum_overlap(windows):
    events = [(w["started"], 1) for w in windows] + [(w["finished"], -1) for w in windows]
    active = highest = 0
    for _, change in sorted(events):
        active += change
        highest = max(highest, active)
    return highest


def test_real_hatchet_per_bot_concurrency_queue_and_isolation(tmp_path):
    from services.chat_execution import ChatExecutionBroker, ChatTurn
    prefix = f"chat-execution-test:{uuid.uuid4().hex}"
    namespace = "test_" + uuid.uuid4().hex
    env = {**os.environ, "CHAT_EXECUTION_REDIS_PREFIX": prefix, "HATCHET_CLIENT_NAMESPACE": namespace}
    from hatchet_sdk import Hatchet, ClientConfig
    broker = ChatExecutionBroker(hatchet=Hatchet(config=ClientConfig(namespace=namespace)))
    broker.prefix = prefix
    output = (tmp_path / "worker.log").open("w")
    command = [sys.executable, "-m", "tests.chat_execution_probe_worker"]
    if os.getenv("CHAT_EXECUTION_DOCKER_IMAGE"):
        private_env = tmp_path / "worker.env"
        allowed = ("HATCHET_CLIENT_", "CHAT_EXECUTION_", "DATABASE_URL", "REDIS_URL", "APP_ENV")
        worker_env = {k:v for k,v in env.items() if k.startswith(allowed)}
        for key in ("HATCHET_CLIENT_HOST_PORT", "HATCHET_CLIENT_SERVER_URL", "DATABASE_URL", "REDIS_URL"):
            if key in worker_env:
                worker_env[key] = worker_env[key].replace("localhost", "host.docker.internal").replace("127.0.0.1", "host.docker.internal")
        private_env.write_text("\n".join(f"{k}={v}" for k,v in worker_env.items()))
        name = f"saas-chat-probe-{uuid.uuid4().hex[:8]}"
        command = ["docker", "run", "--rm", "--name", name, "--env-file", str(private_env),
                   "-v", f"{Path(__file__).resolve().parents[1]}:/app", "-w", "/app",
                   os.environ["CHAT_EXECUTION_DOCKER_IMAGE"], "python", "-m", "tests.chat_execution_probe_worker"]
    worker = subprocess.Popen(command,
                              cwd=Path(__file__).resolve().parents[1], env=env,
                              stdout=output, stderr=subprocess.STDOUT)
    try:
        time.sleep(8)
        assert worker.poll() is None, (tmp_path / "worker.log").read_text()
        assert broker.readiness()["ready"]
        turns = [ChatTurn(organization_id=99001, bot_id=bot, session_id=f"{prefix}:{bot}:{i}",
                          turn_id="turn", message="3") for bot in (99001, 99002) for i in range(15)]
        with ThreadPoolExecutor(max_workers=12) as pool:
            refs = list(pool.map(broker.enqueue, turns))
        results = []
        deadline = time.monotonic() + 80
        while time.monotonic() < deadline:
            results = [broker.load(r.job_id, t.organization_id, t.bot_id, t.session_id)
                       for r, t in zip(refs, turns)]
            if all(r["state"] in {"success", "error", "cancelled"} for r in results):
                break
            time.sleep(0.1)
        assert all(r["state"] == "success" for r in results), results
        for bot in (99001, 99002):
            windows = [r["result"] for r,t in zip(results,turns) if t.bot_id == bot]
            assert _maximum_overlap(windows) == 10
        assert _maximum_overlap([r["result"] for r in results]) >= 15
        with pytest.raises(Exception, match="not accessible"):
            broker.load(refs[0].job_id, 99002, turns[0].bot_id, turns[0].session_id)
        duplicate = broker.enqueue(turns[0])
        assert duplicate.run_id == refs[0].run_id
        replay = list(broker.iterate(refs[0].job_id, 99001, turns[0].bot_id, turns[0].session_id))
        assert replay[-1] == {"type": "done", "done": True}
        broker.redis.delete(broker.key(refs[0].job_id, "events"))
        replay_without_stream = list(broker.iterate(refs[0].job_id, 99001, turns[0].bot_id, turns[0].session_id))
        assert "".join(e.get("token", "") for e in replay_without_stream) == results[0]["result"]["reply"]

        def wait_result(turn, expected="success"):
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                value = broker.load(turn.job_id, turn.organization_id, turn.bot_id, turn.session_id)
                if value["state"] in {"success", "error", "cancelled", "expired"}:
                    assert value["state"] == expected, value
                    return value
                time.sleep(0.05)
            raise AssertionError("Probe did not finish")

        base = dict(organization_id=99001, bot_id=99001, session_id=f"{prefix}:serial", message="0.3")
        serial = [ChatTurn(**base, turn_id=str(i)) for i in range(3)]
        for turn in serial:
            broker.enqueue(turn)
        serial_results = [wait_result(t)["result"] for t in serial]
        assert _maximum_overlap(serial_results) == 1

        failed = ChatTurn(**{**base, "session_id": f"{prefix}:fail", "message": "fail-once"}, turn_id="1")
        old_run = broker.enqueue(failed).run_id
        wait_result(failed, "error")
        retry = failed.model_copy(update={"retry": True})
        with ThreadPoolExecutor(max_workers=2) as pool:
            retried = list(pool.map(broker.enqueue, [retry, retry]))
        assert retried[0].run_id == retried[1].run_id != old_run
        wait_result(retry)

        cancelled = ChatTurn(**{**base, "session_id": f"{prefix}:cancel", "message": "3"}, turn_id="1")
        broker.enqueue(cancelled)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if broker.load(cancelled.job_id, 99001, 99001, cancelled.session_id)["state"] == "running":
                break
            time.sleep(0.05)
        broker.cancel(cancelled.job_id, 99001, 99001, cancelled.session_id)
        wait_result(cancelled, "cancelled")

        blocker = ChatTurn(**{**base, "session_id": f"{prefix}:expiry", "message": "2"}, turn_id="1")
        broker.enqueue(blocker)
        broker.queue_timeout = 1
        expired = blocker.model_copy(update={"turn_id": "2"})
        broker.enqueue(expired)
        wait_result(blocker)
        wait_result(expired, "expired")
    finally:
        if os.getenv("CHAT_EXECUTION_DOCKER_IMAGE"):
            subprocess.run(["docker", "stop", "-t", "3", name], capture_output=True, timeout=15)
        worker.terminate()
        worker.wait(timeout=15)
        output.close()
        keys = list(broker.redis.scan_iter(f"{prefix}:*"))
        if keys:
            broker.redis.delete(*keys)
        broker.close()
