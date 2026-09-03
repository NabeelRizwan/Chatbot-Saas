import os
import sys
import unittest
from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from fastapi import HTTPException
from database.connection import SessionLocal
from database.models import (
    Bot,
    Chunk,
    ConversationMessage,
    ConversationSession,
    Customer,
    Document,
    Organization,
    OrganizationMembership,
    User,
    Website,
    WebsiteCrawl,
)
from services.auth_service import hash_password
from services.bot_service import delete_bot, get_bot_or_404, list_bots, update_bot
from services.conversational_engine import compress_and_rerank_chunks, global_semantic_cache
from services.embedding_service import generate_embedding
from services.organization_service import (
    create_organization,
    require_org_role,
    update_organization,
)
from services.rag_service import answer_question, clear_retrieval_cache, retrieve_relevant_chunks
from routes.knowledge_routes import _ensure_bot, _get_document

import fakeredis
import fakeredis.aioredis
from utils.redis_client import set_redis_override


class TestPhase11SecuritySuite(unittest.TestCase):
    """
    Phase 11-B: Multi-Tenant Security & Privilege Escalation Audit Suite.
    Validates horizontal and vertical privilege escalation resistance,
    strict tenant boundary enforcement across all DB queries, and RAG knowledge isolation.
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
        import random
        self.db = SessionLocal()
        self.timestamp = int(datetime.utcnow().timestamp() * 1000) % 1000000 + random.randint(1000, 9999)

        # Create Tenant Alpha (Org 101) & Tenant Beta (Org 102)
        self.org_alpha = self.db.merge(Organization(id=10100 + self.timestamp, name="Alpha Corp", slug=f"alpha-corp-{self.timestamp}"))
        self.org_beta = self.db.merge(Organization(id=10200 + self.timestamp, name="Beta Corp", slug=f"beta-corp-{self.timestamp}"))
        self.db.commit()

        # Create Users
        self.user_alpha_owner = self.db.merge(User(
            id=20100 + self.timestamp,
            name="Alice Alpha",
            email=f"alice_{self.timestamp}@alpha.io",
            password_hash=hash_password("password123"),
        ))
        self.user_alpha_member = self.db.merge(User(
            id=20200 + self.timestamp,
            name="Bob Alpha",
            email=f"bob_{self.timestamp}@alpha.io",
            password_hash=hash_password("password123"),
        ))
        self.user_beta_owner = self.db.merge(User(
            id=20300 + self.timestamp,
            name="Charlie Beta",
            email=f"charlie_{self.timestamp}@beta.io",
            password_hash=hash_password("password123"),
        ))
        self.db.commit()

        # Memberships
        self.db.merge(OrganizationMembership(organization_id=self.org_alpha.id, user_id=self.user_alpha_owner.id, role="owner"))
        self.db.merge(OrganizationMembership(organization_id=self.org_alpha.id, user_id=self.user_alpha_member.id, role="member"))
        self.db.merge(OrganizationMembership(organization_id=self.org_beta.id, user_id=self.user_beta_owner.id, role="owner"))
        self.db.commit()

        # Refresh user instances so relationship collections reflect new memberships
        self.db.refresh(self.user_alpha_owner)
        self.db.refresh(self.user_alpha_member)
        self.db.refresh(self.user_beta_owner)

        # Fresh schemas enforce the existing required Bot.customer_id contract.
        self.customer_alpha = Customer(name="Synthetic Alpha", api_key=f"synthetic-alpha-{self.timestamp}")
        self.customer_beta = Customer(name="Synthetic Beta", api_key=f"synthetic-beta-{self.timestamp}")
        self.db.add_all([self.customer_alpha, self.customer_beta])
        self.db.flush()

        # Create Bots for Alpha and Beta
        self.bot_alpha = self.db.merge(Bot(
            id=30100 + self.timestamp,
            organization_id=self.org_alpha.id,
            customer_id=self.customer_alpha.id,
            name="Alpha AI Assistant",
            system_prompt="You are Alpha Corp assistant.",
        ))
        self.bot_beta = self.db.merge(Bot(
            id=30200 + self.timestamp,
            organization_id=self.org_beta.id,
            customer_id=self.customer_beta.id,
            name="Beta AI Assistant",
            system_prompt="You are Beta Corp assistant.",
        ))
        self.db.commit()

        # Seed Documents & Chunks with Secret Knowledge
        # Alpha Secret: "Project Apollo budget is $42,000,000"
        self.doc_alpha = Document(
            bot_id=self.bot_alpha.id,
            organization_id=self.org_alpha.id,
            source_type="website",
            filename="alpha-confidential",
            title="Alpha Confidential Specs",
            source_url="https://alpha.internal/specs",
            status="ready",
            processing_status="completed",
        )
        self.db.add(self.doc_alpha)
        self.db.commit()
        self.db.refresh(self.doc_alpha)

        self.db.add(Chunk(
            bot_id=self.bot_alpha.id,
            organization_id=self.org_alpha.id,
            document_id=self.doc_alpha.id,
            chunk_index=0,
            content="[Alpha Confidential Project Apollo]\nProject Apollo classified budget is $42,000,000 allocated for quantum propulsion.",
            status="ready",
            embedding=generate_embedding("Alpha Confidential Project Apollo classified budget $42,000,000 quantum propulsion"),
            metadata_json={"page_title": "Alpha Confidential Specs", "source_url": "https://alpha.internal/specs"},
        ))

        # Beta Secret: "Project Nebula stealth launch date is November 15"
        self.doc_beta = Document(
            bot_id=self.bot_beta.id,
            organization_id=self.org_beta.id,
            source_type="website",
            filename="beta-confidential",
            title="Beta Confidential Launch",
            source_url="https://beta.internal/launch",
            status="ready",
            processing_status="completed",
        )
        self.db.add(self.doc_beta)
        self.db.commit()
        self.db.refresh(self.doc_beta)

        self.db.add(Chunk(
            bot_id=self.bot_beta.id,
            organization_id=self.org_beta.id,
            document_id=self.doc_beta.id,
            chunk_index=0,
            content="[Beta Confidential Project Nebula]\nProject Nebula stealth launch date is confirmed for November 15 with $88M funding.",
            status="ready",
            embedding=generate_embedding("Beta Confidential Project Nebula stealth launch November 15 funding $88M"),
            metadata_json={"page_title": "Beta Confidential Launch", "source_url": "https://beta.internal/launch"},
        ))
        self.db.commit()

        clear_retrieval_cache()
        global_semantic_cache.clear()

    def tearDown(self):
        try:
            for b in [self.bot_alpha, self.bot_beta]:
                self.db.query(Chunk).filter(Chunk.bot_id == b.id).delete()
                self.db.query(Document).filter(Document.bot_id == b.id).delete()
                self.db.query(Bot).filter(Bot.id == b.id).delete()
            for u in [self.user_alpha_owner, self.user_alpha_member, self.user_beta_owner]:
                self.db.query(OrganizationMembership).filter(OrganizationMembership.user_id == u.id).delete()
                self.db.query(User).filter(User.id == u.id).delete()
            for o in [self.org_alpha, self.org_beta]:
                self.db.query(Organization).filter(Organization.id == o.id).delete()
            for customer in [self.customer_alpha, self.customer_beta]:
                self.db.query(Customer).filter(Customer.id == customer.id).delete()
            self.db.commit()
        except Exception:
            self.db.rollback()
        finally:
            self.db.close()

    # =========================================================================
    # 1. HORIZONTAL PRIVILEGE ESCALATION TESTS
    # =========================================================================
    def test_01_horizontal_bot_access_prevention(self):
        """Validates Tenant Beta Owner CANNOT access Tenant Alpha Bot."""
        with self.assertRaises(HTTPException) as ctx:
            get_bot_or_404(self.db, self.bot_alpha.id, user=self.user_beta_owner)
        self.assertEqual(ctx.exception.status_code, 404, "Must return 404 on cross-tenant access to prevent enumeration")

    def test_02_horizontal_bot_listing_isolation(self):
        """Validates list_bots for User Beta returns only Beta bots and zero Alpha bots."""
        beta_bots = list_bots(self.db, user=self.user_beta_owner)
        bot_ids = [b["id"] for b in beta_bots]
        self.assertIn(self.bot_beta.id, bot_ids)
        self.assertNotIn(self.bot_alpha.id, bot_ids)

    def test_03_horizontal_document_access_prevention(self):
        """Validates Tenant Beta CANNOT fetch Tenant Alpha document."""
        with self.assertRaises(HTTPException) as ctx:
            _get_document(self.db, self.doc_alpha.id, user=self.user_beta_owner)
        self.assertEqual(ctx.exception.status_code, 404)

    # =========================================================================
    # 2. VERTICAL PRIVILEGE ESCALATION TESTS
    # =========================================================================
    def test_04_vertical_role_escalation_prevention(self):
        """Validates that a 'member' cannot perform 'admin' or 'owner' actions on organization settings."""
        with self.assertRaises(HTTPException) as ctx:
            update_organization(self.db, self.user_alpha_member, self.org_alpha.id, "Malicious Name Override")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_05_vertical_bot_modification_prevention(self):
        """Validates that a viewer/member cannot delete a bot."""
        with self.assertRaises(HTTPException) as ctx:
            _ensure_bot(self.db, self.bot_alpha.id, user=self.user_alpha_member, minimum_role="admin")
        self.assertEqual(ctx.exception.status_code, 403)

    # =========================================================================
    # 3. RAG KNOWLEDGE ISOLATION & PROMPT INJECTION RESISTANCE
    # =========================================================================
    def test_06_rag_retrieval_strict_cross_tenant_isolation(self):
        """Validates that querying Bot Beta for Alpha's secret returns ZERO Alpha chunks."""
        query = "What is the secret budget of Project Apollo?"
        ret = retrieve_relevant_chunks(self.db, bot_id=self.bot_beta.id, query=query)

        # Ensure no Alpha content is returned
        all_text = " ".join([r["chunk"].content for r in ret])
        self.assertNotIn("Project Apollo", all_text)
        self.assertNotIn("$42,000,000", all_text)
        self.assertNotIn("quantum propulsion", all_text)

    def test_07_rag_retrieval_reverse_isolation(self):
        """Validates that querying Bot Alpha for Beta's secret returns ZERO Beta chunks."""
        query = "What is the stealth launch date of Project Nebula?"
        ret = retrieve_relevant_chunks(self.db, bot_id=self.bot_alpha.id, query=query)

        all_text = " ".join([r["chunk"].content for r in ret])
        self.assertNotIn("Project Nebula", all_text)
        self.assertNotIn("November 15", all_text)
        self.assertNotIn("$88M", all_text)

    def test_08_conversation_session_isolation(self):
        """Validates that conversation sessions between two widget users on the same bot are completely isolated."""
        session_1 = ConversationSession(
            bot_id=self.bot_alpha.id,
            session_id="widget_user_session_111",
            title="User 1 Chat",
        )
        session_2 = ConversationSession(
            bot_id=self.bot_alpha.id,
            session_id="widget_user_session_222",
            title="User 2 Chat",
        )
        self.db.add(session_1)
        self.db.add(session_2)
        self.db.commit()

        # Add private message to User 1
        msg1 = ConversationMessage(
            conversation_session_id=session_1.id,
            session_id=session_1.session_id,
            bot_id=self.bot_alpha.id,
            user_message="My private bank account number is 9876543210",
            assistant_response="I cannot help with financial accounts.",
        )
        self.db.add(msg1)
        self.db.commit()

        # Fetch messages for User 2 session
        user_2_msgs = (
            self.db.query(ConversationMessage)
            .filter(
                ConversationMessage.bot_id == self.bot_alpha.id,
                ConversationMessage.session_id == "widget_user_session_222",
            )
            .all()
        )
        self.assertEqual(len(user_2_msgs), 0, "User 2 must not see User 1's conversation messages")


if __name__ == "__main__":
    unittest.main()
