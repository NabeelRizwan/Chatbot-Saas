import json
import os
import threading
import time
import uuid
from functools import lru_cache
from typing import Iterator

import redis

from .models import ChatExecutionError, ChatTurn, DispatchInput, JobReference
from .settlement import turn_settlement

WORKFLOW_NAME = "saas-chat-turn-v1"
TERMINAL = {"success", "error", "cancelled", "expired"}
SAFE_ERROR = "We couldn't complete that reply. Please retry in a moment."


def is_enabled() -> bool:
    return os.getenv("CHAT_EXECUTION_MODE", "inline").strip().lower() == "hatchet"


class ChatExecutionBroker:
    """Private Redis payload/event relay; Hatchet receives only opaque references."""

    def __init__(self, redis_client=None, hatchet=None):
        self.redis = redis_client or redis.Redis.from_url(
            os.environ["REDIS_URL"], decode_responses=True,
            socket_connect_timeout=3, socket_timeout=20,
        )
        self._hatchet = hatchet
        self._hatchet_lock = threading.Lock()
        self.prefix = os.getenv("CHAT_EXECUTION_REDIS_PREFIX", "chat-execution:v1")
        self.retention = int(os.getenv("CHAT_EXECUTION_RETENTION_SECONDS", "3600"))
        self.queue_timeout = int(os.getenv("CHAT_EXECUTION_QUEUE_TIMEOUT_SECONDS", "120"))
        self.execution_timeout = int(os.getenv("CHAT_EXECUTION_TIMEOUT_SECONDS", "180"))
        self.max_events = int(os.getenv("CHAT_EXECUTION_MAX_EVENTS", "2048"))
        if min(self.retention, self.queue_timeout, self.execution_timeout, self.max_events) < 1:
            raise ValueError("Chat execution limits must be positive")
        if self.retention < self.queue_timeout + self.execution_timeout + 120:
            raise ValueError("Chat retention must cover the complete queue/execution lifetime")

    @property
    def hatchet(self):
        if self._hatchet is None:
            with self._hatchet_lock:
                if self._hatchet is None:
                    from hatchet_sdk import Hatchet
                    self._hatchet = Hatchet()
        return self._hatchet

    def key(self, job_id: str, suffix: str = "state") -> str:
        if len(job_id) != 64 or any(c not in "0123456789abcdef" for c in job_id):
            raise ValueError("Invalid chat job identifier")
        return f"{self.prefix}:{job_id}:{suffix}"

    def enqueue(self, turn: ChatTurn) -> JobReference:
        now = time.time()
        identity = turn.job_id
        payload = json.dumps(turn.model_dump(), separators=(",", ":"), ensure_ascii=False)
        if len(payload.encode()) > 100000:
            raise ChatExecutionError("Chat request exceeds the queue payload limit")
        with turn_settlement(turn) as db:
            if db is not None:
                from services.usage_service import reserve_message_quota
                # Preflight quota may have raced an expiring previous attempt.
                reserve_message_quota(db, turn.organization_id, idempotency_key=turn.usage_key, channel="widget")
            created = self.redis.eval("""
                if redis.call('EXISTS', KEYS[1]) == 1 then
                    local state = redis.call('HGET', KEYS[1], 'state')
                    if ARGV[11] ~= '1' or (state ~= 'error' and state ~= 'cancelled' and state ~= 'expired') then return 0 end
                    redis.call('DEL', KEYS[1], KEYS[2], KEYS[4])
                end
                redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', ARGV[1])
                redis.call('ZREMRANGEBYSCORE', KEYS[5], '-inf', ARGV[1])
                if redis.call('ZCARD', KEYS[3]) >= tonumber(ARGV[5]) then return -1 end
                if redis.call('ZCARD', KEYS[5]) >= tonumber(ARGV[12]) then return -1 end
                redis.call('HSET', KEYS[1], 'state', 'queued', 'created_at', ARGV[1],
                    'queue_deadline', ARGV[2], 'bot_key', ARGV[6], 'conversation_key', ARGV[7], 'dispatch_id', ARGV[10])
                redis.call('EXPIRE', KEYS[1], ARGV[4])
                redis.call('SET', KEYS[2], ARGV[3], 'EX', ARGV[4])
                redis.call('ZADD', KEYS[3], ARGV[8], ARGV[9])
                redis.call('ZADD', KEYS[5], ARGV[8], ARGV[9])
                redis.call('EXPIRE', KEYS[3], ARGV[4])
                redis.call('EXPIRE', KEYS[5], ARGV[4])
                return 1
            """, 5, self.key(identity), self.key(identity, "payload"),
                f"{self.prefix}:pending:{turn.bot_key}", self.key(identity, "events"),
                f"{self.prefix}:pending:global", now, now + self.queue_timeout,
                payload, self.retention, int(os.getenv("CHAT_EXECUTION_MAX_PENDING_PER_BOT", "100")),
                turn.bot_key, turn.conversation_key,
                now + self.queue_timeout + self.execution_timeout + 90, identity, uuid.uuid4().hex,
                "1" if turn.retry else "0", int(os.getenv("CHAT_EXECUTION_MAX_PENDING_GLOBAL", "2000")))
        if int(created) < 0:
            raise ChatExecutionError("This bot's chat queue is full; please retry shortly")
        state = self.load(identity, turn.organization_id, turn.bot_id, turn.session_id)
        if state.get("run_id") or state.get("state") in TERMINAL:
            return JobReference(identity, state["state"], state.get("run_id"))
        # Engine-side idempotency makes retrying an uncertain dispatch safe.
        from hatchet_sdk import IdempotencyCollisionError
        dispatch = DispatchInput(job_id=identity, dispatch_id=state["dispatch_id"], bot_key=turn.bot_key,
                                 conversation_key=turn.conversation_key)
        task = self.hatchet.stubs.task(name=WORKFLOW_NAME, input_validator=DispatchInput)
        try:
            ref = task.run(dispatch, wait_for_result=False)
            run_id = ref.workflow_run_id
        except IdempotencyCollisionError as exc:
            run_id = exc.existing_run_external_id
        except Exception as exc:
            raise ChatExecutionError("Chat scheduling is temporarily unavailable") from exc
        self.redis.eval("""
            if redis.call('HGET', KEYS[1], 'dispatch_id') ~= ARGV[1] then return 0 end
            redis.call('HSET', KEYS[1], 'run_id', ARGV[2])
            return 1
        """, 1, self.key(identity), state["dispatch_id"], run_id)
        return JobReference(identity, state["state"], run_id)

    def payload(self, job_id: str) -> ChatTurn:
        raw = self.redis.get(self.key(job_id, "payload"))
        if not raw:
            raise ChatExecutionError("Chat request expired")
        turn = ChatTurn.model_validate_json(raw)
        if turn.job_id != job_id:
            raise ChatExecutionError("Chat request identity mismatch")
        return turn

    def load(self, job_id: str, organization_id: int, bot_id: int, session_id: str) -> dict:
        turn = self.payload(job_id)
        if (turn.organization_id, turn.bot_id, turn.session_id) != (organization_id, bot_id, session_id):
            raise ChatExecutionError("Chat request is not accessible")
        data = self.redis.hgetall(self.key(job_id))
        needs_settlement = (
            data.get("state") == "queued" and time.time() > float(data["queue_deadline"])
            or data.get("state") == "running" and time.time() > float(data["started_at"]) + self.execution_timeout + 90
        )
        if needs_settlement:
            with turn_settlement(turn):
                data = self.redis.hgetall(self.key(job_id))
                if data.get("state") == "queued" and time.time() > float(data["queue_deadline"]):
                    expired = self.redis.eval("""
                        if redis.call('HGET', KEYS[1], 'state') ~= 'queued'
                            or redis.call('HGET', KEYS[1], 'dispatch_id') ~= ARGV[2]
                            or tonumber(redis.call('HGET', KEYS[1], 'queue_deadline') or '0') > tonumber(ARGV[3]) then return 0 end
                        redis.call('HSET', KEYS[1], 'state', 'expired')
                        redis.call('ZREM', KEYS[2], ARGV[1])
                        redis.call('ZREM', KEYS[3], ARGV[1])
                        return 1
                    """, 3, self.key(job_id), f"{self.prefix}:pending:{turn.bot_key}", f"{self.prefix}:pending:global",
                        job_id, data["dispatch_id"], time.time())
                    if expired:
                        from .runner import release_pending
                        if turn.usage_key:
                            release_pending(turn, broker=self, expected_dispatch_id=data["dispatch_id"])
                        data["state"] = "expired"
                    else:
                        data = self.redis.hgetall(self.key(job_id))
                if data.get("state") == "running" and time.time() > float(data["started_at"]) + self.execution_timeout + 90:
                    if self.finish(job_id, "error", expected_dispatch_id=data["dispatch_id"]):
                        from .runner import release_pending
                        if turn.usage_key:
                            release_pending(turn, broker=self, expected_dispatch_id=data["dispatch_id"])
                        data["state"] = "error"
                    else:
                        data = self.redis.hgetall(self.key(job_id))
        if data.get("result"):
            data["result"] = json.loads(data["result"])
        return data

    def publish(self, job_id: str, event: dict, *, expected_dispatch_id: str | None = None) -> str | None:
        encoded = json.dumps(event, separators=(",", ":"), ensure_ascii=False)
        if len(encoded.encode()) > 512000:
            raise ChatExecutionError("Chat event exceeds the relay limit")
        return self.redis.eval("""
            if ARGV[4] ~= '' and redis.call('HGET', KEYS[1], 'dispatch_id') ~= ARGV[4] then return false end
            local id = redis.call('XADD', KEYS[2], 'MAXLEN', '=', ARGV[2], '*', 'event', ARGV[1])
            redis.call('EXPIRE', KEYS[2], ARGV[3])
            return id
        """, 2, self.key(job_id), self.key(job_id, "events"), encoded,
            self.max_events, self.retention, expected_dispatch_id or "")

    def start(self, job_id: str, dispatch_id: str) -> bool:
        return bool(self.redis.eval("""
            if redis.call('HGET', KEYS[1], 'state') ~= 'queued'
                or redis.call('HGET', KEYS[1], 'dispatch_id') ~= ARGV[1] then return 0 end
            redis.call('HSET', KEYS[1], 'state', 'running', 'started_at', ARGV[2])
            return 1
        """, 1, self.key(job_id), dispatch_id, time.time()))

    def finish(self, job_id: str, state: str, result: dict | None = None,
               expected_dispatch_id: str | None = None) -> bool:
        if state not in TERMINAL:
            raise ValueError("Invalid terminal chat state")
        turn = self.payload(job_id)
        with turn_settlement(turn):
            return bool(self.redis.eval("""
                if ARGV[5] ~= '' and redis.call('HGET', KEYS[1], 'dispatch_id') ~= ARGV[5] then return 0 end
                local state = redis.call('HGET', KEYS[1], 'state')
                if state ~= 'running' and state ~= 'queued' then return 0 end
                redis.call('HSET', KEYS[1], 'state', ARGV[1], 'finished_at', ARGV[2], 'result', ARGV[3])
                redis.call('ZREM', KEYS[2], ARGV[4])
                redis.call('ZREM', KEYS[3], ARGV[4])
                return 1
            """, 3, self.key(job_id), f"{self.prefix}:pending:{turn.bot_key}", f"{self.prefix}:pending:global", state,
                time.time(), json.dumps(result or {}, separators=(",", ":")), job_id, expected_dispatch_id or ""))

    def cancelled(self, job_id: str, *, expected_dispatch_id: str | None = None) -> bool:
        dispatch_id, requested = self.redis.hmget(self.key(job_id), "dispatch_id", "cancel_requested")
        return requested == "1" or (expected_dispatch_id is not None and dispatch_id != expected_dispatch_id)

    def cancel(self, job_id: str, organization_id: int, bot_id: int, session_id: str) -> bool:
        state = self.load(job_id, organization_id, bot_id, session_id)
        if state.get("state") in TERMINAL:
            return False
        changed = self.redis.eval("""
            if redis.call('HGET', KEYS[1], 'dispatch_id') ~= ARGV[1] then return 0 end
            local state = redis.call('HGET', KEYS[1], 'state')
            if state ~= 'queued' and state ~= 'running' then return 0 end
            redis.call('HSET', KEYS[1], 'cancel_requested', '1')
            return 1
        """, 1, self.key(job_id), state["dispatch_id"])
        if not changed:
            return False
        # Running sync calls keep their slot until they observe cancellation;
        # cancelling the engine immediately would free capacity while work runs.
        # The engine may assign a queued run between this read and cancellation.
        # Let it observe the durable flag before starting work instead of freeing
        # a potentially running slot prematurely.
        self.publish(job_id, {"type": "error", "message": "Reply cancelled", "retryable": True},
                     expected_dispatch_id=state["dispatch_id"])
        return True

    def iterate(self, job_id: str, organization_id: int, bot_id: int, session_id: str,
                after: str = "0-0") -> Iterator[dict]:
        state = self.load(job_id, organization_id, bot_id, session_id)
        if state.get("state") == "success":
            yield {"type": "meta", "session_id": session_id, "buffered": True}
            yield {"type": "token", "token": state["result"]["reply"]}
            if state["result"].get("sources"):
                yield {"type": "sources", "sources": state["result"]["sources"]}
            yield {"type": "done", "done": True}
            return
        if state.get("state") in TERMINAL:
            yield {"type": "error", "message": SAFE_ERROR, "retryable": True}
            return
        deadline = float(state["created_at"]) + self.queue_timeout + self.execution_timeout + 10
        cursor = after
        delivered = ""
        while time.time() < deadline:
            entries = self.redis.xread({self.key(job_id, "events"): cursor}, block=1000, count=100)
            for _, rows in entries:
                for event_id, values in rows:
                    cursor = event_id
                    event = json.loads(values["event"])
                    if event.get("type") == "token":
                        delivered += str(event.get("token") or "")
                    yield event
                    if event.get("type") in {"done", "error"}:
                        return
            if not entries:
                state = self.load(job_id, organization_id, bot_id, session_id)
                if state.get("state") == "success":
                    reply = state["result"]["reply"]
                    if not reply.startswith(delivered):
                        yield {"type": "error", "message": SAFE_ERROR, "retryable": True}
                        return
                    if len(reply) > len(delivered):
                        yield {"type": "token", "token": reply[len(delivered):]}
                    if state["result"].get("sources"):
                        yield {"type": "sources", "sources": state["result"]["sources"]}
                    yield {"type": "done", "done": True}
                    return
                if state.get("state") in TERMINAL:
                    yield {"type": "error", "message": SAFE_ERROR, "retryable": True}
                    return
                yield {"type": "keepalive"}
        yield {"type": "error", "message": SAFE_ERROR, "retryable": True}

    def readiness(self) -> dict:
        try:
            self.redis.ping()
            from datetime import datetime, timezone
            workers = self.hatchet.workers.list().rows or []
            workflow_name = self.hatchet.config.namespace + WORKFLOW_NAME
            active = [w for w in workers if w.name.startswith(self.hatchet.config.namespace + "saas-chat-worker")
                      and w.status.value == "ACTIVE" and w.last_heartbeat_at
                      and any(action.startswith(workflow_name + ":") for action in (w.actions or []))
                      and (datetime.now(timezone.utc) - w.last_heartbeat_at).total_seconds() < 60]
            return {"ready": bool(active), "workers": len(active)}
        except Exception:
            return {"ready": False, "workers": 0}

    def close(self):
        self.redis.close()


@lru_cache(maxsize=1)
def get_broker() -> ChatExecutionBroker:
    return ChatExecutionBroker()
