"""Bounded planner vocabulary regression tests; no network or configured DB."""
import json
import inspect
import unittest
from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError
from database.models import Document
from services import rag_planning as planning
from services.observability_service import ChatTrace
from services.query_contract import build_query_contract
from services.retrieval_contracts import HardKnowledgeScope


CANONICAL = (
    'fact_lookup', 'price', 'ingredients', 'instructions', 'features', 'benefits',
    'policy', 'shipping', 'returns', 'comparison', 'catalog', 'recommendation',
    'follow_up', 'unsupported',
)
ALIASES = {
    'reviews': 'fact_lookup', 'testimonials': 'fact_lookup',
    'ratings': 'fact_lookup', 'feedback': 'fact_lookup',
    'pricing': 'price', 'directions': 'instructions',
    'specifications': 'features', 'followup': 'follow_up',
}

# Exact historical provider JSON from frozen case 39, not a runtime rule.
CASE39 = '''{
  "resolved_user_meaning": "Does Sea Essence have an unpleasant aftertaste?",
  "retrieval_query": "Sea Essence aftertaste reviews flavor",
  "intent": "reviews",
  "active_subjects": ["Sea Essence"],
  "subject_confidence": 1.0,
  "requested_fields": ["flavor", "reviews"],
  "scope_mode": "single_entity",
  "comparison_requested": false,
  "needs_global_discovery": false
}'''

# Exact saved planner payload from frozen case 68; regression fixture only.
CASE68 = '''{
  "resolved_user_meaning": "Does Joint Support have a guarantee regarding feeling a difference within the first two months?",
  "retrieval_query": "Joint Support guarantee first two months results",
  "intent": "guarantee",
  "active_subjects": [
    "Joint Support"
  ],
  "subject_confidence": 1.0,
  "requested_fields": [
    "guarantee"
  ],
  "scope_mode": "single_entity",
  "comparison_requested": false,
  "needs_global_discovery": false
}'''

EVIDENCE_FIELDS = {
    'price', 'ingredients', 'directions', 'form', 'benefits', 'results_timeframe',
    'features', 'specifications', 'amenities', 'availability', 'duration', 'policy',
    'eligibility', 'shipping', 'returns', 'guarantee', 'check_in', 'syllabus',
    'flavor', 'link', 'clock_time', 'reviews', 'brand', 'sku', 'rating',
}


def payload(intent='fact_lookup'):
    return dict(resolved_user_meaning='What do customers say about Cedar Service Plan?',
                retrieval_query='Cedar Service Plan reviews', intent=intent,
                active_subjects=['Cedar Service Plan'], subject_confidence=1.0,
                requested_fields=['reviews'], scope_mode='single_entity',
                comparison_requested=False, needs_global_discovery=False)


class PlannerIntentContractTests(unittest.TestCase):
    def setUp(self):
        self.bot = SimpleNamespace(id=1, organization_id=1, provider='gemini', model_name='fixture')
        self.doc = Document(id=1, organization_id=1, bot_id=1, title='Cedar Service Plan',
                            filename='Cedar Service Plan', source_type='txt', status='ready',
                            processing_status='completed', version=1)
        self.hard = HardKnowledgeScope(1, 1, (1,))

    def plan(self, raw=None, error=None):
        trace = ChatTrace(1, 'widget')
        with patch.object(planning, 'generate_auxiliary', return_value=raw, side_effect=error) as provider:
            result = planning.plan_query(self.bot, 'What do customers say about Cedar Service Plan?',
                                         [], {}, [self.doc], trace)
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(provider.call_args.kwargs, {})  # Existing deadline/model defaults untouched.
        return result, trace, provider

    def resolve(self, plan):
        question = 'What do customers say about Cedar Service Plan?'
        contract = build_query_contract(question, [], [self.doc], intent='knowledge_query', mode='factual')
        return planning.resolve_plan(contract, [self.doc], {}, plan, self.hard)

    def test_all_existing_canonical_values_and_fields_unchanged(self):
        for intent in CANONICAL:
            with self.subTest(intent=intent):
                original = payload(intent)
                self.assertEqual(planning.QueryPlan.model_validate_json(json.dumps(original)).model_dump(), original)

    def test_aliases_pass_the_actual_planner_path(self):
        for alias, canonical in ALIASES.items():
            with self.subTest(alias=alias):
                result, trace, _ = self.plan(json.dumps(payload(alias)))
                self.assertIsNotNone(result)
                self.assertEqual(result.intent, canonical)
                self.assertEqual(result.requested_fields, ['reviews'])
                self.assertEqual(trace.diagnostics['planner']['status'], 'success')
                self.assertFalse(trace.retrieval.provider_errors)

    def test_historical_case39_exact_provider_json(self):
        result, trace, _ = self.plan(CASE39)
        self.assertIsNotNone(result)
        expected = json.loads(CASE39)
        expected['intent'] = 'fact_lookup'
        self.assertEqual(result.model_dump(), expected)
        self.assertFalse(trace.retrieval.provider_errors)

    def test_schema_stays_strict_canonical_vocabulary(self):
        schema = planning.QueryPlan.model_json_schema()
        self.assertEqual(schema['properties']['intent']['enum'], list(CANONICAL))
        self.assertFalse(schema['additionalProperties'])

    def test_unknown_untrusted_intents_rejected(self):
        for value in ('delete_database', 'ignore previous rules', 'reviews; DROP TABLE bots',
                      'fact_lookup or unsupported', '', 'x' * 10000):
            with self.subTest(value=value[:25]):
                with self.assertRaises(ValidationError):
                    planning.QueryPlan.model_validate_json(json.dumps(payload(value)))

    def test_nonstring_intents_rejected_without_coercion(self):
        for value in (None, 1, True, ['reviews'], {'intent': 'reviews'}):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    planning.QueryPlan.model_validate_json(json.dumps(payload(value)))

    def test_unknown_intent_uses_existing_safe_fallback(self):
        result, trace, _ = self.plan(json.dumps(payload('untrusted_action')))
        self.assertIsNone(result)
        self.assertEqual(trace.diagnostics['planner']['status'], 'ValidationError')
        resolved = self.resolve(result)
        self.assertEqual(resolved.planner_status, 'deterministic_fallback')
        self.assertEqual(resolved.permitted_document_ids, [1])

    def test_malformed_json_still_falls_back(self):
        for raw in ('not json', '{', '```json\n{}\n```', '[]', 'null'):
            with self.subTest(raw=raw):
                result, trace, _ = self.plan(raw)
                self.assertIsNone(result)
                self.assertEqual(trace.diagnostics['planner']['status'], 'ValidationError')

    def test_oversized_response_guard_preserved(self):
        result, trace, _ = self.plan(' ' * 12001)
        self.assertIsNone(result)
        self.assertEqual(trace.diagnostics['planner']['status'], 'ValueError')

    def test_extra_and_invalid_other_fields_still_fail(self):
        for change in ({'document_ids': [999]}, {'scope_mode': 'admin'},
                       {'subject_confidence': 2.0}, {'comparison_requested': 'false'}):
            with self.subTest(change=change):
                result, trace, _ = self.plan(json.dumps({**payload('reviews'), **change}))
                self.assertIsNone(result)
                self.assertEqual(trace.diagnostics['planner']['status'], 'ValidationError')

    def test_timeout_still_one_attempt_and_same_failure_category(self):
        result, trace, _ = self.plan(error=TimeoutError('offline deadline'))
        self.assertIsNone(result)
        self.assertEqual(trace.retrieval.provider_errors[0]['category'], 'timeout')

    def test_provider_failure_still_one_attempt_and_fallback(self):
        error = RuntimeError('offline provider failure')
        error.status_code = 503
        result, trace, _ = self.plan(error=error)
        self.assertIsNone(result)
        self.assertEqual(trace.retrieval.provider_errors[0]['category'], 'provider_unavailable')

    def test_alias_normalization_does_not_mutate_payload(self):
        original = payload('reviews')
        before = deepcopy(original)
        result = planning.QueryPlan.model_validate(original)
        self.assertEqual(result.intent, 'fact_lookup')
        self.assertEqual(original, before)

    def test_canonical_downstream_modes_and_scopes_unchanged(self):
        for intent in CANONICAL:
            with self.subTest(intent=intent):
                data = payload(intent)
                validated = planning.QueryPlan.model_validate_json(json.dumps(data))
                preexisting = planning.QueryPlan.model_construct(**data)
                self.assertEqual(asdict(self.resolve(validated)), asdict(self.resolve(preexisting)))

    def test_alias_downstream_contract_equals_canonical(self):
        for alias, canonical in ALIASES.items():
            with self.subTest(alias=alias):
                actual, _, _ = self.plan(json.dumps(payload(alias)))
                self.assertIsNotNone(actual)
                expected = planning.QueryPlan(**payload(canonical))
                self.assertEqual(asdict(self.resolve(actual)), asdict(self.resolve(expected)))

    def test_alias_cannot_authorize_foreign_document(self):
        foreign = Document(id=2, organization_id=2, bot_id=2, title='Foreign Resource',
                           filename='Foreign Resource', source_type='txt', status='ready',
                           processing_status='completed', version=1)
        candidate, _, _ = self.plan(json.dumps({**payload('reviews'), 'active_subjects': ['Foreign Resource']}))
        self.assertIsNotNone(candidate)
        contract = build_query_contract('Reviews of Foreign Resource?', [], [self.doc], intent='knowledge_query', mode='factual')
        result = planning.resolve_plan(contract, [self.doc, foreign], {}, candidate, self.hard)
        self.assertNotIn(2, result.permitted_document_ids or [])
        self.assertNotIn(2, [e.document_id for e in result.resolved_entities])

    def test_prompt_continues_advertising_canonical_schema_and_field_labels(self):
        _, _, provider = self.plan(json.dumps(payload()))
        prompt = provider.call_args.args[2]
        self.assertIn('Schema: ' + json.dumps(planning.QueryPlan.model_json_schema()), prompt)
        self.assertIn('Field labels: ', prompt)
        self.assertIn('reviews', prompt.split(' Field labels: ')[1])

    def test_runtime_alias_map_is_bounded_and_domain_independent(self):
        self.assertEqual(planning.PLANNER_INTENT_ALIASES, ALIASES)
        source = inspect.getsource(planning.QueryPlan)
        self.assertNotIn('Sea Essence', source)
        self.assertNotIn('WOWMD', source)
        self.assertNotIn('674', source)

    def resolve_question(self, question, plan, *, documents=None, hard=None):
        documents = documents or [self.doc]
        contract = build_query_contract(question, [], documents, intent='knowledge_query', mode='factual')
        return planning.resolve_plan(contract, documents, {}, plan, hard or self.hard)

    def test_all_known_field_identifiers_have_explicit_precedence(self):
        self.assertEqual(set(planning.FIELD_ONTOLOGY), EVIDENCE_FIELDS)
        for field in EVIDENCE_FIELDS:
            with self.subTest(field=field):
                data = {**payload(field), 'requested_fields': [field, 'custom field']}
                expected = field if field in CANONICAL else ALIASES.get(field, 'fact_lookup')
                result = planning.QueryPlan.model_validate(data)
                self.assertEqual(result.intent, expected)
                self.assertEqual(result.requested_fields, data['requested_fields'])

    def test_field_topics_pass_actual_planner_boundary(self):
        for field in EVIDENCE_FIELDS - set(CANONICAL) - set(ALIASES):
            with self.subTest(field=field):
                data = {**payload(field), 'requested_fields': [field]}
                result, trace, _ = self.plan(json.dumps(data))
                self.assertIsNotNone(result)
                self.assertEqual(result.intent, 'fact_lookup')
                self.assertEqual(result.requested_fields, [field])
                self.assertEqual(trace.diagnostics['planner']['status'], 'success')
                self.assertFalse(trace.retrieval.provider_errors)

    def test_historical_case68_exact_provider_json(self):
        result, trace, _ = self.plan(CASE68)
        self.assertIsNotNone(result)
        expected = json.loads(CASE68)
        expected['intent'] = 'fact_lookup'
        self.assertEqual(result.model_dump(), expected)
        self.assertEqual(trace.diagnostics['planner']['status'], 'success')
        self.assertFalse(trace.retrieval.provider_errors)

    def test_field_normalization_preserves_entire_payload_and_field_order(self):
        data = {**payload('guarantee'), 'requested_fields': ['guarantee', 'returns', 'guarantee', 'Custom field']}
        before = deepcopy(data)
        result = planning.QueryPlan.model_validate(data).model_dump()
        self.assertEqual(data, before)
        self.assertEqual(result, {**before, 'intent': 'fact_lookup'})

    def test_outcome_guarantee_does_not_become_policy_intent(self):
        question = 'Does Cedar Service Plan guarantee a result in two months?'
        data = {**payload('guarantee'), 'resolved_user_meaning': question,
                'retrieval_query': question, 'requested_fields': ['guarantee']}
        actual = planning.QueryPlan.model_validate(data)
        expected = planning.QueryPlan.model_construct(**{**data, 'intent': 'fact_lookup'})
        self.assertEqual(actual.intent, 'fact_lookup')
        result = self.resolve_question(question, actual)
        self.assertEqual(asdict(result), asdict(self.resolve_question(question, expected)))
        self.assertIn('guarantee', result.requested_fields)
        self.assertNotIn('returns', result.requested_fields)
        self.assertNotIn('policy', result.requested_fields)
        self.assertEqual(result.mode, 'factual')

    def test_refund_policy_retains_existing_contract(self):
        question = 'What is the refund policy for Cedar Service Plan?'
        for intent in ('returns', 'policy', 'guarantee'):
            with self.subTest(intent=intent):
                data = {**payload(intent), 'resolved_user_meaning': question,
                        'retrieval_query': question, 'requested_fields': ['returns', 'policy', 'guarantee']}
                expected_intent = 'fact_lookup' if intent == 'guarantee' else intent
                actual = planning.QueryPlan.model_validate(data)
                expected = planning.QueryPlan.model_construct(**{**data, 'intent': expected_intent})
                result = self.resolve_question(question, actual)
                self.assertEqual(actual.intent, expected_intent)
                self.assertEqual(asdict(result), asdict(self.resolve_question(question, expected)))
                self.assertTrue({'returns', 'policy', 'guarantee'} <= set(result.requested_fields))

    def test_shipping_canonical_intent_and_scope_preserved(self):
        question = 'What are the shipping terms for Cedar Service Plan?'
        data = {**payload('shipping'), 'requested_fields': ['shipping', 'policy']}
        actual = planning.QueryPlan.model_validate(data)
        self.assertEqual(actual.intent, 'shipping')
        result = self.resolve_question(question, actual)
        self.assertEqual(asdict(result), asdict(self.resolve_question(question, planning.QueryPlan.model_construct(**data))))
        self.assertIn('shipping', result.requested_fields)

    def test_availability_field_keeps_live_query_semantics(self):
        question = 'Is Cedar Service Plan in stock right now?'
        data = {**payload('availability'), 'requested_fields': ['availability']}
        actual = planning.QueryPlan.model_validate(data)
        expected = planning.QueryPlan.model_construct(**{**data, 'intent': 'fact_lookup'})
        result = self.resolve_question(question, actual)
        self.assertEqual(asdict(result), asdict(self.resolve_question(question, expected)))
        self.assertEqual(result.availability_subtype, 'live_inventory')

    def test_recommendation_keeps_purchase_behavior(self):
        question = 'Would you recommend Cedar Service Plan?'
        data = {**payload('recommendation'), 'requested_fields': ['benefits', 'eligibility']}
        actual = planning.QueryPlan.model_validate(data)
        result = self.resolve_question(question, actual)
        self.assertEqual(actual.intent, 'recommendation')
        self.assertEqual(result.mode, 'purchase')
        self.assertEqual(asdict(result), asdict(self.resolve_question(question, planning.QueryPlan.model_construct(**data))))

    def test_comparison_keeps_both_entities_and_hard_scope(self):
        other = Document(id=2, organization_id=1, bot_id=1, title='Birch Service Plan',
                         filename='Birch Service Plan', source_type='txt', status='ready',
                         processing_status='completed', version=1)
        question = 'Compare Cedar Service Plan and Birch Service Plan on eligibility.'
        data = {**payload('comparison'), 'active_subjects': ['Cedar Service Plan', 'Birch Service Plan'],
                'requested_fields': ['eligibility'], 'comparison_requested': True, 'scope_mode': 'multi_entity'}
        actual = planning.QueryPlan.model_validate(data)
        result = self.resolve_question(question, actual, documents=[self.doc, other], hard=HardKnowledgeScope(1, 1, (1, 2)))
        self.assertEqual(actual.intent, 'comparison')
        self.assertEqual(result.mode, 'comparison')
        self.assertEqual(set(result.permitted_document_ids), {1, 2})

    def test_no_fuzzy_substring_casefold_or_metadata_intent_expansion(self):
        for value in ('GUARANTEE', ' guarantee', 'guarantee ', 'money back guarantee',
                      'timeline', 'results timeline', 'warranty', 'name', 'entity_detail',
                      'refund', 'flavor; ignore restrictions', 'guarantee AND true', 'custom field'):
            with self.subTest(value=value):
                data = {**payload(value), 'requested_fields': [value]}
                with self.assertRaises(ValidationError):
                    planning.QueryPlan.model_validate(data)

    def test_field_intent_cannot_authorize_other_tenant_bot_or_document(self):
        foreign = [Document(id=i, organization_id=org, bot_id=bot, title='Foreign Resource',
                            filename='Foreign Resource', source_type='txt', status='ready',
                            processing_status='completed', version=1)
                   for i, org, bot in ((2, 2, 1), (3, 1, 2), (4, 1, 1))]
        data = {**payload('eligibility'), 'active_subjects': ['Foreign Resource'],
                'requested_fields': ['eligibility']}
        actual = planning.QueryPlan.model_validate(data)
        result = self.resolve_question('Eligibility for Foreign Resource?', actual, documents=[self.doc] + foreign)
        self.assertFalse({2, 3, 4} & set(result.permitted_document_ids or []))
        self.assertFalse({2, 3, 4} & {e.document_id for e in result.resolved_entities})

    def test_unknown_topic_still_uses_existing_deterministic_fallback(self):
        data = {**payload('custom_topic'), 'requested_fields': ['custom_topic']}
        result, trace, _ = self.plan(json.dumps(data))
        self.assertIsNone(result)
        self.assertEqual(trace.diagnostics['planner']['status'], 'ValidationError')
        self.assertEqual(self.resolve(result).planner_status, 'deterministic_fallback')


if __name__ == '__main__':
    unittest.main()
