"""Server-owned, immutable organisation policy accepted for one unit of work."""
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Pipeline = Literal["og", "rag2_improved"]


class PipelineSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    organization_id: int = Field(gt=0)
    pipeline: Pipeline
    revision: int = Field(ge=0)


_policy: ContextVar[PipelineSnapshot | None] = ContextVar("knowledge_pipeline_policy", default=None)


def current_pipeline_policy() -> PipelineSnapshot | None:
    return _policy.get()


@contextmanager
def pipeline_policy_context(snapshot: PipelineSnapshot):
    snapshot = PipelineSnapshot.model_validate(snapshot)
    token = _policy.set(snapshot)
    try:
        yield snapshot
    finally:
        _policy.reset(token)


def resolve_pipeline_policy(db, bot_or_org) -> PipelineSnapshot:
    from database.models import Organization
    organization_id = (bot_or_org.id if isinstance(bot_or_org, Organization)
                       else bot_or_org.organization_id)
    if not isinstance(organization_id, int) or organization_id <= 0:
        raise ValueError("A tenant-owned knowledge scope is required")
    # Select columns so a long-lived ORM identity-map cannot reuse an old policy.
    row = db.query(Organization.knowledge_pipeline, Organization.knowledge_pipeline_revision).filter(
        Organization.id == organization_id).first()
    if row is None:
        raise ValueError("Knowledge organisation is no longer available")
    return PipelineSnapshot(organization_id=organization_id, pipeline=row[0], revision=row[1])


def capture_pipeline_policy(db, bot_or_org) -> PipelineSnapshot:
    current = current_pipeline_policy()
    if current is None:
        return resolve_pipeline_policy(db, bot_or_org)
    from database.models import Organization
    organization_id = (bot_or_org.id if isinstance(bot_or_org, Organization)
                       else bot_or_org.organization_id)
    if organization_id != current.organization_id:
        raise ValueError("Knowledge policy tenant mismatch")
    return current
