"""Optional literal question coverage keeps the established model budgets."""
from dataclasses import replace

import pytest

from retrieval_engine.config import RetrievalConfig
from retrieval_engine.query_constraints import independent_question_clauses
from retrieval_engine.retrieval import LocalRetrievalEngine
from test_discovery_integration import engine_fixture


def test_complete_independent_questions_preserve_exact_constraints():
    question = 'Are recurring plans excluded from refunds? Can I suspend or end a recurring plan?'
    assert independent_question_clauses(question) == (
        'Are recurring plans excluded from refunds?', 'Can I suspend or end a recurring plan?')


@pytest.mark.parametrize('question', [
    'Can I return this device? How much does it cost?',
    'Which lamp is smaller, North or South?',
    'How do I cancel a plan? And pause?',
    'Is a refund possible? If yes, how do I claim a refund?',
    'What does "Can I cancel?" mean? Can I return orders?',
    'What are the costs? What are the costs?',
    'What are the costs? What are the terms? What are the fees? What are the dates?',
    'Does Starter Plan have logs? Which plans offer logs? Exclude Starter Plan.',
])
def test_ambiguous_or_dependent_questions_keep_full_query(question):
    assert independent_question_clauses(question) == ()


def test_flag_defaults_off_and_affects_provenance():
    base = RetrievalConfig()
    assert not base.independent_question_coverage
    enabled = replace(base, independent_question_coverage=True)
    assert LocalRetrievalEngine(base).pipeline_provenance() != LocalRetrievalEngine(enabled).pipeline_provenance()
    with pytest.raises(ValueError, match='Independent question'):
        replace(base, independent_question_coverage=1)


def test_disabled_flag_is_exact_context_neutral():
    engine = engine_fixture(0)
    question = 'Are recurring orders eligible for refunds? Can I suspend recurring orders?'
    baseline = engine.retrieve(question)
    assert baseline['audit']['scored_pairs'] == 64
    assert baseline['audit']['independent_question_clauses'] == []
    assert len(engine._fusion.calls) == 1
    engine.config = replace(engine.config, independent_question_coverage=False)
    repeated = engine.retrieve(question)
    assert repeated['context'] == baseline['context']


def test_independent_lanes_share_budget_and_keep_full_original_query():
    engine = engine_fixture(0)
    engine.config = replace(engine.config, independent_question_coverage=True)
    def mutating_reranker(candidates, query_bundle):
        for index, candidate in enumerate(candidates):
            candidate.score = float(len(candidates) - index)
        return list(candidates)
    engine._reranker.postprocess_nodes = mutating_reranker
    question = 'Are recurring orders eligible for refunds? Can I suspend recurring orders?'
    result = engine.retrieve(question)
    audit = result['audit']
    assert audit['scored_pairs'] == 64
    assert audit['generative_provider_calls'] == 0
    assert len(engine._fusion.calls) == 3
    assert len(audit['independent_question_clauses']) == 2
    groups = {key: [c for c in audit['candidates'] if c['query_group'] == key]
              for key in ('global', 'question-clause/0', 'question-clause/1')}
    assert [len(candidates) for candidates in groups.values()] == [32, 16, 16]
    assert all(c['ranking_query'] == question for c in groups['global'])
    assert result['context_tokens'] <= engine.config.context_token_budget
    # Fixed fixture returns the same wrappers for each search. Upstream-style
    # score mutation in one lane must not overwrite the earlier lane scores.
    ranks = audit['reranked_candidates']
    assert next(x['score'] for x in ranks if x['query_group'] == 'global') == 32
    assert next(x['score'] for x in ranks if x['query_group'] == 'question-clause/0') == 16
