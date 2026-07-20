from __future__ import annotations

import logging
import os
from collections import defaultdict, deque
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Optional


logger = logging.getLogger("chatbot.observability")
METRICS_ENABLED = os.getenv("CHATBOT_METRICS_LOGS", "").lower() in {"1", "true", "yes"}
MAX_RECENT_VALUES = 200


@dataclass
class ChatTrace:
    bot_id: int
    channel: str
    started_at: float = field(default_factory=perf_counter)
    timings_ms: dict[str, int] = field(default_factory=dict)
    used_retrieval: bool = False
    used_fallback: bool = False
    provider_error: bool = False
    intent: str = "unknown"
    cache_hit: bool = False
    confidence: float = 0.0
    critique_passed: bool = True
    memory_turns: int = 0
    followups: list[str] = field(default_factory=list)

    def mark(self, name: str, started_at: float) -> None:
        self.timings_ms[name] = int((perf_counter() - started_at) * 1000)

    def total_ms(self) -> int:
        return int((perf_counter() - self.started_at) * 1000)

    def to_debug_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "cache_hit": self.cache_hit,
            "confidence": self.confidence,
            "used_retrieval": self.used_retrieval,
            "used_fallback": self.used_fallback,
            "memory_turns": self.memory_turns,
            "timings_ms": self.timings_ms,
        }


_counters: dict[str, int] = defaultdict(int)
_latencies: dict[str, deque[int]] = defaultdict(lambda: deque(maxlen=MAX_RECENT_VALUES))


def increment_metric(name: str, amount: int = 1) -> None:
    _counters[name] += amount


def observe_latency(name: str, value_ms: int) -> None:
    _latencies[name].append(value_ms)


def track_chat_completion(trace: ChatTrace, status: str = "success") -> None:
    total_ms = trace.total_ms()
    increment_metric(f"chat.{status}")
    observe_latency("chat.response_ms", total_ms)

    if trace.intent:
        increment_metric(f"intent.{trace.intent}")
    if trace.cache_hit:
        increment_metric("chat.cache_hit")
    if trace.used_retrieval:
        increment_metric("chat.retrieval_used")
    if trace.used_fallback:
        increment_metric("chat.fallback_used")
    if trace.provider_error:
        increment_metric("provider.error")

    if METRICS_ENABLED:
        logger.info(
            "chat_completion",
            extra={
                "bot_id": trace.bot_id,
                "channel": trace.channel,
                "status": status,
                "total_ms": total_ms,
                "timings_ms": trace.timings_ms,
                "intent": trace.intent,
                "cache_hit": trace.cache_hit,
                "confidence": trace.confidence,
                "used_retrieval": trace.used_retrieval,
                "used_fallback": trace.used_fallback,
                "provider_error": trace.provider_error,
            },
        )


def get_internal_metrics_snapshot() -> dict[str, Any]:
    return {
        "counters": dict(_counters),
        "latencies": {
            name: {
                "count": len(values),
                "average_ms": round(sum(values) / len(values), 2) if values else None,
                "latest_ms": values[-1] if values else None,
            }
            for name, values in _latencies.items()
        },
    }
