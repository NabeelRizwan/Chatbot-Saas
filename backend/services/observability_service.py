from __future__ import annotations

import logging
import math
import os
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Optional
from uuid import uuid4

from utils.secret_redaction import redact_secrets


logger = logging.getLogger("chatbot.observability")
METRICS_ENABLED = os.getenv("CHATBOT_METRICS_LOGS", "").lower() in {"1", "true", "yes"}
MAX_RECENT_VALUES = 200


def _safe_trace_value(value):
    """Redact diagnostic strings recursively; never read secret configuration."""
    if isinstance(value, str):
        value = redact_secrets(value)
        value = re.sub(r"\bAIza[A-Za-z0-9_-]{20,}\b", "[REDACTED]", value)
        value = re.sub(r"(?i)(\b(?:password|passwd|pwd|credential)\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED]", value)
        return re.sub(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", value)
    if isinstance(value, dict):
        return {_safe_trace_value(key): _safe_trace_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_trace_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def evidence_key(item: dict) -> tuple[int, int]:
    def identifier(value):
        return int(value.get("id", 0) if isinstance(value, dict) else getattr(value, "id", 0) or 0)
    return identifier(item.get("document")), identifier(item.get("chunk"))


@dataclass
class CandidateTrace:
    document_id: int
    chunk_id: int
    entry_stage: str
    channels: list[str] = field(default_factory=list)
    vector_distance: float | None = None
    vector_score: float | None = None
    vector_rank: int | None = None
    lexical_score: float | None = None
    lexical_rank: int | None = None
    fusion_score: float | None = None
    fusion_rank: int | None = None
    fts_score: float | None = None
    fts_rank: int | None = None
    dense_rrf_contribution: float | None = None
    fts_rrf_contribution: float | None = None
    rrf_total: float | None = None
    rrf_rank: int | None = None
    signals: dict[str, dict[str, float]] = field(default_factory=dict)
    indicators: dict[str, Any] = field(default_factory=dict)
    reached_reviewer: bool = False
    reviewer_result: str = "not_run"
    included_final_context: bool = False
    final_reason: str | None = None
    context_order: int | None = None
    events: list[dict[str, str]] = field(default_factory=list)

    def decision(self, stage: str, reason: str) -> None:
        event = {"stage": stage, "reason": reason}
        if event not in self.events:
            self.events.append(event)
        self.final_reason = reason

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict
        result = asdict(self)
        result.update({
            "removed_as_duplicate": self.final_reason == "excluded_duplicate",
            "removed_by_document_cap": self.final_reason == "excluded_document_cap",
            "removed_by_context_budget": self.final_reason == "excluded_context_budget",
            "removed_by_security_lifecycle_scope": self.final_reason in {
                "excluded_tenant_scope", "excluded_bot_scope", "excluded_document_scope",
                "excluded_not_ready", "excluded_embedding_profile", "excluded_security_or_lifecycle_scope",
            },
        })
        return result


@dataclass
class RetrievalTrace:
    """Detailed selection ledger owned and serialized by the existing ChatTrace.

    Never stores chunk bodies, model prompts, or credentials. SQL boundaries
    record applied filters/counts; we do not inspect foreign rows to explain a
    SQL rejection. An adapter returning an unhydratable ID gets a scope reason.
    """
    request_id: str = field(default_factory=lambda: uuid4().hex)
    original_user_message: str = ""
    retrieval_query: str = ""
    resolved_active_subject: str | None = None
    requested_fields: list[str] = field(default_factory=list)
    selected_document_ids: list[int] = field(default_factory=list)
    scope_reason: str = "not_resolved"
    mode: str = "unknown"
    cache: str = "miss"
    stage_counts: dict[str, int] = field(default_factory=dict)
    score_statistics: dict[str, float] = field(default_factory=dict)
    scope_filters: list[str] = field(default_factory=list)
    candidates: dict[tuple[int, int], CandidateTrace] = field(default_factory=dict)
    fallback_reason: str | None = None
    fallback_events: list[str] = field(default_factory=list)
    retrieval_has_candidates: bool = False
    retrieval_scope_is_valid: bool = False
    reviewer_found_supported_evidence: bool | None = None
    final_context_has_evidence: bool = False
    final_answer_is_grounded: bool | None = None
    monetary_evidence: list[dict[str, Any]] = field(default_factory=list)
    requested_propositions: list[dict[str, Any]] = field(default_factory=list)
    entity_resolution: dict[str, Any] = field(default_factory=dict)
    availability: dict[str, Any] = field(default_factory=dict)
    provider_errors: list[dict[str, Any]] = field(default_factory=list)
    reviewer_outcome: dict[str, Any] = field(default_factory=dict)
    terminal_response_category: str | None = None
    terminal_reason: str | None = None
    source_suppression_reason: str | None = None
    hybrid: dict[str, Any] = field(default_factory=dict)
    context_assembly: dict[str, Any] = field(default_factory=dict)
    hard_scope: dict[str, Any] = field(default_factory=dict)
    soft_scope: dict[str, Any] = field(default_factory=dict)
    scope_decision: dict[str, Any] = field(default_factory=dict)
    resource_discovery: dict[str, Any] = field(default_factory=dict)

    def terminal(self, category: str, reason: str | None = None, suppression: str | None = None) -> None:
        self.terminal_response_category = category
        self.terminal_reason = reason or category
        self.source_suppression_reason = suppression
        from services.retrieval_contracts import AbsenceBasis
        basis = {"temporary_service_failure": AbsenceBasis.TECHNICAL,
                 "live_data_unavailable": AbsenceBasis.LIVE_DATA,
                 "clarification": AbsenceBasis.UNRESOLVED,
                 "missing_knowledge": AbsenceBasis.SELECTED_CONTEXT}.get(category)
        if category == "temporary_service_failure" and reason in {"generation_provider_error", "empty_generation", "retrieval_provider_error"}:
            basis = AbsenceBasis.PROVIDER
        if basis:
            self.scope_decision["absence_basis"] = basis.value
        if reason:
            self.fallback(reason)
            self.fallback_reason = reason

    def provider_failure(self, stage: str, exc: Exception, bot=None) -> dict[str, Any]:
        from services.provider_failure import provider_failure
        outcome = provider_failure(exc, stage, bot)
        self.provider_errors.append(outcome)
        return outcome

    def configure(self, original: str, query: str, contract=None) -> None:
        from services.hybrid_retrieval import hybrid_config
        self.hybrid.update(hybrid_config().identity())
        self.original_user_message, self.retrieval_query = original, query
        if contract is not None:
            self.resolved_active_subject = contract.resolved_subject
            self.requested_fields = list(contract.requested_fields)
            self.mode = contract.mode
            if contract.execution:
                for key, value in contract.execution.trace_sections().items():
                    setattr(self, key, value)

    def candidate(self, item: dict, stage: str) -> CandidateTrace:
        doc_id, chunk_id = evidence_key(item)
        key = (doc_id, chunk_id)
        if key not in self.candidates:
            self.candidates[key] = CandidateTrace(doc_id, chunk_id, stage)
        return self.candidates[key]

    def record_channel(self, item: dict, channel: str, **values) -> None:
        candidate = self.candidate(item, channel)
        if channel not in candidate.channels:
            candidate.channels.append(channel)
        for key, value in values.items():
            setattr(candidate, key, value)

    def decide(self, item: dict, stage: str, reason: str) -> None:
        self.candidate(item, stage).decision(stage, reason)

    def stage(self, name: str, items: list[dict]) -> None:
        self.stage_counts[name] = len(items)
        for item in items:
            self.candidate(item, name)

    def fallback(self, reason: str, *, terminal: bool = True) -> None:
        if reason not in self.fallback_events:
            self.fallback_events.append(reason)
        if terminal:
            self.fallback_reason = self.fallback_reason or reason

    def context(self, selected: list[dict]) -> None:
        self.stage_counts["final_context"] = len(selected)
        self.final_context_has_evidence = bool(selected)
        for candidate in self.candidates.values():
            candidate.included_final_context, candidate.context_order = False, None
        for order, item in enumerate(selected):
            candidate = self.candidate(item, "context")
            candidate.included_final_context, candidate.context_order = True, order
            candidate.decision("context", "included_final_context")

    def to_dict(self, timings: dict[str, int] | None = None) -> dict[str, Any]:
        result = {key: value for key, value in vars(self).items() if key != "candidates"}
        result["auxiliary_provider_failures"] = [v for v in self.provider_errors if v.get("stage") in {"planner", "reviewer"}]
        # Preserve the exact user instruction in memory/final generation;
        # redact user-pasted credentials in persisted diagnostics only.
        result["candidates"] = [candidate.to_dict() for candidate in self.candidates.values()]
        result["timings_ms"] = dict(timings or {})
        return _safe_trace_value(result)


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
    diagnostics: dict[str, Any] = field(default_factory=dict)
    conversation_state: dict[str, Any] = field(default_factory=dict)
    retrieval: RetrievalTrace = field(default_factory=RetrievalTrace)

    def mark(self, name: str, started_at: float) -> None:
        self.timings_ms[name] = int((perf_counter() - started_at) * 1000)

    def total_ms(self) -> int:
        return int((perf_counter() - self.started_at) * 1000)

    def compact_diagnostics(self) -> dict[str, Any]:
        payload = {
            "intent": self.intent,
            "cache_hit": self.cache_hit,
            "confidence": round(float(self.confidence or 0.0), 3),
            "used_retrieval": self.used_retrieval,
            "used_fallback": self.used_fallback,
            "timings_ms": dict(self.timings_ms),
        }
        for key, value in (self.diagnostics or {}).items():
            if key in payload or key in {"prompt", "history", "context", "answer"}:
                continue
            payload[key] = value
        payload["retrieval_trace"] = self.retrieval.to_dict(self.timings_ms)
        return payload

    def to_debug_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "cache_hit": self.cache_hit,
            "confidence": self.confidence,
            "used_retrieval": self.used_retrieval,
            "used_fallback": self.used_fallback,
            "memory_turns": self.memory_turns,
            "timings_ms": self.timings_ms,
            "diagnostics": self.compact_diagnostics(),
        }


_counters: dict[str, int] = defaultdict(int)
_latencies: dict[str, deque[int]] = defaultdict(lambda: deque(maxlen=MAX_RECENT_VALUES))


def increment_metric(name: str, amount: int = 1) -> None:
    _counters[name] += amount


def observe_latency(name: str, value_ms: int) -> None:
    _latencies[name].append(value_ms)


def compact_chat_diagnostics(trace: ChatTrace | None) -> dict[str, Any]:
    if trace is None:
        return {}
    return {"diagnostics": trace.compact_diagnostics(), "conversation_state": trace.conversation_state}


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
