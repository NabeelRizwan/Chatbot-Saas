# Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
# Licensed under the Apache License, Version 2.0.
# Modified for Chatbot-SaaS: explicit scoped imports; see port manifest.
import logging
from typing import Annotated, Literal, Any
from pydantic import BaseModel, Field, StringConstraints, model_validator

class RaptorConfig(BaseModel):
    """Dataset parser configuration for RAPTOR summary generation."""

    use_raptor: Annotated[bool, Field(default=False)]
    prompt: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1),
        Field(
            default="Summarize the paragraphs below without inventing facts or changing numbers.\nOutput exactly two parts in the same language as the source:\n1. First line: a concise title only.\n2. Following lines: a concise summary of the content.\nDo not output labels, Markdown headings, bullet points, or any other commentary.\n\nParagraphs:\n{cluster_content}"
        ),
    ]
    max_token: Annotated[int, Field(default=512, ge=512, le=2048)]
    clustering_threshold: Annotated[float, Field(default=0.3, ge=0.0, le=1.0)]
    clustering_ratio: Annotated[float, Field(default=0.5, ge=0.0, le=1.0)]
    max_cluster: Annotated[int, Field(default=64, ge=1, le=1024)]
    random_seed: Annotated[int, Field(default=0, ge=0)]
    scope: Annotated[Literal["file", "dataset"], Field(default="file")]
    auto_disable_for_structured_data: Annotated[bool, Field(default=True)]

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_fields(cls, value: Any) -> Any:
        """Accept old RAPTOR fields but do not retain them in the config."""
        if not isinstance(value, dict):
            return value

        normalized = dict(value)
        changed_fields = []
        for field in ("threshold", "clustering_method", "tree_builder"):
            if field in normalized:
                normalized.pop(field)
                changed_fields.append(field)
        max_token = normalized.get("max_token")
        if isinstance(max_token, (int, float)) and not isinstance(max_token, bool) and max_token < 512:
            normalized["max_token"] = 512
            changed_fields.append("max_token")
        if changed_fields:
            logging.debug("RaptorConfig normalized legacy fields: %s", sorted(changed_fields))
        return normalized
