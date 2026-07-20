import sys
import httpx
from database.connection import SessionLocal
from sqlalchemy import text
from services.conversational_engine import (
    ContextMemory,
    compress_and_rerank_chunks,
    critique_response,
    global_semantic_cache,
)
from services.intent_router import classify_intent

BASE_URL = "http://127.0.0.1:8000"


def log_test(step_name, success, info=""):
    status = "SUCCESS" if success else "FAILED"
    print(f"[{status}] {step_name} {f'({info})' if info else ''}")
    if not success:
        sys.exit(1)


def run_conversational_engine_unit_tests():
    print("--- 1. CONVERSATIONAL ENGINE UNIT TESTS (PHASE 5D) ---")

    # Semantic Cache Test
    global_semantic_cache.clear()
    global_semantic_cache.set(999, "what is your pricing?", {"reply": "Our pricing starts at $29/mo.", "sources": []})
    cached = global_semantic_cache.get(999, "What is your pricing?")
    log_test("Semantic Cache Get/Set", cached is not None and cached["reply"] == "Our pricing starts at $29/mo.")

    # Context Memory & Entity Extraction Test
    history = [
        {"role": "user", "content": "Tell me about OpenAI and Sam Altman in 2024."},
        {"role": "assistant", "content": "OpenAI is an AI research lab led by Sam Altman."}
    ]
    memory = ContextMemory(history=history)
    summary = memory.get_summary()
    log_test(
        "Context Memory Entity Extraction",
        "OpenAI" in summary["entities"] and "Sam" in summary["entities"],
        f"Entities: {summary['entities']}"
    )

    # RAG Chunk Reranker & Context Compression Test
    raw_chunks = [
        {"chunk": type("Chunk", (), {"id": 1, "content": "OpenAI was founded in 2015 by Sam Altman and Elon Musk."}), "document": type("Doc", (), {"id": 10}), "score": 0.85},
        {"chunk": type("Chunk", (), {"id": 2, "content": "OpenAI was founded in 2015 by Sam Altman and Elon Musk."}), "document": type("Doc", (), {"id": 10}), "score": 0.84}, # duplicate
        {"chunk": type("Chunk", (), {"id": 3, "content": "Short"}), "document": type("Doc", (), {"id": 10}), "score": 0.90}, # fragment
    ]
    reranked, compressed = compress_and_rerank_chunks(raw_chunks, query="who founded OpenAI")
    log_test(
        "Context Compressor (Deduplication & Noise Filter)",
        len(reranked) == 1 and "OpenAI was founded" in compressed,
        f"Count: {len(reranked)}, Compressed text: '{compressed}'"
    )

    # Response Critique Test
    valid, msg = critique_response("OpenAI is an AI research company.", "what is OpenAI?")
    log_test("Critique (Valid Response)", valid is True)

    invalid, msg_inv = critique_response("According to document 1, OpenAI is a company.", "what is OpenAI?")
    log_test("Critique (Robotic Grounding Leak Detection)", invalid is False, f"Reason: {msg_inv}")

    print("All Conversational Engine unit tests passed!\n")


def run_e2e_phase5d_api_tests():
    print("--- 2. E2E PHASE 5D API & DEBUG TESTS ---")
    client = httpx.Client(timeout=30.0)

    try:
        # First query (populate cache)
        res1 = client.post(
            f"{BASE_URL}/public/chat/2",
            json={"session_id": "test-session-5d", "message": "What is your refund policy?"}
        )
        if res1.status_code != 200:
            print("Query 1 Status:", res1.status_code, "Body:", res1.text)
        log_test("Public Chat Query 1", res1.status_code == 200)

        # Second query (verify Semantic Cache hit)
        res2 = client.post(
            f"{BASE_URL}/public/chat/2",
            json={"session_id": "test-session-5d", "message": "What is your refund policy?"}
        )
        log_test("Public Chat Query 2 (Semantic Cache Hit)", res2.status_code == 200)
        log_test("Cached answer matches", res1.json()["reply"] == res2.json()["reply"])

    except Exception as e:
        import traceback
        traceback.print_exc()
        log_test("E2E Phase 5D API Failure", False, str(e))

    print("All Phase 5D E2E API tests passed!\n")


if __name__ == "__main__":
    run_conversational_engine_unit_tests()
    run_e2e_phase5d_api_tests()
