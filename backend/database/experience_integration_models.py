from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKeyConstraint, Integer, JSON

from database.connection import Base


class ExperienceIntegration(Base):
    __tablename__ = "experience_integrations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["bot_id", "organization_id"], ["bots.id", "bots.organization_id"],
            ondelete="CASCADE", name="fk_experience_integrations_bot_owner",
        ),
    )

    bot_id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True)
    config_json = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
