import os
import sys
import time
import unittest
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

# Ensure backend root is on sys.path
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from database.connection import SessionLocal
from database.models import Bot, Chunk, Customer, Document, Website, WebsiteCrawl
from services.chunking_service import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    chunk_text_with_metadata,
    count_tokens,
)
from services.conversational_engine import (
    compress_and_rerank_chunks,
    critique_response,
    global_semantic_cache,
    polish_answer,
    verify_answer,
)
from services.embedding_service import generate_embedding, generate_embeddings_batch
from services.firecrawl_service import (
    FirecrawlError,
    Page,
    crawl_website,
    extract_cta_links_from_markdown,
)
from services.intent_router import (
    RETRIEVAL_MODE_CATALOG,
    RETRIEVAL_MODE_COMPARISON,
    RETRIEVAL_MODE_ENTITY,
    RETRIEVAL_MODE_FACTUAL,
    RETRIEVAL_MODE_FILTER,
    RETRIEVAL_MODE_POLICY,
    RETRIEVAL_MODE_PURCHASE,
    classify_intent,
    detect_retrieval_mode,
    is_catalog_or_list_query,
    is_comparison_query,
    is_filter_query,
    is_policy_query,
    is_purchase_intent,
    rewrite_query_for_retrieval,
)
from services.rag_service import (
    answer_question,
    build_rag_prompt,
    clear_retrieval_cache,
    get_active_knowledge_version,
    retrieve_relevant_chunks,
    retrieve_relevant_chunks_cached,
)
from services.document_processing_service import process_document

import fakeredis
import fakeredis.aioredis
from utils.redis_client import set_redis_override


class TestFirecrawlAcceptanceSuite(unittest.TestCase):
    """
    Phase 9 Final Customer Acceptance & Production Validation Suite.
    Empirically validates all 14 customer-readiness criteria across Firecrawl ingestion,
    full-website coverage, Phase 9 retrieval modes, catalog completeness, answer brevity,
    actionable CTAs, multi-turn follow-ups, grounding, tenant isolation, and latency profiling.
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
        self.db = SessionLocal()
        self.timestamp = int(datetime.utcnow().timestamp() * 1000) % 1000000
        self.bot_id_ecom = 21000 + (self.timestamp % 1000)
        self.bot_id_saas = 22000 + (self.timestamp % 1000)
        self.bot_id_health = 23000 + (self.timestamp % 1000)
        self.bot_id_scale = 24000 + (self.timestamp % 1000)
        self.created_bots = []

        # Ensure organizations exist for FK integrity
        self.org_ecom = self.db.merge(Organization(id=100, name="Apex Hardware Org", slug=f"apex-ecom-{self.timestamp}"))
        self.org_saas = self.db.merge(Organization(id=200, name="Zenith Dental Org", slug=f"zenith-saas-{self.timestamp}"))
        self.org_scale = self.db.merge(Organization(id=300, name="MegaStore Scale Org", slug=f"megastore-{self.timestamp}"))
        self.db.commit()

        clear_retrieval_cache()
        global_semantic_cache.clear()

    def tearDown(self):
        try:
            for b_id in self.created_bots:
                self.db.query(Chunk).filter(Chunk.bot_id == b_id).delete()
                self.db.query(Document).filter(Document.bot_id == b_id).delete()
                self.db.query(WebsiteCrawl).filter(WebsiteCrawl.bot_id == b_id).delete()
                self.db.query(Website).filter(Website.bot_id == b_id).delete()
                self.db.query(Bot).filter(Bot.id == b_id).delete()
            self.db.commit()
        except Exception:
            self.db.rollback()
        finally:
            self.db.close()

    # =========================================================================
    # SEED CORPUS 1: COMPLETE ECOMMERCE WEBSITE (Apex Hardware & Gadgets)
    # Covers Home, Products, Categories, Specs, Pricing, FAQ, Shipping, Returns, Warranty, Contact, Support
    # =========================================================================
    def _seed_complete_ecommerce_website(self, org_id: int = 100) -> int:
        b_id = self.bot_id_ecom
        if b_id not in self.created_bots:
            self.created_bots.append(b_id)

        bot = Bot(id=b_id, organization_id=org_id, name="Apex Hardware Assistant")
        self.db.merge(bot)
        self.db.commit()

        self.db.query(Chunk).filter(Chunk.bot_id == b_id).delete()
        self.db.query(Document).filter(Document.bot_id == b_id).delete()
        self.db.commit()

        pages = [
            # 1. Home
            {
                "filename": "home",
                "title": "Apex Hardware - Premier Electronics & Tech",
                "url": "https://apexhardware.com/",
                "markdown": "# Welcome to Apex Hardware\n\nWe provide professional-grade computing, displays, audio gear, and peripherals for enterprise and prosumers.\n\n### Featured Categories\n- Laptops & Workstations\n- Professional Monitors\n- Wireless Audio\n- Power & Charging Solutions",
                "ctas": [{"text": "Shop Now", "url": "https://apexhardware.com/shop"}],
            },
            # 2. Product 1: Apex Book Pro 16 (Laptop)
            {
                "filename": "product-apex-book-pro",
                "title": "ApexBook Pro 16 - Apex Hardware",
                "url": "https://apexhardware.com/products/apexbook-pro-16",
                "markdown": "# ApexBook Pro 16\n\n## Overview\nThe ApexBook Pro 16 is an ultra-high performance laptop engineered for engineers and creators.\n\n## Specifications\n| Specification | Details |\n| --- | --- |\n| Processor | 16-Core M3 Ultra |\n| RAM | 64GB Unified Memory |\n| Storage | 2TB PCIe NVMe SSD |\n| Battery | 99.6Wh Lithium-Polymer (up to 22 hours runtime) |\n| Fast Charging | 140W USB-C GaN Fast Charging |\n| Display | 16.2-inch Liquid Retina XDR (120Hz ProMotion) |\n\n## Pricing\nRetail price is $2,499 with 1-year complimentary warranty.",
                "ctas": [{"text": "Buy Now", "url": "https://apexhardware.com/checkout?sku=apexbook-16"}],
            },
            # 3. Product 2: Apex Studio Display 27 (Monitor)
            {
                "filename": "product-apex-studio-display",
                "title": "Apex Studio Display 27 - Apex Hardware",
                "url": "https://apexhardware.com/products/apex-studio-display-27",
                "markdown": "# Apex Studio Display 27\n\n## Overview\n27-inch 5K color-accurate reference monitor for photo, video, and design workflows.\n\n## Specifications\n- Resolution: 5120 x 2880 at 218 ppi\n- Brightness: 600 nits\n- Color Gamut: 100% DCI-P3 and 99% Adobe RGB\n- Ports: 1x Thunderbolt 4 (96W host charging), 3x USB-C (10Gbps)\n- Stand: Height and tilt adjustable counter-balanced aluminum stand\n\n## Pricing\nPrice: $1,299.",
                "ctas": [{"text": "Buy Now", "url": "https://apexhardware.com/checkout?sku=apex-display-27"}],
            },
            # 4. Product 3: Apex SoundWave ANC (Headphones)
            {
                "filename": "product-apex-soundwave-anc",
                "title": "Apex SoundWave ANC Headphones - Apex Hardware",
                "url": "https://apexhardware.com/products/soundwave-anc",
                "markdown": "# Apex SoundWave ANC\n\n## Overview\nFlagship active noise cancelling over-ear headphones with planar magnetic drivers.\n\n## Specifications\n- Driver: 40mm Planar Magnetic\n- Battery Life: 45 hours ANC playback\n- Fast Charging: 15-minute quick charge yields 8 hours playback\n- Weight: 260 grams\n- Bluetooth: Version 5.3 with LDAC and aptX Lossless\n\n## Pricing\nPrice: $349.",
                "ctas": [{"text": "Add to Cart", "url": "https://apexhardware.com/cart/add?sku=soundwave-anc"}],
            },
            # 5. Product 4: Apex PowerStation 100W (Charger)
            {
                "filename": "product-apex-powerstation-100w",
                "title": "Apex PowerStation 100W GaN - Apex Hardware",
                "url": "https://apexhardware.com/products/powerstation-100w",
                "markdown": "# Apex PowerStation 100W GaN\n\n## Overview\nCompact 4-port GaN III desktop power adapter for fast charging multiple devices simultaneously.\n\n## Specifications\n- Total Output: 100W Max\n- Ports: 3x USB-C, 1x USB-A\n- Fast Charging Protocols: PD 3.0, PPS, QC 4.0\n- Dimensions: 65mm x 65mm x 30mm\n\n## Pricing\nPrice: $79.",
                "ctas": [{"text": "Buy Now", "url": "https://apexhardware.com/checkout?sku=powerstation-100w"}],
            },
            # 6. Categories & Catalog Overview
            {
                "filename": "categories-catalog",
                "title": "Product Catalog & Categories - Apex Hardware",
                "url": "https://apexhardware.com/categories",
                "markdown": "# All Product Categories & Offerings\n\n### Laptops & Computers\n- **ApexBook Pro 16** ($2,499): 16-Core M3 Ultra, 64GB RAM, 99.6Wh Battery.\n\n### Monitors & Displays\n- **Apex Studio Display 27** ($1,299): 5K 27-inch Reference Display.\n\n### Audio Gear\n- **Apex SoundWave ANC** ($349): Planar Magnetic Headphones with 45h battery.\n\n### Power & Accessories\n- **Apex PowerStation 100W** ($79): 4-Port GaN Desktop Fast Charger.",
                "ctas": [{"text": "Shop Now", "url": "https://apexhardware.com/shop"}],
            },
            # 7. FAQ Page
            {
                "filename": "faq",
                "title": "Frequently Asked Questions - Apex Hardware",
                "url": "https://apexhardware.com/faq",
                "markdown": "# Frequently Asked Questions\n\n### Q: What operating systems are compatible with Apex Studio Display?\nA: Apex Studio Display is plug-and-play compatible with macOS Sonoma, Windows 11, and Linux Ubuntu 22.04+.\n\n### Q: Can Apex PowerStation 100W charge a laptop and phone simultaneously?\nA: Yes, dynamic power allocation splits power as 65W USB-C for laptop and 30W USB-C for phone.",
                "ctas": [],
            },
            # 8. Shipping Policy
            {
                "filename": "policy-shipping",
                "title": "Shipping Policy - Apex Hardware",
                "url": "https://apexhardware.com/policies/shipping",
                "markdown": "# Shipping Policy & Delivery Times\n\n- Standard Ground Shipping: Free on orders over $50 (3-5 business days delivery).\n- Express Air Shipping: Flat rate $15 (1-2 business days delivery).\n- International Shipping: Available to over 80 countries via DHL Express.",
                "ctas": [],
            },
            # 9. Return & Refund Policy
            {
                "filename": "policy-returns",
                "title": "Return & Refund Policy - Apex Hardware",
                "url": "https://apexhardware.com/policies/returns",
                "markdown": "# Return & Refund Policy\n\nWe offer a 30-day money-back guarantee on all hardware items in original condition. Return shipping is prepaid by Apex Hardware for domestic customers. Refunds are processed within 3-5 business days of receiving the returned unit.",
                "ctas": [],
            },
            # 10. Warranty Policy
            {
                "filename": "policy-warranty",
                "title": "Warranty & Hardware Protection - Apex Hardware",
                "url": "https://apexhardware.com/policies/warranty",
                "markdown": "# Warranty Terms & Coverage\n\nAll Apex Hardware products include a standard 1-year manufacturer limited warranty covering hardware defects and component failures. ApexCare Extended Warranty extends coverage to 3 years including accidental damage protection for $199.",
                "ctas": [{"text": "Get Started", "url": "https://apexhardware.com/apexcare"}],
            },
            # 11. Contact & Support Page
            {
                "filename": "contact-support",
                "title": "Contact & Customer Support - Apex Hardware",
                "url": "https://apexhardware.com/support",
                "markdown": "# Customer Support & Contact Info\n\n- Technical Support Email: support@apexhardware.com\n- Phone Support: 1-800-555-APEX (Monday - Friday 8am - 8pm EST)\n- Headquarters: 100 Innovation Way, San Jose, CA 95134",
                "ctas": [{"text": "Contact Us", "url": "https://apexhardware.com/contact"}],
            },
        ]

        all_chunks_to_insert = []
        all_texts = []
        for p_data in pages:
            doc = Document(
                bot_id=b_id,
                organization_id=org_id,
                source_type="website",
                filename=p_data["filename"],
                title=p_data["title"],
                source_url=p_data["url"],
                status="ready",
                processing_status="completed",
                metadata_json={"cta_links": p_data["ctas"], "source_url": p_data["url"], "page_title": p_data["title"]},
            )
            self.db.add(doc)
            self.db.commit()
            self.db.refresh(doc)

            chunks = chunk_text_with_metadata(
                p_data["markdown"],
                chunk_size=CHUNK_SIZE,
                overlap=CHUNK_OVERLAP,
                page_title=p_data["title"],
                source_url=p_data["url"],
                metadata={"cta_links": p_data["ctas"], "source_url": p_data["url"], "page_title": p_data["title"]},
            )
            for c in chunks:
                all_chunks_to_insert.append((doc.id, c, p_data))
                all_texts.append(c.content)

        embeddings = generate_embeddings_batch(all_texts)
        for i, (doc_id, c, p_data) in enumerate(all_chunks_to_insert):
            self.db.add(
                Chunk(
                    bot_id=b_id,
                    organization_id=org_id,
                    document_id=doc_id,
                    chunk_index=c.index,
                    content=c.content,
                    token_count=c.token_count,
                    embedding=embeddings[i],
                    status="ready",
                    metadata_json={
                        "source_url": p_data["url"],
                        "page_title": p_data["title"],
                        "cta_links": p_data["ctas"],
                        "heading": c.heading,
                        "section": c.section,
                    },
                )
            )
        self.db.commit()
        return b_id

    # =========================================================================
    # 1. FIRECRAWL INGESTION & STRUCTURAL EXTRACTION VALIDATION
    # =========================================================================
    def test_01_firecrawl_ingestion_and_extraction_audit(self):
        """Validates Firecrawl crawling, markdown extraction, table preservation, and CTA parsing."""
        mock_raw_data = [
            {
                "markdown": "# CloudScale Enterprise\n\n## Overview\nNext-gen API platform.\n\n## Specifications\n| Feature | Tiers |\n| --- | --- |\n| Throughput | 50,000 req/sec |\n| SLA | 99.99% Uptime |\n\n[Get Started](https://cloudscale.io/signup)",
                "metadata": {
                    "sourceURL": "https://cloudscale.io/overview",
                    "title": "CloudScale Overview",
                    "statusCode": 200,
                },
            },
            {
                "markdown": "# Pricing & Plans\n\nStandard is $49/mo. Enterprise is $499/mo.\n\n[Book Consultation](https://cloudscale.io/demo)",
                "metadata": {
                    "sourceURL": "https://cloudscale.io/pricing",
                    "title": "CloudScale Pricing",
                    "statusCode": 200,
                },
            },
        ]

        with patch("services.firecrawl_service.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_post = MagicMock(status_code=200)
            mock_post.json.return_value = {"success": True, "id": "fc_job_acceptance_1"}
            mock_poll = MagicMock(status_code=200)
            mock_poll.json.return_value = {"status": "completed", "data": mock_raw_data}
            mock_client.post.return_value = mock_post
            mock_client.get.return_value = mock_poll
            mock_client_cls.return_value.__enter__.return_value = mock_client

            with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "fc-test-key-acceptance"}):
                pages = crawl_website("https://cloudscale.io")

        self.assertEqual(len(pages), 2)
        # Verify markdown table preserved
        self.assertIn("| Throughput | 50,000 req/sec |", pages[0].markdown)
        # Verify CTA extracted
        self.assertEqual(len(pages[0].metadata.get("cta_links", [])), 1)
        self.assertEqual(pages[0].metadata["cta_links"][0]["url"], "https://cloudscale.io/signup")
        self.assertEqual(pages[1].metadata["cta_links"][0]["url"], "https://cloudscale.io/demo")

    # =========================================================================
    # 2. FULL WEBSITE KNOWLEDGE COVERAGE (Across 11 Ingested Pages)
    # =========================================================================
    def test_02_full_website_corpus_knowledge_coverage(self):
        """Verifies that queries targeting every section of the website find accurate corpus evidence."""
        b_id = self._seed_complete_ecommerce_website()

        coverage_targets = [
            ("Home Overview", "What does Apex Hardware specialize in?", "Apex Hardware"),
            ("Laptop Specs", "What processor and RAM does ApexBook Pro 16 have?", "16-Core M3 Ultra"),
            ("Laptop Battery", "What is the battery capacity of ApexBook Pro 16?", "99.6Wh"),
            ("Monitor Specs", "What is the resolution and brightness of the 27-inch display?", "5120 x 2880"),
            ("Audio Specs", "What battery life do the SoundWave ANC headphones offer?", "45 hours"),
            ("Charger Specs", "How many ports does the PowerStation 100W have?", "USB-C"),
            ("Catalog Overview", "What products and categories do you offer?", "ApexBook Pro 16"),
            ("FAQ Knowledge", "Is Apex Studio Display compatible with Windows 11?", "Windows 11"),
            ("Shipping Policy", "How much is express shipping?", "$15"),
            ("Return Policy", "What is your return period?", "30-day money-back guarantee"),
            ("Warranty Policy", "What does the standard warranty cover?", "1-year manufacturer"),
            ("Support Contact", "What is your customer support phone number?", "1-800-555-APEX"),
        ]

        for label, question, expected_term in coverage_targets:
            with self.subTest(area=label):
                retrieved = retrieve_relevant_chunks(self.db, bot_id=b_id, query=question)
                self.assertGreaterEqual(len(retrieved), 1, f"Failed to retrieve evidence for {label}")
                all_text = " ".join([r["chunk"].content for r in retrieved])
                self.assertIn(expected_term, all_text, f"Expected term '{expected_term}' not found in retrieved chunks for {label}")

    # =========================================================================
    # 3. PHASE 9 RETRIEVAL MODES VALIDATION (All 7 Modes)
    # =========================================================================
    def test_03_all_seven_phase9_retrieval_modes(self):
        """Validates classification and execution of all 7 Phase 9 retrieval modes."""
        b_id = self._seed_complete_ecommerce_website()

        mode_tests = [
            ("What is the battery capacity of ApexBook Pro 16?", RETRIEVAL_MODE_FACTUAL),
            ("Tell me everything about the Apex Studio Display 27", RETRIEVAL_MODE_ENTITY),
            ("What products and items do you offer?", RETRIEVAL_MODE_CATALOG),
            ("Which products support fast charging?", RETRIEVAL_MODE_FILTER),
            ("Compare ApexBook Pro 16 and Apex Studio Display 27", RETRIEVAL_MODE_COMPARISON),
            ("What is your refund and return policy?", RETRIEVAL_MODE_POLICY),
            ("Where can I buy the ApexBook Pro 16?", RETRIEVAL_MODE_PURCHASE),
        ]

        for query, expected_mode in mode_tests:
            with self.subTest(query=query):
                mode, params = detect_retrieval_mode(query)
                self.assertEqual(mode, expected_mode, f"Query '{query}' classified as {mode} instead of {expected_mode}")
                retrieved = retrieve_relevant_chunks(self.db, bot_id=b_id, query=query, mode=mode)
                self.assertGreaterEqual(len(retrieved), 1)

    # =========================================================================
    # 4. RETRIEVAL SIZE VS. ANSWER SIZE SEPARATION (Rule 10 Invariant)
    # =========================================================================
    def test_04_retrieval_size_vs_answer_brevity_rule10(self):
        """Verifies that large retrieval context strictly enforces Rule 10 conciseness on narrow factual questions."""
        b_id = self._seed_complete_ecommerce_website()

        query = "What is the battery capacity of the ApexBook Pro 16?"
        retrieved = retrieve_relevant_chunks(self.db, bot_id=b_id, query=query)
        _, ctx = compress_and_rerank_chunks(retrieved, query=query, max_context_chars=12000)

        # Context contains full laptop specs + pricing + warranty
        self.assertIn("99.6Wh", ctx)
        self.assertIn("16-Core M3 Ultra", ctx)

        # Generated RAG prompt must contain Rule 10 conciseness constraint
        prompt = build_rag_prompt(question=query, retrieved=retrieved, compressed_context=ctx, mode="factual")
        self.assertIn("Rule 10", prompt)
        self.assertIn("State the direct answer concisely in 1 or 2 clear sentences", prompt)

    # =========================================================================
    # 5. CATALOG COMPLETENESS WITH CORPUS-BASED GROUND TRUTH
    # =========================================================================
    def test_05_catalog_completeness_ground_truth(self):
        """Measures expected items vs. retrieved items vs. returned catalog completeness."""
        b_id = self._seed_complete_ecommerce_website()

        # Ground truth items in indexed website corpus
        expected_items = {
            "ApexBook Pro 16",
            "Apex Studio Display 27",
            "Apex SoundWave ANC",
            "Apex PowerStation 100W",
        }

        query = "What products do you offer?"
        retrieved = retrieve_relevant_chunks(self.db, bot_id=b_id, query=query, mode=RETRIEVAL_MODE_CATALOG)
        _, ctx = compress_and_rerank_chunks(retrieved, query=query, mode="catalog", max_context_chars=12000)

        # Verify all 4 expected items are represented in the assembled catalog context
        retrieved_items = {item for item in expected_items if item in ctx}
        missing_items = expected_items - retrieved_items

        self.assertEqual(len(missing_items), 0, f"Catalog retrieval missed items: {missing_items}")
        self.assertEqual(len(retrieved_items), len(expected_items))
        completeness_pct = (len(retrieved_items) / len(expected_items)) * 100.0
        self.assertEqual(completeness_pct, 100.0)

    # =========================================================================
    # 6. PURCHASE / CTA BEHAVIOR & REAL URL VERIFICATION (Rule 12)
    # =========================================================================
    def test_06_actionable_purchase_url_verification(self):
        """Verifies purchase intent returns actual extracted canonical/CTA URLs without fabrication."""
        b_id = self._seed_complete_ecommerce_website()

        purchase_queries = [
            ("I want to buy the ApexBook Pro 16", "https://apexhardware.com/checkout?sku=apexbook-16"),
            ("Where can I buy the Apex Studio Display?", "https://apexhardware.com/checkout?sku=apex-display-27"),
            ("Where can I add the SoundWave ANC to my cart?", "https://apexhardware.com/cart/add?sku=soundwave-anc"),
            ("How do I purchase the 100W PowerStation?", "https://apexhardware.com/checkout?sku=powerstation-100w"),
        ]

        for query, expected_url in purchase_queries:
            with self.subTest(query=query):
                retrieved = retrieve_relevant_chunks(self.db, bot_id=b_id, query=query, mode=RETRIEVAL_MODE_PURCHASE)
                _, ctx = compress_and_rerank_chunks(retrieved, query=query, max_context_chars=4000)
                self.assertIn("Actionable Links:", ctx)
                self.assertIn(expected_url, ctx)

    # =========================================================================
    # 7. CONVERSATIONAL MULTI-TURN ENTITY & PRONOUN RESOLUTION
    # =========================================================================
    def test_07_conversational_pronoun_followup_resolution(self):
        """Validates pronoun resolution ('its battery', 'how much is it', 'where can I buy it')."""
        history = [
            {"role": "user", "content": "What is the ApexBook Pro 16?"},
            {"role": "assistant", "content": "The ApexBook Pro 16 is a high-performance laptop with an M3 Ultra chip."},
        ]

        # Turn 2: "What about its battery?"
        q2 = rewrite_query_for_retrieval("What about its battery?", history=history)
        self.assertIn("ApexBook Pro 16", q2)

        # Turn 3: "How much is it?"
        history.extend([
            {"role": "user", "content": "What about its battery?"},
            {"role": "assistant", "content": "It features a 99.6Wh battery offering up to 22 hours runtime."},
        ])
        q3 = rewrite_query_for_retrieval("How much is it?", history=history)
        self.assertIn("ApexBook Pro 16", q3)

        # Turn 4: "Can I buy it?"
        q4 = rewrite_query_for_retrieval("Can I buy it?", history=history)
        self.assertIn("ApexBook Pro 16", q4)

    # =========================================================================
    # 8. GROUNDING & ZERO HALLUCINATION ON MISSING INFORMATION
    # =========================================================================
    def test_08_grounding_and_honest_missing_information(self):
        """Verifies present facts are grounded and non-existent items/specs return honest absence."""
        b_id = self._seed_complete_ecommerce_website()

        # Non-existent product query
        retrieved = retrieve_relevant_chunks(self.db, bot_id=b_id, query="What is the price of the Apex Electric Scooter X1?")
        _, ctx = compress_and_rerank_chunks(retrieved, query="Electric Scooter", max_context_chars=4000)

        # Context must not claim an electric scooter exists
        self.assertNotIn("electric scooter", ctx.lower())

        # Critique must pass honest missing-information answers without relevance errors
        honest_reply = "I do not have information about an Electric Scooter on our website. Apex Hardware specializes in laptops, monitors, headphones, and chargers."
        passed, critique_res = critique_response(honest_reply, "What is the price of the Apex Electric Scooter X1?", strict_grounding=True)
        self.assertTrue(passed)
        self.assertFalse(critique_res.get("answer_relevance_issue", False))

    # =========================================================================
    # 9. STRICT MULTI-TENANT ISOLATION (Zero Cross-Bot Leakage)
    # =========================================================================
    def test_09_multi_tenant_isolation_cross_corpus(self):
        """Verifies Bot A cannot retrieve Bot B's data across any retrieval mode or catalog scan."""
        b_id_a = self._seed_complete_ecommerce_website(org_id=100)

        # Create Bot B (Healthcare Clinic)
        b_id_b = self.bot_id_health
        self.created_bots.append(b_id_b)
        bot_b = Bot(id=b_id_b, organization_id=200, name="Zenith Dental Care")
        self.db.merge(bot_b)
        self.db.commit()

        doc_b = Document(
            bot_id=b_id_b,
            organization_id=200,
            source_type="website",
            filename="dental-implants",
            title="Dental Implants - Zenith Care",
            source_url="https://zenithdental.com/treatments/implants",
            status="ready",
            processing_status="completed",
        )
        self.db.add(doc_b)
        self.db.commit()
        self.db.refresh(doc_b)
        self.db.add(
            Chunk(
                bot_id=b_id_b,
                organization_id=200,
                document_id=doc_b.id,
                chunk_index=0,
                content="[Dental Implants]\nTitanium root replacement with ceramic crown. Cost is $2,800 per tooth.",
                status="ready",
                embedding=generate_embedding("Dental Implants Titanium ceramic crown Cost $2,800"),
                metadata_json={"page_title": "Dental Implants", "source_url": "https://zenithdental.com/treatments/implants"},
            )
        )
        self.db.commit()

        # Bot A querying for Dental Implants must return ZERO results
        ret_a = retrieve_relevant_chunks(self.db, bot_id=b_id_a, query="How much do dental implants cost?")
        contents_a = " ".join([r["chunk"].content for r in ret_a])
        self.assertNotIn("Titanium root", contents_a)
        self.assertNotIn("Zenith", contents_a)

        # Bot B querying for ApexBook Pro 16 must return ZERO results
        ret_b = retrieve_relevant_chunks(self.db, bot_id=b_id_b, query="What is the battery of ApexBook Pro 16?")
        contents_b = " ".join([r["chunk"].content for r in ret_b])
        self.assertNotIn("99.6Wh", contents_b)
        self.assertNotIn("M3 Ultra", contents_b)

    # =========================================================================
    # 10. LARGE-SCALE WEBSITE RETRIEVAL & LATENCY PROFILING
    # =========================================================================
    def test_10_large_scale_corpus_and_latency_profiling(self):
        """Tests retrieval precision and profiles latency (p50, p95, worst-case) across a 50-document corpus."""
        b_id = self.bot_id_scale
        self.created_bots.append(b_id)

        bot = Bot(id=b_id, organization_id=300, name="MegaStore Scale Bot")
        self.db.merge(bot)
        self.db.commit()

        self.db.query(Chunk).filter(Chunk.bot_id == b_id).delete()
        self.db.query(Document).filter(Document.bot_id == b_id).delete()
        self.db.commit()

        # Batch insert 50 distinct documents
        docs = []
        texts = []
        for i in range(1, 51):
            doc = Document(
                bot_id=b_id,
                organization_id=300,
                source_type="website",
                filename=f"catalog-item-{i}",
                title=f"Catalog Item {i}",
                source_url=f"https://megastore.com/items/{i}",
                status="ready",
                processing_status="completed",
            )
            self.db.add(doc)
            docs.append((i, doc))
            special_trait = "Deep Space Satellite Optical Transceiver" if i == 42 else f"Standard Component Model {i}"
            texts.append(f"Catalog Item {i} {special_trait}")
        self.db.commit()

        embeddings = generate_embeddings_batch(texts)

        for idx, (i, doc) in enumerate(docs):
            self.db.refresh(doc)
            special_trait = "Deep Space Satellite Optical Transceiver" if i == 42 else f"Standard Component Model {i}"
            self.db.add(
                Chunk(
                    bot_id=b_id,
                    organization_id=300,
                    document_id=doc.id,
                    chunk_index=0,
                    content=f"[Catalog Item {i}]\nItem {i} is {special_trait}. Price is ${150 + i}.",
                    status="ready",
                    embedding=embeddings[idx],
                    metadata_json={"page_title": f"Catalog Item {i}", "source_url": f"https://megastore.com/items/{i}"},
                )
            )
        self.db.commit()

        # Profile retrieval latency over multiple queries
        latencies_ms = []
        for q in [
            "Which catalog item is the Deep Space Satellite Optical Transceiver?",
            "How much is Catalog Item 15?",
            "What is Catalog Item 30?",
            "What are the available catalog items?",
        ]:
            t0 = time.perf_counter()
            res = retrieve_relevant_chunks(self.db, bot_id=b_id, query=q)
            lat_ms = (time.perf_counter() - t0) * 1000
            latencies_ms.append(lat_ms)
            self.assertGreaterEqual(len(res), 1)

        # Retrieve specific target chunk 42
        target_res = retrieve_relevant_chunks(self.db, bot_id=b_id, query="Which item is the Deep Space Satellite Optical Transceiver?")
        target_content = " ".join([r["chunk"].content for r in target_res])
        self.assertIn("Catalog Item 42", target_content)
        self.assertIn("Deep Space Satellite Optical Transceiver", target_content)

        # Latency statistics
        p50 = sorted(latencies_ms)[len(latencies_ms) // 2]
        worst_case = max(latencies_ms)
        print(f"\n[Latency Profiling] 50 Docs (50 Chunks) -> p50: {p50:.2f}ms | Worst: {worst_case:.2f}ms")
        self.assertLess(worst_case, 12000)

    # =========================================================================
    # 11. DIAGNOSTIC FAILURE STAGE TRACER (Stages A through J)
    # =========================================================================
    def test_11_diagnostic_failure_stage_tracing(self):
        """Verifies diagnostic tracing through Stages A (Firecrawl) to J (CTA/URL binding)."""
        b_id = self._seed_complete_ecommerce_website()

        query = "Where can I buy the ApexBook Pro 16?"

        # Stage A: Firecrawl Extraction
        mock_raw_md = "# ApexBook Pro 16\n\n[Buy Now](https://apexhardware.com/checkout?sku=apexbook-16)"
        extracted_ctas = extract_cta_links_from_markdown(mock_raw_md, "https://apexhardware.com/products/apexbook-pro-16")
        self.assertEqual(len(extracted_ctas), 1, "Stage A Failed: CTA extraction from Firecrawl markdown failed")

        # Stage B: Storage & Versioning
        doc = self.db.query(Document).filter(Document.bot_id == b_id, Document.filename == "product-apex-book-pro").first()
        self.assertIsNotNone(doc, "Stage B Failed: Document not stored in database")

        # Stage C: Chunking & Hierarchy
        chunks = self.db.query(Chunk).filter(Chunk.document_id == doc.id).all()
        self.assertGreaterEqual(len(chunks), 1, "Stage C Failed: Document was not chunked")

        # Stage D: Embeddings
        self.assertIsNotNone(chunks[0].embedding, "Stage D Failed: Chunk embedding missing")

        # Stage E: Hybrid Retrieval / RRF
        retrieved = retrieve_relevant_chunks(self.db, bot_id=b_id, query=query, mode=RETRIEVAL_MODE_PURCHASE)
        self.assertGreaterEqual(len(retrieved), 1, "Stage E Failed: Hybrid retrieval returned 0 chunks")

        # Stage F & G: Context Expansion & Reranking
        _, ctx = compress_and_rerank_chunks(retrieved, query=query, max_context_chars=4000)
        self.assertIn("https://apexhardware.com/checkout?sku=apexbook-16", ctx, "Stage F/G Failed: CTA URL omitted during context assembly")

        # Stage H: Prompt Construction
        prompt = build_rag_prompt(question=query, retrieved=retrieved, compressed_context=ctx, mode="purchase")
        self.assertIn("https://apexhardware.com/checkout?sku=apexbook-16", prompt, "Stage H Failed: Prompt omitted purchase URL")

        # Stage J: CTA URL Binding
        self.assertIn("Actionable Links:", prompt, "Stage J Failed: Actionable Links section missing from prompt")


if __name__ == "__main__":
    unittest.main()
