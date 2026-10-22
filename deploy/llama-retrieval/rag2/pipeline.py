"""Arbitrary authorized corpora use the same RAG2 stages as the frozen test.

No saved questions, plans, source packets, scores, or benchmark answers are read.
The caller supplies focused queries produced by its question-only planner.
"""
from copy import deepcopy
from time import perf_counter

from rag2_engine.retrieval import LocalRetrievalEngine
from .assemble_packets import assemble_lanes, digest_text, validate_result
from .context_blocks_six_span_control import prepare_block_index
from .context_block_rerank import prepare_candidates, assemble
from .voyage import VoyagePredictor, PassageRanker, VoyageError
from .request_budget import RequestBudget, yield_cpu


def assemble_searches(question, queries, retrieve, documents, tokenizer):
    """Keep the original RAG2 packet and append complete focused-lane evidence."""
    validate_queries(queries)
    started = perf_counter()
    receipts = {}
    lanes = []
    for index, query in enumerate([question, *queries]):
        if query not in receipts:
            receipts[query] = retrieve(query)
            validate_result(receipts[query], documents, tokenizer, 5200)
        lanes.append({'name': 'original' if index == 0 else f'focused-{index}',
                      'query_id': digest_text(query), 'result': receipts[query]})
    original = lanes[0]['result']
    if queries:
        packet = assemble_lanes(lanes, documents, tokenizer, 48000, append_only=True)
        result = packet['result']
        result['audit'] = deepcopy(original.get('audit', {}))
        result['audit']['planned_assembly'] = packet['assembly']
    else:
        result = deepcopy(original)
        validate_result(result, documents, tokenizer, 5200)
    if len(result['evidence']) > 448:
        raise ValueError('Planned evidence exceeds seven bounded query lanes.')
    result['question'] = question
    result['timings'] = deepcopy(original.get('timings', {}))
    result['timings']['planned_retrieval_ms'] = round((perf_counter() - started) * 1000, 3)
    result['planning'] = {'queries': list(queries), 'unique_searches': len(receipts),
                          'context_cap': 48000 if queries else 5200,
                          'method': 'rag2-voyage-append48000-v1'}
    return result


def validate_queries(queries):
    if (not isinstance(queries, list) or len(queries) > 6
            or any(not isinstance(q, str) or not q.strip() or len(q) > 420
                   or len(q.split()) > 65 for q in queries)
            or len(queries) != len(set(queries))):
        raise ValueError('Focused queries must be up to six unique nonempty short strings.')
    return queries


class PlannedRetrievalEngine(LocalRetrievalEngine):
    def build_or_load(self):
        result = super().build_or_load()
        self._block_index = prepare_block_index(self._source_nodes, self._documents)
        return result

    def retrieve_planned(self, question, queries, *, budget=None):
        validate_queries(queries)
        budget = budget or RequestBudget()
        with self._lock:
            budget.remaining()
            # Request-private predictor/postprocessor; never modify runtime.reranker.
            self._voyage_predictor = VoyagePredictor.from_environment(self.config.root,
                budget=budget, remote_context=lambda: yield_cpu(self.runtime.lock))
            try:
                return assemble_searches(question, queries, self.retrieve,
                                         self._documents, self.runtime.context_tokenizer)
            finally:
                self._voyage_predictor = None

    def retrieve(self, question):
        # The API enters retrieve_planned even for the empty focused-query list.
        with self._lock:
            predictor = getattr(self, '_voyage_predictor', None)
            if predictor is None:
                raise VoyageError('voyage_request_scope_required')
            predictor.budget.remaining()
            original = self._reranker
            self._reranker = PassageRanker(self.runtime.reranker, predictor)
            try:
                base = super().retrieve(question)
            finally:
                self._reranker = original
            with self.runtime.lock:
                from llama_index.core.schema import NodeWithScore
                groups = {}
                for item in base['audit']['reranked_candidates']:
                    groups.setdefault(item['query_group'], []).append(
                        NodeWithScore(node=self._model_nodes[item['node_id']], score=item['score']))
                started = perf_counter()
                prepared = prepare_candidates(base, groups, self._source_nodes, self._documents,
                    self.runtime.context_tokenizer, self._block_index,
                    pair_tokenizer=self.runtime.tokenizer, max_pairs=32, max_block_tokens=240)
                proposals = prepared['proposals']
                # Crucially, runtime.reranker retains MiniLM for this second pass.
                scores = ([float(v) for v in self.runtime.reranker._model.predict(
                    [(p['query'], p['model_text']) for p in proposals])] if proposals else [])
                result = assemble(base, proposals, scores, self.runtime.context_tokenizer,
                                  extra_tokens=1200, max_spans=6, max_total_tokens=5200)
                result['context_sha256'] = digest_text(result['context'])
                result.setdefault('timings', {})['rag2_second_pass_ms'] = round((perf_counter() - started) * 1000, 3)
                validate_result(result, self._documents, self.runtime.context_tokenizer, 5200)
                if not result['context'].startswith(base['context']):
                    raise ValueError('RAG2 baseline context changed.')
                return result
