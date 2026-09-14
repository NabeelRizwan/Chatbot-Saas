"""Offline reviewer capacity, provider metadata and fail-closed contract tests."""
import json
import unittest
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

from services import rag_planning as planning, llm_router as router
from services.observability_service import ChatTrace
from services.query_contract import QueryContract, extract_requested_fields
from services.requested_propositions import RequestedProposition


BOT = NS(id=7, organization_id=11, provider='gemini', model_name='gemini-fixture')


def contract(question='Compare the requested details', propositions=0):
    result = QueryContract(question, question, question, 'comparison', 'comparison')
    result.requested_propositions = [RequestedProposition(
        f'p{i}', 'guarantee_eligibility', 'guarantee', (0, 9)) for i in range(propositions)]
    return result


def candidates(count):
    return [dict(chunk=NS(id=i+1, content='A guarantee applies.', chunk_index=i),
                 document=NS(id=1, title='Fixture', filename='fixture.txt')) for i in range(count)]


class ReviewerBudgetTests(unittest.TestCase):
    def test_few_candidates_few_propositions_remains_modest(self):
        self.assertEqual(planning.reviewer_output_budget(2, 1), 768)

    def test_many_candidates_few_propositions(self):
        self.assertGreater(planning.reviewer_output_budget(48, 1), planning.reviewer_output_budget(2, 1))

    def test_few_candidates_many_propositions(self):
        self.assertGreater(planning.reviewer_output_budget(2, 15), planning.reviewer_output_budget(2, 1))

    def test_many_candidates_many_propositions(self):
        self.assertGreater(planning.reviewer_output_budget(48, 15), planning.reviewer_output_budget(2, 15))

    def test_maximum_candidate_pool(self):
        self.assertEqual(planning.reviewer_output_budget(10000, 2), planning.reviewer_output_budget(48, 2))

    def test_maximum_bounded_matrix(self):
        value = planning.reviewer_output_budget(48, 104)
        self.assertGreater(value, planning.reviewer_output_budget(48, 15))
        self.assertLessEqual(value, planning.MAX_REVIEWER_OUTPUT_TOKENS)

    def test_hard_ceiling(self):
        self.assertLessEqual(planning.reviewer_output_budget(10**9, 10**9), planning.MAX_REVIEWER_OUTPUT_TOKENS)

    def test_actual_reviewer_uses_visible_count_not_pool(self):
        with patch.object(planning, 'POLICY', NS(reviewer_max=48, reviewer_preview_chars=40,
                reviewer_chunk_preview_chars=20)), patch.object(planning, 'generate_auxiliary',
                return_value='{"ranked_candidates":[0]}') as generate, \
                patch.object(router, 'get_last_auxiliary_metadata', return_value={}):
            planning.review_evidence(BOT, contract(propositions=15), candidates(48))
        payload = json.loads(generate.call_args.args[1])
        self.assertEqual(len(payload['candidates']), 2)
        self.assertEqual(generate.call_args.kwargs['tokens'], planning.reviewer_output_budget(2, 15))
        generate.assert_called_once()


class ReviewerValidationTests(unittest.TestCase):
    def run_review(self, raw, metadata=None, count=2, props=0, error=None):
        trace = ChatTrace(BOT.id, 'test')
        with patch.object(planning, 'generate_auxiliary', return_value=raw, side_effect=error) as generate, \
                patch.object(router, 'get_last_auxiliary_metadata', return_value=metadata or {}):
            result = planning.review_evidence(BOT, contract(propositions=props), candidates(count), trace)
        generate.assert_called_once()
        return result, trace

    def test_malformed_json_fails_closed_not_transport(self):
        _, trace = self.run_review('{not json')
        self.assertTrue(trace.retrieval.reviewer_outcome['fallback_used'])
        self.assertEqual(trace.retrieval.reviewer_outcome['failure_category'], 'reviewer_invalid_structured_output')
        self.assertEqual(trace.diagnostics['evidence_review']['validation_result'], 'malformed_json')
        self.assertEqual(trace.retrieval.provider_errors, [])

    def test_truncated_json_without_finish_reason_is_not_guessed(self):
        _, trace = self.run_review('{"ranked_candidates":[0],"contradicting_')
        self.assertEqual(trace.retrieval.reviewer_outcome['failure_category'], 'reviewer_invalid_structured_output')
        self.assertIsNone(trace.diagnostics['evidence_review']['finish_reason'])

    def test_max_tokens_is_proven_truncation(self):
        _, trace = self.run_review('{"ranked_candidates":[0],"contradicting_',
                                   {'finish_reason': 'MAX_TOKENS', 'output_tokens': 764})
        self.assertEqual(trace.retrieval.reviewer_outcome['failure_category'], 'reviewer_output_truncated')
        self.assertEqual(trace.diagnostics['evidence_review']['output_tokens'], 764)

    def test_max_tokens_with_parseable_json_still_fails_closed(self):
        _, trace = self.run_review('{"ranked_candidates":[0]}', {'finish_reason':'MAX_TOKENS'})
        self.assertTrue(trace.retrieval.reviewer_outcome['fallback_used'])

    def test_schema_mismatch_is_not_transport(self):
        _, trace = self.run_review('{"ranked_candidates":["0"]}')
        self.assertEqual(trace.diagnostics['evidence_review']['validation_result'], 'schema_mismatch')

    def test_unknown_reference_rejected(self):
        _, trace = self.run_review('{"ranked_candidates":[47]}')
        self.assertTrue(trace.retrieval.reviewer_outcome['fallback_used'])
        self.assertEqual(trace.diagnostics['evidence_review']['validation_result'], 'reference_validation')

    def test_unknown_proposition_rejected(self):
        raw = json.dumps(dict(ranked_candidates=[0], proposition_support=[dict(
            proposition_id='unknown', support_state='supported', supporting_candidates=[0])]))
        _, trace = self.run_review(raw)
        self.assertTrue(trace.retrieval.reviewer_outcome['fallback_used'])

    def test_normal_json_unchanged(self):
        result, trace = self.run_review('{"ranked_candidates":[1,0]}', {'finish_reason':'STOP'})
        self.assertEqual([r['chunk'].id for r in result], [2,1])
        self.assertFalse(trace.retrieval.reviewer_outcome['fallback_used'])
        self.assertEqual(trace.diagnostics['evidence_review']['validation_result'], 'valid')

    def test_valid_large_reply_near_old_boundary_accepted(self):
        raw = json.dumps(dict(ranked_candidates=[0], proposition_support=[dict(
            proposition_id=f'p{i}', support_state='supported', supporting_candidates=[0],
            contradicting_candidates=[]) for i in range(15)]))
        self.assertGreater(len(raw), 1800)
        _, trace = self.run_review(raw, {'finish_reason':'STOP', 'output_tokens':764}, props=15)
        self.assertFalse(trace.retrieval.reviewer_outcome['fallback_used'])
        self.assertEqual(len(trace.retrieval.reviewer_outcome['proposition_support']), 15)

    def test_all_bounded_propositions_fit_schema_and_parser(self):
        raw = json.dumps(dict(ranked_candidates=[0], proposition_support=[dict(
            proposition_id=f'p{i}', support_state='supported', supporting_candidates=[0],
            contradicting_candidates=[]) for i in range(104)]))
        self.assertGreater(len(raw), 12000)
        _, trace = self.run_review(raw, {'finish_reason':'STOP'}, props=104)
        self.assertFalse(trace.retrieval.reviewer_outcome['fallback_used'])

    def test_schema_still_bounds_proposition_count(self):
        with self.assertRaises(ValueError):
            planning.EvidenceReview.model_validate(dict(ranked_candidates=[0], proposition_support=[dict(
                proposition_id='p', support_state='missing')]*105))

    def test_429_stays_rate_limit(self):
        _, trace = self.run_review('', error=RuntimeError('429 rate limit'))
        self.assertEqual(trace.retrieval.reviewer_outcome['failure_category'], 'rate_limit')

    def test_timeout_stays_timeout(self):
        _, trace = self.run_review('', error=TimeoutError('deadline'))
        self.assertEqual(trace.retrieval.reviewer_outcome['failure_category'], 'timeout')


class ProviderMetadataTests(unittest.TestCase):
    def test_actual_gemini_adapter_captures_sdk_finish_reason(self):
        from google.genai import types
        from services.providers.gemini_provider import GeminiProvider
        client = MagicMock()
        client.models.generate_content.return_value = NS(text='{}', candidates=[
            NS(finish_reason=types.FinishReason.MAX_TOKENS)],
            usage_metadata=NS(prompt_token_count=100, candidates_token_count=764))
        provider = GeminiProvider()
        with patch.object(provider, '_client', return_value=client):
            result = provider.generate_with_metadata('fixture', 'gemini-fixture', '{}')
        self.assertEqual(result.finish_reason, 'MAX_TOKENS')
        self.assertEqual(result.usage.output_tokens, 764)

    def test_actual_router_preserves_metadata_and_single_attempt(self):
        provider = NS(generate_with_metadata=MagicMock(return_value=NS(text='{}',
            finish_reason='STOP', usage=NS(input_tokens=99, output_tokens=18))))
        with patch.dict(router.PROVIDERS, {'gemini':provider}), \
                patch.object(router, '_resolve_api_key', return_value=('fixture',False)), \
                patch.object(router, 'execute_with_resilience', side_effect=lambda fn,*a,**k:fn()) as execute:
            self.assertEqual(router.generate_auxiliary(BOT,'{}','schema',tokens=2048), '{}')
        metadata = router.get_last_auxiliary_metadata()
        self.assertEqual(metadata['finish_reason'], 'STOP')
        self.assertEqual(metadata['output_tokens'], 18)
        self.assertEqual(metadata['max_output_tokens'], 2048)
        self.assertEqual(execute.call_args.kwargs['max_retries'], 0)
        provider.generate_with_metadata.assert_called_once()


class PlannerFormTests(unittest.TestCase):
    def resolved(self, question, fields=None):
        base = contract(question)
        base.requested_fields = fields if fields is not None else extract_requested_fields(question)
        plan = planning.QueryPlan(resolved_user_meaning=question, retrieval_query=question,
            intent='instructions', subject_confidence=.9, requested_fields=['directions','form'],
            scope_mode='uncertain')
        return planning.resolve_plan(base, [], {}, plan)

    def test_quantity_capsules_does_not_create_separate_form(self):
        self.assertNotIn('form', self.resolved('How many capsules and how should I take each?').requested_fields)

    def test_quantity_gummies_does_not_create_separate_form(self):
        self.assertNotIn('form', self.resolved('How many gummies?').requested_fields)

    def test_scoop_quantity_does_not_create_separate_form(self):
        self.assertNotIn('form', self.resolved('One scoop?').requested_fields)

    def test_unrelated_domain_quantity(self):
        self.assertNotIn('form', self.resolved('How many drops should I apply?').requested_fields)

    def test_explicit_independent_form_remains_additive(self):
        fields = self.resolved('What form is it, and how should I use it?', ['form','ingredients']).requested_fields
        self.assertEqual(set(fields), {'form','ingredients','directions'})

    def test_explicit_alternative_form_preserved(self):
        self.assertIn('form', self.resolved('Is it capsules or liquid, and how should I take it?').requested_fields)

    def test_no_quantity_or_usage_evidence_does_not_strip_planner_fields(self):
        self.assertIn('form', self.resolved('Tell me about the item.').requested_fields)


if __name__ == '__main__':
    unittest.main()
