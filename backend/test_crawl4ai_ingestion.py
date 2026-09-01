import hashlib
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure backend root is on sys.path
BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from database.connection import SessionLocal
from database.models import Bot, Chunk, Customer, Document
from services.crawl4ai_service import Page
from services.document_processing_service import process_document
from services.rag_service import retrieve_relevant_chunks
import fakeredis
import fakeredis.aioredis
from utils.redis_client import set_redis_override


class TestCrawl4AIIngestion(unittest.TestCase):

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
        # Find or create a test customer
        self.customer = self.db.query(Customer).first()
        if not self.customer:
            self.customer = Customer(
                name="TestCustomer",
                api_key=f"test_key_{int(datetime.utcnow().timestamp())}",
            )
            self.db.add(self.customer)
            self.db.commit()
            self.db.refresh(self.customer)

        # Create a unique test bot
        self.bot_name = f"TestBot_Crawl4AI_{int(datetime.utcnow().timestamp())}"
        self.bot = Bot(
            name=self.bot_name,
            customer_id=self.customer.id,
            system_prompt="You are a helpful documentation assistant.",
            model_name="gemini-2.5-flash",
        )
        self.db.add(self.bot)
        self.db.commit()
        self.db.refresh(self.bot)

    def tearDown(self):
        try:
            # Clean up chunks, documents, and bot
            self.db.query(Chunk).filter(Chunk.bot_id == self.bot.id).delete()
            self.db.query(Document).filter(Document.bot_id == self.bot.id).delete()
            self.db.query(Bot).filter(Bot.id == self.bot.id).delete()
            self.db.commit()
        except Exception:
            self.db.rollback()
        finally:
            self.db.close()

    def test_mock_multi_page_ingestion_with_cta(self):
        """Tests ingestion of multiple Crawl4AI pages including CTA metadata and structure."""
        mock_pages = [
            Page(
                url="https://example-shop.com/",
                title="Example Shop Home",
                markdown="# Welcome to Example Shop\n\nWe provide top quality AI gadgets.\n\n## Featured Product\nNovaPhone Ultra with next-gen AI chip.",
                html="<div><h1>Welcome</h1><a href='/cart/add?id=1' class='btn'>Buy Now</a></div>",
                metadata={
                    "crawl_depth": 0,
                    "cta_links": [
                        {
                            "text": "Buy Now",
                            "url": "https://example-shop.com/cart/add?id=1",
                            "source_url": "https://example-shop.com/",
                            "context": "Featured Product",
                            "is_internal": True,
                            "type": "a",
                        }
                    ],
                },
                links=["https://example-shop.com/pricing"],
                status="success",
                status_code=200,
            ),
            Page(
                url="https://example-shop.com/pricing",
                title="Example Shop Pricing",
                markdown="# Pricing Plans\n\n| Plan | Price |\n| --- | --- |\n| Starter | $10/mo |\n| Pro | $50/mo |\n\nContact support for enterprise inquiries.",
                html="<div><h1>Pricing</h1><a href='/checkout' class='btn'>Get Started</a></div>",
                metadata={
                    "crawl_depth": 1,
                    "cta_links": [
                        {
                            "text": "Get Started",
                            "url": "https://example-shop.com/checkout",
                            "source_url": "https://example-shop.com/pricing",
                            "context": "Pricing Plans",
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

        with patch("services.document_processing_service.crawl_website", return_value=mock_pages):
            # Create initial root document
            doc = Document(
                bot_id=self.bot.id,
                source_type="website",
                source_url="https://example-shop.com/",
                filename="example-shop.com",
                title="Example Shop Home",
                raw_text="",
                processing_status="pending",
            )
            self.db.add(doc)
            self.db.commit()
            self.db.refresh(doc)

            # Process document
            processed_doc = process_document(self.db, doc.id)

            # 1. Verify root document status
            self.assertEqual(processed_doc.processing_status, "completed")
            self.assertGreater(processed_doc.chunk_count, 0)

            # 2. Verify both documents exist in DB
            docs = self.db.query(Document).filter(Document.bot_id == self.bot.id).all()
            self.assertEqual(len(docs), 2)
            urls = {d.source_url for d in docs}
            self.assertIn("https://example-shop.com/", urls)
            self.assertIn("https://example-shop.com/pricing", urls)

            # 3. Verify chunks created with embeddings and metadata
            chunks = self.db.query(Chunk).filter(Chunk.bot_id == self.bot.id).all()
            self.assertGreaterEqual(len(chunks), 2)
            for chunk in chunks:
                self.assertIsNotNone(chunk.embedding)
                self.assertIsInstance(chunk.metadata_json, dict)
                self.assertIn("source_url", chunk.metadata_json)
                self.assertEqual(chunk.bot_id, self.bot.id)

            # 4. Verify CTA metadata preserved on chunks
            home_chunk = next(c for c in chunks if c.metadata_json.get("source_url") == "https://example-shop.com/")
            self.assertIn("cta_links", home_chunk.metadata_json)
            self.assertEqual(home_chunk.metadata_json["cta_links"][0]["text"], "Buy Now")

            # 5. Verify Phase 9 retrieval can query the ingested content
            retrieval_res = retrieve_relevant_chunks(
                db=self.db,
                bot_id=self.bot.id,
                query="What is the price of the Pro plan?",
                top_k=3,
            )
            self.assertGreater(len(retrieval_res), 0)
            self.assertTrue(any("Pricing" in r["chunk"].content or "Pro" in r["chunk"].content for r in retrieval_res))

    def test_incremental_recrawl_skips_unchanged_pages(self):
        """Verifies that re-crawling identical content does not recreate chunks or regenerate embeddings."""
        page_md = "# Documentation\n\nStable unchanged content."
        p_hash = hashlib.sha256(page_md.encode("utf-8")).hexdigest()
        mock_pages = [
            Page(
                url="https://docs.example.com/",
                title="Documentation",
                markdown=page_md,
                metadata={"content_hash": p_hash},
                status="success",
                status_code=200,
            )
        ]

        with patch("services.document_processing_service.crawl_website", return_value=mock_pages):
            doc = Document(
                bot_id=self.bot.id,
                source_type="website",
                source_url="https://docs.example.com/",
                filename="docs.example.com",
                title="Documentation",
                raw_text="",
                processing_status="pending",
            )
            self.db.add(doc)
            self.db.commit()
            self.db.refresh(doc)

            # First run: creates chunk
            process_document(self.db, doc.id)
            initial_chunk = self.db.query(Chunk).filter(Chunk.document_id == doc.id).first()
            self.assertIsNotNone(initial_chunk)
            initial_chunk_id = initial_chunk.id

            # Second run with same content hash: should skip re-chunking and retain same chunk ID
            process_document(self.db, doc.id)
            second_chunk = self.db.query(Chunk).filter(Chunk.document_id == doc.id).first()
            self.assertEqual(second_chunk.id, initial_chunk_id)

    def test_live_docs_python_ingestion(self):
        """Performs a live test on docs.python.org using limited pages."""
        test_url = "https://docs.python.org/3/"
        doc = Document(
            bot_id=self.bot.id,
            source_type="website",
            source_url=test_url,
            filename="docs.python.org",
            title="Python Docs Test",
            raw_text="",
            processing_status="pending",
        )
        self.db.add(doc)
        self.db.commit()
        self.db.refresh(doc)

        print(f"\n[Test] Ingesting live site {test_url} into Bot {self.bot.id} (limited crawl)...")
        from services.crawl4ai_service import crawl_website as real_crawl

        with patch("services.document_processing_service.crawl_website", side_effect=lambda url: real_crawl(url, max_pages=3, max_depth=1, verbose_diagnostics=True)):
            processed_doc = process_document(self.db, doc.id)

        self.assertEqual(processed_doc.processing_status, "completed")
        self.assertGreater(processed_doc.chunk_count, 0)

        docs = self.db.query(Document).filter(Document.bot_id == self.bot.id).all()
        print(f"[Test] Successfully ingested {len(docs)} documents for Bot {self.bot.id}.")
        self.assertGreaterEqual(len(docs), 1)

        chunks = self.db.query(Chunk).filter(Chunk.bot_id == self.bot.id).all()
        print(f"[Test] Successfully generated {len(chunks)} embedded chunks.")
        self.assertGreaterEqual(len(chunks), 1)

        # Query retrieved context
        retrieval_res = retrieve_relevant_chunks(
            db=self.db,
            bot_id=self.bot.id,
            query="Python documentation download",
            top_k=3,
        )
        self.assertGreater(len(retrieval_res), 0)
        print(f"[Test] Retrieved {len(retrieval_res)} relevant chunks from live ingested pages.")


if __name__ == "__main__":
    unittest.main()
