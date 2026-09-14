"""Explicit test-process cache isolation; never imported by application routes."""
from contextlib import contextmanager, ExitStack
from unittest.mock import patch


@contextmanager
def isolated_answer_caches():
    from services import rag_service as rag
    with ExitStack() as stack:
        stack.enter_context(patch.object(rag, '_RETRIEVAL_CACHE', {}))
        stack.enter_context(patch.object(rag.global_semantic_cache, 'get', return_value=None))
        stack.enter_context(patch.object(rag.global_semantic_cache, 'set', return_value=None))
        yield
