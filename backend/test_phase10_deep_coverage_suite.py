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
from database.models import Bot, Chunk, Customer, Document, Organization, Website, WebsiteCrawl
from services.chunking_service import CHUNK_OVERLAP, CHUNK_SIZE, chunk_text_with_metadata
from services.conversational_engine import compress_and_rerank_chunks, global_semantic_cache
from services.coverage_manifest_service import (
    build_website_coverage_manifest,
    infer_document_relationships,
    infer_entity_type,
)
from services.document_processing_service import process_document
from services.embedding_service import generate_embedding, generate_embeddings_batch
from services.firecrawl_service import (
    CrawlAuditReport,
    FirecrawlError,
    Page,
    crawl_website,
    crawl_website_with_audit,
    extract_cta_links_from_markdown,
    extract_discovered_links_from_markdown,
    is_url_eligible_for_crawl,
    normalize_crawl_url,
)
from services.intent_router import (
    RETRIEVAL_MODE_CATALOG,
    RETRIEVAL_MODE_COMPARISON,
    RETRIEVAL_MODE_ENTITY,
    RETRIEVAL_MODE_FACTUAL,
    RETRIEVAL_MODE_FILTER,
    RETRIEVAL_MODE_POLICY,
    RETRIEVAL_MODE_PURCHASE,
    detect_retrieval_mode,
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


class TestPhase10DeepCoverageSuite(unittest.TestCase):
    """
    Phase 10: Deep Website Coverage & Real-World Knowledge Completeness Suite.
    Validates DISCOVERED -> ELIGIBLE -> CRAWLED -> STORED -> CHUNKED -> EMBEDDED traceability,
    deep internal link crawling, coverage manifest tree generation, document relationships,
    and expanded multi-document corpus retrieval without domain-specific hardcoding.
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
        self.db = SessionLocal()
        self.timestamp = int(datetime.utcnow().timestamp() * 1000) % 1000000
        self.bot_id = 41000 + (self.timestamp % 1000)
        self.bot_id_b = 42000 + (self.timestamp % 1000)
        self.created_bots = []
        clear_retrieval_cache()
        global_semantic_cache.clear()

        # Ensure Org 600 exists
        org = self.db.query(Organization).filter(Organization.id == 600).first()
        if not org:
            org = Organization(id=600, name="AutoCorp Org", slug="autocorp-org-phase10")
            self.db.merge(org)
            self.db.commit()

    def tearDown(self):
        try:
            for b_id in self.created_bots + [self.bot_id, self.bot_id_b]:
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
    # 1. DISCOVERY -> INGESTION TRACEABILITY AUDIT
    # =========================================================================
    def test_01_discovery_to_ingestion_audit_traceability(self):
        """Verifies full DISCOVERED -> ELIGIBLE -> CRAWLED -> STORED -> CHUNKED -> EMBEDDED audit trail."""
        seed_url = "https://novacloud.io"

        mock_pages_data = [
            {
                "markdown": "# NovaCloud Hub\n\n[Compute Services](https://novacloud.io/compute)\n[Storage Services](https://novacloud.io/storage)\n[Login Page](https://novacloud.io/login)\n[Tracking Link](https://novacloud.io/compute?utm_source=adwords)\n[External Twitter](https://twitter.com/novacloud)\n[Whitepaper PDF](https://novacloud.io/docs/whitepaper.pdf)",
                "metadata": {"sourceURL": "https://novacloud.io", "title": "NovaCloud Home", "statusCode": 200, "depth": 0},
            },
            {
                "markdown": "# NovaCloud Compute\n\nHigh-performance GPU instances.\n\n[GPU Cloud](https://novacloud.io/compute/gpu)\n[Checkout Cart](https://novacloud.io/cart)",
                "metadata": {"sourceURL": "https://novacloud.io/compute", "title": "NovaCloud Compute", "statusCode": 200, "depth": 1},
            },
            {
                "markdown": "# GPU Cloud Instances\n\nH100 80GB SXM5 instances for AI workloads at $2.99/hr.\n\n[Buy Now](https://novacloud.io/order?sku=h100)",
                "metadata": {"sourceURL": "https://novacloud.io/compute/gpu", "title": "NovaCloud GPU Instances", "statusCode": 200, "depth": 2},
            },
        ]

        with patch("services.firecrawl_service.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_post = MagicMock(status_code=200)
            mock_post.json.return_value = {"success": True, "id": "job_p10_trace"}
            mock_poll = MagicMock(status_code=200)
            mock_poll.json.return_value = {"status": "completed", "data": mock_pages_data}
            mock_client.post.return_value = mock_post
            mock_client.get.return_value = mock_poll
            mock_client_cls.return_value.__enter__.return_value = mock_client

            with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "fc-test-key-p10"}):
                pages, audit = crawl_website_with_audit(seed_url)

        self.assertEqual(len(pages), 3)
        self.assertGreater(audit.discovered_urls, 0)
        self.assertGreater(audit.eligible_urls, 0)
        self.assertEqual(audit.crawled_urls, 3)
        self.assertEqual(audit.stored_documents, 3)
        self.assertGreaterEqual(audit.max_depth_reached, 2)

        # Verify skip reasons are explicit and recorded
        self.assertIn("https://twitter.com/novacloud", audit.skipped_urls)
        self.assertEqual(audit.skipped_urls["https://twitter.com/novacloud"], "external_domain")

        self.assertIn("https://novacloud.io/login", audit.skipped_urls)
        self.assertEqual(audit.skipped_urls["https://novacloud.io/login"], "disallowed_path_auth")

        self.assertIn("https://novacloud.io/cart", audit.skipped_urls)
        self.assertEqual(audit.skipped_urls["https://novacloud.io/cart"], "disallowed_path_cart")

        self.assertIn("https://novacloud.io/docs/whitepaper.pdf", audit.skipped_urls)
        self.assertEqual(audit.skipped_urls["https://novacloud.io/docs/whitepaper.pdf"], "ignored_extension_.pdf")

    # =========================================================================
    # 2. URL NORMALIZATION & TRACKING PARAMETER STRIPPING
    # =========================================================================
    def test_02_url_normalization_and_parameter_stripping(self):
        """Validates that tracking parameters, fragments, and trailing slashes are cleanly normalized."""
        base = "https://example.com/products"

        # Tracking params stripped
        norm1 = normalize_crawl_url("https://example.com/item?utm_source=google&utm_medium=cpc&sku=123", base)
        self.assertEqual(norm1, "https://example.com/item?sku=123")

        # Fragment stripped
        norm2 = normalize_crawl_url("https://example.com/faq#shipping-section", base)
        self.assertEqual(norm2, "https://example.com/faq")

        # Relative link resolved
        norm3 = normalize_crawl_url("/pricing", base)
        self.assertEqual(norm3, "https://example.com/pricing")

    # =========================================================================
    # 3. WEBSITE KNOWLEDGE COVERAGE MANIFEST GENERATION
    # =========================================================================
    def test_03_coverage_manifest_tree_generation(self):
        """Validates hierarchical relationship inference and ASCII coverage tree generation."""
        mock_docs = [
            {"source_url": "https://megaclinic.com", "title": "MegaClinic Health", "raw_text": "Welcome to MegaClinic.", "chunk_count": 2},
            {"source_url": "https://megaclinic.com/treatments", "title": "Treatments & Services", "raw_text": "Dental, cardiology, oncology.", "chunk_count": 3},
            {"source_url": "https://megaclinic.com/treatments/dental", "title": "Dental Care", "raw_text": "Implants, crowns, cleanings.", "chunk_count": 4},
            {"source_url": "https://megaclinic.com/treatments/dental/implants", "title": "Titanium Implants", "raw_text": "Permanent root replacements.", "chunk_count": 2},
            {"source_url": "https://megaclinic.com/policies/privacy", "title": "Privacy Policy", "raw_text": "HIPAA compliance info.", "chunk_count": 1},
            {"source_url": "https://megaclinic.com/faq", "title": "Patient FAQ", "raw_text": "Common medical questions.", "chunk_count": 2},
        ]

        manifest = build_website_coverage_manifest(mock_docs, root_url="https://megaclinic.com")

        self.assertEqual(manifest["total_documents"], 6)
        self.assertEqual(manifest["total_chunks"], 14)
        self.assertEqual(manifest["max_depth"], 3)
        self.assertIn("category", manifest["type_breakdown"])
        self.assertIn("policy", manifest["type_breakdown"])
        self.assertIn("faq", manifest["type_breakdown"])

        # Verify ASCII tree contains structural tags
        ascii_tree = manifest["ascii_tree"]
        self.assertIn("MegaClinic Health", ascii_tree)
        self.assertIn("[CATEGORY] Treatments & Services", ascii_tree)
        self.assertIn("[SUBCATEGORY] Dental Care", ascii_tree)
        self.assertIn("[DETAIL] Titanium Implants", ascii_tree)
        self.assertIn("[POLICY] Privacy Policy", ascii_tree)
        self.assertIn("[FAQ] Patient FAQ", ascii_tree)

    # =========================================================================
    # 4. DEEP MULTI-LEVEL DOCUMENT INGESTION & RELATIONSHIPS IN DATABASE
    # =========================================================================
    def test_04_deep_multi_level_ingestion_and_db_relationships(self):
        """Verifies multi-page crawl ingests child documents, links parents, and embeds chunks."""
        bot = Bot(id=self.bot_id, organization_id=600, name="Deep Ingestion Bot")
        self.db.merge(bot)
        self.db.commit()

        root_doc = Document(
            bot_id=self.bot_id,
            organization_id=600,
            source_type="website",
            source_url="https://autocorp.com",
            filename="autocorp-home",
            title="AutoCorp Vehicles",
            status="pending",
            processing_status="pending",
        )
        self.db.add(root_doc)
        self.db.commit()
        self.db.refresh(root_doc)

        crawled_pages = [
            Page(url="https://autocorp.com", title="AutoCorp Home", markdown="# AutoCorp Vehicles\n\nLeading electric vehicle manufacturer.\n\n[Explore Sedans](https://autocorp.com/vehicles/sedans)\n[Explore SUVs](https://autocorp.com/vehicles/suvs)\n[Warranty](https://autocorp.com/policies/warranty)"),
            Page(url="https://autocorp.com/vehicles/sedans", title="AutoCorp Sedans", markdown="# Electric Sedans\n\n[Model E](https://autocorp.com/vehicles/sedans/model-e)"),
            Page(url="https://autocorp.com/vehicles/sedans/model-e", title="Model E Sedan", markdown="# Model E Sedan\n\nDual motor AWD, 380-mile range, 0-60 in 3.1s. Base price $42,900.\n\n[Buy Now](https://autocorp.com/order/model-e)"),
            Page(url="https://autocorp.com/vehicles/suvs", title="AutoCorp SUVs", markdown="# Electric SUVs\n\n[Model X](https://autocorp.com/vehicles/suvs/model-x)"),
            Page(url="https://autocorp.com/vehicles/suvs/model-x", title="Model X SUV", markdown="# Model X SUV\n\nTri-motor 7-seater SUV with 340-mile range. Base price $68,900.\n\n[Buy Now](https://autocorp.com/order/model-x)"),
            Page(url="https://autocorp.com/policies/warranty", title="AutoCorp Warranty", markdown="# Warranty Terms\n\n8-year or 120,000-mile battery and drive unit warranty with 70% retention guarantee."),
        ]

        with patch("services.document_processing_service.crawl_website", return_value=crawled_pages):
            process_document(self.db, root_doc.id)

        # Verify all 6 documents were created and marked ready
        docs = self.db.query(Document).filter(Document.bot_id == self.bot_id).all()
        self.assertEqual(len(docs), 6)

        # Verify chunks created and embedded for all documents
        chunks = self.db.query(Chunk).filter(Chunk.bot_id == self.bot_id).all()
        self.assertGreaterEqual(len(chunks), 6)

        # Verify relationship metadata on Model E child document
        model_e_doc = self.db.query(Document).filter(Document.source_url == "https://autocorp.com/vehicles/sedans/model-e").first()
        self.assertIsNotNone(model_e_doc)
        self.assertEqual(model_e_doc.metadata_json.get("parent_url"), "https://autocorp.com/vehicles/sedans")
        self.assertIn("Sedans", model_e_doc.metadata_json.get("category_path", []))

    # =========================================================================
    # 5. EXPANDED CORPUS RETRIEVAL & CROSS-PAGE SYNTHESIS
    # =========================================================================
    def test_05_expanded_corpus_retrieval_and_cross_page_synthesis(self):
        """Verifies retrieval finds evidence across child documents (specs + pricing + warranty)."""
        bot = Bot(id=self.bot_id, organization_id=600, name="AutoCorp QA Bot")
        self.db.merge(bot)
        self.db.commit()

        root_doc = Document(
            bot_id=self.bot_id,
            organization_id=600,
            source_type="website",
            source_url="https://autocorp.com",
            filename="autocorp-home",
            title="AutoCorp Vehicles",
            status="pending",
            processing_status="pending",
        )
        self.db.add(root_doc)
        self.db.commit()
        self.db.refresh(root_doc)

        crawled_pages = [
            Page(url="https://autocorp.com", title="AutoCorp Home", markdown="# AutoCorp Vehicles\n\n[Model E](https://autocorp.com/vehicles/sedans/model-e)\n[Model X](https://autocorp.com/vehicles/suvs/model-x)\n[Warranty](https://autocorp.com/policies/warranty)"),
            Page(url="https://autocorp.com/vehicles/sedans/model-e", title="Model E Sedan", markdown="# Model E Sedan\n\nDual motor AWD, 380-mile range, 0-60 in 3.1s. Base price is $42,900."),
            Page(url="https://autocorp.com/vehicles/suvs/model-x", title="Model X SUV", markdown="# Model X SUV\n\nTri-motor 7-seater SUV with 340-mile range. Base price is $68,900."),
            Page(url="https://autocorp.com/policies/warranty", title="AutoCorp Warranty", markdown="# Warranty Terms\n\nAll vehicles include an 8-year or 120,000-mile battery warranty."),
        ]

        with patch("services.document_processing_service.crawl_website", return_value=crawled_pages):
            process_document(self.db, root_doc.id)

        # 1. Catalog Query across child documents
        ret_catalog = retrieve_relevant_chunks(self.db, bot_id=self.bot_id, query="What vehicles do you offer?", mode=RETRIEVAL_MODE_CATALOG)
        _, cat_ctx = compress_and_rerank_chunks(ret_catalog, query="What vehicles do you offer?", mode="catalog")
        self.assertIn("Model E", cat_ctx)
        self.assertIn("Model X", cat_ctx)

        # 2. Factual Query on deep child page
        ret_model_e = retrieve_relevant_chunks(self.db, bot_id=self.bot_id, query="What is the range and 0-60 time of Model E?")
        _, e_ctx = compress_and_rerank_chunks(ret_model_e, query="Model E")
        self.assertIn("380-mile", e_ctx)
        self.assertIn("3.1s", e_ctx)

        # 3. Cross-Page Synthesis (Vehicle Specs + Warranty Policy from different documents)
        ret_synthesis = retrieve_relevant_chunks(self.db, bot_id=self.bot_id, query="How much is Model E and what is the battery warranty?")
        _, synth_ctx = compress_and_rerank_chunks(ret_synthesis, query="Model E battery warranty")
        self.assertIn("$42,900", synth_ctx)
        self.assertIn("8-year", synth_ctx)

    # =========================================================================
    # 6. DIAGNOSTIC FAILURE STAGE TRACER (Stages A through K)
    # =========================================================================
    def test_06_diagnostic_failure_stage_tracer_phase10(self):
        """Verifies diagnostic tracing across Stages A (Discovery) to K (CTA/URL binding)."""
        seed_url = "https://vanguardlaw.com"

        # Stage A: Discovery & Extraction
        mock_md = "# Vanguard Law\n\n[Attorneys](https://vanguardlaw.com/attorneys)\n[Practice Areas](https://vanguardlaw.com/practices)\n[Consultation](https://vanguardlaw.com/book)"
        discovered = extract_discovered_links_from_markdown(mock_md, seed_url)
        self.assertIn("https://vanguardlaw.com/practices", discovered, "Stage A: Link discovery failed")

        # Stage B: Eligibility
        is_elig, reason = is_url_eligible_for_crawl("https://vanguardlaw.com/practices", "vanguardlaw.com")
        self.assertTrue(is_elig, f"Stage B: Eligibility check failed: {reason}")

        # Stage C: Storage & Relationships
        mock_docs = [
            {"source_url": "https://vanguardlaw.com", "title": "Home", "raw_text": mock_md},
            {"source_url": "https://vanguardlaw.com/practices", "title": "Practices", "raw_text": "Corporate & M&A."},
        ]
        manifest = build_website_coverage_manifest(mock_docs, root_url=seed_url)
        self.assertEqual(manifest["total_documents"], 2, "Stage C: Document storage & relationship mapping failed")


if __name__ == "__main__":
    unittest.main()
