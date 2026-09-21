# Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
# Licensed under the Apache License, Version 2.0.
# Modified for Chatbot-SaaS: explicit scoped imports; see port manifest.
from typing import Annotated, Literal
from pydantic import BaseModel, Field

class GraphragConfig(BaseModel):
    """Dataset parser configuration for GraphRAG generation."""

    use_graphrag: Annotated[bool, Field(default=False)]
    entity_types: Annotated[list[str], Field(default_factory=lambda: ["organization", "person", "geo", "event", "category"])]
    method: Annotated[Literal["light", "general", "ner"], Field(default="light")]
    community: Annotated[bool, Field(default=False)]
    resolution: Annotated[bool, Field(default=False)]
    batch_chunk_token_size: Annotated[int, Field(default=4096, ge=512, le=8196)]
    retry_attempts: Annotated[int, Field(default=2, ge=1, le=10)]
    retry_backoff_seconds: Annotated[float, Field(default=2.0, ge=0.0, le=600.0)]
    retry_backoff_max_seconds: Annotated[float, Field(default=60.0, ge=0.0, le=3600.0)]
    build_subgraph_timeout_per_chunk_seconds: Annotated[int, Field(default=300, ge=1, le=86400)]
    build_subgraph_min_timeout_seconds: Annotated[int, Field(default=600, ge=1, le=86400)]
    merge_timeout_seconds: Annotated[int, Field(default=180, ge=0, le=86400)]
    resolution_timeout_seconds: Annotated[int, Field(default=1800, ge=0, le=86400)]
    community_timeout_seconds: Annotated[int, Field(default=1800, ge=0, le=86400)]
    lock_acquire_timeout_seconds: Annotated[int, Field(default=600, ge=0, le=86400)]
