"""Required alternatives decisions stay grounded without changing current criteria."""
import atexit
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

_temp = TemporaryDirectory(prefix='question-alternatives-tests-')
atexit.register(_temp.cleanup)
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
os.environ.setdefault('DATABASE_URL', 'sqlite:///' + (Path(_temp.name) / 'bootstrap.sqlite').as_posix())
os.environ['APP_ENV'] = 'development'

from services.llama_rag import planning
from services.providers.generation_input import current_input


class AlternativesContractTests(unittest.TestCase):
    history = [
        {'role': 'user', 'content': 'Which lamp is rechargeable?'},
        {'role': 'assistant', 'content': 'Beacon lamp is rechargeable.'},
        {'role': 'user', 'content': 'Find a foldable chair under $150, no leather.'},
        {'role': 'assistant', 'content': 'Cedar chair is an option. Atlas chair is also suitable.'},
    ]

    def envelope(self, *, intent='not_new_options', options=(), **edit):
        return {'alternatives': {'intent': intent, 'prior_options': list(options)},
                'plan': {'action': 'retrieve', **edit}}

    def mention(self, subject='Cedar chair', index=3):
        return {'subject': subject, 'history_index': index}

    def resolve(self, question, payload, *, history=None, contract=True, guard=True, provider='gemini', model='gemini-3.5-flash-lite'):
        raw = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        seen = []

        def generate(*args, **kwargs):
            seen.append(current_input())
            return raw

        bot = SimpleNamespace(provider=provider, model_name=model)
        with patch.dict(os.environ, {'LLAMA_QUESTION_ALTERNATIVES_CONTRACT': '1' if contract else '0',
                                     'LLAMA_QUESTION_PLAN_GUARD': '1' if guard else '0',
                                     'LLAMA_ANSWER_NATIVE_MESSAGES': '0'}), patch.object(
                planning, 'generate_auxiliary', side_effect=generate) as generated:
            result = planning.resolve(bot, question, self.history if history is None else history)
        self.assertIsNone(current_input().schema)
        if history != []:
            generated.assert_called_once()
            self.assertFalse(generated.call_args.kwargs['use_auxiliary_model'])
            self.assertEqual(generated.call_args.kwargs['tokens'], 640)
        return result, generated, seen

    def test_changed_criteria_keep_exact_current_question_and_prior_exclusion(self):
        question = 'What other non-folding chairs under $100 are available? Leather is fine.'
        result, _, _ = self.resolve(question, self.envelope(intent='new_options', options=[self.mention()]))
        self.assertEqual(result.question, question + '\nbesides Cedar chair')
        self.assertNotIn('$150', result.question)
        self.assertNotIn('no leather', result.question)
        self.assertNotIn('Beacon', result.question)
        self.assertEqual(planning.get_last_plan_metadata()['prior_option_count'], 1)

    def test_general_decisions_do_not_depend_on_an_english_intent_word(self):
        cases = [
            'Show me three more foldable chairs under $150.',
            'Show me different foldable chairs under $150.',
            'Show me additional foldable chairs under $150.',
            'Zeig mir weitere faltbare Stühle unter 150 Euro.',
            'मुझे कुछ और कुर्सियाँ दिखाइए।',
            '¿Qué otras sillas hay por menos de 100 euros?',
        ]
        for question in cases:
            with self.subTest(question=question):
                result, _, _ = self.resolve(question, self.envelope(intent='new_options', options=[self.mention()]))
                self.assertEqual(result.question, question + '\nbesides Cedar chair')

    def test_general_grounding_across_products_services_and_accommodation(self):
        for option in ['Copper Pan 20', 'Nimbus Backup Basic', 'Harbor Hotel', 'Élan Service', 'नीला कप']:
            history = [{'role': 'user', 'content': 'Please suggest an option.'},
                       {'role': 'assistant', 'content': f'{option} is available.'}]
            result, _, _ = self.resolve('Any others?', self.envelope(intent='new_options',
                options=[self.mention(option, 1)]), history=history)
            self.assertEqual(result.question, 'Any others?\nbesides ' + option)

    def test_ellipsis_preserves_old_criteria_only_when_not_replaced_by_current_question(self):
        result, _, _ = self.resolve('Any others?', self.envelope(intent='new_options', options=[self.mention()],
            ellipsis=self.mention('a foldable chair under $150, no leather', 2)))
        self.assertEqual(result.question, 'Any others?\nContext subject: a foldable chair under $150, no leather\nbesides Cedar chair')

    def test_normal_questions_and_explicit_topic_changes_remain_unchanged(self):
        for question in ['What is the price of Cedar chair?', 'Compare Atlas chair with Cedar chair.',
                         'How do plain and chocolate collagen directions differ?',
                         'Does Nimbus Backup support Linux?', 'Is it really safe to wash the cover at 40C?']:
            with self.subTest(question=question):
                result, _, _ = self.resolve(question, self.envelope())
                self.assertEqual(result.question, question)
                self.assertEqual(planning.get_last_plan_metadata()['status'], 'validated')

    def test_reconsider_does_not_exclude_previous_options(self):
        question = 'Compare those chairs again; you can suggest previous options.'
        result, _, _ = self.resolve(question, self.envelope(intent='reconsider'))
        self.assertEqual(result.question, question)

    def test_no_prior_recommendation_is_valid_without_inventing_one(self):
        result, _, _ = self.resolve('Any other payment methods?', self.envelope(intent='new_options'))
        self.assertEqual(result.question, 'Any other payment methods?')
        self.assertEqual(planning.get_last_plan_metadata()['status'], 'validated')

    def test_grounded_pronoun_and_plural_quantifier_still_work(self):
        result, _, _ = self.resolve('Is it foldable?', self.envelope(references=[{'span': 'it', **self.mention()}]))
        self.assertEqual(result.question, 'Is Cedar chair foldable?')
        result, _, _ = self.resolve('How much is each of them?', self.envelope(references=[{'span': 'each of them',
            'subjects': [self.mention(), self.mention('Atlas chair')]}]))
        self.assertEqual(result.question, 'How much is each of Cedar chair and Atlas chair?')

    def test_grounded_clarification_still_works(self):
        result, _, _ = self.resolve('Is it foldable?', self.envelope(action='clarify', unresolved_span='it',
            clarification='Do you mean Cedar chair or Atlas chair?'))
        self.assertEqual(result.clarification, 'Do you mean Cedar chair or Atlas chair?')

    def test_invalid_ref_cannot_discard_valid_derived_exclusions(self):
        question = 'Show other non-folding chairs under $100.'
        result, _, _ = self.resolve(question, self.envelope(intent='new_options', options=[self.mention()],
            references=[{'span': 'non-folding chairs', **self.mention()}]))
        self.assertEqual(result.question, question + '\nbesides Cedar chair')
        self.assertEqual(planning.get_last_plan_metadata()['status'], 'rejected_search_original')

    def test_prior_options_require_exact_assistant_message_grounding(self):
        options = [self.mention('Imaginary chair'), self.mention('cedar chair'), self.mention(index=1),
                   self.mention(index=99), self.mention('a foldable chair under $150', 2)]
        for option in options:
            with self.subTest(option=option):
                result, _, _ = self.resolve('Any others?', self.envelope(intent='new_options', options=[option]))
                self.assertEqual(result.question, 'Any others?')
                self.assertEqual(planning.get_last_plan_metadata()['status'], 'rejected_search_original')

    def test_exclusions_merge_and_deduplicate(self):
        mention = self.mention()
        result, _, _ = self.resolve('Any others?', self.envelope(intent='new_options',
            options=[mention, mention, self.mention('Atlas chair')], exclusions=[mention]))
        self.assertEqual(result.question, 'Any others?\nbesides Cedar chair, Atlas chair')

    def test_inconsistent_decision_rejected_without_inventing_a_clarification(self):
        for intent in ['not_new_options', 'reconsider', 'made_up_intent']:
            result, _, _ = self.resolve('What is the price?', self.envelope(intent=intent, options=[self.mention()]))
            self.assertEqual(result.question, 'What is the price?')

    def test_missing_required_decision_and_invalid_envelope_search_original(self):
        for payload in [{'action': 'retrieve'}, {'plan': {'action': 'retrieve'}},
                        {'alternatives': {'intent': 'new_options'}, 'plan': {'action': 'retrieve'}}, 'not json']:
            result, _, _ = self.resolve('Is Nimbus Backup compatible with Linux?', payload)
            self.assertEqual(result.question, 'Is Nimbus Backup compatible with Linux?')
            self.assertEqual(planning.get_last_plan_metadata()['status'], 'rejected_search_original')

    def test_native_contract_is_scoped_and_supported_without_guard_flag(self):
        _, generated, seen = self.resolve('Is Cedar chair foldable?', self.envelope(), guard=False)
        self.assertEqual(seen[0].schema, planning._alternatives_schema())
        payload = json.loads(generated.call_args.args[1])
        self.assertEqual([row['history_index'] for row in payload['history']], [0, 1, 2, 3])
        self.assertNotIn('JSON schema:', generated.call_args.args[2])

    def test_unknown_provider_gets_same_schema_in_prompt_without_native_transport(self):
        _, generated, seen = self.resolve('Is Cedar chair foldable?', self.envelope(), provider='unknown')
        self.assertIsNone(seen[0].schema)
        self.assertIn('JSON schema:', generated.call_args.args[2])
        self.assertIn('prior_options', generated.call_args.args[2])

    def test_supported_openai_uses_the_same_scoped_native_contract(self):
        _, generated, seen = self.resolve('Is Cedar chair foldable?', self.envelope(),
                                         provider='openai', model='gpt-4.1-mini')
        self.assertEqual(seen[0].schema, planning._alternatives_schema())
        self.assertNotIn('JSON schema:', generated.call_args.args[2])

    def test_native_schema_requires_every_object_field_and_disallows_extras(self):
        schema = planning._alternatives_schema()

        def check(value):
            if isinstance(value, dict):
                if value.get('type') == 'object':
                    self.assertEqual(value['required'], list(value['properties']))
                    self.assertFalse(value['additionalProperties'])
                self.assertNotIn('default', value)
                for child in value.values():
                    check(child)
            elif isinstance(value, list):
                for child in value:
                    check(child)

        check(schema)

    def test_flag_off_keeps_original_prompt_request_and_optional_edit_response(self):
        result, generated, seen = self.resolve('Is Cedar chair foldable?', {'action': 'retrieve'},
            contract=False, guard=False)
        self.assertEqual(result.question, 'Is Cedar chair foldable?')
        self.assertEqual(generated.call_args.args[2], planning.PROMPT)
        self.assertEqual(json.loads(generated.call_args.args[1]), {'history': self.history,
            'question': 'Is Cedar chair foldable?'})
        self.assertIsNone(seen[0].schema)

    def test_no_history_still_needs_no_planner_call(self):
        result, generated, _ = self.resolve('Any other payment methods?', 'unused', history=[])
        self.assertEqual(result.question, 'Any other payment methods?')
        generated.assert_not_called()


if __name__ == '__main__':
    unittest.main()
