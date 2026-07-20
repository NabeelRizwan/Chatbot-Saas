from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, Float, ForeignKey,
    Index, Integer, JSON, LargeBinary, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from database.connection import Base

EMBEDDING_DIMENSIONS = 768


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    api_key = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    bots = relationship("Bot", back_populates="customer", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    password_hash = Column(Text, nullable=False)
    disabled = Column(Boolean, default=False, nullable=False)
    bio = Column(Text, nullable=True)
    avatar_url = Column(Text, nullable=True)
    preferences = Column(JSON, default=dict, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    is_admin = Column(Boolean, default=False, nullable=False)

    customer = relationship("Customer")
    memberships = relationship("OrganizationMembership", back_populates="user", cascade="all, delete-orphan")
    refresh_sessions = relationship("AuthRefreshSession", back_populates="user", cascade="all, delete-orphan")


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=False)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    memberships = relationship("OrganizationMembership", back_populates="organization", cascade="all, delete-orphan")
    bots = relationship("Bot", back_populates="organization")
    documents = relationship("Document", back_populates="organization")
    subscription = relationship("Subscription", back_populates="organization", uselist=False, cascade="all, delete-orphan")


class OrganizationMembership(Base):
    __tablename__ = "organization_memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_members_user"),
    )

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String, default="member", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    organization = relationship("Organization", back_populates="memberships")
    user = relationship("User", back_populates="memberships")


class OrganizationInvitation(Base):
    __tablename__ = "organization_invitations"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    email = Column(String, nullable=False, index=True)
    role = Column(String, default="member", nullable=False)
    token_hash = Column(String, unique=True, nullable=False, index=True)
    invited_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String, default="pending", nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    responded_at = Column(DateTime, nullable=True)


class AuthRefreshSession(Base):
    __tablename__ = "auth_refresh_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String, unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="refresh_sessions")


class Plan(Base):
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    monthly_price_cents = Column(Integer, default=0, nullable=False)
    limits_json = Column(JSON, default=dict, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), unique=True, nullable=False, index=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False, index=True)
    status = Column(String, default="active", nullable=False, index=True)
    provider = Column(String, default="manual", nullable=False)
    provider_subscription_id = Column(String, nullable=True, index=True)
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    organization = relationship("Organization", back_populates="subscription")
    plan = relationship("Plan")


class UsageDaily(Base):
    __tablename__ = "usage_daily"
    __table_args__ = (
        UniqueConstraint("organization_id", "date", name="uq_usage_daily_org_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    messages_sent = Column(Integer, default=0, nullable=False)
    tokens_used = Column(Integer, default=0, nullable=False)
    embeddings_used = Column(Integer, default=0, nullable=False)
    document_uploads = Column(Integer, default=0, nullable=False)
    storage_bytes = Column(Integer, default=0, nullable=False)
    active_bots = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class UsageMonthly(Base):
    __tablename__ = "usage_monthly"
    __table_args__ = (
        UniqueConstraint("organization_id", "month", name="uq_usage_monthly_org_month"),
    )

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    month = Column(String, nullable=False, index=True)
    messages_sent = Column(Integer, default=0, nullable=False)
    tokens_used = Column(Integer, default=0, nullable=False)
    embeddings_used = Column(Integer, default=0, nullable=False)
    document_uploads = Column(Integer, default=0, nullable=False)
    storage_bytes = Column(Integer, default=0, nullable=False)
    active_bots = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Bot(Base):
    __tablename__ = "bots"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    description = Column(Text, nullable=True)
    category = Column(String, default="general", nullable=True)
    avatar_url = Column(Text, nullable=True)
    status = Column(String, default="active", nullable=True)
    tone = Column(String, default="neutral", nullable=True)
    capabilities = Column(JSON, default=dict, nullable=True)
    system_prompt = Column(Text, nullable=True)
    provider = Column(String, default="gemini", nullable=False)
    model_name = Column(String, default="gemini-2.5-flash", nullable=False)
    provider_api_key = Column(Text, nullable=True)
    welcome_message = Column(Text, nullable=True)
    widget_config = Column(JSON, default=dict, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    customer = relationship("Customer", back_populates="bots")
    organization = relationship("Organization", back_populates="bots")
    documents = relationship("Document", back_populates="bot", cascade="all, delete-orphan")
    conversation_sessions = relationship("ConversationSession", back_populates="bot", cascade="all, delete-orphan")
    # 1:1 back-ref from PlatformApiKey.allocated_to_bot_id
    platform_api_key = relationship(
        "PlatformApiKey",
        back_populates="bot",
        uselist=False,
        foreign_keys="PlatformApiKey.allocated_to_bot_id",
    )


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("bot_id", "source_url", name="uq_documents_bot_source_url"),
    )

    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(Integer, ForeignKey("bots.id"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    filename = Column(String, nullable=False)
    source_type = Column(String, nullable=False)
    source_url = Column(Text, nullable=True)
    title = Column(String, nullable=True)
    raw_text = Column(Text, nullable=True)
    file_path = Column(Text, nullable=True)
    file_size = Column(Integer, nullable=True)
    processing_status = Column(String, default="pending", nullable=False, index=True)
    processing_error = Column(Text, nullable=True)
    chunk_count = Column(Integer, default=0, nullable=False)
    token_count = Column(Integer, default=0, nullable=False)
    metadata_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    bot = relationship("Bot", back_populates="documents")
    organization = relationship("Organization", back_populates="documents")
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    bot_id = Column(Integer, ForeignKey("bots.id"), nullable=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    chunk_index = Column(Integer, default=0, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    metadata_json = Column(JSON, default=dict, nullable=False)
    token_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    document = relationship("Document", back_populates="chunks")
    bot = relationship("Bot")


DocumentChunk = Chunk


class ConversationSession(Base):
    __tablename__ = "conversation_sessions"
    __table_args__ = (
        UniqueConstraint("bot_id", "session_id", name="uq_conversation_sessions_bot_session"),
    )

    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(Integer, ForeignKey("bots.id"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    session_id = Column(String, nullable=False, index=True)
    title = Column(String, nullable=True)
    is_archived = Column(Boolean, default=False, nullable=True)
    is_pinned = Column(Boolean, default=False, nullable=True)
    shared_token = Column(String, unique=True, nullable=True, index=True)
    channel = Column(String, default="widget", nullable=False)
    status = Column(String, default="open", nullable=True)
    tags = Column(JSON, default=list, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    bot = relationship("Bot", back_populates="conversation_sessions")
    messages = relationship("ConversationMessage", back_populates="session", cascade="all, delete-orphan")


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_session_id = Column(Integer, ForeignKey("conversation_sessions.id"), nullable=False, index=True)
    bot_id = Column(Integer, ForeignKey("bots.id"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    session_id = Column(String, nullable=False, index=True)
    user_message = Column(Text, nullable=True)
    assistant_response = Column(Text, nullable=True)
    response_time_ms = Column(Integer, nullable=True)
    token_usage = Column(JSON, nullable=True)
    status = Column(String, default="success", nullable=False, index=True)
    error_message = Column(Text, nullable=True)
    is_fallback = Column(Boolean, default=False, nullable=True)
    had_knowledge_hit = Column(Boolean, default=False, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    session = relationship("ConversationSession", back_populates="messages")
    bot = relationship("Bot")


class BotAnalyticsDaily(Base):
    __tablename__ = "bot_analytics_daily"
    __table_args__ = (
        UniqueConstraint("bot_id", "date", name="uq_bot_analytics_daily_bot_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(Integer, ForeignKey("bots.id"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    date = Column(Date, nullable=False, index=True)
    conversation_count = Column(Integer, default=0, nullable=False)
    message_count = Column(Integer, default=0, nullable=False)
    average_response_time_ms = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    bot = relationship("Bot")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    action = Column(String, nullable=False)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


# ─────────────────────────────────────────────────────────────────────────────
# Platform API Key Pool
# ─────────────────────────────────────────────────────────────────────────────

class PlatformApiKey(Base):
    """
    Admin-managed provider API keys allocated to individual bots.

    Rules enforced here and in platform_key_service:
    - Keys are NEVER generated by the platform; admins upload them manually.
    - One key → one bot (1:1 allocation enforced by UNIQUE constraint).
    - Keys are stored encrypted at rest (Fernet symmetric encryption).
    - Status lifecycle: available ↔ assigned | disabled.
    - Usage metrics tracked per key for audit and capacity planning.
    """
    __tablename__ = "platform_api_keys"
    __table_args__ = (
        Index("ix_platform_api_keys_provider", "provider"),
        Index("ix_platform_api_keys_status", "status"),
        Index("ix_platform_api_keys_allocated_to_bot_id", "allocated_to_bot_id"),
    )

    id = Column(Integer, primary_key=True, index=True)

    # Provider identifier: "gemini" | "openai" | "claude" | "grok"
    provider = Column(String, nullable=False)

    # Fernet-encrypted API key bytes — never stored in plaintext
    encrypted_key = Column(LargeBinary, nullable=False)

    # Optional human-readable label / description for admin UI
    label = Column(String, nullable=True)

    # Lifecycle status
    # "available" → free for allocation
    # "assigned"  → dedicated to one bot
    # "disabled"  → administratively disabled; cannot be allocated
    status = Column(String, default="available", nullable=False)

    # 1:1 bot allocation — UNIQUE constraint prevents double-allocation
    allocated_to_bot_id = Column(
        Integer,
        ForeignKey("bots.id", ondelete="SET NULL"),
        unique=True,
        nullable=True,
    )

    # Usage metrics — incremented by LLM router on every successful call
    requests_count = Column(BigInteger, default=0, nullable=False)
    tokens_used = Column(BigInteger, default=0, nullable=False)
    last_used_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    bot = relationship(
        "Bot",
        back_populates="platform_api_key",
        foreign_keys=[allocated_to_bot_id],
    )
