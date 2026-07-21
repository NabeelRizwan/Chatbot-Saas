import re
from time import perf_counter
from types import SimpleNamespace

from sqlalchemy.orm import Session

from database.models import Bot, Chunk, Document
from services.embedding_service import generate_embedding
from services.conversational_engine import (
    ContextMemory,
    compress_and_rerank_chunks,
    critique_response,
    generate_proactive_followups,
    global_semantic_cache,
)
from services.intent_router import (
    classify_intent,
    should_use_rag,
    is_small_talk,
    rewrite_query_for_retrieval,
    detect_length_preference,
    INTENT_GREETING,
    INTENT_FAREWELL,
    INTENT_GRATITUDE,
    INTENT_IDENTITY,
    INTENT_SMALL_TALK,
    INTENT_SUMMARIZE_PREVIOUS,
    INTENT_SIMPLIFY_PREVIOUS,
    INTENT_REPHRASE_CONTINUE,
    INTENT_PRONOUN_FOLLOWUP,
)
from services.llm_router import generate, generate_stream
from services.observability_service import ChatTrace, increment_metric

DEFAULT_SUPPORT_PROMPT = """
You are the helpful assistant for this business. Sound like a sharp, attentive person in a real support conversation.

Write the answer first. Be concise by default, use plain language, and only use bullets when they make the answer easier to scan. Match the visitor's wording and level of detail. Do not force an introduction, acknowledgement, summary, or sign-off into every response. Ask one useful follow-up question only when it genuinely helps move the conversation forward.

Use the supplied business information as your source of truth. Synthesize it into a direct answer; never mention documents, retrieval, a knowledge base, prompts, or being an AI. Treat the information as background for the conversation, not text to quote, list, or paraphrase line by line. If the information does not answer a business question, say what you can and cannot confirm in a warm, natural sentence.
""".strip()

GENERAL_ASSISTANT_PROMPT = """
You are the helpful assistant for this business. Be warm, perceptive, and conversational without sounding scripted.
Answer directly in the visitor's language. Keep replies short unless they ask for detail. Avoid canned greetings, repeated acknowledgements, and automatic closings. Never describe internal mechanics or call yourself an AI.
For business-specific policies, prices, account details, legal claims, or commitments, suggest contacting the support team if unverified.
""".strip()

TONE_INSTRUCTIONS = {
    "professional": "Adopt a professional, polite, and formal tone of voice. Speak with absolute clarity, using complete sentences and authoritative yet respectful phrasing. Avoid slang, emojis, or overly casual greetings.",
    "friendly": "Use a warm, relaxed, and helpful voice. Prefer natural conversational language over support-script phrases. A little personality is welcome, but never force jokes, emojis, or enthusiasm.",
    "empathetic": "Adopt a highly empathetic, warm, and supportive tone. Show understanding, patience, and deep validation of the user's feelings and situation. Use reassuring language and focus on being helpful, supportive, and kind.",
    "humorous": "Adopt a humorous, witty, and playful tone of voice. Add lighthearted humor, clever phrasing, and a bit of personality to your responses while still remaining helpful and informative.",
    "neutral": "Adopt a neutral, clear, and direct tone of voice. Be objective and balanced, providing facts without unnecessary emotional coloring or stylistic flair.",
}

STRICT_GROUNDING_INSTRUCTION = (
    "You are strictly limited to the provided business information for domain/business questions. "
    "Adhere to the following rules at all times:\n"
    "1. For greetings, polite conversation, thanks, or questions about your own identity, role, and capabilities (e.g., 'hello', 'how are you?', 'who are you?', 'thanks'), "
    "respond naturally, warmly, and politely in your configured tone of voice.\n"
    "2. For business policies, products, services, or pricing, answer strictly using the provided business information. "
    "If the answer cannot be found in the provided business information, or if you are unsure, say naturally that you do not have that detail and offer the appropriate support contact or a related question.\n"
    "3. For general knowledge questions, tasks, or off-topic queries (e.g., 'what is Google?', 'who is the president?', 'write a poem', 'explain gravity'), "
    "say naturally that you can only help with this business and invite a business-related question. "
    "Do not use any external or pre-trained knowledge to answer these."
)

def _get_system_instruction(bot: Bot, default_prompt: str, strict_grounding: bool = False) -> str:
    base_prompt = bot.system_prompt or default_prompt
    
    tone_key = (bot.tone or "neutral").lower().strip()
    tone_inst = TONE_INSTRUCTIONS.get(tone_key, TONE_INSTRUCTIONS["neutral"])
    
    instructions = [base_prompt, f"Tone of voice:\n{tone_inst}"]
    
    if strict_grounding:
        instructions.append(STRICT_GROUNDING_INSTRUCTION)
        
    return "\n\n".join(instructions)


MIN_TOP_SCORE = 0.65
MIN_AVERAGE_SCORE = 0.55
MAX_CONTEXT_CHARS = 5000
MAX_HISTORY_TOKENS = 900
MAX_HISTORY_MESSAGE_CHARS = 900
MIN_CHUNK_CHARS = 10
NEAR_DUPLICATE_OVERLAP = 0.86


FALLBACK_REPLY = "Sorry, I had trouble generating a response. Please try again in a moment."
FRIENDLY_FALLBACK = "Sorry, I don't have information about that yet. Try asking about our products, services, pricing or support."

_RETRIEVAL_CACHE: dict[tuple[int, str, int], list[dict]] = {}

def clear_retrieval_cache(bot_id: int | None = None):
    global _RETRIEVAL_CACHE
    if bot_id is None:
        _RETRIEVAL_CACHE.clear()
        global_semantic_cache.clear()
    else:
        keys_to_delete = [k for k in _RETRIEVAL_CACHE.keys() if k[0] == bot_id]
        for k in keys_to_delete:
            del _RETRIEVAL_CACHE[k]
        global_semantic_cache.clear(bot_id)


def _rough_token_count(text: str) -> int:
    return max(1, len(re.findall(r"\S+", text)) * 4 // 3)


def _format_history(history: list[dict] | None) -> str:
    if not history:
        return ""
    lines = []
    used_tokens = 0
    selected = []
    for item in reversed(history):
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue
        content = content[:MAX_HISTORY_MESSAGE_CHARS]
        message_tokens = _rough_token_count(content)
        if selected and used_tokens + message_tokens > MAX_HISTORY_TOKENS:
            break
        used_tokens += message_tokens
        selected.append((role, content))
    for role, content in reversed(selected):
        lines.append(f"{role.title()}: {content}")
    return "\n".join(lines)


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def _token_set(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", value.lower()))


def _is_near_duplicate(content: str, seen: list[set[str]]) -> bool:
    tokens = _token_set(content)
    if not tokens:
        return True
    for previous in seen:
        overlap = len(tokens.intersection(previous)) / max(1, min(len(tokens), len(previous)))
        if overlap >= NEAR_DUPLICATE_OVERLAP:
            return True
    seen.append(tokens)
    return False


def clean_retrieved_chunks(retrieved: list[dict], top_k: int) -> list[dict]:
    cleaned = []
    seen_texts: set[str] = set()
    seen_token_sets: list[set[str]] = []

    for item in sorted(retrieved, key=lambda row: (-float(row.get("score") or 0.0), row["chunk"].chunk_index)):
        content = item["chunk"].content.strip()
        normalized = _normalized_text(content)
        if len(content) < MIN_CHUNK_CHARS or normalized in seen_texts:
            continue
        if _is_near_duplicate(content, seen_token_sets):
            continue
        seen_texts.add(normalized)
        cleaned.append(item)
        if len(cleaned) >= top_k:
            break

    return sorted(cleaned, key=lambda row: (row["document"].id, row["chunk"].chunk_index))


def retrieve_relevant_chunks_cached(db: Session, bot_id: int, query: str, top_k: int = 4) -> list[dict]:
    cache_key = (bot_id, query, top_k)
    if cache_key in _RETRIEVAL_CACHE:
        cached = _RETRIEVAL_CACHE[cache_key]
        return [
            {
                "score": item["score"],
                "chunk": SimpleNamespace(**item["chunk"]),
                "document": SimpleNamespace(**item["document"]),
            }
            for item in cached
        ]

    retrieved = retrieve_relevant_chunks(db=db, bot_id=bot_id, query=query, top_k=top_k)

    to_cache = [
        {
            "score": item["score"],
            "chunk": {
                "id": item["chunk"].id,
                "chunk_index": item["chunk"].chunk_index,
                "content": item["chunk"].content,
                "token_count": item["chunk"].token_count,
                "metadata_json": item["chunk"].metadata_json,
            },
            "document": {
                "id": item["document"].id,
                "filename": item["document"].filename,
                "source_url": item["document"].source_url,
            }
        }
        for item in retrieved
    ]

    if len(_RETRIEVAL_CACHE) >= 1000:
        _RETRIEVAL_CACHE.clear()
    _RETRIEVAL_CACHE[cache_key] = to_cache
    return retrieved


def retrieve_relevant_chunks(db: Session, bot_id: int, query: str, top_k: int = 4) -> list[dict]:
    has_sources = (
        db.query(Document.id)
        .filter(Document.bot_id == bot_id)
        .filter(Document.processing_status == "completed")
        .first()
    )
    if not has_sources:
        return []

    query_embedding = generate_embedding(query)
    distance = Chunk.embedding.cosine_distance(query_embedding).label("distance")
    candidate_limit = min(max(top_k * 3, top_k), 18)
    rows = (
        db.query(Chunk, Document, distance)
        .join(Document, Chunk.document_id == Document.id)
        .filter(Document.bot_id == bot_id)
        .filter(Document.processing_status == "completed")
        .order_by(distance)
        .limit(candidate_limit)
        .all()
    )
    retrieved = [
        {
            "chunk": chunk,
            "document": document,
            "score": max(0.0, 1.0 - float(distance_value or 0.0)),
        }
        for chunk, document, distance_value in rows
    ]
    return clean_retrieved_chunks(retrieved, top_k=top_k)


def retrieval_confidence(retrieved: list[dict]) -> dict:
    if not retrieved:
        return {"top_score": 0.0, "average_score": 0.0, "is_confident": False}
    scores = [float(item.get("score") or 0.0) for item in retrieved]
    top_score = max(scores)
    average_score = sum(scores) / len(scores)
    return {
        "top_score": top_score,
        "average_score": average_score,
        "is_confident": top_score >= MIN_TOP_SCORE or average_score >= MIN_AVERAGE_SCORE,
    }


def build_general_prompt(question: str, history: list[dict] | None = None) -> str:
    conversation = _format_history(history)
    length_pref = detect_length_preference(question)
    length_instruction = f"\nLength constraint: Keep the answer {length_pref.replace('_', ' ')}." if length_pref else ""

    return f"""
Recent conversation:
{conversation or "No previous messages."}

User message:
{question}
{length_instruction}

Respond naturally, helpfully, and conversationally.
""".strip()


def build_transform_prompt(question: str, history: list[dict] | None = None, mode: str = "summarize") -> str:
    conversation = _format_history(history)
    length_pref = detect_length_preference(question)
    length_instruction = f" ({length_pref.replace('_', ' ')})." if length_pref else "."

    if mode == "simplify":
        task_desc = f"Explain the previous assistant response simply in plain terms{length_instruction}"
    else:
        task_desc = f"Summarize the previous assistant response clearly{length_instruction}"

    return f"""
Recent conversation:
{conversation or "No previous messages."}

User request:
{question}

Task:
{task_desc} Do not search for new information. Focus purely on transforming the previous answer.
""".strip()


def build_rag_prompt(question: str, retrieved: list[dict], history: list[dict] | None = None) -> str:
    top_items, compressed_context = compress_and_rerank_chunks(retrieved, question)
    conversation = _format_history(history)

    length_pref = detect_length_preference(question)
    length_instruction = f"\nFormat/Length constraint: Please format your output as {length_pref.replace('_', ' ')}." if length_pref else ""

    return f"""
Useful business information:
{compressed_context or "No relevant information found."}

Recent conversation:
{conversation or "No previous messages."}

User question:
{question}
{length_instruction}

Answer as though you already know this business. Use the relevant facts to give one cohesive, visitor-ready response; do not reproduce, enumerate, or summarize the source text chunk by chunk. Lead with the answer, resolve any conflict in the information carefully, and include only details that answer the question. Do not cite or describe internal search mechanics.
""".strip()


def _format_retrieved_chunks(retrieved: list[dict]) -> list[dict]:
    formatted = []
    for item in retrieved:
        chunk: Chunk = item["chunk"]
        document: Document = item["document"]
        formatted.append(
            {
                "chunk_id": chunk.id,
                "document_id": document.id,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "token_count": chunk.token_count,
                "score": item["score"],
                "source_filename": document.filename,
                "source_url": document.source_url,
                "metadata": chunk.metadata_json or {},
            }
        )
    return formatted


def _format_sources(retrieved: list[dict]) -> list[dict]:
    sources: dict[int, dict] = {}
    for item in retrieved:
        chunk: Chunk = item["chunk"]
        document: Document = item["document"]
        source = sources.setdefault(
            document.id,
            {
                "document_id": document.id,
                "filename": document.filename,
                "source_url": document.source_url,
                "chunk_refs": [],
            },
        )
        source["chunk_refs"].append(chunk.chunk_index)
    return list(sources.values())


def _general_answer(bot: Bot, question: str, history: list[dict] | None = None) -> str:
    prompt = build_general_prompt(question=question, history=history)
    system_instruction = _get_system_instruction(bot, GENERAL_ASSISTANT_PROMPT)
    try:
        answer = generate(bot=bot, prompt=prompt, system_instruction=system_instruction)
    except Exception:
        increment_metric("chat.provider_error")
        return FRIENDLY_FALLBACK
    if not answer.strip():
        increment_metric("chat.empty_generation")
        return FALLBACK_REPLY
    return answer


def answer_question(
    db: Session,
    bot: Bot,
    question: str,
    top_k: int = 4,
    history: list[dict] | None = None,
    trace: ChatTrace | None = None,
) -> tuple[str, list[dict], list[dict]]:
    route_started_at = perf_counter()

    # 1. Semantic Cache Check
    cached_response = global_semantic_cache.get(bot.id, question)
    if cached_response:
        if trace:
            trace.cache_hit = True
            trace.intent = "cached"
        return (
            cached_response["reply"],
            cached_response["sources"],
            cached_response["retrieved_chunks"],
        )

    # 2. Context Memory Analysis
    memory = ContextMemory(history=history)
    if trace:
        trace.memory_turns = len(history or [])

    # 3. Classify intent
    intent = classify_intent(question, history=history)
    if trace:
        trace.intent = intent

    # 4. Check grounding & capabilities
    capabilities = bot.capabilities or {}
    web_search_enabled = capabilities.get("web_search", False)

    has_sources = (
        db.query(Document.id)
        .filter(Document.bot_id == bot.id)
        .filter(Document.processing_status == "completed")
        .first()
    ) is not None

    strict_grounding = has_sources and not web_search_enabled

    # Handle In-place transformations (Summarize, Simplify) without re-retrieval
    if intent in (INTENT_SUMMARIZE_PREVIOUS, INTENT_SIMPLIFY_PREVIOUS) and history and len(history) >= 2:
        mode = "simplify" if intent == INTENT_SIMPLIFY_PREVIOUS else "summarize"
        prompt = build_transform_prompt(question, history=history, mode=mode)
        system_instruction = _get_system_instruction(bot, GENERAL_ASSISTANT_PROMPT)
        answer = generate(bot=bot, prompt=prompt, system_instruction=system_instruction)
        final_answer = answer or FALLBACK_REPLY
        global_semantic_cache.set(bot.id, question, {"reply": final_answer, "sources": [], "retrieved_chunks": []})
        return final_answer, [], []

    # Handle Casual Conversational intents without RAG retrieval
    if intent in (INTENT_GREETING, INTENT_FAREWELL, INTENT_GRATITUDE, INTENT_IDENTITY, INTENT_SMALL_TALK):
        answer = _general_answer(bot=bot, question=question, history=history)
        global_semantic_cache.set(bot.id, question, {"reply": answer, "sources": [], "retrieved_chunks": []})
        return answer, [], []

    # Handle Strict Grounding mode
    if strict_grounding:
        search_query = rewrite_query_for_retrieval(question, history=history)
        retrieval_started_at = perf_counter()
        try:
            retrieved = retrieve_relevant_chunks_cached(db=db, bot_id=bot.id, query=search_query, top_k=top_k)
        except Exception:
            if trace:
                trace.used_fallback = True
            increment_metric("chat.retrieval_failure")
            retrieved = []

        if trace:
            trace.mark("retrieval_ms", retrieval_started_at)
            trace.used_retrieval = True

        system_prompt = _get_system_instruction(bot, DEFAULT_SUPPORT_PROMPT, strict_grounding=True)
        prompt = build_rag_prompt(question=question, retrieved=retrieved, history=history)
        generation_started_at = perf_counter()
        try:
            answer = generate(bot=bot, prompt=prompt, system_instruction=system_prompt)
        except Exception:
            if trace:
                trace.used_fallback = True
            answer = FRIENDLY_FALLBACK
        
        if trace:
            trace.mark("generation_start_ms", generation_started_at)
        
        if not answer.strip():
            increment_metric("chat.empty_generation")
            answer = FRIENDLY_FALLBACK

        # Critique
        passed, _ = critique_response(answer, question, strict_grounding=True)
        if trace:
            trace.critique_passed = passed

        sources = _format_sources(retrieved)
        ret_chunks = _format_retrieved_chunks(retrieved)
        global_semantic_cache.set(bot.id, question, {"reply": answer, "sources": sources, "retrieved_chunks": ret_chunks})
        return answer, sources, ret_chunks

    # Standard / Flexible Mode
    use_rag = should_use_rag(question, history=history)
    if trace:
        trace.mark("intent_routing_ms", route_started_at)

    if not use_rag:
        answer = _general_answer(bot=bot, question=question, history=history)
        global_semantic_cache.set(bot.id, question, {"reply": answer, "sources": [], "retrieved_chunks": []})
        return answer, [], []

    search_query = rewrite_query_for_retrieval(question, history=history)
    retrieval_started_at = perf_counter()
    try:
        retrieved = retrieve_relevant_chunks_cached(db=db, bot_id=bot.id, query=search_query, top_k=top_k)
    except Exception:
        if trace:
            trace.used_fallback = True
        increment_metric("chat.retrieval_failure")
        return _general_answer(bot=bot, question=question, history=history), [], []

    if trace:
        trace.mark("retrieval_ms", retrieval_started_at)
    confidence = retrieval_confidence(retrieved)
    if trace:
        trace.confidence = confidence.get("top_score", 0.0)

    if not confidence["is_confident"]:
        if trace:
            trace.used_fallback = True
        increment_metric("chat.retrieval_low_confidence")
        return FRIENDLY_FALLBACK, [], []

    if trace:
        trace.used_retrieval = True

    system_prompt = _get_system_instruction(bot, DEFAULT_SUPPORT_PROMPT, strict_grounding=False)
    prompt = build_rag_prompt(question=question, retrieved=retrieved, history=history)
    generation_started_at = perf_counter()
    try:
        answer = generate(bot=bot, prompt=prompt, system_instruction=system_prompt)
    except Exception:
        if trace:
            trace.used_fallback = True
        answer = FRIENDLY_FALLBACK
    if trace:
        trace.mark("generation_start_ms", generation_started_at)
    if not answer.strip():
        increment_metric("chat.empty_generation")
        answer = FALLBACK_REPLY

    sources = _format_sources(retrieved)
    ret_chunks = _format_retrieved_chunks(retrieved)
    global_semantic_cache.set(bot.id, question, {"reply": answer, "sources": sources, "retrieved_chunks": ret_chunks})
    return answer, sources, ret_chunks


def stream_answer_question(
    db: Session,
    bot: Bot,
    question: str,
    top_k: int = 4,
    history: list[dict] | None = None,
    trace: ChatTrace | None = None,
):
    route_started_at = perf_counter()

    # 1. Semantic Cache Check
    cached_response = global_semantic_cache.get(bot.id, question)
    if cached_response:
        if trace:
            trace.cache_hit = True
            trace.intent = "cached"
        yield cached_response["reply"]
        return

    # 2. Intent & Memory
    intent = classify_intent(question, history=history)
    if trace:
        trace.intent = intent

    capabilities = bot.capabilities or {}
    web_search_enabled = capabilities.get("web_search", False)

    has_sources = (
        db.query(Document.id)
        .filter(Document.bot_id == bot.id)
        .filter(Document.processing_status == "completed")
        .first()
    ) is not None

    strict_grounding = has_sources and not web_search_enabled

    # Handle In-place transformations (Summarize, Simplify) streaming
    if intent in (INTENT_SUMMARIZE_PREVIOUS, INTENT_SIMPLIFY_PREVIOUS) and history and len(history) >= 2:
        mode = "simplify" if intent == INTENT_SIMPLIFY_PREVIOUS else "summarize"
        prompt = build_transform_prompt(question, history=history, mode=mode)
        system_instruction = _get_system_instruction(bot, GENERAL_ASSISTANT_PROMPT)
        generation_started_at = perf_counter()
        first_token = True
        emitted = False
        full_tokens = []
        for token in generate_stream(bot=bot, prompt=prompt, system_instruction=system_instruction):
            if first_token and trace:
                trace.mark("generation_start_ms", generation_started_at)
                first_token = False
            emitted = True
            full_tokens.append(token)
            yield token
        if not emitted:
            yield FALLBACK_REPLY
        else:
            global_semantic_cache.set(bot.id, question, {"reply": "".join(full_tokens), "sources": [], "retrieved_chunks": []})
        return

    # Handle Casual Conversational intents streaming
    if intent in (INTENT_GREETING, INTENT_FAREWELL, INTENT_GRATITUDE, INTENT_IDENTITY, INTENT_SMALL_TALK):
        prompt = build_general_prompt(question=question, history=history)
        system_instruction = _get_system_instruction(bot, GENERAL_ASSISTANT_PROMPT)
        generation_started_at = perf_counter()
        first_token = True
        emitted = False
        full_tokens = []
        for token in generate_stream(bot=bot, prompt=prompt, system_instruction=system_instruction):
            if first_token and trace:
                trace.mark("generation_start_ms", generation_started_at)
                first_token = False
            emitted = True
            full_tokens.append(token)
            yield token
        if not emitted:
            yield FALLBACK_REPLY
        else:
            global_semantic_cache.set(bot.id, question, {"reply": "".join(full_tokens), "sources": [], "retrieved_chunks": []})
        return

    # Strict Grounding Streaming
    if strict_grounding:
        search_query = rewrite_query_for_retrieval(question, history=history)
        retrieval_started_at = perf_counter()
        try:
            retrieved = retrieve_relevant_chunks_cached(db=db, bot_id=bot.id, query=search_query, top_k=top_k)
        except Exception:
            if trace:
                trace.used_fallback = True
            increment_metric("chat.retrieval_failure")
            retrieved = []

        if trace:
            trace.mark("retrieval_ms", retrieval_started_at)
            trace.used_retrieval = True

        system_instruction = _get_system_instruction(bot, DEFAULT_SUPPORT_PROMPT, strict_grounding=True)
        prompt = build_rag_prompt(question=question, retrieved=retrieved, history=history)
        generation_started_at = perf_counter()
        first_token = True
        emitted = False
        full_tokens = []
        for token in generate_stream(bot=bot, prompt=prompt, system_instruction=system_instruction):
            if first_token and trace:
                trace.mark("generation_start_ms", generation_started_at)
                first_token = False
            emitted = True
            full_tokens.append(token)
            yield token
        if not emitted:
            increment_metric("chat.empty_generation")
            yield FRIENDLY_FALLBACK
        else:
            sources = _format_sources(retrieved)
            ret_chunks = _format_retrieved_chunks(retrieved)
            global_semantic_cache.set(bot.id, question, {"reply": "".join(full_tokens), "sources": sources, "retrieved_chunks": ret_chunks})
        return

    # Standard / Flexible Streaming
    use_rag = should_use_rag(question, history=history)
    if trace:
        trace.mark("intent_routing_ms", route_started_at)

    if not use_rag:
        prompt = build_general_prompt(question=question, history=history)
        system_instruction = _get_system_instruction(bot, GENERAL_ASSISTANT_PROMPT)
        generation_started_at = perf_counter()
        first_token = True
        emitted = False
        full_tokens = []
        for token in generate_stream(bot=bot, prompt=prompt, system_instruction=system_instruction):
            if first_token and trace:
                trace.mark("generation_start_ms", generation_started_at)
                first_token = False
            emitted = True
            full_tokens.append(token)
            yield token
        if not emitted:
            increment_metric("chat.empty_generation")
            yield FALLBACK_REPLY
        else:
            global_semantic_cache.set(bot.id, question, {"reply": "".join(full_tokens), "sources": [], "retrieved_chunks": []})
        return

    search_query = rewrite_query_for_retrieval(question, history=history)
    retrieval_started_at = perf_counter()
    try:
        retrieved = retrieve_relevant_chunks_cached(db=db, bot_id=bot.id, query=search_query, top_k=top_k)
    except Exception:
        if trace:
            trace.used_fallback = True
        increment_metric("chat.retrieval_failure")
        prompt = build_general_prompt(question=question, history=history)
        system_instruction = _get_system_instruction(bot, GENERAL_ASSISTANT_PROMPT)
        generation_started_at = perf_counter()
        first_token = True
        emitted = False
        full_tokens = []
        for token in generate_stream(bot=bot, prompt=prompt, system_instruction=system_instruction):
            if first_token and trace:
                trace.mark("generation_start_ms", generation_started_at)
                first_token = False
            emitted = True
            full_tokens.append(token)
            yield token
        if not emitted:
            increment_metric("chat.empty_generation")
            yield FALLBACK_REPLY
        else:
            global_semantic_cache.set(bot.id, question, {"reply": "".join(full_tokens), "sources": [], "retrieved_chunks": []})
        return

    if trace:
        trace.mark("retrieval_ms", retrieval_started_at)
    confidence = retrieval_confidence(retrieved)
    if trace:
        trace.confidence = confidence.get("top_score", 0.0)

    if not confidence["is_confident"]:
        if trace:
            trace.used_fallback = True
        increment_metric("chat.retrieval_low_confidence")
        yield FRIENDLY_FALLBACK
        return

    if trace:
        trace.used_retrieval = True

    system_instruction = _get_system_instruction(bot, DEFAULT_SUPPORT_PROMPT, strict_grounding=strict_grounding)
    prompt = build_rag_prompt(question=question, retrieved=retrieved, history=history)
    generation_started_at = perf_counter()
    first_token = True
    emitted = False
    full_tokens = []
    for token in generate_stream(bot=bot, prompt=prompt, system_instruction=system_instruction):
        if first_token and trace:
            trace.mark("generation_start_ms", generation_started_at)
            first_token = False
        emitted = True
        full_tokens.append(token)
        yield token
    if not emitted:
        increment_metric("chat.empty_generation")
        yield FALLBACK_REPLY
    else:
        sources = _format_sources(retrieved)
        ret_chunks = _format_retrieved_chunks(retrieved)
        global_semantic_cache.set(bot.id, question, {"reply": "".join(full_tokens), "sources": sources, "retrieved_chunks": ret_chunks})
