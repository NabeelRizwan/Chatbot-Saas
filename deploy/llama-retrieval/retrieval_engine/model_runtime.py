"""Process-lifetime, offline model resources shared by isolated corpus indexes."""
from __future__ import annotations

import hashlib
import threading
import time

from .config import RetrievalConfig


class ModelRuntime:
    def __init__(self, config: RetrievalConfig):
        self.config = config
        # LlamaIndex retrievers and tokenizers have mutable query state. A runtime
        # is one inference lane; independent service processes provide more lanes.
        self.lock = threading.RLock()
        self.ready = False
        self.load_ms = None
        self.embedding = self.reranker = None
        self.tokenizer = self.embedding_tokenizer = self.context_tokenizer = None
        self.disabled_llm = None

    def compatible(self, config: RetrievalConfig) -> bool:
        fields = ('root', 'embedding_model', 'reranker_model', 'cpu_threads',
                  'rerank_candidates', 'adaptive_evidence', 'reranker_batch_size')
        return all(getattr(config, key) == getattr(self.config, key) for key in fields)

    def load(self):
        with self.lock:
            if self.ready:
                return self
            started = time.perf_counter()
            config = self.config
            config.apply_runtime_environment()
            required = (config.embedding_path / 'model_optimized.onnx',
                        config.reranker_path / 'config.json',
                        config.models_path / 'nltk_data/corpora/stopwords',
                        config.models_path / 'nltk_data/tokenizers/punkt_tab',
                        config.models_path / 'tiktoken' / hashlib.sha1(
                            b'https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken'
                        ).hexdigest())
            if not all(path.exists() for path in required):
                raise FileNotFoundError('Required offline retrieval model artifacts are missing.')

            import tiktoken
            import torch
            from tokenizers import Tokenizer
            from llama_index.core.llms import MockLLM
            from llama_index.embeddings.fastembed import FastEmbedEmbedding
            from .local_reranker import LocalReranker

            class DisabledLLM(MockLLM):
                def complete(self, *args, **kwargs):
                    raise RuntimeError('Generative LLM calls are disabled in the retrieval service.')

                def stream_complete(self, *args, **kwargs):
                    raise RuntimeError('Generative LLM calls are disabled in the retrieval service.')

            torch.set_num_threads(config.cpu_threads)
            self.context_tokenizer = tiktoken.get_encoding('cl100k_base')
            self.disabled_llm = DisabledLLM()
            self.reranker = LocalReranker(
                model=str(config.reranker_path),
                top_n=max(config.rerank_candidates, 96) if config.adaptive_evidence else config.rerank_candidates,
                batch_size=config.reranker_batch_size, device='cpu',
                trust_remote_code=False, keep_retrieval_score=False)
            self.tokenizer = self.reranker._model.tokenizer
            self.embedding = FastEmbedEmbedding(
                model_name=config.embedding_model,
                cache_dir=str(config.models_path / 'fastembed-cache'),
                specific_model_path=str(config.embedding_path), local_files_only=True,
                threads=config.cpu_threads, providers=['CPUExecutionProvider'])
            self.embedding_tokenizer = Tokenizer.from_str(self.embedding._model.model.tokenizer.to_str())
            self.embedding_tokenizer.no_truncation()
            self.embedding_tokenizer.no_padding()
            # Exercise both real CPU inference paths before reporting readiness.
            # This synthetic pair is never persisted, retrieved or sent to an AI.
            self.embedding.get_query_embedding(config.embedding_query_prefix + 'model readiness')
            self.reranker._model.predict([('model readiness', 'The retrieval model is ready.')])
            self.load_ms = round((time.perf_counter() - started) * 1000, 2)
            self.ready = True
            return self

    def shared_object_ids(self):
        return {id(value) for value in (self, self.embedding, self.reranker, self.tokenizer,
                                       self.embedding_tokenizer, self.context_tokenizer, self.disabled_llm)}
