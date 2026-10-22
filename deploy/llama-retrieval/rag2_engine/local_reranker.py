"""Batch configuration for the official LlamaIndex/SentenceTransformers ranker.

LlamaIndex delegates scoring to CrossEncoder.predict without exposing batch_size.
This adapter supplies that argument; tokenization, inference and sorting remain
in the maintained libraries. It does not change model weights or scores.
"""
from llama_index.core.postprocessor import SentenceTransformerRerank


class BatchedPredictor:
    def __init__(self, model, batch_size):
        self.model = model
        self.batch_size = batch_size
        self.tokenizer = model.tokenizer

    def predict(self, pairs):
        lengths = self.tokenizer([q for q, _ in pairs], [p for _, p in pairs],
                                 truncation=False, padding=False)['input_ids']
        if any(len(ids) > 512 for ids in lengths):
            raise ValueError('A reranking pair exceeds 512 tokens; no text was truncated.')
        return self.model.predict(pairs, batch_size=self.batch_size, show_progress_bar=False)


class LocalReranker(SentenceTransformerRerank):
    def __init__(self, *, batch_size=4, **kwargs):
        super().__init__(**kwargs)
        self._model = BatchedPredictor(self._model, batch_size)
