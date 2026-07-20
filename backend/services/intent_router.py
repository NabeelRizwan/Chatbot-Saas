import re
from typing import Optional


# Intent Constants
INTENT_GREETING = "greeting"
INTENT_FAREWELL = "farewell"
INTENT_GRATITUDE = "gratitude"
INTENT_IDENTITY = "identity"
INTENT_SMALL_TALK = "small_talk"
INTENT_SUMMARIZE_PREVIOUS = "summarize_previous"
INTENT_SIMPLIFY_PREVIOUS = "simplify_previous"
INTENT_REPHRASE_CONTINUE = "rephrase_continue"
INTENT_PRONOUN_FOLLOWUP = "pronoun_followup"
INTENT_KNOWLEDGE_QUERY = "knowledge_query"


GREETING_PATTERNS = {
    "hi", "hello", "hey", "heya", "hiya", "yo", "sup", "good morning",
    "good afternoon", "good evening", "greetings", "howdy", "welcome"
}

FAREWELL_PATTERNS = {
    "bye", "goodbye", "see ya", "see you", "talk to you later", "catch you later",
    "have a good day", "have a nice day", "good night", "cya"
}

GRATITUDE_PATTERNS = {
    "thanks", "thank you", "thx", "thank you so much", "thanks a lot",
    "appreciate it", "awesome thanks", "great thanks", "perfect thanks",
    "thank you for your help", "that helps", "much appreciated"
}

IDENTITY_PATTERNS = (
    r"\bwho are you\b",
    r"\bwhat are you\b",
    r"\bwhat can you do\b",
    r"\bwho made you\b",
    r"\bwho created you\b",
    r"\bwhat is your name\b",
    r"\bwhat is your role\b",
    r"\bhow can you help\b",
)

SMALL_TALK_PATTERNS = {
    "how are you", "how are you?", "how is it going", "how's it going",
    "how are things", "what's up", "ok", "okay", "cool", "nice", "great",
    "sounds good", "got it", "understood", "nice to meet you"
}

SUMMARIZE_PATTERNS = (
    r"\bsummarize( this| that)?\b",
    r"\btldr\b",
    r"\bmake it shorter\b",
    r"\bshort version\b",
    r"\bgive me a summary\b",
    r"\bcan you summarize\b",
    r"\bin brief\b",
    r"\bkey points\b",
)

SIMPLIFY_PATTERNS = (
    r"\bexplain (it |this |that )?simply\b",
    r"\bexplain like i('?m| am) 5\b",
    r"\beli5\b",
    r"\bsimplify (this|that|it)\b",
    r"\bin simple terms\b",
    r"\bmake it simple\b",
    r"\beasier to understand\b",
)

CONTINUE_PATTERNS = (
    r"\btell me more\b",
    r"\bexplain more\b",
    r"\bcontinue\b",
    r"\belaborate\b",
    r"\bgo on\b",
    r"\bmore details\b",
    r"\bwhat else\b",
    r"\bkeep going\b",
    r"\bcan you expand\b",
)

PRONOUN_PATTERNS = (
    r"\b(it|this|that|them|those|these|the above|previous answer|earlier)\b",
)

RAG_INTENT_TERMS = {
    "account", "billing", "cancel", "company", "contact", "delivery", "docs",
    "documentation", "feature", "features", "guarantee", "integration", "login",
    "order", "policy", "price", "pricing", "product", "refund", "return",
    "service", "shipping", "support", "terms", "warranty", "how to", "where is",
    "can i", "do you offer", "what is", "how do"
}


def _normalize(message: str) -> str:
    text = re.sub(r"\s+", " ", message.lower()).strip()
    return re.sub(r"^[^\w]+|[^\w?!.]+$", "", text)


def is_small_talk(message: str) -> bool:
    text = _normalize(message)
    if text in GREETING_PATTERNS or text in SMALL_TALK_PATTERNS or text in GRATITUDE_PATTERNS or text in FAREWELL_PATTERNS:
        return True
    if any(re.search(p, text) for p in IDENTITY_PATTERNS):
        return True
    words = text.split()
    return len(words) <= 3 and any(text.startswith(g) for g in ("hi", "hello", "hey", "thanks", "bye"))


def is_general_conversation(message: str) -> bool:
    text = _normalize(message)
    if is_small_talk(text):
        return True
    if any(re.search(p, text) for p in (SUMMARIZE_PATTERNS + SIMPLIFY_PATTERNS + CONTINUE_PATTERNS)):
        return True
    general_patterns = (
        r"\btell me (a )?joke\b",
        r"\bmake me laugh\b",
        r"\bwrite (a )?(poem|story|email|message)\b",
        r"\bbrainstorm\b",
    )
    if any(re.search(pattern, text) for pattern in general_patterns):
        business_cues = {"your", "you", "company", "product", "service", "pricing", "policy", "refund"}
        return not any(cue in text.split() for cue in business_cues)
    return False


def classify_intent(message: str, history: list[dict] | None = None) -> str:
    text = _normalize(message)
    if not text:
        return INTENT_SMALL_TALK

    # 1. Greetings
    if text in GREETING_PATTERNS or (len(text.split()) <= 2 and any(text.startswith(g) for g in ("hi", "hello", "hey", "greetings"))):
        return INTENT_GREETING

    # 2. Farewell
    if text in FAREWELL_PATTERNS or (len(text.split()) <= 3 and any(text.startswith(f) for f in ("bye", "goodbye", "cya"))):
        return INTENT_FAREWELL

    # 3. Gratitude
    if text in GRATITUDE_PATTERNS or any(phrase in text for phrase in ("thank you", "thanks", "appreciate it")):
        return INTENT_GRATITUDE

    # 4. Identity / Capabilities
    if any(re.search(p, text) for p in IDENTITY_PATTERNS):
        return INTENT_IDENTITY

    # 5. Small Talk / Acknowledgement
    if text in SMALL_TALK_PATTERNS:
        return INTENT_SMALL_TALK

    # 6. Summarization of previous context
    if any(re.search(p, text) for p in SUMMARIZE_PATTERNS):
        return INTENT_SUMMARIZE_PREVIOUS

    # 7. Simplification of previous context
    if any(re.search(p, text) for p in SIMPLIFY_PATTERNS):
        return INTENT_SIMPLIFY_PREVIOUS

    # 8. Rephrase / Continue
    if any(re.search(p, text) for p in CONTINUE_PATTERNS):
        return INTENT_REPHRASE_CONTINUE

    # 9. Pronoun / Contextual Follow-up
    if history and len(history) >= 2 and any(re.search(p, text) for p in PRONOUN_PATTERNS):
        return INTENT_PRONOUN_FOLLOWUP

    # 10. Otherwise knowledge query
    return INTENT_KNOWLEDGE_QUERY


def should_use_rag(message: str, history: list[dict] | None = None) -> bool:
    """Determine whether RAG vector retrieval is genuinely required."""
    intent = classify_intent(message, history=history)

    # Do NOT run RAG for greetings, farewells, gratitude, identity, small talk, or in-place transformations
    if intent in (
        INTENT_GREETING,
        INTENT_FAREWELL,
        INTENT_GRATITUDE,
        INTENT_IDENTITY,
        INTENT_SMALL_TALK,
        INTENT_SUMMARIZE_PREVIOUS,
        INTENT_SIMPLIFY_PREVIOUS,
    ):
        return False

    text = _normalize(message)
    words = set(re.findall(r"[a-z0-9']+", text))
    if words.intersection(RAG_INTENT_TERMS):
        return True
    if any(phrase in text for phrase in ("your ", "you offer", "do you", "can you help with", "how do i", "tell me about")):
        return True

    if intent in (INTENT_REPHRASE_CONTINUE, INTENT_PRONOUN_FOLLOWUP):
        return True

    return len(words) > 5


def rewrite_query_for_retrieval(query: str, history: list[dict] | None = None) -> str:
    """Rewrite ambiguous follow-up queries ('tell me more', 'how much is it?') into standalone retrieval queries."""
    if not history:
        return query

    # Find the most recent user turn that was substantive
    last_user_turn = None
    last_assistant_turn = None

    for item in reversed(history):
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        if role == "user" and not last_user_turn and not is_small_talk(content):
            last_user_turn = content
        elif role == "assistant" and not last_assistant_turn:
            last_assistant_turn = content
        if last_user_turn and last_assistant_turn:
            break

    if not last_user_turn:
        return query

    intent = classify_intent(query, history=history)

    if intent == INTENT_REPHRASE_CONTINUE:
        return f"{last_user_turn} - elaborate in detail"

    if intent == INTENT_PRONOUN_FOLLOWUP or any(re.search(p, _normalize(query)) for p in PRONOUN_PATTERNS):
        return f"{last_user_turn} {query}"

    return query


def detect_length_preference(message: str) -> Optional[str]:
    """Extract requested answer length preferences from the user's message."""
    text = _normalize(message)

    if any(p in text for p in ("in 1 sentence", "one sentence", "in a single sentence", "1 line", "one line")):
        return "one_sentence"
    if any(p in text for p in ("in 2 lines", "two lines", "2 lines", "very short", "tldr")):
        return "very_short"
    if any(p in text for p in ("short", "briefly", "in brief", "concise")):
        return "short"
    if any(p in text for p in ("detailed", "in detail", "comprehensive", "explain fully", "deep dive")):
        return "detailed"
    if any(p in text for p in ("bullet points", "bullets", "list format")):
        return "bullet_points"

    return None
