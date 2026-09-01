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
from database.models import (
    Bot,
    Chunk,
    ConversationMessage,
    ConversationSession,
    Document,
    IngestionJob,
    Organization,
    OrganizationMembership,
    User,
    Website,
    WebsiteCrawl,
)
from services.auth_service import hash_password
from services.conversational_engine import compress_and_rerank_chunks, global_semantic_cache
from services.embedding_service import generate_embeddings_batch
from services.intent_router import (
    RETRIEVAL_MODE_CATALOG,
    RETRIEVAL_MODE_COMPARISON,
    RETRIEVAL_MODE_FACTUAL,
    RETRIEVAL_MODE_FILTER,
    RETRIEVAL_MODE_POLICY,
    RETRIEVAL_MODE_PURCHASE,
)
from services.queue_service import enqueue_ingestion_job
from services.rag_service import answer_question, clear_retrieval_cache, retrieve_relevant_chunks
from utils.rate_limiter import check_rate_limit
from workers.crawl_worker import execute_crawl_job

import fakeredis
import fakeredis.aioredis
from utils.redis_client import set_redis_override


# ---------------------------------------------------------------------------
# MULTI-TENANT LOAD SIMULATION CORPUS & WORKLOADS
# ---------------------------------------------------------------------------
TENANT_SPECS = [
    {
        "name": "OmniRealty Group",
        "slug": "omnirealty",
        "docs": [
            ("Studio Luxe", "https://omnirealty.io/studio", "Studio Luxe unit is 540 sqft with designer kitchen. Rent is $1,600/mo."),
            ("Penthouse Suite", "https://omnirealty.io/penthouse", "Penthouse Suite is 1,800 sqft with panoramic rooftop terrace. Rent is $4,100/mo."),
            ("Lease Agreement Terms", "https://omnirealty.io/terms", "12-month standard residential lease requires 1 month deposit. Pets allowed with $300 deposit."),
        ],
        "queries": [
            ("What is the rent for the Studio Luxe?", RETRIEVAL_MODE_FACTUAL),
            ("Compare Studio Luxe and Penthouse Suite square footage", RETRIEVAL_MODE_COMPARISON),
            ("What is the pet policy and lease deposit?", RETRIEVAL_MODE_POLICY),
        ],
    },
    {
        "name": "Boutique Hospitality Co",
        "slug": "boutique-hospitality",
        "docs": [
            ("Tasting Menu", "https://boutique.test/menu/tasting", "7-course seasonal tasting menu with wine pairing. Price is $145 per guest."),
            ("Private Dining", "https://boutique.test/events/private", "Private dining room accommodates up to 24 guests. Minimum spend is $2,000."),
            ("Reservation Policy", "https://boutique.test/policies", "Reservations require credit card guarantee. 48-hour cancellation policy applies."),
        ],
        "queries": [
            ("How much does the 7-course tasting menu cost?", RETRIEVAL_MODE_FACTUAL),
            ("How many guests can the private dining room accommodate?", RETRIEVAL_MODE_FACTUAL),
            ("What is the reservation cancellation policy?", RETRIEVAL_MODE_POLICY),
        ],
    },
    {
        "name": "Apex Alpine Tours",
        "slug": "apex-alpine",
        "docs": [
            ("Glacier Heli-Skiing", "https://apex.test/tours/heli-ski", "Advanced heli-skiing expedition in Zermatt. 3 drops included. Price: $1,250."),
            ("Family Snowshoe Trek", "https://apex.test/tours/snowshoe", "Gentle 3-hour guided snowshoe hike for all skill levels. Price: $120."),
            ("Equipment Rental Policy", "https://apex.test/policies/gear", "All safety avalanche gear and carbon skis included in tour packages."),
        ],
        "queries": [
            ("Show me all ski and snowshoe tours with pricing", RETRIEVAL_MODE_CATALOG),
            ("Compare Heli-Skiing and Family Snowshoe packages", RETRIEVAL_MODE_COMPARISON),
            ("Is avalanche safety gear included in the tour price?", RETRIEVAL_MODE_POLICY),
        ],
    },
]


def seed_tenant_environment(db, tenant_index: int, base_ts: int) -> dict:
    spec = TENANT_SPECS[tenant_index]
    org_id = 70000 + (base_ts % 1000) * 10 + tenant_index
    bot_id = 80000 + (base_ts % 1000) * 10 + tenant_index

    org = Organization(id=org_id, name=spec["name"], slug=f"{spec['slug']}-{base_ts}")
    bot = Bot(id=bot_id, organization_id=org_id, name=f"{spec['name']} Assistant")
    db.merge(org)
    db.merge(bot)
    db.commit()

    # Ingest documents with batch embeddings
    texts = [c for _, _, c in spec["docs"]]
    embeddings = generate_embeddings_batch(texts, org_id)

    doc_ids = []
    for i, (title, url, content) in enumerate(spec["docs"]):
        doc = Document(
            bot_id=bot_id,
            organization_id=org_id,
            source_type="website",
            filename=f"doc_{tenant_index}_{i}",
            title=title,
            source_url=url,
            status="ready",
            processing_status="completed",
        )
        db.add(doc)
        db.flush()
        doc_ids.append(doc.id)

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

    return {
        "org_id": org_id,
        "bot_id": bot_id,
        "spec": spec,
        "doc_ids": doc_ids,
    }


def simulate_concurrent_tenant_request(tenant_data: dict, client_id: str) -> dict:
    """Executes a single multi-tenant request with DB session lifecycle, rate limiting, and RAG retrieval."""
    db = SessionLocal()
    start_time = time.perf_counter()
    bot_id = tenant_data["bot_id"]
    org_id = tenant_data["org_id"]
    spec = tenant_data["spec"]
    query_text, mode = random.choice(spec["queries"])

    status = "success"
    error_msg = None

    try:
        # Rate limit check
        allowed, retry_after, _ = check_rate_limit(
            scope="public_chat",
            org_id=org_id,
            bot_id=bot_id,
            client_id=client_id,
            limit=1000,
            window_seconds=60,
        )

        if not allowed:
            return {
                "status": "rate_limited",
                "latency_ms": (time.perf_counter() - start_time) * 1000,
                "error": "Rate limit exceeded",
            }

        # Hybrid RRF retrieval
        retrieved = retrieve_relevant_chunks(db, bot_id=bot_id, query=query_text, mode=mode)
        _, ctx = compress_and_rerank_chunks(retrieved, query=query_text, mode=mode, max_context_chars=6000)

        if not ctx:
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
        "error": error_msg,
    }


def run_production_load_suite(concurrency_levels: List[int]):
    fake_redis = fakeredis.FakeRedis()
    fake_async_redis = fakeredis.aioredis.FakeRedis()
    set_redis_override(fake_redis, fake_async_redis)

    db = SessionLocal()
    base_ts = int(time.time() * 1000) % 1000000 + random.randint(1000, 9999)
    tenants = []

    try:
        print("[SETUP] Seeding 3 multi-tenant environments with isolated knowledge bases...")
        for i in range(len(TENANT_SPECS)):
            t_data = seed_tenant_environment(db, i, base_ts)
            tenants.append(t_data)

        print("[OK] Seeding complete. Initializing multi-tenant load tests...")

        results_summary = []

        for concurrency in concurrency_levels:
            total_requests = concurrency * 4
            print(f"\n[LOAD TEST] Executing {concurrency} Concurrent Workers across 3 Tenants ({total_requests} Total Requests)...")

            start_wall = time.perf_counter()
            results = []

            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = []
                for i in range(total_requests):
                    t = random.choice(tenants)
                    client_id = f"client_{i % concurrency}"
                    futures.append(
                        executor.submit(simulate_concurrent_tenant_request, t, client_id)
                    )

                for future in as_completed(futures):
                    results.append(future.result())

            duration_s = time.perf_counter() - start_wall
            latencies = sorted([r["latency_ms"] for r in results])

            successes = sum(1 for r in results if r["status"] == "success")
            errors = sum(1 for r in results if r["status"] == "error")
            p50 = latencies[int(len(latencies) * 0.50)] if latencies else 0.0
            p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0.0
            p99 = latencies[int(len(latencies) * 0.99)] if latencies else 0.0
            worst = latencies[-1] if latencies else 0.0
            throughput = len(results) / duration_s if duration_s > 0 else 0.0
            pool_stat = get_pool_status()

            summary = {
                "concurrency": concurrency,
                "requests": len(results),
                "success_rate": (successes / len(results) * 100) if results else 0.0,
                "throughput": round(throughput, 2),
                "p50": round(p50, 2),
                "p95": round(p95, 2),
                "p99": round(p99, 2),
                "worst": round(worst, 2),
                "pool_checkedout": pool_stat.get("checkedout", 0),
                "pool_overflow": pool_stat.get("overflow", 0),
            }
            results_summary.append(summary)

            print(f"  * Success Rate: {summary['success_rate']:.1f}% ({successes}/{len(results)})")
            print(f"  * Throughput:   {summary['throughput']} req/sec")
            print(f"  * p50 Latency:  {summary['p50']} ms")
            print(f"  * p95 Latency:  {summary['p95']} ms")
            print(f"  * p99 Latency:  {summary['p99']} ms")
            print(f"  * DB Pool:      checkedout={summary['pool_checkedout']}, overflow={summary['pool_overflow']}")

        # Print Final Summary Table
        print("\n" + "=" * 90)
        print("PRODUCTION LOAD TEST MULTI-TENANT RESULTS")
        print("=" * 90)
        print(f"{'Concurrency':<12} | {'Requests':<10} | {'Success Rate':<14} | {'Throughput':<12} | {'p50 (ms)':<10} | {'p95 (ms)':<10} | {'p99 (ms)':<10}")
        print("-" * 90)
        for s in results_summary:
            print(f"{s['concurrency']:<12} | {s['requests']:<10} | {s['success_rate']:<5.1f}%{'':<8} | {s['throughput']:<6.1f} rps | {s['p50']:<10.1f} | {s['p95']:<10.1f} | {s['p99']:<10.1f}")
        print("=" * 90)

    finally:
        try:
            for t in tenants:
                b_id = t["bot_id"]
                o_id = t["org_id"]
                db.query(Chunk).filter(Chunk.bot_id == b_id).delete()
                db.query(Document).filter(Document.bot_id == b_id).delete()
                db.query(Bot).filter(Bot.id == b_id).delete()
                db.query(Organization).filter(Organization.id == o_id).delete()
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
            set_redis_override(None, None)


if __name__ == "__main__":
    run_production_load_suite([10, 25, 50, 75, 100])
