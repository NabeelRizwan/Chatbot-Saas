"""Versioned input contracts for saved answers and independently reviewed facts."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


Identifier = str


def _unique(values: list[str], label: str) -> None:
    if any(not value.strip() for value in values) or len(set(values)) != len(values):
        raise ValueError(f"{label} must be nonblank and unique")


class Source(Record):
    id: Identifier
    excerpt: str = Field(min_length=1)
    url: str | None = None


class Fact(Record):
    id: Identifier
    text: str = Field(min_length=1)
    source_ids: list[Identifier] = Field(default_factory=list)


class Exclusion(Record):
    id: Identifier
    text: str = Field(min_length=1)


class FixtureAssertions(Record):
    """Literal regression checks, explicitly not semantic judgements."""

    contains: list[str] = Field(default_factory=list)
    excludes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def nonblank(self):
        if any(not text.strip() for text in self.contains + self.excludes):
            raise ValueError("fixture assertions cannot be blank")
        return self


class Case(Record):
    id: Identifier
    dataset: Identifier
    split: Literal["development", "heldout", "evaluation"]
    question: str = Field(min_length=1)
    reference: str = ""
    facts: list[Fact] = Field(default_factory=list)
    exclusions: list[Exclusion] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    require_citations: StrictBool = False
    fixtures: FixtureAssertions = Field(default_factory=FixtureAssertions)

    @model_validator(mode="after")
    def validate_ids(self):
        _unique([self.id], "case id")
        _unique([self.dataset], "dataset id")
        _unique([fact.id for fact in self.facts], "fact ids")
        _unique([item.id for item in self.exclusions], "exclusion ids")
        _unique([source.id for source in self.sources], "source ids")
        known = {source.id for source in self.sources}
        for fact in self.facts:
            _unique(fact.source_ids, "fact source ids")
            if set(fact.source_ids) - known:
                raise ValueError(f"fact {fact.id} references an unknown source")
        return self


class Dataset(Record):
    schema_version: Literal[1] = 1
    name: str = Field(min_length=1)
    cases: list[Case] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_cases(self):
        _unique([case.id for case in self.cases], "case ids across datasets")
        return self


class Latency(Record):
    """Independent observations in milliseconds; never inferred from each other."""

    retrieval_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    first_token_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    total_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    provider_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class Output(Record):
    case_id: Identifier
    answer: str
    status: Literal["ok", "error", "timeout"] = "ok"
    error: str | None = None
    cited_source_ids: list[Identifier] | None = None
    retrieved_source_ids: list[Identifier] | None = None
    latency: Latency = Field(default_factory=Latency)

    @model_validator(mode="after")
    def unique_sources(self):
        _unique([self.case_id], "output case id")
        if self.cited_source_ids is not None:
            _unique(self.cited_source_ids, "cited source ids")
        if self.retrieved_source_ids is not None:
            _unique(self.retrieved_source_ids, "retrieved source ids")
        return self


class Run(Record):
    schema_version: Literal[1] = 1
    name: str = Field(min_length=1)
    pipeline_revision: str
    outputs: list[Output]
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_outputs(self):
        _unique([output.case_id for output in self.outputs], "output case ids")
        return self


class FactJudgement(Record):
    fact_id: Identifier
    verdict: Literal["covered", "missing", "contradicted", "uncertain"]
    reason: str = Field(min_length=1)


class ExclusionJudgement(Record):
    exclusion_id: Identifier
    verdict: Literal["respected", "violated", "uncertain"]
    reason: str = Field(min_length=1)


class ExtraClaim(Record):
    text: str = Field(min_length=1)
    verdict: Literal["supported", "unsupported", "contradicted", "uncertain"]
    reason: str = Field(min_length=1)


class Review(Record):
    case_id: Identifier
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer: str = Field(min_length=1)
    kind: Literal["human", "assisted_review", "external_judge", "fixture"]
    status: Literal["complete", "error"]
    error: str | None = None
    all_claims_reviewed: StrictBool = False
    facts: list[FactJudgement] = Field(default_factory=list)
    exclusions: list[ExclusionJudgement] = Field(default_factory=list)
    extra_claims: list[ExtraClaim] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_judgements(self):
        _unique([item.fact_id for item in self.facts], "fact judgements")
        _unique([item.exclusion_id for item in self.exclusions], "exclusion judgements")
        return self


class ReviewSet(Record):
    schema_version: Literal[1] = 1
    reviews: list[Review] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_reviews(self):
        _unique([review.case_id for review in self.reviews], "review case ids")
        return self


def _digest(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def case_digest(case: Case) -> str:
    return _digest(case.model_dump(mode="json"))


def output_digest(output: Output) -> str:
    # Timing may be attached later; reviews bind only the exact answer and evidence IDs.
    return _digest(output.model_dump(mode="json", exclude={"latency"}))
