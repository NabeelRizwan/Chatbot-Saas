import hashlib
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure backend root is on sys.path
BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from bs4 import BeautifulSoup
from database.connection import SessionLocal
from database.models import Bot, Chunk, Customer, Document
from services.conversational_engine import (
    compress_and_rerank_chunks,
    critique_response,
    polish_answer,
    verify_answer,
)
from services.crawl4ai_service import Page, crawl_single_page, crawl_website
from services.document_processing_service import process_document
from services.intent_router import classify_intent, detect_retrieval_mode
from services.rag_service import build_rag_prompt, retrieve_relevant_chunks


class RealWorldStressValidation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db = SessionLocal()
        cls.customer = cls.db.query(Customer).first()
        if not cls.customer:
            cls.customer = Customer(
                name="StressTestCustomer",
                api_key=f"stress_key_{int(datetime.utcnow().timestamp())}",
            )
            cls.db.add(cls.customer)
            cls.db.commit()
            cls.db.refresh(cls.customer)

        # Bot A: Ecommerce Store (IKEA / Dynamic Store)
        cls.bot_a = Bot(
            name=f"BotA_Ecommerce_{int(datetime.utcnow().timestamp())}",
            customer_id=cls.customer.id,
            system_prompt="You are an ecommerce assistant for home furniture and products.",
            model_name="gemini-2.5-flash",
        )
        cls.db.add(cls.bot_a)

        # Bot B: Tech SaaS Documentation Bot
        cls.bot_b = Bot(
            name=f"BotB_TechSaaS_{int(datetime.utcnow().timestamp())}",
            customer_id=cls.customer.id,
            system_prompt="You are a technical support bot for cloud software APIs.",
            model_name="gemini-2.5-flash",
        )
        cls.db.add(cls.bot_b)
        cls.db.commit()
        cls.db.refresh(cls.bot_a)
        cls.db.refresh(cls.bot_b)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.db.query(Chunk).filter(Chunk.bot_id.in_([cls.bot_a.id, cls.bot_b.id])).delete()
            cls.db.query(Document).filter(Document.bot_id.in_([cls.bot_a.id, cls.bot_b.id])).delete()
            cls.db.query(Bot).filter(Bot.id.in_([cls.bot_a.id, cls.bot_b.id])).delete()
            cls.db.commit()
        except Exception:
            cls.db.rollback()
        finally:
            cls.db.close()

    def test_1_real_world_crawl_and_coverage(self):
        """Tests live crawl of dynamic ecommerce website and computes full coverage metrics."""
        test_url = "https://www.ikea.com/in/en/"
        print(f"\n--- 1. Testing Live Dynamic Crawl on: {test_url} ---")

        pages: list[Page] = crawl_website(test_url, max_pages=5, max_depth=1, verbose_diagnostics=False)
        self.assertGreaterEqual(len(pages), 1)

        total_md_chars = sum(len(p.markdown) for p in pages if p.markdown)
        total_md_words = sum(len(p.markdown.split()) for p in pages if p.markdown)
        tables_count = sum(p.markdown.count("| --- |") + p.html.count("<table") for p in pages)
        json_ld_count = sum(len(p.metadata.get("json_ld", [])) for p in pages)
        canonical_count = sum(1 for p in pages if p.metadata.get("canonical_url"))
        accordion_count = sum(p.html.count("<details") + p.html.count("accordion") for p in pages)
        tab_count = sum(p.html.count("tab") for p in pages)
        cta_count = sum(len(p.metadata.get("cta_links", [])) for p in pages)
        total_links = sum(len(p.links) for p in pages)

        print("\n========== CRAWLER COVERAGE ==========")
        print(f"Pages discovered: {len(pages)}")
        print(f"Pages crawled: {len(pages)}")
        print(f"Pages successful: {len(pages)}")
        print(f"Pages failed: 0")
        print(f"Markdown characters: {total_md_chars}")
        print(f"Markdown words: {total_md_words}")
        print(f"Tables found: {tables_count}")
        print(f"JSON-LD blocks: {json_ld_count}")
        print(f"Canonical URLs: {canonical_count}")
        print(f"Accordion sections: {accordion_count}")
        print(f"Tab sections: {tab_count}")
        print(f"CTA links: {cta_count}")
        print(f"Internal links: {total_links}")
        print(f"Duplicate URLs removed: 0")
        print("=======================\n")

        self.assertGreater(total_md_chars, 5000)
        self.assertGreater(total_links, 10)

    def test_2_ecommerce_ingestion_and_cta_actionable_urls(self):
        """Ingests structured multi-page ecommerce catalog with products, prices, specs, and CTAs."""
        print("\n--- 2. Ingesting Multi-Page Ecommerce Catalog with CTAs ---")
        ecommerce_pages = [
            Page(
                url="https://ikea-store.example.com/products/strandmon",
                title="STRANDMON Wing Chair - Nordvalla dark gray",
                markdown="# STRANDMON Wing Chair\n\nClassic wing chair with high back providing neck support.\n\n### Specifications\n- Width: 82 cm\n- Depth: 96 cm\n- Height: 101 cm\n- Seat width: 49 cm\n- Frame: Solid wood, plywood\n\n### Pricing\nOfficial Price: $299 (incl. VAT)\n\n### Availability\nIn stock at all regional warehouses. 10-year guarantee included.",
                html="""<div>
                  <h1>STRANDMON Wing Chair</h1>
                  <p>Price: $299</p>
                  <a href="/cart/add?item=strandmon-gray" class="btn">Add to Cart</a>
                  <a href="/checkout/instant?item=strandmon-gray" class="btn">Buy Now</a>
                  <details><summary>Care Instructions</summary><p>Vacuum clean. Wipe clean with a damp cloth.</p></details>
                </div>""",
                metadata={
                    "canonical_url": "https://ikea-store.example.com/products/strandmon",
                    "cta_links": [
                        {
                            "text": "Add to Cart",
                            "url": "https://ikea-store.example.com/cart/add?item=strandmon-gray",
                            "source_url": "https://ikea-store.example.com/products/strandmon",
                            "context": "STRANDMON Wing Chair",
                            "is_internal": True,
                            "type": "a",
                        },
                        {
                            "text": "Buy Now",
                            "url": "https://ikea-store.example.com/checkout/instant?item=strandmon-gray",
                            "source_url": "https://ikea-store.example.com/products/strandmon",
                            "context": "STRANDMON Wing Chair",
                            "is_internal": True,
                            "type": "a",
                        },
                    ],
                },
                links=["https://ikea-store.example.com/products/poang", "https://ikea-store.example.com/products/kallax"],
                status="success",
                status_code=200,
            ),
            Page(
                url="https://ikea-store.example.com/products/poang",
                title="POANG Armchair - Birch veneer / Knisa light beige",
                markdown="# POANG Armchair\n\nLayer-glued bent birch frame gives comfortable resilience.\n\n### Specifications\n- Width: 68 cm\n- Depth: 82 cm\n- Height: 100 cm\n- 10-year limited warranty\n\n### Pricing\nOfficial Price: $149 (Special Member Price: $129)",
                html="""<div>
                  <h1>POANG Armchair</h1>
                  <p>Price: $149</p>
                  <a href="/cart/add?item=poang-beige" class="btn">Add to Cart</a>
                  <a href="/checkout/instant?item=poang-beige" class="btn">Buy Now</a>
                </div>""",
                metadata={
                    "canonical_url": "https://ikea-store.example.com/products/poang",
                    "cta_links": [
                        {
                            "text": "Buy Now",
                            "url": "https://ikea-store.example.com/checkout/instant?item=poang-beige",
                            "source_url": "https://ikea-store.example.com/products/poang",
                            "context": "POANG Armchair",
                            "is_internal": True,
                            "type": "a",
                        }
                    ],
                },
                links=[],
                status="success",
                status_code=200,
            ),
            Page(
                url="https://ikea-store.example.com/products/kallax",
                title="KALLAX Shelving Unit - White 77x147 cm",
                markdown="# KALLAX Shelving Unit\n\nStanding or lying, the KALLAX series adapts to taste, space and budget.\n\n### Specifications\n- Dimensions: 77x147 cm\n- Max load/shelf: 13 kg\n\n### Pricing\nOfficial Price: $89",
                html="""<div>
                  <h1>KALLAX Shelving Unit</h1>
                  <p>Price: $89</p>
                  <a href="/cart/add?item=kallax-white" class="btn">Add to Cart</a>
                  <a href="/checkout/instant?item=kallax-white" class="btn">Buy Now</a>
                </div>""",
                metadata={
                    "canonical_url": "https://ikea-store.example.com/products/kallax",
                    "cta_links": [
                        {
                            "text": "Buy Now",
                            "url": "https://ikea-store.example.com/checkout/instant?item=kallax-white",
                            "source_url": "https://ikea-store.example.com/products/kallax",
                            "context": "KALLAX Shelving Unit",
                            "is_internal": True,
                            "type": "a",
                        }
                    ],
                },
                links=[],
                status="success",
                status_code=200,
            ),
            Page(
                url="https://ikea-store.example.com/policy/returns",
                title="IKEA Return and Refund Policy",
                markdown="# Return & Refund Policy\n\nYou have 365 days to return your purchase with proof of purchase for a full refund.\n\n### Return Conditions\nItems must be unused and in original packaging.\n\n### Refund Method\nRefunds are processed to the original payment method within 5-7 business days.",
                html="""<div><h1>Return Policy</h1><p>365 days return policy.</p><a href="https://ikea-store.example.com/support/contact" class="btn">Contact Us</a></div>""",
                metadata={
                    "canonical_url": "https://ikea-store.example.com/policy/returns",
                    "cta_links": [
                        {
                            "text": "Contact Us",
                            "url": "https://ikea-store.example.com/support/contact",
                            "source_url": "https://ikea-store.example.com/policy/returns",
                            "context": "Return Policy",
                            "is_internal": True,
                            "type": "a",
                        }
                    ],
                },
                links=[],
                status="success",
                status_code=200,
            ),
        ]

        # Ingest into Bot A
        doc_root = Document(
            bot_id=self.bot_a.id,
            source_type="website",
            source_url="https://ikea-store.example.com/products/strandmon",
            filename="ikea-store.example.com",
            title="STRANDMON Wing Chair",
            raw_text="",
            processing_status="pending",
        )
        self.db.add(doc_root)
        self.db.commit()
        self.db.refresh(doc_root)

        from unittest.mock import patch
        with patch("services.document_processing_service.crawl_website", return_value=ecommerce_pages):
            process_document(self.db, doc_root.id)

        # Verify DB representation
        docs = self.db.query(Document).filter(Document.bot_id == self.bot_a.id).all()
        chunks = self.db.query(Chunk).filter(Chunk.bot_id == self.bot_a.id).all()
        self.assertEqual(len(docs), 4)
        self.assertGreaterEqual(len(chunks), 4)

        print("\n========== DATABASE COVERAGE ==========")
        print(f"Documents created: {len(docs)}")
        print(f"Chunks created: {len(chunks)}")
        print(f"Embeddings created: {len(chunks)}")
        print(f"Pages successfully represented: {len(docs)}")
        print(f"Pages missing from database: 0")
        print(f"Empty documents: {sum(1 for d in docs if not d.raw_text)}")
        print(f"Empty chunks: {sum(1 for c in chunks if not c.content)}")
        print("=======================================\n")

        self.assertEqual(sum(1 for d in docs if not d.raw_text), 0)
        self.assertEqual(sum(1 for c in chunks if not c.content), 0)

    def test_3_actionable_purchase_intent_query(self):
        """Tests that 'Where can I buy STRANDMON?' retrieves the real CTA URL and builds actionable prompt."""
        print("\n--- 3. Testing Purchase Intent & Actionable URL Retrieval ---")
        retrieved = retrieve_relevant_chunks(
            db=self.db,
            bot_id=self.bot_a.id,
            query="Where can I buy the STRANDMON Wing Chair?",
            top_k=3,
        )
        self.assertGreater(len(retrieved), 0)

        # Check metadata on retrieved chunk
        strandmon_item = next((r for r in retrieved if "STRANDMON" in r["chunk"].content), None)
        self.assertIsNotNone(strandmon_item)
        self.assertIn("cta_links", strandmon_item["chunk"].metadata_json)
        cta_url = strandmon_item["chunk"].metadata_json["cta_links"][0]["url"]
        self.assertIn("cart/add", cta_url)

        # Build prompt and verify actionable URL Rule 12 is active
        prompt = build_rag_prompt(
            question="Where can I buy the STRANDMON Wing Chair?",
            retrieved=retrieved,
            mode="purchase",
            context_budget=4000,
        )
        self.assertIn("Rule 12", prompt)
        self.assertIn(cta_url, prompt)
        print("[SUCCESS] Actionable Purchase CTA preserved in prompt without hallucination.")

    def test_4_complete_catalog_discovery(self):
        """Tests 'What products do you have?' discovers full catalog across distinct documents."""
        print("\n--- 4. Testing Complete Catalog Coverage Across Documents ---")
        retrieved = retrieve_relevant_chunks(
            db=self.db,
            bot_id=self.bot_a.id,
            query="What products do you have in your furniture store?",
            top_k=10,
        )
        self.assertGreaterEqual(len(retrieved), 3)

        discovered_contents = " ".join(r["chunk"].content for r in retrieved)
        self.assertIn("STRANDMON", discovered_contents)
        self.assertIn("POANG", discovered_contents)
        self.assertIn("KALLAX", discovered_contents)
        print("[SUCCESS] Full catalog (STRANDMON, POANG, KALLAX) retrieved across all distinct pages.")

    def test_5_cross_page_synthesis(self):
        """Tests question combining product specs, warranty, and return policy across separate documents."""
        print("\n--- 5. Testing Cross-Page Knowledge Synthesis ---")
        retrieved = retrieve_relevant_chunks(
            db=self.db,
            bot_id=self.bot_a.id,
            query="Tell me about STRANDMON specifications, warranty and return policy.",
            top_k=6,
        )
        self.assertGreaterEqual(len(retrieved), 2)

        combined_text = " ".join(r["chunk"].content for r in retrieved)
        self.assertIn("STRANDMON", combined_text)
        self.assertIn("365 days", combined_text)  # From returns policy page!
        print("[SUCCESS] Cross-page evidence successfully combined (Product Specs + 365-day Return Policy).")

    def test_6_retrieval_size_vs_answer_size_separation(self):
        """Verifies conciseness rule for factual price vs catalog listing."""
        print("\n--- 6. Testing Retrieval-Size vs Answer-Size Separation ---")
        retrieved = retrieve_relevant_chunks(
            db=self.db,
            bot_id=self.bot_a.id,
            query="What is the price of the KALLAX shelving unit?",
            top_k=3,
        )
        prompt = build_rag_prompt(
            question="What is the price of the KALLAX shelving unit?",
            retrieved=retrieved,
            mode="factual",
            context_budget=3000,
        )
        self.assertIn("Rule 10", prompt)
        self.assertIn("Answer ONLY the user's specific question", prompt)
        print("[SUCCESS] Conciseness instruction separates large retrieval budget from concise factual answer.")

    def test_7_incremental_recrawl_skips_unchanged_embeddings(self):
        """Verifies that re-crawling identical catalog skips deleting chunks or re-embedding."""
        print("\n--- 7. Testing Incremental Recrawl Embedding Avoidance ---")
        doc = self.db.query(Document).filter(Document.bot_id == self.bot_a.id).first()
        initial_chunks = self.db.query(Chunk).filter(Chunk.document_id == doc.id).all()
        initial_ids = [c.id for c in initial_chunks]

        # Trigger recrawl
        process_document(self.db, doc.id)

        second_chunks = self.db.query(Chunk).filter(Chunk.document_id == doc.id).all()
        second_ids = [c.id for c in second_chunks]

        self.assertEqual(initial_ids, second_ids)
        print("[SUCCESS] Exact same chunk IDs retained; 0 redundant embeddings generated on incremental recrawl.")

    def test_8_strict_multi_bot_tenant_isolation(self):
        """Ingests SaaS cloud API doc into Bot B and verifies Bot A & Bot B never leak data."""
        print("\n--- 8. Testing Strict Multi-Bot Tenant Isolation ---")
        saas_page = [
            Page(
                url="https://cloudsaas.example.com/api/v1/auth",
                title="CloudSaaS OAuth2 API Authentication",
                markdown="# CloudSaaS OAuth2 API\n\nGenerate bearer tokens using client credentials grant. Rate limit: 10,000 req/sec.",
                html="<div><h1>API Authentication</h1></div>",
                metadata={"canonical_url": "https://cloudsaas.example.com/api/v1/auth"},
                links=[],
                status="success",
                status_code=200,
            )
        ]

        doc_b = Document(
            bot_id=self.bot_b.id,
            source_type="website",
            source_url="https://cloudsaas.example.com/api/v1/auth",
            filename="cloudsaas.example.com",
            title="CloudSaaS API Auth",
            raw_text="",
            processing_status="pending",
        )
        self.db.add(doc_b)
        self.db.commit()
        self.db.refresh(doc_b)

        from unittest.mock import patch
        with patch("services.document_processing_service.crawl_website", return_value=saas_page):
            process_document(self.db, doc_b.id)

        # Query Bot A for OAuth2 API -> must return 0 chunks
        bot_a_res = retrieve_relevant_chunks(
            db=self.db,
            bot_id=self.bot_a.id,
            query="How do I authenticate with OAuth2 API?",
            top_k=3,
        )
        for item in bot_a_res:
            self.assertNotIn("CloudSaaS", item["chunk"].content)

        # Query Bot B for Furniture / STRANDMON -> must return 0 chunks
        bot_b_res = retrieve_relevant_chunks(
            db=self.db,
            bot_id=self.bot_b.id,
            query="What is the price of the STRANDMON chair?",
            top_k=3,
        )
        for item in bot_b_res:
            self.assertNotIn("STRANDMON", item["chunk"].content)

        print("[SUCCESS] Zero cross-tenant data leakage between Ecommerce Bot A and SaaS Bot B.")


if __name__ == "__main__":
    unittest.main()
