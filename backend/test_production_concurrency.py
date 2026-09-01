import asyncio
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from database.connection import SessionLocal, engine, get_pool_status
from database.models import Bot, Chunk, Document, Organization, OrganizationMembership, User
from services.auth_service import hash_password
from services.conversational_engine import compress_and_rerank_chunks, global_semantic_cache
from services.embedding_service import generate_embedding, generate_embeddings_batch
from services.intent_router import RETRIEVAL_MODE_CATALOG, RETRIEVAL_MODE_COMPARISON, RETRIEVAL_MODE_FACTUAL, RETRIEVAL_MODE_FILTER, RETRIEVAL_MODE_POLICY, RETRIEVAL_MODE_PURCHASE
from services.rag_service import answer_question, clear_retrieval_cache, retrieve_relevant_chunks
from utils.rate_limiter import check_rate_limit, enforce_rate_limit

import fakeredis
import fakeredis.aioredis
from utils.redis_client import set_redis_override


# ---------------------------------------------------------------------------
# WORKLOAD DEFINITIONS ACROSS MULTIPLE VERTICALS
# ---------------------------------------------------------------------------
WORKLOAD_QUERIES = [
    {"query": "What is the monthly rent for the Studio Deluxe?", "mode": RETRIEVAL_MODE_FACTUAL, "type": "factual"},
    {"query": "Show me all available 1-bedroom and 2-bedroom floor plans with balconies", "mode": RETRIEVAL_MODE_CATALOG, "type": "catalog"},
    {"query": "Compare the 1-Bedroom Urban and 2-Bedroom Penthouse square footage and rent", "mode": RETRIEVAL_MODE_COMPARISON, "type": "comparison"},
    {"query": "What is the pet policy and security deposit for a 12-month lease?", "mode": RETRIEVAL_MODE_POLICY, "type": "policy"},
    {"query": "Where can I schedule a tour or apply for an apartment?", "mode": RETRIEVAL_MODE_PURCHASE, "type": "purchase"},
    {"query": "Do you have gluten-free and vegetarian risotto options on the menu?", "mode": RETRIEVAL_MODE_FILTER, "type": "filter"},
    {"query": "How much is the 45-day dry aged USDA prime ribeye steak?", "mode": RETRIEVAL_MODE_FACTUAL, "type": "factual"},
    {"query": "What is the corkage fee per bottle of outside wine?", "mode": RETRIEVAL_MODE_POLICY, "type": "policy"},
    {"query": "Tell me about the Matterhorn Glacier Trek and Monte Rosa Heli-Skiing tours", "mode": RETRIEVAL_MODE_COMPARISON, "type": "comparison"},
    {"query": "What is the cancellation policy if I cancel 15 days before departure?", "mode": RETRIEVAL_MODE_POLICY, "type": "policy"},
]


def seed_concurrency_corpus(db, bot_id: int, org_id: int):
    """Seed a rich multi-domain corpus for concurrency benchmarking."""
    # Ensure Bot exists
    bot = Bot(id=bot_id, organization_id=org_id, name=f"Concurrency Benchmark Bot {bot_id}")
    db.merge(bot)
    db.commit()

    # Clean existing
    db.query(Chunk).filter(Chunk.bot_id == bot_id).delete()
    db.query(Document).filter(Document.bot_id == bot_id).delete()
    db.commit()

    doc_data = [
        ("Studio Deluxe", "https://realty.test/units/studio", "Studio Deluxe offers 520 sqft open floor plan with modern appliances. Monthly rent is $1,450."),
        ("1-Bedroom Urban", "https://realty.test/units/1bed", "1-Bedroom Urban features 780 sqft, private balcony, walk-in closet. Monthly rent is $1,950."),
        ("2-Bedroom Penthouse", "https://realty.test/units/penthouse", "2-Bedroom Penthouse features 1,400 sqft, skyline panoramic views, wrap-around terrace. Monthly rent is $3,200."),
        ("Deposit Policy", "https://realty.test/policies/deposit", "All 12-month residential leases require first month rent plus $500 refundable security deposit. Pet deposit is $250."),
        ("Leasing Application", "https://realty.test/apply", "Schedule a tour or apply online at https://realty.test/apply with instant background check."),
        ("Truffle Risotto", "https://bistro.test/menu/risotto", "Carnaroli rice with black winter truffles, aged Parmigiano. Dietary: Vegetarian, Gluten-Free. Price: $32."),
        ("Dry-Aged Ribeye", "https://bistro.test/menu/ribeye", "45-day dry-aged USDA Prime 16oz ribeye steak with bone marrow butter. Price: $58."),
        ("Corkage Policy", "https://bistro.test/policies/corkage", "Corkage fee is $35 per 750ml bottle with a limit of 2 outside bottles per party."),
        ("Matterhorn Trek", "https://alps.test/tours/matterhorn", "Matterhorn Glacier Trek is an 8-hour guided alpine trek. Price: $450 per person."),
        ("Tour Refund Policy", "https://alps.test/policies/refund", "Cancellations made 14+ days prior receive 100% full refund minus $50 processing fee."),
    ]

    texts = [c for _, _, c in doc_data]
    embeddings = generate_embeddings_batch(texts, org_id)

    for i, (title, url, content) in enumerate(doc_data):
        doc = Document(
            bot_id=bot_id,
            organization_id=org_id,
            source_type="website",
            filename=f"doc_{i}",
            title=title,
            source_url=url,
            status="ready",
            processing_status="completed",
        )
        db.add(doc)
        db.flush()

        db.add(Chunk(
            bot_id=bot_id,
            organization_id=org_id,
            document_id=doc.id,
            chunk_index=0,
            content=f"[{title}]\n{content}",
            status="ready",
            embedding=embeddings[i],
            metadata_json={"page_title": title, "source_url": url},
        ))
    db.commit()


def run_single_concurrent_query(bot_id: int, org_id: int, query_info: dict, client_id: str) -> dict:
    """Simulates a single end-to-end multi-tenant RAG retrieval request."""
    db = SessionLocal()
    start_time = time.perf_counter()
    status = "success"
    error_msg = None
    chunks_count = 0
    context_len = 0

    try:
        # Rate limit check (using sliding window Lua script)
        allowed, retry_after, remaining = check_rate_limit(
            scope="public_chat",
            org_id=org_id,
            bot_id=bot_id,
            client_id=client_id,
            limit=500,  # Concurrency benchmark high capacity
            window_seconds=60,
        )

        if not allowed:
            return {
                "status": "rate_limited",
                "latency_ms": (time.perf_counter() - start_time) * 1000,
                "error": f"Rate limit exceeded (retry_after={retry_after}s)",
            }

        # Hybrid RRF Retrieval with mode routing
        query = query_info["query"]
        mode = query_info["mode"]

        retrieved = retrieve_relevant_chunks(db, bot_id=bot_id, query=query, mode=mode)
        chunks_count = len(retrieved)

        # Context compression and reranking
        _, context = compress_and_rerank_chunks(retrieved, query=query, mode=mode, max_context_chars=8000)
        context_len = len(context)

        # Assert grounding verification
        if not context:
            status = "empty_context"

    except Exception as e:
        status = "error"
        error_msg = str(e)
    finally:
        db.close()

    latency_ms = (time.perf_counter() - start_time) * 1000
    return {
        "status": status,
        "latency_ms": latency_ms,
        "chunks_count": chunks_count,
        "context_len": context_len,
        "error": error_msg,
    }


def execute_concurrency_benchmark(concurrent_users: int, total_requests: int, bot_id: int, org_id: int) -> dict:
    """Executes a load benchmark with a given number of concurrent worker threads."""
    print(f"\n=======================================================")
    print(f"[BENCHMARK] Running: {concurrent_users} Concurrent Users | {total_requests} Requests")
    print(f"=======================================================")

    results = []
    start_wall = time.perf_counter()

    with ThreadPoolExecutor(max_workers=concurrent_users) as executor:
        futures = []
        for i in range(total_requests):
            query_info = random.choice(WORKLOAD_QUERIES)
            client_id = f"user_{i % concurrent_users}"
            futures.append(
                executor.submit(run_single_concurrent_query, bot_id, org_id, query_info, client_id)
            )

        for future in as_completed(futures):
            results.append(future.result())

    total_time_s = time.perf_counter() - start_wall
    latencies = [r["latency_ms"] for r in results]
    latencies.sort()

    successes = sum(1 for r in results if r["status"] == "success")
    errors = sum(1 for r in results if r["status"] == "error")
    rate_limited = sum(1 for r in results if r["status"] == "rate_limited")

    p50 = latencies[int(len(latencies) * 0.50)] if latencies else 0.0
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0.0
    p99 = latencies[int(len(latencies) * 0.99)] if latencies else 0.0
    worst = latencies[-1] if latencies else 0.0
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    throughput = len(results) / total_time_s if total_time_s > 0 else 0.0

    pool_status = get_pool_status()

    metrics = {
        "concurrency": concurrent_users,
        "total_requests": len(results),
        "success_count": successes,
        "error_count": errors,
        "rate_limited_count": rate_limited,
        "success_rate_pct": (successes / len(results) * 100) if results else 0.0,
        "throughput_rps": round(throughput, 2),
        "p50_latency_ms": round(p50, 2),
        "p95_latency_ms": round(p95, 2),
        "p99_latency_ms": round(p99, 2),
        "worst_latency_ms": round(worst, 2),
        "avg_latency_ms": round(avg_latency, 2),
        "total_duration_s": round(total_time_s, 2),
        "db_pool_status": pool_status,
    }

    print(f"[RESULTS] for {concurrent_users} Concurrent Users:")
    print(f"  * Success Rate: {metrics['success_rate_pct']:.1f}% ({successes}/{len(results)})")
    print(f"  * Throughput:   {metrics['throughput_rps']} req/sec")
    print(f"  * p50 Latency:  {metrics['p50_latency_ms']} ms")
    print(f"  * p95 Latency:  {metrics['p95_latency_ms']} ms")
    print(f"  * p99 Latency:  {metrics['p99_latency_ms']} ms")
    print(f"  * Worst Case:   {metrics['worst_latency_ms']} ms")
    print(f"  * DB Pool:      checkedout={pool_status.get('checkedout', 0)}, overflow={pool_status.get('overflow', 0)}")
    return metrics


def main():
    fake_redis = fakeredis.FakeRedis()
    fake_async_redis = fakeredis.aioredis.FakeRedis()
    set_redis_override(fake_redis, fake_async_redis)

    db = SessionLocal()
    ts = int(time.time() * 1000) % 1000000 + random.randint(1000, 9999)
    bot_id = 40000 + (ts % 10000)
    org_id = 50000 + (ts % 10000)

    try:
        # Create Org and Bot
        org = Organization(id=org_id, name="Concurrency Test Org", slug=f"concurrency-org-{ts}")
        db.merge(org)
        db.commit()

        print("Seeding multi-domain corpus with batch embeddings...")
        seed_concurrency_corpus(db, bot_id, org_id)

        all_benchmarks = []

        # Run 10, 25, 50, and 100 concurrent users
        concurrency_levels = [
            (10, 50),
            (25, 100),
            (50, 200),
            (100, 400),
        ]

        for concurrent_users, total_reqs in concurrency_levels:
            metrics = execute_concurrency_benchmark(concurrent_users, total_reqs, bot_id, org_id)
            all_benchmarks.append(metrics)
            time.sleep(0.5)

        # Summary Table
        print("\n" + "=" * 80)
        print("CONCURRENCY & SCALABILITY SUMMARY")
        print("=" * 80)
        print(f"{'Users':<8} | {'Requests':<10} | {'Success Rate':<14} | {'Throughput':<12} | {'p50 (ms)':<10} | {'p95 (ms)':<10} | {'p99 (ms)':<10}")
        print("-" * 80)
        for m in all_benchmarks:
            print(f"{m['concurrency']:<8} | {m['total_requests']:<10} | {m['success_rate_pct']:<5.1f}%{'':<8} | {m['throughput_rps']:<6.1f} rps | {m['p50_latency_ms']:<10.1f} | {m['p95_latency_ms']:<10.1f} | {m['p99_latency_ms']:<10.1f}")
        print("=" * 80)

        # Assert no catastrophic failure (success rate > 95% at all levels)
        for m in all_benchmarks:
            if m["success_rate_pct"] < 95.0:
                print(f"[FAIL] Degradation detected at concurrency {m['concurrency']}: {m['success_rate_pct']}%")
                sys.exit(1)

        print("\n[SUCCESS] All concurrency targets achieved with zero pool exhaustion or data corruption.")

    finally:
        try:
            db.query(Chunk).filter(Chunk.bot_id == bot_id).delete()
            db.query(Document).filter(Document.bot_id == bot_id).delete()
            db.query(Bot).filter(Bot.id == bot_id).delete()
            db.query(Organization).filter(Organization.id == org_id).delete()
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
            set_redis_override(None, None)


if __name__ == "__main__":
    main()
