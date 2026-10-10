import json
import time
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import fakeredis

from services.chat_execution.broker import ChatExecutionBroker
from services.chat_execution.models import ChatTurn, DispatchInput
from services.chat_execution.workflow import build_task


class LocalHatchet:
    def __init__(self):
        self.stubs = SimpleNamespace(task=lambda **_: SimpleNamespace(run=self.run))

    def run(self, *_args, **_kwargs):
        return SimpleNamespace(workflow_run_id=uuid4().hex)

    def task(self, **_kwargs):
        return lambda function: function


def setup_turn():
    redis = fakeredis.FakeRedis(decode_responses=True)
    broker = ChatExecutionBroker(redis_client=redis, hatchet=LocalHatchet())
    turn = ChatTurn(organization_id=1, bot_id=1, session_id="session", turn_id="turn", message="Question")
    broker.enqueue(turn)
    return broker, turn, redis.hget(broker.key(turn.job_id), "dispatch_id")


def retry_after_failure(broker, turn, dispatch_id):
    assert broker.finish(turn.job_id, "error", expected_dispatch_id=dispatch_id)
    broker.enqueue(turn.model_copy(update={"retry": True}))
    return broker.redis.hget(broker.key(turn.job_id), "dispatch_id")


def test_late_event_from_failed_dispatch_cannot_pollute_retry_stream():
    broker, turn, old_dispatch = setup_turn()
    new_dispatch = retry_after_failure(broker, turn, old_dispatch)
    assert new_dispatch != old_dispatch
    assert broker.publish(turn.job_id, {"type": "error"}, expected_dispatch_id=old_dispatch) is None
    assert broker.redis.xlen(broker.key(turn.job_id, "events")) == 0
    assert broker.publish(turn.job_id, {"type": "token", "token": "New answer"}, expected_dispatch_id=new_dispatch)
    broker.publish(turn.job_id, {"type": "done"}, expected_dispatch_id=new_dispatch)
    events = list(broker.iterate(turn.job_id, 1, 1, turn.session_id))
    assert events == [{"type": "token", "token": "New answer"}, {"type": "done"}]


def test_workflow_fences_failure_event_when_retry_arrives_after_finish():
    broker, turn, old_dispatch = setup_turn()
    original_finish = broker.finish
    def finish_then_retry(*args, **kwargs):
        changed = original_finish(*args, **kwargs)
        if changed and args[1] == "error":
            broker.enqueue(turn.model_copy(update={"retry": True}))
        return changed
    def fail(*_args):
        raise ValueError("Controlled failure")
    task = build_task(LocalHatchet(), runner=fail, broker_factory=lambda: broker)
    with patch.object(broker, "finish", side_effect=finish_then_retry):
        task(DispatchInput(job_id=turn.job_id, dispatch_id=old_dispatch, bot_key=turn.bot_key,
                           conversation_key=turn.conversation_key), SimpleNamespace(done=lambda: False))
    current = broker.load(turn.job_id, 1, 1, turn.session_id)
    assert current["state"] == "queued" and current["dispatch_id"] != old_dispatch
    assert broker.redis.xlen(broker.key(turn.job_id, "events")) == 0


def test_stale_expiry_observer_cannot_expire_a_fresh_retry():
    broker, turn, old_dispatch = setup_turn()
    broker.redis.hset(broker.key(turn.job_id), "queue_deadline", time.time() - 1)
    original_eval = broker.redis.eval
    retried = []
    def retry_before_expiry(script, *args):
        if not retried and "'queue_deadline') or '0'" in script:
            retried.append(True)
            retry_after_failure(broker, turn, old_dispatch)
        return original_eval(script, *args)
    with patch.object(broker.redis, "eval", side_effect=retry_before_expiry):
        observed = broker.load(turn.job_id, 1, 1, turn.session_id)
    assert retried
    assert observed["state"] == "queued" and observed["dispatch_id"] != old_dispatch
    assert float(observed["queue_deadline"]) > time.time()
    assert broker.redis.zscore(f"{broker.prefix}:pending:global", turn.job_id) is not None


def test_stale_cancel_observer_cannot_cancel_a_fresh_retry():
    broker, turn, old_dispatch = setup_turn()
    observed = broker.load(turn.job_id, 1, 1, turn.session_id)
    new_dispatch = retry_after_failure(broker, turn, old_dispatch)
    with patch.object(broker, "load", return_value=observed):
        assert not broker.cancel(turn.job_id, 1, 1, turn.session_id)
    assert not broker.cancelled(turn.job_id, expected_dispatch_id=new_dispatch)
    assert broker.cancelled(turn.job_id, expected_dispatch_id=old_dispatch)
    assert broker.redis.xlen(broker.key(turn.job_id, "events")) == 0


def test_late_dispatch_ack_cannot_overwrite_retry_run_id():
    broker, turn, old_dispatch = setup_turn()
    broker.redis.hdel(broker.key(turn.job_id), "run_id")
    new_run = []
    def acknowledge_after_retry(*_args, **_kwargs):
        original = broker.hatchet.run
        broker.hatchet.run = LocalHatchet().run
        try:
            retry_after_failure(broker, turn, old_dispatch)
            new_run.append(broker.redis.hget(broker.key(turn.job_id), "run_id"))
        finally:
            broker.hatchet.run = original
        return SimpleNamespace(workflow_run_id="old-delayed-run")
    broker.hatchet.run = acknowledge_after_retry
    broker.enqueue(turn)
    assert new_run and broker.redis.hget(broker.key(turn.job_id), "run_id") == new_run[0]


def test_current_dispatch_events_keep_exact_stream_bound():
    broker, turn, dispatch = setup_turn()
    broker.max_events = 2
    for index in range(3):
        broker.publish(turn.job_id, {"type": "token", "token": str(index)}, expected_dispatch_id=dispatch)
    values = broker.redis.xrange(broker.key(turn.job_id, "events"))
    assert [json.loads(value["event"])["token"] for _, value in values] == ["1", "2"]
    assert broker.redis.ttl(broker.key(turn.job_id, "events")) > 0
