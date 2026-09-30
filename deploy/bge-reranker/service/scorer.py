"""Pinned official CrossEncoder inference with complete-input validation.

Sentence Transformers owns tokenization and scoring. This adapter owns model
identity, resource selection and an all-pairs preflight; it adds no rank formula.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
from math import isfinite
from pathlib import Path

MODEL = "BAAI/bge-reranker-v2-m3"
REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
MAX_TOKENS = 8192
MAX_DOCUMENTS = 32
MAX_BODY_BYTES = 1048576
PROCESSING = {"text": {"truncation": False, "max_length": MAX_TOKENS}}


class InputError(ValueError):
    """Safe category only; never include user input in errors."""


class PairTooLong(InputError):
    pass


def validate_request(value):
    if not isinstance(value, dict) or set(value) != {"query", "documents"}:
        raise InputError("INVALID_REQUEST")
    query, documents = value["query"], value["documents"]
    if not isinstance(query, str) or not query.strip() or len(query) > 16384:
        raise InputError("INVALID_QUERY")
    if not isinstance(documents, list) or not 1 <= len(documents) <= MAX_DOCUMENTS:
        raise InputError("INVALID_DOCUMENT_COUNT")
    if any(not isinstance(document, str) or not document.strip() for document in documents):
        raise InputError("INVALID_DOCUMENT")
    return query, documents


def verify_artifacts(model_dir):
    root = Path(model_dir).resolve(strict=True)
    records = json.loads(Path(__file__).with_name("model-artifacts.json").read_text())
    for row in records:
        target = root / row["path"]
        if not target.is_file() or target.stat().st_size != row["bytes"]:
            raise RuntimeError("MODEL_ARTIFACT_MISMATCH")
        with target.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest != row["sha256"]:
            raise RuntimeError("MODEL_ARTIFACT_MISMATCH")
    # Reject additional model configuration/code instead of letting an unpinned
    # local file change the library's loader behavior.
    allowed = {row["path"] for row in records}
    if any(path.is_file() and path.name not in allowed for path in root.iterdir()):
        raise RuntimeError("UNEXPECTED_MODEL_ARTIFACT")
    return root


def package_gate(device):
    expected = {"sentence-transformers": "6.1.0", "transformers": "5.17.0",
                "huggingface-hub": "1.7.2",
                "torch": "2.10.0+cpu" if device == "cpu" else "2.10.0+cu126"}
    for name, version in expected.items():
        if importlib.metadata.version(name) != version:
            raise RuntimeError("RUNTIME_PACKAGE_MISMATCH")


class BGEScorer:
    """One model per process. Caller serializes score operations."""

    def __init__(self, model_dir, *, device, threads=2):
        if device not in {"cpu", "cuda"}:
            raise ValueError("DEVICE_MUST_BE_CPU_OR_CUDA")
        if type(threads) is not int or not 1 <= threads <= 8:
            raise ValueError("THREADS_MUST_BE_1_TO_8")
        self.model_dir, self.device, self.threads = Path(model_dir), device, threads
        self.model = None

    @property
    def loaded(self):
        return self.model is not None

    def load(self):
        package_gate(self.device)
        root = verify_artifacts(self.model_dir)
        import torch
        from sentence_transformers import CrossEncoder

        torch.set_num_threads(self.threads)
        torch.set_num_interop_threads(1)
        if self.device == "cuda":
            if not torch.cuda.is_available():
                raise RuntimeError("CONFIGURED_CUDA_UNAVAILABLE")
            major, minor = torch.cuda.get_device_capability(0)
            if f"sm_{major}{minor}" not in torch.cuda.get_arch_list():
                raise RuntimeError("CONFIGURED_CUDA_ARCHITECTURE_UNSUPPORTED")
        model = CrossEncoder(str(root), device=self.device, trust_remote_code=False,
                             local_files_only=True, max_length=MAX_TOKENS,
                             model_kwargs={"dtype": torch.float32, "attn_implementation": "sdpa"},
                             activation_fn=torch.nn.Identity())
        if model.default_prompt_name is not None or model.prompts:
            raise RuntimeError("UNEXPECTED_MODEL_PROMPT_CONFIGURATION")
        model.eval()
        self.model = model

    def score(self, query, documents):
        validate_request({"query": query, "documents": documents})
        if self.model is None:
            raise RuntimeError("MODEL_NOT_LOADED")
        pairs = [(query, document) for document in documents]
        lengths = []
        # Same official processor/settings as predict, batch size 1. Preflight
        # every pair before any inference: no partial result or truncation.
        for pair in pairs:
            features = self.model.preprocess([pair], prompt=None, processing_kwargs=PROCESSING)
            ids, mask = features.get("input_ids"), features.get("attention_mask")
            if ids is None or mask is None or ids.ndim != 2 or ids.shape != mask.shape:
                raise RuntimeError("MODEL_PREPROCESSING_MISMATCH")
            row = [int(n) for n in mask.sum(dim=1).tolist()]
            if len(row) != 1 or row[0] < 1 or int(ids.shape[1]) != row[0]:
                raise RuntimeError("MODEL_PREPROCESSING_MISMATCH")
            if row[0] > MAX_TOKENS:
                raise PairTooLong("PAIR_TOKEN_LIMIT_EXCEEDED")
            lengths.extend(row)
        scores = []
        for pair in pairs:
            values = self.model.predict([pair], prompt=None, batch_size=1,
                                       show_progress_bar=False, processing_kwargs=PROCESSING,
                                       convert_to_numpy=True).reshape(-1).tolist()
            if len(values) != 1 or type(values[0]) not in (int, float) or not isfinite(values[0]):
                raise RuntimeError("MODEL_SCORE_MISMATCH")
            scores.append(float(values[0]))
        return {"model": MODEL, "revision": REVISION, "scores": scores, "token_counts": lengths}
