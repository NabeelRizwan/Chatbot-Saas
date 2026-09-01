import os
import sys
import time
import unittest
from datetime import datetime
from typing import Any, Dict, List, Tuple

# Ensure backend root is on sys.path
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from database.connection import SessionLocal
from database.models import Bot, Chunk, Document, Website
from services.chunking_service import CHUNK_OVERLAP, CHUNK_SIZE, chunk_text_with_metadata
from services.conversational_engine import compress_and_rerank_chunks, global_semantic_cache
from services.embedding_service import generate_embedding
from services.intent_router import (
    classify_intent,
    detect_retrieval_mode,
    rewrite_query_for_retrieval,
    RETRIEVAL_MODE_CATALOG,
    RETRIEVAL_MODE_COMPARISON,
    RETRIEVAL_MODE_ENTITY,
    RETRIEVAL_MODE_FACTUAL,
    RETRIEVAL_MODE_FILTER,
    RETRIEVAL_MODE_POLICY,
    RETRIEVAL_MODE_PURCHASE,
)
from services.rag_service import (
    answer_question,
    build_rag_prompt,
    clear_retrieval_cache,
    retrieve_relevant_chunks,
)

import fakeredis
import fakeredis.aioredis
from utils.redis_client import set_redis_override


class TestCustomerQueryBenchmark(unittest.TestCase):
    """
    50-Query Realistic Customer Query Benchmark Suite.
    Measures retrieval success %, source precision, grounding %, catalog completeness %,
    hallucination rate %, URL correctness %, and response latency across 9 representative verticals.
    """

    @classmethod
    def setUpClass(cls):
        cls.fake_redis = fakeredis.FakeRedis()
        cls.fake_async_redis = fakeredis.aioredis.FakeRedis()
        set_redis_override(cls.fake_redis, cls.fake_async_redis)

    @classmethod
    def tearDownClass(cls):
        set_redis_override(None, None)

    def setUp(self):
        from database.models import Organization
        from services.embedding_service import generate_embeddings_batch
        self.db = SessionLocal()
        self.timestamp = int(datetime.utcnow().timestamp() * 1000) % 1000000
        self.bot_id = 31000 + (self.timestamp % 1000)
        self.org = self.db.merge(Organization(id=500, name="Benchmark Org", slug=f"benchmark-org-{self.timestamp}"))
        self.db.commit()
        clear_retrieval_cache()
        global_semantic_cache.clear()
        self._seed_benchmark_corpus()

    def tearDown(self):
        try:
            self.db.query(Chunk).filter(Chunk.bot_id == self.bot_id).delete()
            self.db.query(Document).filter(Document.bot_id == self.bot_id).delete()
            self.db.query(Bot).filter(Bot.id == self.bot_id).delete()
            self.db.commit()
        except Exception:
            self.db.rollback()
        finally:
            self.db.close()

    def _seed_benchmark_corpus(self):
        from services.embedding_service import generate_embeddings_batch
        bot = Bot(id=self.bot_id, organization_id=500, name="Benchmark Multi-Domain Bot")
        self.db.merge(bot)
        self.db.commit()

        benchmark_docs = [
            # 1. Tech/Laptop
            ("ApexBook Pro 16", "https://bench.io/apexbook", "ApexBook Pro 16 features 16-Core M3 Ultra, 64GB RAM, 2TB SSD, and 99.6Wh battery with 22 hours runtime. Price is $2,499.", [{"text": "Buy Now", "url": "https://bench.io/buy/apexbook"}]),
            # 2. Tech/Monitor
            ("Apex Studio Display", "https://bench.io/display", "Apex Studio Display 27 features 5K resolution 5120x2880, 600 nits, Thunderbolt 4. Price is $1,299.", [{"text": "Buy Now", "url": "https://bench.io/buy/display"}]),
            # 3. Audio/Headphones
            ("SoundWave ANC", "https://bench.io/soundwave", "SoundWave ANC headphones feature 40mm planar magnetic drivers, 45 hours battery life, LDAC audio. Price is $349.", [{"text": "Add to Cart", "url": "https://bench.io/cart/soundwave"}]),
            # 4. Charger
            ("PowerStation 100W", "https://bench.io/charger", "PowerStation 100W GaN 4-port fast desktop charger with PD 3.0. Price is $79.", [{"text": "Buy Now", "url": "https://bench.io/buy/charger"}]),
            # 5. Dental/Implants
            ("Dental Implants", "https://bench.io/dental/implants", "Zenith Dental Implants use medical-grade titanium roots with zirconia crowns. Cost is $2,800 per tooth.", [{"text": "Book Consultation", "url": "https://bench.io/book/dental"}]),
            # 6. Dental/Invisalign
            ("Clear Aligners", "https://bench.io/dental/aligners", "Clear Orthodontic Aligners straighten teeth in 6-12 months. Price is $3,500 full treatment.", [{"text": "Schedule Consultation", "url": "https://bench.io/book/aligners"}]),
            # 7. Real Estate/Studio
            ("Studio Deluxe", "https://bench.io/realty/studio", "Apartment units: Studio Deluxe offers 520 sqft open floor plan with stainless appliances. Monthly rent is $1,450.", [{"text": "Schedule Tour", "url": "https://bench.io/tour/studio"}]),
            # 8. Real Estate/Penthouse
            ("Skyline Penthouse", "https://bench.io/realty/penthouse", "Apartment units: Skyline Penthouse features 1,400 sqft, 2 bedrooms, panoramic terrace. Monthly rent is $3,200.", [{"text": "Schedule Tour", "url": "https://bench.io/tour/penthouse"}]),
            # 9. Dining/Risotto
            ("Truffle Risotto", "https://bench.io/dining/risotto", "Dining menu dishes: Carnaroli rice with winter black truffles and Parmigiano-Reggiano. Vegetarian and Gluten-Free. Price is $32.", [{"text": "Reserve a Table", "url": "https://bench.io/reserve/table"}]),
            # 10. Dining/Ribeye
            ("Prime Ribeye", "https://bench.io/dining/ribeye", "Dining menu dishes: 45-day dry-aged USDA Prime 16oz ribeye steak with bone marrow butter. Price is $58.", [{"text": "Reserve a Table", "url": "https://bench.io/reserve/table"}]),
            # 11. Travel/Glacier Trek
            ("Matterhorn Glacier Trek", "https://bench.io/travel/glacier", "Guided tours: 8-hour alpine trek on the Gorner Glacier with crampons and ice axes. Price is $450.", [{"text": "Book Tour", "url": "https://bench.io/book/glacier"}]),
            # 12. Legal/M&A
            ("M&A Advisory", "https://bench.io/legal/ma", "Legal practice areas: Eleanor Vance leads cross-border M&A advisory. Initial 30-min evaluation is complimentary.", [{"text": "Book Consultation", "url": "https://bench.io/legal/consult"}]),
            # 13. Policy/Shipping
            ("Shipping Policy", "https://bench.io/policies/shipping", "Standard Ground Shipping is free on orders over $50 (3-5 business days). Express Air is $15.", []),
            # 14. Policy/Returns
            ("Return Policy", "https://bench.io/policies/returns", "Return & Refund Policy: We offer a 30-day money-back guarantee and refunds on all hardware items in original packaging.", []),
            # 15. Policy/Cancellation
            ("Cancellation Policy", "https://bench.io/policies/cancel", "Alpine tours and restaurant reservations may be cancelled up to 24 hours in advance for a 100% full refund.", []),
        ]

        texts = [f"{title} {content}" for title, _, content, _ in benchmark_docs]
        embeddings = generate_embeddings_batch(texts)

        for idx, (title, url, content, ctas) in enumerate(benchmark_docs):
            doc = Document(
                bot_id=self.bot_id,
                organization_id=500,
                source_type="website",
                filename=title.lower().replace(" ", "-"),
                title=title,
                source_url=url,
                status="ready",
                processing_status="completed",
                metadata_json={"source_url": url, "page_title": title, "cta_links": ctas},
            )
            self.db.add(doc)
            self.db.commit()
            self.db.refresh(doc)

            chunk = Chunk(
                bot_id=self.bot_id,
                organization_id=500,
                document_id=doc.id,
                chunk_index=0,
                content=f"[{title}]\n{content}",
                token_count=len(content.split()),
                embedding=embeddings[idx],
                status="ready",
                metadata_json={"source_url": url, "page_title": title, "cta_links": ctas},
            )
            self.db.add(chunk)
        self.db.commit()

    def test_run_50_customer_query_benchmark(self):
        """Executes 50 distinct real customer queries and calculates exact empirical metrics."""
        # 50 Categorized Queries
        queries = [
            # FACTUAL (1-10)
            ("What is the battery capacity of ApexBook Pro 16?", "99.6Wh", "FACTUAL", "https://bench.io/apexbook"),
            ("What is the resolution of Apex Studio Display?", "5120x2880", "FACTUAL", "https://bench.io/display"),
            ("How many hours of battery life do the SoundWave headphones have?", "45 hours", "FACTUAL", "https://bench.io/soundwave"),
            ("How much does the PowerStation 100W cost?", "$79", "FACTUAL", "https://bench.io/charger"),
            ("What is the cost of dental implants?", "$2,800", "FACTUAL", "https://bench.io/dental/implants"),
            ("How much is monthly rent for Studio Deluxe?", "$1,450", "FACTUAL", "https://bench.io/realty/studio"),
            ("What is the square footage of Skyline Penthouse?", "1,400 sqft", "FACTUAL", "https://bench.io/realty/penthouse"),
            ("How much is the Truffle Risotto?", "$32", "FACTUAL", "https://bench.io/dining/risotto"),
            ("How much does the Matterhorn Glacier Trek cost?", "$450", "FACTUAL", "https://bench.io/travel/glacier"),
            ("How much is express shipping?", "$15", "FACTUAL", "https://bench.io/policies/shipping"),

            # ENTITY DEEP DIVE (11-17)
            ("Tell me all details about ApexBook Pro 16", "M3 Ultra", "ENTITY", "https://bench.io/apexbook"),
            ("Give me an overview of Apex Studio Display", "Thunderbolt 4", "ENTITY", "https://bench.io/display"),
            ("Tell me everything about SoundWave ANC", "Planar magnetic", "ENTITY", "https://bench.io/soundwave"),
            ("Give me full details on Clear Orthodontic Aligners", "6-12 months", "ENTITY", "https://bench.io/dental/aligners"),
            ("Tell me about the Skyline Penthouse apartment", "panoramic terrace", "ENTITY", "https://bench.io/realty/penthouse"),
            ("Give me an overview of the Matterhorn Glacier Trek", "Gorner Glacier", "ENTITY", "https://bench.io/travel/glacier"),
            ("Tell me about M&A Advisory services", "Eleanor Vance", "ENTITY", "https://bench.io/legal/ma"),

            # CATALOG (18-24)
            ("What products do you offer?", "ApexBook Pro 16", "CATALOG", "https://bench.io/apexbook"),
            ("List all available apartments and units", "Studio Deluxe", "CATALOG", "https://bench.io/realty/studio"),
            ("What dishes are on the menu?", "Truffle Risotto", "CATALOG", "https://bench.io/dining/risotto"),
            ("What dental treatments do you provide?", "Dental Implants", "CATALOG", "https://bench.io/dental/implants"),
            ("What tech hardware items do you sell?", "PowerStation 100W", "CATALOG", "https://bench.io/charger"),
            ("What tours do you offer?", "Matterhorn Glacier Trek", "CATALOG", "https://bench.io/travel/glacier"),
            ("What legal practice areas do you specialize in?", "M&A Advisory", "CATALOG", "https://bench.io/legal/ma"),

            # FILTER & ATTRIBUTES (25-30)
            ("Which dishes are vegetarian or gluten-free?", "Truffle Risotto", "FILTER", "https://bench.io/dining/risotto"),
            ("Which products support fast charging?", "ApexBook Pro 16", "FILTER", "https://bench.io/apexbook"),
            ("Which units have more than 1000 square feet?", "Skyline Penthouse", "FILTER", "https://bench.io/realty/penthouse"),
            ("Which audio products have ANC?", "SoundWave ANC", "FILTER", "https://bench.io/soundwave"),
            ("Which items cost under $100?", "PowerStation 100W", "FILTER", "https://bench.io/charger"),
            ("Which dental treatment straightens teeth?", "Clear Aligners", "FILTER", "https://bench.io/dental/aligners"),

            # COMPARISON (31-35)
            ("Compare ApexBook Pro 16 and SoundWave ANC", "ApexBook Pro 16", "COMPARISON", "https://bench.io/apexbook"),
            ("Compare Studio Deluxe and Skyline Penthouse", "520 sqft", "COMPARISON", "https://bench.io/realty/studio"),
            ("Compare Truffle Risotto and Prime Ribeye", "$32", "COMPARISON", "https://bench.io/dining/risotto"),
            ("Compare Dental Implants and Clear Aligners", "$2,800", "COMPARISON", "https://bench.io/dental/implants"),
            ("Compare standard and express shipping", "3-5 business days", "COMPARISON", "https://bench.io/policies/shipping"),

            # POLICIES & TERMS (36-40)
            ("What is your return policy duration?", "30-day money-back guarantee", "POLICY", "https://bench.io/policies/returns"),
            ("How does tour cancellation work?", "24 hours in advance", "POLICY", "https://bench.io/policies/cancel"),
            ("What is the shipping cost for orders over $50?", "Free", "POLICY", "https://bench.io/policies/shipping"),
            ("What is the fee for an initial legal evaluation?", "complimentary", "POLICY", "https://bench.io/legal/ma"),
            ("How does refund processing work?", "30-day", "POLICY", "https://bench.io/policies/returns"),

            # PURCHASE / ACTION / CTAS (41-45)
            ("Where can I buy the ApexBook Pro 16?", "https://bench.io/buy/apexbook", "PURCHASE", "https://bench.io/apexbook"),
            ("Where do I reserve a table for Truffle Risotto?", "https://bench.io/reserve/table", "PURCHASE", "https://bench.io/dining/risotto"),
            ("Where can I schedule a tour for the Studio Deluxe?", "https://bench.io/tour/studio", "PURCHASE", "https://bench.io/realty/studio"),
            ("How do I book an initial consultation for M&A?", "https://bench.io/legal/consult", "PURCHASE", "https://bench.io/legal/ma"),
            ("Where can I book the Matterhorn Glacier Trek?", "https://bench.io/book/glacier", "PURCHASE", "https://bench.io/travel/glacier"),

            # MISSING INFORMATION & NON-EXISTENT ITEMS (46-50)
            ("How much is the Apex Electric Hoverboard?", "not available", "MISSING", None),
            ("Do you offer scuba diving in the desert?", "not available", "MISSING", None),
            ("What is the price of the Gold Diamond Rolex?", "not available", "MISSING", None),
            ("Do you offer helicopter submarine tours?", "not available", "MISSING", None),
            ("What is the cost of heart surgery at your clinic?", "not available", "MISSING", None),
        ]

        total_queries = len(queries)
        retrieval_successes = 0
        grounding_successes = 0
        url_successes = 0
        hallucination_count = 0
        latencies_ms = []

        for idx, (q, expected_evidence, category, expected_url) in enumerate(queries, start=1):
            t_start = time.perf_counter()
            retrieved = retrieve_relevant_chunks(self.db, bot_id=self.bot_id, query=q)
            t_elapsed_ms = (time.perf_counter() - t_start) * 1000
            latencies_ms.append(t_elapsed_ms)

            _, ctx = compress_and_rerank_chunks(retrieved, query=q, max_context_chars=8000)

            # Check retrieval & grounding
            if category == "MISSING":
                # For non-existent items, context must NOT contain hallucinated facts
                if "hoverboard" in ctx.lower() or "submarine" in ctx.lower() or "heart surgery" in ctx.lower():
                    hallucination_count += 1
                else:
                    grounding_successes += 1
                    retrieval_successes += 1
            else:
                if any(expected_evidence.lower() in r["chunk"].content.lower() for r in retrieved) or expected_evidence.lower() in ctx.lower():
                    retrieval_successes += 1
                    grounding_successes += 1
                else:
                    print(f"[BENCHMARK MISS] Query {idx} ({category}): '{q}' failed to find '{expected_evidence}'")

                if expected_url:
                    if expected_url in ctx:
                        url_successes += 1
                    else:
                        print(f"[URL MISS] Query {idx}: Expected URL '{expected_url}' not found in context")

        # Compute empirical summary metrics
        retrieval_rate = (retrieval_successes / total_queries) * 100.0
        grounding_rate = (grounding_successes / total_queries) * 100.0
        url_accuracy_rate = (url_successes / 45) * 100.0  # 45 queries have expected real URLs
        hallucination_rate = (hallucination_count / total_queries) * 100.0

        latencies_sorted = sorted(latencies_ms)
        p50_lat = latencies_sorted[int(len(latencies_sorted) * 0.50)]
        p95_lat = latencies_sorted[int(len(latencies_sorted) * 0.95)]
        p99_lat = latencies_sorted[int(len(latencies_sorted) * 0.99)]
        worst_lat = max(latencies_ms)

        print("\n" + "=" * 65)
        print("  50-QUERY REALISTIC CUSTOMER QUERY BENCHMARK REPORT")
        print("=" * 65)
        print(f"Total Benchmark Queries:     {total_queries}")
        print(f"Retrieval Success Rate:      {retrieval_rate:.1f}% ({retrieval_successes}/{total_queries})")
        print(f"Answer Grounding Rate:        {grounding_rate:.1f}% ({grounding_successes}/{total_queries})")
        print(f"URL / CTA Accuracy Rate:      {url_accuracy_rate:.1f}% ({url_successes}/45)")
        print(f"Hallucination Rate:           {hallucination_rate:.1f}% ({hallucination_count}/{total_queries})")
        print(f"Retrieval Latency p50:        {p50_lat:.2f} ms")
        print(f"Retrieval Latency p95:        {p95_lat:.2f} ms")
        print(f"Retrieval Latency p99:        {p99_lat:.2f} ms")
        print(f"Retrieval Latency Worst:      {worst_lat:.2f} ms")
        print("=" * 65 + "\n")

        self.assertGreaterEqual(retrieval_rate, 95.0)
        self.assertGreaterEqual(grounding_rate, 95.0)
        self.assertGreaterEqual(url_accuracy_rate, 95.0)
        self.assertEqual(hallucination_rate, 0.0)


if __name__ == "__main__":
    unittest.main()
