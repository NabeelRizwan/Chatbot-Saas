from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from services.knowledge_policy import PipelineSnapshot


class ChatExecutionError(RuntimeError):
    pass


class UndispatchedChatExecutionError(ChatExecutionError):
    """Admission was rejected before scheduling; reservation was safely checked."""
    pass


class SavedTestReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: int = Field(gt=0)
    result_id: int = Field(gt=0)
    lease_token: str = Field(min_length=1, max_length=64)


class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: int = Field(gt=0)
    bot_id: int = Field(gt=0)
    session_id: str = Field(min_length=1, max_length=200)
    turn_id: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=20000)
    history: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    top_k: int = Field(default=5, ge=1, le=100)
    retry: bool = False
    usage_key: str | None = Field(default=None, max_length=500)
    pipeline_snapshot: PipelineSnapshot | None = None
    channel: Literal["widget", "playground", "playground_stream", "api", "api_stream", "saved_test"] = "widget"
    saved_test: SavedTestReference | None = None

    @model_validator(mode="after")
    def validate_pipeline_tenant(self):
        if self.pipeline_snapshot and self.pipeline_snapshot.organization_id != self.organization_id:
            raise ValueError("Knowledge policy tenant mismatch")
        if (self.channel == "saved_test") != (self.saved_test is not None):
            raise ValueError("Saved test execution requires its trusted result reference")
        return self

    @property
    def accepted_pipeline(self) -> PipelineSnapshot:
        # Old payloads were accepted before per-organisation routing existed.
        return self.pipeline_snapshot or PipelineSnapshot(
            organization_id=self.organization_id, pipeline="og", revision=0)

    @property
    def job_id(self) -> str:
        value = f"{self.organization_id}:{self.bot_id}:{self.session_id}:{self.turn_id}"
        return sha256(value.encode()).hexdigest()

    @property
    def bot_key(self) -> str:
        return f"{self.organization_id}:{self.bot_id}"

    @property
    def conversation_key(self) -> str:
        return f"{self.bot_key}:{sha256(self.session_id.encode()).hexdigest()}"


class DispatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    dispatch_id: str
    bot_key: str = Field(pattern=r"^[1-9][0-9]*:[1-9][0-9]*$")
    conversation_key: str


@dataclass(frozen=True)
class JobReference:
    job_id: str
    state: str
    run_id: str | None = None
