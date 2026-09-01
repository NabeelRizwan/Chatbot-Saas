import unittest
import os
import sys
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.connection import Base
from database.models import Bot, Document, Chunk, Website, WebsiteCrawl, Organization
from services.rag_service import (
    answer_question,
    retrieve_relevant_chunks,
    retrieve_relevant_chunks_cached,
    clear_retrieval_cache,
    build_rag_prompt,
)
from services.conversational_engine import (
    compress_and_rerank_chunks,
    critique_response,
    verify_answer,
    polish_answer,
)
from services.intent_router import (
    classify_intent,
    detect_retrieval_mode,
    rewrite_query_for_retrieval,
    is_catalog_or_list_query,
    is_filter_query,
    is_purchase_intent,
    is_policy_query,
    is_comparison_query,
    RETRIEVAL_MODE_FACTUAL,
    RETRIEVAL_MODE_CATALOG,
    RETRIEVAL_MODE_FILTER,
    RETRIEVAL_MODE_COMPARISON,
    RETRIEVAL_MODE_POLICY,
    RETRIEVAL_MODE_PURCHASE,
    RETRIEVAL_MODE_ENTITY,
)
from services.chunking_service import chunk_text_with_metadata
from services.embedding_service import generate_embedding


from database.connection import SessionLocal
from datetime import datetime
import fakeredis
import fakeredis.aioredis
from utils.redis_client import set_redis_override


class TestRagQualityHardeningSuite(unittest.TestCase):
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
        self.bot_dental_id = 7000 + (self.timestamp % 1000)
        self.bot_uni_id = 8000 + (self.timestamp % 1000)
        self.bot_saas_id = 9000 + (self.timestamp % 1000)
        self.created_bots = []
        clear_retrieval_cache()

    def tearDown(self):
        try:
            for b_id in self.created_bots:
                self.db.query(Chunk).filter(Chunk.bot_id == b_id).delete()
                self.db.query(Document).filter(Document.bot_id == b_id).delete()
                self.db.query(Bot).filter(Bot.id == b_id).delete()
            self.db.commit()
        except Exception:
            self.db.rollback()
        finally:
            self.db.close()

    def _seed_dental_clinic(self, bot_id: int | None = None, org_id: int = 1) -> int:
        """Seeds multi-page website knowledge for Apex Dental Clinic (Healthcare)."""
        target_bot_id = bot_id or self.bot_dental_id
        if target_bot_id not in self.created_bots:
            self.created_bots.append(target_bot_id)

        bot = Bot(
            id=target_bot_id,
            organization_id=org_id,
            name="Apex Dental Assistant",
            system_prompt="You are the AI receptionist for Apex Dental Clinic. Provide accurate, friendly assistance.",
        )
        self.db.merge(bot)
        self.db.commit()

        # Clean existing chunks/documents for this bot if re-seeding
        self.db.query(Chunk).filter(Chunk.bot_id == target_bot_id).delete()
        self.db.query(Document).filter(Document.bot_id == target_bot_id).delete()
        self.db.commit()

        # Page 1: Clinic Overview & Emergency
        doc1 = Document(
            bot_id=target_bot_id,
            organization_id=org_id,
            source_type="website",
            filename="apex-home",
            title="Apex Dental Clinic - Home & Overview",
            source_url="https://apexdental.com/",
            status="ready",
            processing_status="completed",
        )
        self.db.add(doc1)
        self.db.commit()
        self.db.refresh(doc1)

        self.db.add(
            Chunk(
                bot_id=target_bot_id,
                organization_id=org_id,
                document_id=doc1.id,
                chunk_index=0,
                content="[Apex Dental Clinic]\nWelcome to Apex Dental Clinic in Seattle. We specialize in general, cosmetic, and emergency dentistry. 24/7 Emergency Hotline: (555) 987-6543.",
                status="ready",
                embedding=generate_embedding("Apex Dental Clinic Seattle general cosmetic emergency dentistry hotline"),
                metadata_json={"page_title": "Apex Dental Clinic", "source_url": "https://apexdental.com/"},
            )
        )

        # Page 2: Invisalign Treatment & Pricing & CTA
        doc2 = Document(
            bot_id=target_bot_id,
            organization_id=org_id,
            source_type="website",
            filename="apex-invisalign",
            title="Invisalign Clear Aligners - Apex Dental",
            source_url="https://apexdental.com/treatments/invisalign",
            status="ready",
            processing_status="completed",
        )
        self.db.add(doc2)
        self.db.commit()
        self.db.refresh(doc2)

        self.db.add(
            Chunk(
                bot_id=target_bot_id,
                organization_id=org_id,
                document_id=doc2.id,
                chunk_index=0,
                content="[Invisalign Clear Aligners]\nInvisalign orthodontic aligners straighten teeth discretely. Treatment duration is typically 12 to 18 months. Total cost is $3,500 including all retainers and checkups.",
                status="ready",
                embedding=generate_embedding("Invisalign Clear Aligners orthodontic treatment duration 12-18 months cost $3,500 retainers checkups"),
                metadata_json={
                    "page_title": "Invisalign Clear Aligners",
                    "source_url": "https://apexdental.com/treatments/invisalign",
                    "cta_links": [{"text": "Book Invisalign Consultation", "url": "https://apexdental.com/book?service=invisalign"}],
                },
            )
        )

        # Page 3: Root Canal Therapy & CTA
        doc3 = Document(
            bot_id=target_bot_id,
            organization_id=org_id,
            source_type="website",
            filename="apex-root-canal",
            title="Root Canal Therapy - Apex Dental",
            source_url="https://apexdental.com/treatments/root-canal",
            status="ready",
            processing_status="completed",
        )
        self.db.add(doc3)
        self.db.commit()
        self.db.refresh(doc3)

        self.db.add(
            Chunk(
                bot_id=target_bot_id,
                organization_id=org_id,
                document_id=doc3.id,
                chunk_index=0,
                content="[Root Canal Therapy]\nPainless gentle root canal therapy to save infected teeth using 3D imaging. Session length: 60 minutes. Cost: $850 per tooth.",
                status="ready",
                embedding=generate_embedding("Root Canal Therapy painless save infected tooth 60 minutes cost $850"),
                metadata_json={
                    "page_title": "Root Canal Therapy",
                    "source_url": "https://apexdental.com/treatments/root-canal",
                    "cta_links": [{"text": "Book Root Canal", "url": "https://apexdental.com/book?service=root-canal"}],
                },
            )
        )

        # Page 4: Laser Teeth Whitening & CTA
        doc4 = Document(
            bot_id=target_bot_id,
            organization_id=org_id,
            source_type="website",
            filename="apex-whitening",
            title="Laser Teeth Whitening - Apex Dental",
            source_url="https://apexdental.com/treatments/whitening",
            status="ready",
            processing_status="completed",
        )
        self.db.add(doc4)
        self.db.commit()
        self.db.refresh(doc4)

        self.db.add(
            Chunk(
                bot_id=target_bot_id,
                organization_id=org_id,
                document_id=doc4.id,
                chunk_index=0,
                content="[Laser Teeth Whitening]\nIn-office professional laser teeth whitening brightens teeth up to 8 shades in a single 1-hour session. Cost is $350.",
                status="ready",
                embedding=generate_embedding("Laser Teeth Whitening professional 8 shades 1-hour session cost $350"),
                metadata_json={
                    "page_title": "Laser Teeth Whitening",
                    "source_url": "https://apexdental.com/treatments/whitening",
                    "cta_links": [{"text": "Book Whitening", "url": "https://apexdental.com/book?service=whitening"}],
                },
            )
        )

        # Page 5: Our Doctors
        doc5 = Document(
            bot_id=target_bot_id,
            organization_id=org_id,
            source_type="website",
            filename="apex-doctors",
            title="Meet Our Doctors - Apex Dental",
            source_url="https://apexdental.com/doctors",
            status="ready",
            processing_status="completed",
        )
        self.db.add(doc5)
        self.db.commit()
        self.db.refresh(doc5)

        self.db.add(
            Chunk(
                bot_id=target_bot_id,
                organization_id=org_id,
                document_id=doc5.id,
                chunk_index=0,
                content="[Meet Our Doctors]\nDr. Aris Thorne is our Lead Orthodontist with 15 years of experience specializing in Invisalign and complex alignment.\nDr. Maya Lin is our Endodontist, Harvard School of Dental Medicine graduate, specializing in microsurgical root canal therapy.",
                status="ready",
                embedding=generate_embedding("Dr. Aris Thorne Orthodontist Invisalign Dr. Maya Lin Endodontist Harvard root canal therapy"),
                metadata_json={"page_title": "Meet Our Doctors", "source_url": "https://apexdental.com/doctors"},
            )
        )

        # Page 6: Cancellation Policy
        doc6 = Document(
            bot_id=target_bot_id,
            organization_id=org_id,
            source_type="website",
            filename="apex-cancellation",
            title="Appointment & Cancellation Policy - Apex Dental",
            source_url="https://apexdental.com/policies/cancellation",
            status="ready",
            processing_status="completed",
        )
        self.db.add(doc6)
        self.db.commit()
        self.db.refresh(doc6)

        self.db.add(
            Chunk(
                bot_id=target_bot_id,
                organization_id=org_id,
                document_id=doc6.id,
                chunk_index=0,
                content="[Appointment & Cancellation Policy]\nWe require at least 24 hours advance notice to cancel or reschedule appointments. Missed appointments without notice incur a $50 cancellation fee.",
                status="ready",
                embedding=generate_embedding("Appointment Cancellation Policy 24 hours advance notice reschedule missed appointment $50 fee"),
                metadata_json={"page_title": "Appointment Policy", "source_url": "https://apexdental.com/policies/cancellation"},
            )
        )

        self.db.commit()
        return target_bot_id

    def _seed_university(self, bot_id: int | None = None, org_id: int = 2) -> int:
        """Seeds multi-page website knowledge for Summit Global University (Higher Education)."""
        target_bot_id = bot_id or self.bot_uni_id
        if target_bot_id not in self.created_bots:
            self.created_bots.append(target_bot_id)

        bot = Bot(
            id=target_bot_id,
            organization_id=org_id,
            name="Summit University Advisor",
            system_prompt="You are the academic admissions advisor for Summit Global University.",
        )
        self.db.merge(bot)
        self.db.commit()

        self.db.query(Chunk).filter(Chunk.bot_id == target_bot_id).delete()
        self.db.query(Document).filter(Document.bot_id == target_bot_id).delete()
        self.db.commit()

        # Degree 1: BSc Computer Science
        doc1 = Document(
            bot_id=target_bot_id,
            organization_id=org_id,
            source_type="website",
            filename="summit-cs-bs",
            title="BSc Computer Science - Summit University",
            source_url="https://summit.edu/academics/cs-bs",
            status="ready",
            processing_status="completed",
        )
        self.db.add(doc1)
        self.db.commit()
        self.db.refresh(doc1)

        self.db.add(
            Chunk(
                bot_id=target_bot_id,
                organization_id=org_id,
                document_id=doc1.id,
                chunk_index=0,
                content="[BSc Computer Science]\nBachelor of Science in Computer Science requires 120 credits across 4 years. Tuition is $18,000 per academic year. Prerequisites: High School Calculus 1 and Intro Programming.",
                status="ready",
                embedding=generate_embedding("BSc Computer Science Bachelor of Science 120 credits 4 years tuition $18,000 Prerequisites Calculus 1 Intro Programming"),
                metadata_json={
                    "page_title": "BSc Computer Science",
                    "source_url": "https://summit.edu/academics/cs-bs",
                    "cta_links": [{"text": "Apply for BSc CS", "url": "https://summit.edu/apply?prog=cs-bs"}],
                },
            )
        )

        # Degree 2: MSc Data Science
        doc2 = Document(
            bot_id=target_bot_id,
            organization_id=org_id,
            source_type="website",
            filename="summit-ds-ms",
            title="MSc Data Science - Summit University",
            source_url="https://summit.edu/academics/ds-ms",
            status="ready",
            processing_status="completed",
        )
        self.db.add(doc2)
        self.db.commit()
        self.db.refresh(doc2)

        self.db.add(
            Chunk(
                bot_id=target_bot_id,
                organization_id=org_id,
                document_id=doc2.id,
                chunk_index=0,
                content="[MSc Data Science]\nMaster of Science in Data Science is a 36-credit program completed in 18 months. Total program tuition is $24,000. Prerequisites: Linear Algebra, Statistics, and Python proficiency.",
                status="ready",
                embedding=generate_embedding("MSc Data Science Master of Science 36 credits 18 months tuition $24,000 Prerequisites Linear Algebra Statistics Python"),
                metadata_json={
                    "page_title": "MSc Data Science",
                    "source_url": "https://summit.edu/academics/ds-ms",
                    "cta_links": [{"text": "Apply for MSc DS", "url": "https://summit.edu/apply?prog=ds-ms"}],
                },
            )
        )

        # Degree 3: Executive MBA
        doc3 = Document(
            bot_id=target_bot_id,
            organization_id=org_id,
            source_type="website",
            filename="summit-emba",
            title="Executive MBA - Summit University",
            source_url="https://summit.edu/academics/emba",
            status="ready",
            processing_status="completed",
        )
        self.db.add(doc3)
        self.db.commit()
        self.db.refresh(doc3)

        self.db.add(
            Chunk(
                bot_id=target_bot_id,
                organization_id=org_id,
                document_id=doc3.id,
                chunk_index=0,
                content="[Executive MBA]\nExecutive MBA consists of 48 credits designed for working professionals. Total tuition is $32,000. Prerequisites: Bachelor's degree and minimum 3 years managerial experience.",
                status="ready",
                embedding=generate_embedding("Executive MBA 48 credits tuition $32,000 Prerequisites Bachelor degree 3 years managerial experience"),
                metadata_json={
                    "page_title": "Executive MBA",
                    "source_url": "https://summit.edu/academics/emba",
                    "cta_links": [{"text": "Apply for EMBA", "url": "https://summit.edu/apply?prog=emba"}],
                },
            )
        )

        # Refund Policy
        doc4 = Document(
            bot_id=target_bot_id,
            organization_id=org_id,
            source_type="website",
            filename="summit-tuition-refund",
            title="Tuition Refund Policy - Summit University",
            source_url="https://summit.edu/policies/refunds",
            status="ready",
            processing_status="completed",
        )
        self.db.add(doc4)
        self.db.commit()
        self.db.refresh(doc4)

        self.db.add(
            Chunk(
                bot_id=target_bot_id,
                organization_id=org_id,
                document_id=doc4.id,
                chunk_index=0,
                content="[Tuition Refund Policy]\nStudents who withdraw within the first 2 weeks of the semester receive a 100% tuition refund. Withdrawals between weeks 3 and 4 receive a 50% refund. No refunds are issued after week 4.",
                status="ready",
                embedding=generate_embedding("Tuition Refund Policy withdraw first 2 weeks 100% refund weeks 3-4 50% refund after week 4 0% refund"),
                metadata_json={"page_title": "Tuition Refund Policy", "source_url": "https://summit.edu/policies/refunds"},
            )
        )

        self.db.commit()
        return target_bot_id

    # -------------------------------------------------------------
    # TEST 1: Full-Website Catalog/Services Discovery (Domain-Agnostic)
    # -------------------------------------------------------------
    def test_01_domain_agnostic_catalog_discovery(self):
        """Validates that broad catalog queries discover all services/programs across distinct documents."""
        bot_d = self._seed_dental_clinic()
        bot_u = self._seed_university()

        # Healthcare intent check
        self.assertTrue(is_catalog_or_list_query("What treatments do you offer?"))
        self.assertTrue(is_catalog_or_list_query("What services do you provide?"))
        mode_d, params_d = detect_retrieval_mode("What treatments do you provide?")
        self.assertEqual(mode_d, RETRIEVAL_MODE_CATALOG)

        # Healthcare retrieval: All 3 treatments must be in retrieved candidates
        retrieved_d = retrieve_relevant_chunks(self.db, bot_id=bot_d, query="What treatments do you offer?")
        contents_d = " ".join([r["chunk"].content for r in retrieved_d])
        self.assertIn("Invisalign", contents_d)
        self.assertIn("Root Canal", contents_d)
        self.assertIn("Laser Teeth Whitening", contents_d)

        # University intent check
        self.assertTrue(is_catalog_or_list_query("What academic programs and degrees do you offer?"))
        mode_u, params_u = detect_retrieval_mode("What degrees are available?")
        self.assertEqual(mode_u, RETRIEVAL_MODE_CATALOG)

        # University retrieval: All 3 degrees must be in retrieved candidates
        retrieved_u = retrieve_relevant_chunks(self.db, bot_id=bot_u, query="What degrees and programs do you offer?")
        contents_u = " ".join([r["chunk"].content for r in retrieved_u])
        self.assertIn("BSc Computer Science", contents_u)
        self.assertIn("MSc Data Science", contents_u)
        self.assertIn("Executive MBA", contents_u)

    # -------------------------------------------------------------
    # TEST 2: Multi-Page Cross-Page Knowledge Synthesis
    # -------------------------------------------------------------
    def test_02_cross_page_synthesis_multi_page_website(self):
        """Validates that a query spanning specs on Page A and policy on Page B combines both sources."""
        bot_u = self._seed_university()

        query = "What are the requirements for BSc Computer Science and what is the tuition refund policy if I withdraw?"
        retrieved = retrieve_relevant_chunks(self.db, bot_id=bot_u, query=query)
        _, assembled_ctx = compress_and_rerank_chunks(retrieved, query=query, max_context_chars=8000)

        # Verify evidence from academics page AND refunds page
        self.assertIn("BSc Computer Science", assembled_ctx)
        self.assertIn("Calculus 1", assembled_ctx)
        self.assertIn("Tuition Refund Policy", assembled_ctx)
        self.assertIn("100%", assembled_ctx)
        self.assertIn("https://summit.edu/academics/cs-bs", assembled_ctx)
        self.assertIn("https://summit.edu/policies/refunds", assembled_ctx)

    # -------------------------------------------------------------
    # TEST 3: Structured Data, Tables, and FAQs
    # -------------------------------------------------------------
    def test_03_structured_data_and_table_retrieval(self):
        """Validates that structured HTML tables, JSON-LD, and FAQs are correctly indexed and retrievable."""
        bot_saas = self.bot_saas_id
        if bot_saas not in self.created_bots:
            self.created_bots.append(bot_saas)

        bot = Bot(id=bot_saas, organization_id=3, name="SaaS Bot")
        self.db.merge(bot)
        self.db.commit()

        self.db.query(Chunk).filter(Chunk.bot_id == bot_saas).delete()
        self.db.query(Document).filter(Document.bot_id == bot_saas).delete()
        self.db.commit()

        doc = Document(
            bot_id=bot_saas,
            organization_id=3,
            source_type="website",
            filename="pricing-matrix",
            title="LogiFlow Cloud Pricing Matrix",
            source_url="https://logiflow.io/pricing",
            status="ready",
            processing_status="completed",
        )
        self.db.add(doc)
        self.db.commit()
        self.db.refresh(doc)

        table_content = (
            "| Tier | Monthly Price | Events / Sec | Retention |\n"
            "| --- | --- | --- | --- |\n"
            "| Starter | $99 | 10,000 | 7 days |\n"
            "| Pro | $499 | 100,000 | 30 days |\n"
            "| Enterprise | $1,999 | 1,000,000 | 365 days |\n"
            "- Starter (Monthly Price: $99, Events / Sec: 10,000, Retention: 7 days)\n"
            "- Pro (Monthly Price: $499, Events / Sec: 100,000, Retention: 30 days)\n"
            "- Enterprise (Monthly Price: $1,999, Events / Sec: 1,000,000, Retention: 365 days)"
        )

        self.db.add(
            Chunk(
                bot_id=bot_saas,
                organization_id=3,
                document_id=doc.id,
                chunk_index=0,
                content=f"[LogiFlow Pricing Matrix]\n{table_content}",
                status="ready",
                embedding=generate_embedding("LogiFlow pricing table Starter Pro Enterprise events retention"),
                metadata_json={"page_title": "Pricing Matrix", "source_url": "https://logiflow.io/pricing"},
            )
        )
        self.db.commit()

        retrieved = retrieve_relevant_chunks(self.db, bot_id=bot_saas, query="How much does the Pro tier cost and what is its event rate?")
        self.assertGreaterEqual(len(retrieved), 1)
        self.assertIn("Pro", retrieved[0]["chunk"].content)
        self.assertIn("$499", retrieved[0]["chunk"].content)
        self.assertIn("100,000", retrieved[0]["chunk"].content)

    # -------------------------------------------------------------
    # TEST 4: Listing Precision vs Hallucination
    # -------------------------------------------------------------
    def test_04_listing_precision_exact_names(self):
        """Validates that doctor/service names are returned with exact source fidelity."""
        bot_d = self._seed_dental_clinic()

        retrieved = retrieve_relevant_chunks(self.db, bot_id=bot_d, query="Who are the doctors at Apex Dental and what are their specialties?")
        _, ctx = compress_and_rerank_chunks(retrieved, query="doctors", max_context_chars=4000)

        self.assertIn("Dr. Aris Thorne", ctx)
        self.assertIn("Orthodontist", ctx)
        self.assertIn("Dr. Maya Lin", ctx)
        self.assertIn("Endodontist", ctx)

    # -------------------------------------------------------------
    # TEST 5: Answer Brevity vs Retrieval Coverage (Separation of Budget & Answer Size)
    # -------------------------------------------------------------
    def test_05_answer_brevity_vs_large_retrieval(self):
        """Validates that a narrow factual query gets conciseness constraints even with large context."""
        bot_u = self._seed_university()

        query = "How much does the Executive MBA program cost?"
        retrieved = retrieve_relevant_chunks(self.db, bot_id=bot_u, query=query)
        _, ctx = compress_and_rerank_chunks(retrieved, query=query, max_context_chars=10000)

        prompt = build_rag_prompt(question=query, retrieved=retrieved, compressed_context=ctx, mode="factual")

        # Prompt must contain Rule 10 enforcing brevity
        self.assertIn("Rule 10", prompt)
        self.assertIn("CRITICAL: Answer ONLY the user's specific question", prompt)
        self.assertIn("Single factual questions", prompt)
        self.assertIn("State the direct answer concisely in 1 or 2 clear sentences", prompt)

    # -------------------------------------------------------------
    # TEST 6: Broad Questions vs Factual Questions Retrieval Scaling
    # -------------------------------------------------------------
    def test_06_retrieval_budget_scaling(self):
        """Validates that broad/catalog queries request larger context budgets than narrow factual queries."""
        mode_f, params_f = detect_retrieval_mode("What is the emergency phone number?")
        mode_c, params_c = detect_retrieval_mode("What services and treatments do you offer?")
        mode_comp, params_comp = detect_retrieval_mode("Compare BSc Computer Science with MSc Data Science")

        self.assertEqual(mode_f, RETRIEVAL_MODE_FACTUAL)
        self.assertEqual(mode_c, RETRIEVAL_MODE_CATALOG)
        self.assertEqual(mode_comp, RETRIEVAL_MODE_COMPARISON)

        self.assertLess(params_f["context_budget"], params_c["context_budget"])
        self.assertLess(params_f["target_depth"], params_c["target_depth"])
        self.assertGreaterEqual(params_c["context_budget"], 10000)

    # -------------------------------------------------------------
    # TEST 7: Balanced Multi-Entity Comparison Retrieval
    # -------------------------------------------------------------
    def test_07_balanced_comparison_retrieval(self):
        """Validates that comparison queries gather balanced evidence for both entities."""
        bot_u = self._seed_university()

        query = "Compare BSc Computer Science and MSc Data Science"
        is_comp, entities = is_comparison_query(query)
        self.assertTrue(is_comp)
        self.assertGreaterEqual(len(entities), 2)

        retrieved = retrieve_relevant_chunks(self.db, bot_id=bot_u, query=query, mode=RETRIEVAL_MODE_COMPARISON)
        _, ctx = compress_and_rerank_chunks(retrieved, query=query, mode="comparison", max_context_chars=9000)

        self.assertIn("BSc Computer Science", ctx)
        self.assertIn("MSc Data Science", ctx)
        self.assertIn("$18,000", ctx)
        self.assertIn("$24,000", ctx)

    # -------------------------------------------------------------
    # TEST 8: Actionable Purchase / Booking / Enrollment URLs & CTAs
    # -------------------------------------------------------------
    def test_08_actionable_booking_and_purchase_ctas(self):
        """Validates that purchase/booking questions provide direct actionable links from chunk metadata."""
        bot_d = self._seed_dental_clinic()

        self.assertTrue(is_purchase_intent("Where can I book an Invisalign consultation?"))
        self.assertTrue(is_purchase_intent("How do I schedule a root canal?"))

        retrieved = retrieve_relevant_chunks(self.db, bot_id=bot_d, query="Where can I book an Invisalign consultation?")
        _, ctx = compress_and_rerank_chunks(retrieved, query="book invisalign", max_context_chars=4000)

        self.assertIn("Actionable Links:", ctx)
        self.assertIn("https://apexdental.com/book?service=invisalign", ctx)

    # -------------------------------------------------------------
    # TEST 9: Multi-Turn Conversational Entity Follow-Up
    # -------------------------------------------------------------
    def test_09_conversational_followup_and_pronoun_resolution(self):
        """Validates that follow-up questions ('how long does it take?', 'where can I book it?') resolve entity context."""
        history = [
            {"role": "user", "content": "Tell me about Invisalign clear aligners."},
            {"role": "assistant", "content": "Invisalign clear aligners straighten teeth discretely over 12-18 months."},
        ]

        rewritten_q = rewrite_query_for_retrieval("How much does it cost and where can I book it?", history=history)
        self.assertIn("Invisalign", rewritten_q)

        rewritten_q2 = rewrite_query_for_retrieval("What about treatment duration?", history=history)
        self.assertIn("Invisalign", rewritten_q2)

    # -------------------------------------------------------------
    # TEST 10: Missing Information Grounding & Honesty
    # -------------------------------------------------------------
    def test_10_missing_information_grounding(self):
        """Validates that asking for non-existent information yields no false context."""
        bot_d = self._seed_dental_clinic()

        retrieved = retrieve_relevant_chunks(self.db, bot_id=bot_d, query="Do you offer pet dentistry or dog teeth cleaning?")
        _, ctx = compress_and_rerank_chunks(retrieved, query="pet dentistry dog cleaning", max_context_chars=4000)

        # Context must not claim pet dentistry exists
        self.assertNotIn("pet dentistry", ctx.lower())
        self.assertNotIn("dog teeth", ctx.lower())

    # -------------------------------------------------------------
    # TEST 11: Strict Multi-Tenant / Multi-Bot / Multi-Website Isolation
    # -------------------------------------------------------------
    def test_11_strict_tenant_isolation(self):
        """Validates zero cross-talk between Dental Clinic and University."""
        bot_d = self._seed_dental_clinic(org_id=1)
        bot_u = self._seed_university(org_id=2)

        # Querying Dental Bot about Computer Science degrees must return NO university chunks
        dental_retrieved = retrieve_relevant_chunks(self.db, bot_id=bot_d, query="What is the Computer Science degree curriculum?")
        dental_contents = " ".join([r["chunk"].content for r in dental_retrieved])
        self.assertNotIn("BSc Computer Science", dental_contents)
        self.assertNotIn("Summit", dental_contents)

        # Querying University Bot about Root Canals must return NO dental chunks
        uni_retrieved = retrieve_relevant_chunks(self.db, bot_id=bot_u, query="How much is a root canal therapy?")
        uni_contents = " ".join([r["chunk"].content for r in uni_retrieved])
        self.assertNotIn("Apex Dental", uni_contents)
        self.assertNotIn("Root Canal Therapy", uni_contents)

    # -------------------------------------------------------------
    # TEST 12: Large Crawl Scalability (30 Distinct Pages / Chunks)
    # -------------------------------------------------------------
    def test_12_large_crawl_scalability_no_silent_drop(self):
        """Validates that in a 30-document website, deep pages (e.g. Doc 29) are reliably retrieved."""
        course_bot_id = 9500 + (self.timestamp % 500)
        if course_bot_id not in self.created_bots:
            self.created_bots.append(course_bot_id)

        bot = Bot(id=course_bot_id, organization_id=4, name="Course Bot")
        self.db.merge(bot)
        self.db.commit()

        self.db.query(Chunk).filter(Chunk.bot_id == course_bot_id).delete()
        self.db.query(Document).filter(Document.bot_id == course_bot_id).delete()
        self.db.commit()

        # Seed 30 distinct course pages
        for i in range(1, 31):
            doc = Document(
                bot_id=course_bot_id,
                organization_id=4,
                source_type="website",
                filename=f"course-module-{i}",
                title=f"Course Module {i} - Syllabus",
                source_url=f"https://academy.io/courses/{i}",
                status="ready",
                processing_status="completed",
            )
            self.db.add(doc)
            self.db.commit()
            self.db.refresh(doc)

            special_topic = "Quantum Superposition & Qubits" if i == 28 else f"Standard Mathematics Topic {i}"
            self.db.add(
                Chunk(
                    bot_id=course_bot_id,
                    organization_id=4,
                    document_id=doc.id,
                    chunk_index=0,
                    content=f"[Course Module {i}]\nModule {i} covers {special_topic}. Passing grade is 75%.",
                    status="ready",
                    embedding=generate_embedding(f"Course Module {i} {special_topic}"),
                    metadata_json={"page_title": f"Course Module {i}", "source_url": f"https://academy.io/courses/{i}"},
                )
            )
        self.db.commit()

        # Query specifically for topic on Page 28
        retrieved = retrieve_relevant_chunks(self.db, bot_id=course_bot_id, query="Which course module covers Quantum Superposition & Qubits?")
        self.assertGreaterEqual(len(retrieved), 1)
        all_contents = " ".join([r["chunk"].content for r in retrieved])
        self.assertIn("Module 28", all_contents)
        self.assertIn("Quantum Superposition", all_contents)

    # -------------------------------------------------------------
    # TEST 13: Retrieval Logs & Match Reason Transparency
    # -------------------------------------------------------------
    def test_13_retrieval_match_reasons_in_metadata(self):
        """Validates that candidate chunks carry explicit match reasons for observability."""
        bot_d = self._seed_dental_clinic()

        retrieved = retrieve_relevant_chunks(self.db, bot_id=bot_d, query="Invisalign clear aligners price")
        self.assertGreaterEqual(len(retrieved), 1)
        first_item = retrieved[0]
        self.assertIn("match_reasons", first_item)
        self.assertTrue(len(first_item["match_reasons"]) >= 1)
        reason_text = " ".join(first_item["match_reasons"]).lower()
        self.assertTrue("vector" in reason_text or "lexical" in reason_text or "hybrid" in reason_text)

    # -------------------------------------------------------------
    # TEST 14: End-to-End Pipeline with Critique, Verify, and Polish
    # -------------------------------------------------------------
    def test_14_end_to_end_critique_verify_polish(self):
        """Validates the complete critique, verification, and polishing pipeline on realistic data."""
        # 1. Critique identifies robotic jargon
        bad_robotic = "According to the provided context in document 1, Invisalign costs $3,500."
        c_res = critique_response(bad_robotic, "How much is Invisalign?")
        self.assertFalse(c_res["passed"])
        self.assertTrue(c_res["grounding_issue"])

        # 2. Critique passes human-like natural answer
        good_answer = "Invisalign clear aligners cost $3,500 at Apex Dental, which includes all retainers and routine checkups."
        c_res2 = critique_response(good_answer, "How much is Invisalign?")
        self.assertTrue(c_res2["passed"])

        # 3. Polisher removes robotic filler
        filler_answer = "Certainly! Here is the answer: Invisalign costs $3,500."
        polished = polish_answer(
            bot=Bot(id=1, tone="friendly"),
            question="How much is Invisalign?",
            answer=filler_answer,
            system_instruction="You are a helpful assistant.",
        )
        self.assertNotIn("Certainly!", polished)
        self.assertNotIn("Here is the answer:", polished)
        self.assertIn("$3,500", polished)


if __name__ == "__main__":
    unittest.main()

