import json
import re
from time import perf_counter
from typing import Any, Dict, List, Optional, Tuple

from services.embedding_service import generate_embedding
from services.intent_router import (
    classify_intent as pattern_classify_intent,
    detect_length_preference,
    rewrite_query_for_retrieval,
    INTENT_GREETING,
    INTENT_FAREWELL,
    INTENT_GRATITUDE,
    INTENT_IDENTITY,
    INTENT_SMALL_TALK,
    INTENT_SUMMARIZE_PREVIOUS,
    INTENT_SIMPLIFY_PREVIOUS,
    INTENT_REPHRASE_CONTINUE,
    INTENT_PRONOUN_FOLLOWUP,
    INTENT_KNOWLEDGE_QUERY,
)


class SemanticCache:
    """In-memory semantic response cache keyed by (bot_id, normalized_query)."""

    def __init__(self, max_size: int = 500, ttl_seconds: int = 3600):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[Tuple[int, str], Dict[str, Any]] = {}

    def _normalize_query(self, query: str) -> str:
        text = re.sub(r"\s+", " ", query.lower()).strip()
        text = re.sub(r"[^\w\s]", "", text)
        return text

    def get(self, bot_id: int, query: str) -> Optional[Dict[str, Any]]:
        key = (bot_id, self._normalize_query(query))
        entry = self._cache.get(key)
        if not entry:
            return None
        if perf_counter() - entry["timestamp"] > self.ttl_seconds:
            del self._cache[key]
            return None
        return entry["data"]

    def set(self, bot_id: int, query: str, data: Dict[str, Any]) -> None:
        key = (bot_id, self._normalize_query(query))
        if len(self._cache) >= self.max_size:
            # Evict oldest entry
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k]["timestamp"])
            del self._cache[oldest_key]
        self._cache[key] = {
            "timestamp": perf_counter(),
            "data": data,
        }

    def clear(self, bot_id: Optional[int] = None) -> None:
        if bot_id is None:
            self._cache.clear()
        else:
            keys_to_del = [k for k in self._cache.keys() if k[0] == bot_id]
            for k in keys_to_del:
                del self._cache[k]


global_semantic_cache = SemanticCache()


class ContextMemory:
    """Lightweight conversation memory tracking entities, current topic, and history summary."""

    def __init__(self, history: Optional[List[Dict[str, str]]] = None):
        self.history = history or []
        self.entities: List[str] = []
        self.current_topic: Optional[str] = None
        self._analyze_history()

    def _analyze_history(self) -> None:
        if not self.history:
            return
        # Extract potential entities (capitalized words, numbers, key terms)
        for item in self.history:
            content = str(item.get("content", ""))
            # Extract capitalized terms (names, products, organizations)
            caps = re.findall(r"\b[A-Z][a-zA-Z0-9'-]+\b", content)
            for c in caps:
                if c.lower() not in {"the", "a", "an", "i", "you", "we", "they", "he", "she", "it", "is", "are", "was", "were", "what", "how", "why"}:
                    if c not in self.entities:
                        self.entities.append(c)

        # Set current topic from last user turn
        for item in reversed(self.history):
            if str(item.get("role", "")).lower() == "user":
                self.current_topic = str(item.get("content", ""))[:100]
                break

    def get_summary(self) -> Dict[str, Any]:
        return {
            "entities": self.entities[:10],
            "current_topic": self.current_topic,
            "turns_count": len(self.history),
        }


def compress_and_rerank_chunks(retrieved: List[Dict[str, Any]], query: str) -> Tuple[List[Dict[str, Any]], str]:
    """
    Deduplicate, filter noise, rerank by relevance, and compress retrieved context.
    """
    if not retrieved:
        return [], ""

    query_tokens = set(re.findall(r"[a-z0-9']+", query.lower()))
    cleaned = []
    seen_texts: set[str] = set()

    for item in retrieved:
        chunk = item.get("chunk")
        content = chunk.content.strip() if hasattr(chunk, "content") else str(chunk.get("content", "")).strip()

        # Reject short fragments or empty chunks
        if len(content) < 15:
            continue

        normalized = re.sub(r"\s+", " ", content.lower()).strip()
        if normalized in seen_texts:
            continue
        seen_texts.add(normalized)

        # Compute keyword overlap score boost
        content_tokens = set(re.findall(r"[a-z0-9']+", content.lower()))
        overlap = len(query_tokens.intersection(content_tokens)) if query_tokens else 0
        original_score = float(item.get("score") or 0.0)
        boosted_score = original_score + (overlap * 0.03)

        cleaned.append({
            "item": item,
            "score": boosted_score,
            "content": content,
        })

    # Sort by boosted score
    cleaned.sort(key=lambda x: x["score"], reverse=True)
    top_items = [c["item"] for c in cleaned[:4]]

    # Compress context into deduplicated bullet facts
    compressed_facts = []
    seen_sentences: set[str] = set()

    for c in cleaned[:4]:
        sentences = re.split(r"(?<=[.!?])\s+", c["content"])
        for s in sentences:
            s_clean = s.strip()
            if len(s_clean) > 10 and s_clean.lower() not in seen_sentences:
                seen_sentences.add(s_clean.lower())
                compressed_facts.append(s_clean)

    compressed_context = "\n".join(compressed_facts[:8])
    return top_items, compressed_context


def critique_response(answer: str, question: str, strict_grounding: bool = False) -> Tuple[bool, str]:
    """
    Evaluate generated answer before returning/streaming to user.
    """
    if not answer or not answer.strip():
        return False, "Answer is empty."

    # Check for hallucination / robotic grounding leak
    lower_answer = answer.lower()
    robotic_phrases = [
        "according to document", "the provided context", "in document 1",
        "retrieved information states", "as an ai model"
    ]
    if any(phrase in lower_answer for phrase in robotic_phrases):
        return False, "Answer contains internal retrieval jargon."

    return True, "Passed critique."


def generate_proactive_followups(answer: str, question: str) -> List[str]:
    """
    Generate 1-2 natural follow-up suggestions when appropriate.
    """
    q_lower = question.lower()
    if any(k in q_lower for k in ("price", "pricing", "cost", "plan")):
        return ["Would you like to know about our enterprise discounts?", "Can I help you compare plans?"]
    if any(k in q_lower for k in ("feature", "features", "capability", "what can")):
        return ["Would you like a quick overview of integration options?", "Shall I explain setup steps?"]
    return []
