"""Configuration for the internal LlamaIndex retrieval service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RetrievalConfig:
    root: Path = Path(__file__).resolve().parents[1]
    corpus_file: Path | None = None
    index_directory: Path | None = None
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_query_prefix: str = "Represent this sentence for searching relevant passages: "
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    cpu_threads: int = 4
    chunk_tokens: int = 280
    chunk_overlap: int = 40
    max_query_tokens: int = 96
    max_question_characters: int = 2000
    retriever_top_k: int = 96
    rerank_candidates: int = 64
    evidence_top_k: int = 12
    context_token_budget: int = 4000
    evidence_role_weight: float = 0.0
    primary_candidate_slots: int = 16
    document_discovery_slots: int = 16
    reranker_batch_size: int = 4
    adaptive_evidence: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root).resolve())
        for field in ("corpus_file", "index_directory"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, Path(value).resolve())
        if not 0 <= self.chunk_overlap < self.chunk_tokens:
            raise ValueError("Chunk overlap must be smaller than the chunk size.")
        if self.chunk_tokens + self.max_query_tokens + 8 > 512:
            raise ValueError("Chunk and question limits must reserve the model's special tokens.")
        if not 1 <= self.evidence_top_k <= self.rerank_candidates <= self.retriever_top_k * 2:
            raise ValueError("Evidence, reranking, and retrieval limits are inconsistent.")
        if min(self.cpu_threads, self.context_token_budget, self.max_query_tokens, self.max_question_characters) < 1:
            raise ValueError("Thread and token limits must be positive.")
        if (not isinstance(self.reranker_batch_size, int) or isinstance(self.reranker_batch_size, bool)
                or not 1 <= self.reranker_batch_size <= 64):
            raise ValueError('Reranker batch size must be an integer from 1 through 64.')
        if not isinstance(self.adaptive_evidence, bool):
            raise ValueError('Adaptive evidence must be a boolean.')
        if not 0 <= self.evidence_role_weight <= 1:
            raise ValueError('Evidence role weight must be in [0, 1].')
        if not 0 <= self.primary_candidate_slots <= self.rerank_candidates:
            raise ValueError('Primary candidate slots exceed the pair budget.')
        if (not isinstance(self.document_discovery_slots, int) or isinstance(self.document_discovery_slots, bool)
                or not 0 <= self.document_discovery_slots <= min(16, self.rerank_candidates)):
            raise ValueError('Document discovery slots must be an integer from0 through16 within the pair budget.')

    @property
    def corpus_path(self) -> Path:
        return self.corpus_file or self.root / "data" / "corpus" / "corpus.jsonl"

    @property
    def index_root(self) -> Path:
        return self.index_directory or self.root / "storage" / "indexes"

    @property
    def models_path(self) -> Path:
        return self.root / "models"

    @property
    def embedding_path(self) -> Path:
        return self.models_path / "embedding"

    @property
    def reranker_path(self) -> Path:
        return self.models_path / "reranker"

    def apply_runtime_environment(self) -> None:
        """Keep cache locations local and forbid model downloads during execution."""
        os.environ["HF_HOME"] = str(self.models_path / "hf-cache")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
        os.environ["TIKTOKEN_CACHE_DIR"] = str(self.models_path / "tiktoken")
        os.environ["NLTK_DATA"] = str(self.models_path / "nltk_data")
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        os.environ["OMP_NUM_THREADS"] = str(self.cpu_threads)
        os.environ["MKL_NUM_THREADS"] = str(self.cpu_threads)
