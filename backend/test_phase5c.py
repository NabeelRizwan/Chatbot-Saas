import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import httpx
from database.connection import SessionLocal
from sqlalchemy import text
from services.intent_router import (
    classify_intent,
    rewrite_query_for_retrieval,
    detect_length_preference,
    INTENT_GREETING,
    INTENT_GRATITUDE,
    INTENT_IDENTITY,
    INTENT_SUMMARIZE_PREVIOUS,
    INTENT_SIMPLIFY_PREVIOUS,
    INTENT_REPHRASE_CONTINUE,
    INTENT_KNOWLEDGE_QUERY,
)

BASE_URL = "http://127.0.0.1:8000"


def log_test(step_name, success, info=""):
    status = "SUCCESS" if success else "FAILED"
    print(f"[{status}] {step_name} {f'({info})' if info else ''}")
    if not success:
        sys.exit(1)


def run_intent_unit_tests():
    print("--- 1. UNIT TESTING CONVERSATION INTELLIGENCE LAYER ---")

    # Intent Classification
    log_test("Classify 'hello'", classify_intent("hello") == INTENT_GREETING)
    log_test("Classify 'who are you?'", classify_intent("who are you?") == INTENT_IDENTITY)
    log_test("Classify 'thank you so much'", classify_intent("thank you so much") == INTENT_GRATITUDE)
    log_test("Classify 'summarize this'", classify_intent("summarize this") == INTENT_SUMMARIZE_PREVIOUS)
    log_test("Classify 'explain like I am 5'", classify_intent("explain like I am 5") == INTENT_SIMPLIFY_PREVIOUS)
    log_test("Classify 'tell me more'", classify_intent("tell me more") == INTENT_REPHRASE_CONTINUE)
    log_test("Classify 'what is pricing?'", classify_intent("what is pricing?") == INTENT_KNOWLEDGE_QUERY)

    # Query Rewriting
    history = [
        {"role": "user", "content": "What is OpenAI?"},
        {"role": "assistant", "content": "OpenAI is an artificial intelligence research organization."}
    ]

    rewritten_continue = rewrite_query_for_retrieval("tell me more", history=history)
    log_test(
        "Rewrite 'tell me more'",
        "OpenAI" in rewritten_continue and "elaborate" in rewritten_continue,
        f"Result: '{rewritten_continue}'"
    )

    rewritten_pronoun = rewrite_query_for_retrieval("how much is it?", history=history)
    log_test(
        "Rewrite pronoun query 'how much is it?'",
        "OpenAI" in rewritten_pronoun,
        f"Result: '{rewritten_pronoun}'"
    )

    # Length preferences
    log_test("Detect 'in 2 lines'", detect_length_preference("explain this in 2 lines") == "very_short")
    log_test("Detect 'detailed explanation'", detect_length_preference("give me a detailed explanation") == "detailed")
    log_test("Detect 'in 1 sentence'", detect_length_preference("summarize in 1 sentence") == "one_sentence")

    print("All Conversation Intelligence unit tests passed!\n")


def run_e2e_api_tests():
    print("--- 2. E2E API INTEGRATION TESTS (PHASE 5C) ---")
    client = httpx.Client(timeout=15.0)

    # Test Public Bot Widget API (Bot #2)
    try:
        # Test Greeting
        res_greet = client.post(
            f"{BASE_URL}/public/chat/2",
            json={"session_id": "test-session-5c", "message": "hello!"}
        )
        log_test("Widget Chat (Greeting)", res_greet.status_code == 200, f"Status: {res_greet.status_code}")
        answer_greet = res_greet.json().get("answer", "")
        log_test("Greeting Response non-empty", len(answer_greet) > 0, f"Answer: {answer_greet[:60]}...")

        # Test Knowledge Query
        res_q = client.post(
            f"{BASE_URL}/public/chat/2",
            json={"session_id": "test-session-5c", "message": "What is your pricing?"}
        )
        log_test("Widget Chat (Knowledge Query)", res_q.status_code == 200)

        # Test Follow-up ("tell me more")
        history = [
            {"role": "user", "content": "What is your pricing?"},
            {"role": "assistant", "content": res_q.json().get("answer", "")}
        ]
        res_continue = client.post(
            f"{BASE_URL}/public/chat/2",
            json={"session_id": "test-session-5c", "message": "tell me more", "history": history}
        )
        log_test("Widget Chat (Follow-up 'tell me more')", res_continue.status_code == 200)

        # Test In-place Summarization ("summarize this in 2 lines")
        res_sum = client.post(
            f"{BASE_URL}/public/chat/2",
            json={"session_id": "test-session-5c", "message": "summarize this in 2 lines", "history": history}
        )
        log_test("Widget Chat (Summarize Previous Response)", res_sum.status_code == 200)

        # Test Streaming Public Endpoint
        res_stream = client.post(
            f"{BASE_URL}/public/chat/2/stream",
            json={"session_id": "test-session-stream", "message": "hi"}
        )
        log_test("Public Stream Endpoint", res_stream.status_code == 200 and len(res_stream.text) > 0)

    except Exception as e:
        log_test("E2E Integration Failure", False, str(e))

    print("All Phase 5C E2E API Integration tests passed!\n")


if __name__ == "__main__":
    run_intent_unit_tests()
    run_e2e_api_tests()
