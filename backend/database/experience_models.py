"""Optional customer-experience records, separate from knowledge and account data."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, Text, UniqueConstraint

from database.connection import Base


def _owner_constraint(name):
    return ForeignKeyConstraint(["bot_id", "organization_id"], ["bots.id", "bots.organization_id"],
        ondelete="CASCADE", name=f"fk_{name}_bot_owner")


class ExperienceSettings(Base):
    __tablename__ = "experience_settings"
    __table_args__ = (_owner_constraint(__tablename__),)
    bot_id = Column(Integer, ForeignKey("bots.id", ondelete="CASCADE"), primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    enabled = Column(Boolean, nullable=False, default=False)
    suggested_questions = Column(JSON, nullable=False, default=list)
    hosted_chat_enabled = Column(Boolean, nullable=False, default=False)
    lead_form_enabled = Column(Boolean, nullable=False, default=False)
    approved_faq_enabled = Column(Boolean, nullable=False, default=False)
    product_cards_enabled = Column(Boolean, nullable=False, default=False)
    font_family = Column(String(16), nullable=False, default="system")
    density = Column(String(16), nullable=False, default="comfortable")
    theme = Column(String(16), nullable=False, default="light")
    corner_style = Column(String(16), nullable=False, default="rounded")
    lead_consent_text = Column(Text, nullable=False, default="I agree to be contacted about my request.")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class ApprovedFaq(Base):
    __tablename__ = "experience_faqs"
    __table_args__ = (_owner_constraint(__tablename__),)
    id = Column(Integer, primary_key=True)
    bot_id = Column(Integer, ForeignKey("bots.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    aliases = Column(JSON, nullable=False, default=list)
    # Keep the binding after source removal so a deleted source suspends its FAQ.
    source_document_id = Column(Integer, nullable=True)
    source_fingerprint = Column(String(64), nullable=True)
    source_url = Column(Text, nullable=True)
    approved = Column(Boolean, nullable=False, default=False)
    enabled = Column(Boolean, nullable=False, default=False)
    approved_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class FaqAlias(Base):
    __tablename__ = "experience_faq_aliases"
    __table_args__ = (UniqueConstraint("bot_id", "question_hash", name="uq_experience_faq_alias"),)
    id = Column(Integer, primary_key=True)
    bot_id = Column(Integer, ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    faq_id = Column(Integer, ForeignKey("experience_faqs.id", ondelete="CASCADE"), nullable=False, index=True)
    normalized_question = Column(String(1000), nullable=False)
    question_hash = Column(String(64), nullable=False)


class ExperienceProduct(Base):
    __tablename__ = "experience_products"
    __table_args__ = (_owner_constraint(__tablename__),)
    id = Column(Integer, primary_key=True)
    bot_id = Column(Integer, ForeignKey("bots.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False, default="")
    url = Column(Text, nullable=False)
    image_url = Column(Text, nullable=True)
    price_amount = Column(String(32), nullable=True)
    currency = Column(String(3), nullable=False, default="USD")
    source_document_id = Column(Integer, nullable=True)
    source_fingerprint = Column(String(64), nullable=True)
    enabled = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class ExperienceLead(Base):
    __tablename__ = "experience_leads"
    __table_args__ = (UniqueConstraint("bot_id", "email_normalized", name="uq_experience_lead_email"), _owner_constraint(__tablename__))
    id = Column(Integer, primary_key=True)
    bot_id = Column(Integer, ForeignKey("bots.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(150), nullable=False)
    email = Column(String(254), nullable=False)
    email_normalized = Column(String(254), nullable=False)
    phone = Column(String(50), nullable=True)
    message = Column(Text, nullable=False, default="")
    status = Column(String(16), nullable=False, default="new")
    consent_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class LeadSubmission(Base):
    __tablename__ = "experience_lead_submissions"
    __table_args__ = (UniqueConstraint("bot_id", "session_id", "idempotency_key", name="uq_experience_lead_submission"),)
    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("experience_leads.id", ondelete="CASCADE"), nullable=False, index=True)
    bot_id = Column(Integer, ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(String(128), nullable=False)
    idempotency_key = Column(String(100), nullable=False)
    payload_hash = Column(String(64), nullable=False)
    name = Column(String(150), nullable=False)
    phone = Column(String(50), nullable=True)
    message = Column(Text, nullable=False)
    consent_text = Column(Text, nullable=False)
    consent_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class SavedTestCase(Base):
    __tablename__ = "experience_test_cases"
    __table_args__ = (_owner_constraint(__tablename__),)
    id = Column(Integer, primary_key=True)
    bot_id = Column(Integer, ForeignKey("bots.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    question = Column(Text, nullable=False)
    expected_answer = Column(Text, nullable=False, default="")
    required_phrases = Column(JSON, nullable=False, default=list)
    forbidden_phrases = Column(JSON, nullable=False, default=list)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class SavedTestRun(Base):
    __tablename__ = "experience_test_runs"
    __table_args__ = (_owner_constraint(__tablename__),)
    id = Column(Integer, primary_key=True)
    bot_id = Column(Integer, ForeignKey("bots.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    status = Column(String(16), nullable=False, default="pending")
    lease_token = Column(String(64), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    provider = Column(String(100), nullable=False)
    model = Column(String(200), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class SavedTestResult(Base):
    __tablename__ = "experience_test_results"
    __table_args__ = (UniqueConstraint("run_id", "position", name="uq_experience_test_position"),)
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("experience_test_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    case_id = Column(Integer, nullable=False)
    position = Column(Integer, nullable=False)
    question = Column(Text, nullable=False)
    expected_answer = Column(Text, nullable=False)
    required_phrases = Column(JSON, nullable=False)
    forbidden_phrases = Column(JSON, nullable=False)
    answer = Column(Text, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    status = Column(String(24), nullable=False, default="pending")
    missing_phrases = Column(JSON, nullable=False, default=list)
    forbidden_matches = Column(JSON, nullable=False, default=list)
    sources = Column(JSON, nullable=False, default=list)
    error = Column(Text, nullable=True)
