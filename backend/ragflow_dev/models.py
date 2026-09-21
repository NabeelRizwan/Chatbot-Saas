"""Pinned, real CPU inference. No provider credentials or automatic downloads."""
import hashlib
import time
from pathlib import Path
import numpy as np
from ragflow_derived.models import CallableEmbeddingAdapter, CallableRerankerAdapter
from .config import PROFILE, DIMENSION


class CpuModels:
    def __init__(self, root="/opt/models"):
        import torch
        from transformers import AutoTokenizer, AutoModel, AutoModelForSequenceClassification
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        self.torch = torch
        self.embedding_tokenizer = AutoTokenizer.from_pretrained(str(Path(root) / "embedding"), local_files_only=True)
        self.embedding_model = AutoModel.from_pretrained(str(Path(root) / "embedding"),
            local_files_only=True, use_safetensors=True).to("cpu").eval()
        self.rerank_tokenizer = AutoTokenizer.from_pretrained(str(Path(root) / "reranker"), local_files_only=True)
        self.rerank_model = AutoModelForSequenceClassification.from_pretrained(str(Path(root) / "reranker"),
            local_files_only=True, use_safetensors=True).to("cpu").eval()
        self.embedding = CallableEmbeddingAdapter(PROFILE, DIMENSION, self.encode, lambda q: self.encode([q])[0])
        # Startup smoke uses the same real callbacks as later requests.
        vectors = self.encode(["A synthetic library lends books."])
        scores = self.score("Where can I borrow a book?", ["The library lends books."])
        if vectors.shape != (1, DIMENSION) or not np.isfinite(vectors).all() or not np.isfinite(scores).all():
            raise RuntimeError("MODEL_STARTUP_FAILED")

    def encode(self, texts):
        batches = []
        with self.torch.inference_mode():
            for offset in range(0, len(texts), 8):
                features = self.embedding_tokenizer(texts[offset:offset + 8], padding=True, truncation=True,
                                                    max_length=256, return_tensors="pt")
                values = self.embedding_model(**features).last_hidden_state
                mask = features["attention_mask"].unsqueeze(-1).expand(values.size()).float()
                pooled = (values * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
                batches.append(self.torch.nn.functional.normalize(pooled, p=2, dim=1).cpu().numpy())
        return np.concatenate(batches) if batches else np.empty((0, DIMENSION))

    def score(self, query, texts):
        scores = []
        with self.torch.inference_mode():
            for offset in range(0, len(texts), 8):
                batch = texts[offset:offset + 8]
                features = self.rerank_tokenizer([query] * len(batch), batch, padding=True,
                    truncation=True, max_length=512, return_tensors="pt")
                logits = self.rerank_model(**features).logits.flatten()
                scores.extend(self.torch.sigmoid(logits).cpu().tolist())
        return np.asarray(scores, dtype=float)

    def traced_reranker(self, trace):
        def score(query, texts):
            started = time.perf_counter()
            scores = self.score(query, texts)
            trace.append({"implementation": "real_cpu_cross_encoder", "count": len(texts),
                "scores": scores.tolist(), "input_sha256": [hashlib.sha256(t.encode()).hexdigest() for t in texts],
                "milliseconds": (time.perf_counter() - started) * 1000})
            return scores
        return CallableRerankerAdapter(score)
