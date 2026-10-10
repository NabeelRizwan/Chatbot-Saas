import os
import logging
import time
from datetime import timedelta

from .broker import SAFE_ERROR, TERMINAL, WORKFLOW_NAME, get_broker
from .models import DispatchInput
from .runner import execute_turn, release_pending
from .settlement import turn_settlement


def build_task(hatchet, runner=execute_turn, broker_factory=get_broker):
    from hatchet_sdk import (ConcurrencyExpression, ConcurrencyLimitStrategy,
                             TTLBasedIdempotencyConfig)

    @hatchet.task(
        name=WORKFLOW_NAME,
        input_validator=DispatchInput,
        concurrency=[
            ConcurrencyExpression(expression="input.conversation_key", max_runs=1,
                limit_strategy=ConcurrencyLimitStrategy.GROUP_ROUND_ROBIN),
            ConcurrencyExpression(expression="input.bot_key", max_runs=10,
                limit_strategy=ConcurrencyLimitStrategy.GROUP_ROUND_ROBIN),
        ],
        idempotency=TTLBasedIdempotencyConfig(key_expression="input.dispatch_id", ttl=timedelta(hours=1)),
        schedule_timeout=timedelta(seconds=int(os.getenv("CHAT_EXECUTION_QUEUE_TIMEOUT_SECONDS", "120"))),
        execution_timeout=timedelta(seconds=int(os.getenv("CHAT_EXECUTION_TIMEOUT_SECONDS", "180")) + 60),
        retries=0,
    )
    def chat_turn(input: DispatchInput, ctx) -> dict:
        broker = broker_factory()
        turn = broker.payload(input.job_id)
        if (turn.bot_key, turn.conversation_key) != (input.bot_key, input.conversation_key):
            raise ValueError("Chat dispatch scope mismatch")
        state = broker.load(input.job_id, turn.organization_id, turn.bot_id, turn.session_id)
        if state.get("state") in TERMINAL:
            return {"job_id": input.job_id, "state": state["state"]}
        if state.get("dispatch_id") != input.dispatch_id:
            return {"job_id": input.job_id, "state": "superseded"}
        expired = time.time() > float(state["queue_deadline"])
        if expired or broker.cancelled(input.job_id, expected_dispatch_id=input.dispatch_id) or ctx.done():
            with turn_settlement(turn):
                if broker.redis.hget(broker.key(input.job_id), "dispatch_id") != input.dispatch_id:
                    return {"job_id": input.job_id, "state": "superseded"}
                if runner is execute_turn:
                    release_pending(turn, broker=broker, expected_dispatch_id=input.dispatch_id)
                broker.finish(input.job_id, "expired" if expired else "cancelled", expected_dispatch_id=input.dispatch_id)
            broker.publish(input.job_id, {"type": "error", "message": SAFE_ERROR, "retryable": True},
                           expected_dispatch_id=input.dispatch_id)
            return {"job_id": input.job_id, "state": "expired" if expired else "cancelled"}
        if not broker.start(input.job_id, input.dispatch_id):
            return {"job_id": input.job_id, "state": "superseded"}
        broker.publish(input.job_id, {"type": "meta", "session_id": turn.session_id,
                                     "turn_id": turn.turn_id,
                                     "buffered": os.getenv("CHAT_STREAM_MODE", "buffered") != "progressive"},
                       expected_dispatch_id=input.dispatch_id)
        deadline = time.monotonic() + broker.execution_timeout
        def cancelled():
            return ctx.done() or broker.cancelled(input.job_id, expected_dispatch_id=input.dispatch_id) or time.monotonic() > deadline
        try:
            result = (runner(turn, broker, cancelled, expected_dispatch_id=input.dispatch_id)
                      if runner is execute_turn else runner(turn, broker, cancelled))
            streamed = result.pop("_streamed", False)
            if not broker.finish(input.job_id, "success", result, expected_dispatch_id=input.dispatch_id):
                return {"job_id": input.job_id, "state": "superseded"}
            # Emit only a persisted result; the same replay is safe on reconnect.
            from services.rag_service import iter_approved_answer_chunks
            if not streamed:
                for part in iter_approved_answer_chunks(result["reply"]):
                    broker.publish(input.job_id, {"type": "token", "token": part},
                                   expected_dispatch_id=input.dispatch_id)
            if result.get("sources"):
                broker.publish(input.job_id, {"type": "sources", "sources": result["sources"]},
                               expected_dispatch_id=input.dispatch_id)
            broker.publish(input.job_id, {"type": "done", "done": True}, expected_dispatch_id=input.dispatch_id)
            return {"job_id": input.job_id, "state": "success"}
        except Exception as exc:
            logging.getLogger(__name__).warning("chat_job_failed category=%s", type(exc).__name__)
            status = "cancelled" if isinstance(exc, InterruptedError) else "error"
            if broker.finish(input.job_id, status, expected_dispatch_id=input.dispatch_id):
                broker.publish(input.job_id, {"type": "error", "message": SAFE_ERROR, "retryable": True},
                               expected_dispatch_id=input.dispatch_id)
            return {"job_id": input.job_id, "state": status}

    return chat_turn
