"""Compare opt-in planner safeguards with the preserved baseline contract."""
import atexit
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

_temp = TemporaryDirectory(prefix='question-guard-tests-')
atexit.register(_temp.cleanup)
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
os.environ.setdefault('DATABASE_URL', 'sqlite:///' + (Path(_temp.name) / 'bootstrap.sqlite').as_posix())
os.environ['APP_ENV'] = 'development'

from services.llama_rag import planning


class QuestionPlanGuardTests(unittest.TestCase):
    history = [
        {'role': 'user', 'content': 'Find a foldable chair under $150, no leather.'},
        {'role': 'assistant', 'content': 'Cedar chair is an option. Atlas desk is also available.'},
    ]

    def resolve(self, question, payload, *, guarded=True, history=None):
        raw = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        with patch.dict(os.environ, {'LLAMA_QUESTION_PLAN_GUARD': '1' if guarded else '0',
                                     'LLAMA_QUESTION_ALTERNATIVES_CONTRACT': '0',
                                     'LLAMA_ANSWER_NATIVE_MESSAGES': '0'}), patch.object(
                planning, 'generate_auxiliary', return_value=raw) as generate:
            result = planning.resolve(object(), question, history or self.history)
        generate.assert_called_once()
        self.assertFalse(generate.call_args.kwargs['use_auxiliary_model'])
        return result, generate

    def reference(self, span, subject='Cedar chair'):
        return {'action': 'retrieve', 'references': [{'span': span, 'subject': subject, 'history_index': 1}]}

    def test_explicit_subject_attack_is_rejected_across_domains(self):
        cases = [
            ('Compare the copper pan with the steel pan.', 'copper pan'),
            ('Does the Nimbus backup service support Linux?', 'Nimbus backup service'),
            ('Is Alpine Hotel accessible?', 'Alpine Hotel'),
            ('How do Basic and Premium subscriptions differ?', 'Premium'),
            ('Does this Copper Pan need seasoning?', 'Copper Pan'),
        ]
        for question, span in cases:
            with self.subTest(question=question):
                result, _ = self.resolve(question, self.reference(span))
                self.assertEqual(result.question, question)
                self.assertEqual(planning.get_last_plan_metadata()['status'], 'rejected_search_original')

    def test_numbers_negation_preferences_and_quantity_are_not_references(self):
        question = 'Find a 20 cm copper pan, no nonstick coating, one handle, under $100.'
        for span in ['20 cm', '20', 'no nonstick coating', 'under $100', 'one', 'one handle']:
            with self.subTest(span=span):
                result, _ = self.resolve(question, self.reference(span))
                self.assertEqual(result.question, question)

    def test_bad_clarification_cannot_require_new_name_to_exist_in_history(self):
        question = 'How does Nimbus hosting compare with Aurora hosting?'
        for span in ['Nimbus hosting', question]:
            result, _ = self.resolve(question, {'action': 'clarify', 'unresolved_span': span,
                'clarification': 'Which Cedar chair do you mean? '})
            self.assertEqual(result.question, question)
            self.assertEqual(result.action, 'retrieve')

    def test_valid_pronoun_keeps_all_explicit_constraints(self):
        question = 'Can it fit through a 90 cm doorway without disassembly? No power tools.'
        result, _ = self.resolve(question, self.reference('it'))
        self.assertEqual(result.question, question.replace('it', 'Cedar chair', 1))

    def test_valid_multilingual_reference_preserves_literals(self):
        question = 'क्या इसे 90 सेमी चौड़े दरवाज़े से बिना खोले ले जा सकते हैं?'
        result, _ = self.resolve(question, self.reference('इसे'))
        self.assertEqual(result.question, question.replace('इसे', 'Cedar chair'))

    def test_plural_and_demonstrative_references_still_work(self):
        for span in ['them', 'these products', 'the previous one']:
            question = f'Compare {span} for use outdoors, without leather.'
            result, _ = self.resolve(question, {'action': 'retrieve', 'references': [{'span': span,
                'subjects': [{'subject': 'Cedar chair', 'history_index': 1},
                             {'subject': 'Atlas desk', 'history_index': 1}]}]})
            self.assertEqual(result.question, question.replace(span, 'Cedar chair and Atlas desk'))

    def test_quantified_reference_preserves_quantifier_and_current_task(self):
        for prefix in ['each', 'both', 'all', 'either', 'neither', 'one', 'any', 'some', 'none']:
            for reference in ['them', 'these', 'those', 'these ones', 'those ones']:
                span = f'{prefix} of {reference}'
                question = f'How much would {span} cost for 20 users?'
                result, _ = self.resolve(question, {'action': 'retrieve', 'references': [{'span': span,
                    'subjects': [{'subject': 'Cedar chair', 'history_index': 1},
                                 {'subject': 'Atlas desk', 'history_index': 1}]}]})
                self.assertEqual(result.question, question.replace(reference, 'Cedar chair and Atlas desk'))

    def test_quantified_reference_cannot_wrap_an_explicit_name_or_constraint(self):
        for span in ['both of Cedar chair', 'each of the $150 plans', 'one of no leather']:
            question = f'Compare {span} with Atlas desk.'
            result, _ = self.resolve(question, self.reference(span))
            self.assertEqual(result.question, question)

    def test_quantified_repeated_occurrences_preserve_each_original_prefix(self):
        question = 'Is each of them available and is each of them foldable?'
        result, _ = self.resolve(question, {'action': 'retrieve', 'references': [
            {'span': 'each of them', 'occurrence': index, 'subject': subject, 'history_index': 1}
            for index, subject in enumerate(['Cedar chair', 'Atlas desk'])]})
        self.assertEqual(result.question, 'Is each of Cedar chair available and is each of Atlas desk foldable?')

    def test_repeated_pronouns_and_exact_positions_still_work(self):
        question = 'Is it foldable and is it heavy?'
        result, _ = self.resolve(question, self.reference('it'))
        self.assertEqual(result.question, question.replace('it', 'Cedar chair'))

    def test_capitalized_acronym_is_not_a_pronoun(self):
        question = 'Can IT support export files?'
        for span in ['IT', 'it']:
            result, _ = self.resolve(question, self.reference(span))
            self.assertEqual(result.question, question)
        result, _ = self.resolve(question, {'action': 'clarify', 'unresolved_span': 'it',
            'clarification': 'Which chair?'})
        self.assertEqual(result.question, question)

    def test_valid_ellipsis_preserves_question(self):
        for question in ['How much?', 'And shipping?', 'What about warranty?']:
            result, _ = self.resolve(question, {'action': 'retrieve', 'ellipsis':
                {'subject': 'Cedar chair', 'history_index': 1}})
            self.assertEqual(result.question, question + '\nContext subject: Cedar chair')

    def test_ellipsis_with_new_constraints_keeps_existing_followup_contract(self):
        question = 'And for a 90 cm doorway, without taking it apart?'
        result, _ = self.resolve(question, {'action': 'retrieve', 'ellipsis':
            {'subject': 'Cedar chair', 'history_index': 1}})
        self.assertEqual(result.question, question + '\nContext subject: Cedar chair')

    def test_alternatives_preserve_new_constraints_and_grounded_exclusion(self):
        question = 'What other non-folding chairs under $100 are available? Leather is fine.'
        result, _ = self.resolve(question, {'action': 'retrieve', 'exclusions':
            [{'subject': 'Cedar chair', 'history_index': 1}]})
        self.assertEqual(result.question, question + '\nbesides Cedar chair')
        self.assertNotIn('$150', result.question)
        self.assertNotIn('no leather', result.question)

    def test_bad_reference_does_not_discard_valid_exclusions(self):
        question = 'What other non-folding chairs under $100 are available? Leather is fine.'
        payload = self.reference('non-folding chairs')
        payload['exclusions'] = [{'subject': 'Cedar chair', 'history_index': 1}]
        result, _ = self.resolve(question, payload)
        self.assertEqual(result.question, question + '\nbesides Cedar chair')
        self.assertEqual(planning.get_last_plan_metadata()['exclusion_count'], 1)

    def test_invalid_exclusions_are_not_salvaged_and_valid_ones_deduplicate(self):
        question = 'What other non-folding chairs are available?'
        mention = {'subject': 'Cedar chair', 'history_index': 1}
        payload = self.reference('non-folding chairs')
        payload['exclusions'] = [mention, {'subject': 'Imaginary stool', 'history_index': 1}, mention]
        result, _ = self.resolve(question, payload)
        self.assertEqual(result.question, question + '\nbesides Cedar chair')

    def test_grounded_exclusions_are_not_removed_by_an_intent_lexicon(self):
        questions = ['Show me three more foldable chairs under $150.',
                     'Show me different foldable chairs under $150.',
                     'Show me additional foldable chairs under $150.',
                     'Zeig mir weitere faltbare Stühle unter 150 Euro.',
                     'मुझे कुछ और कुर्सियाँ दिखाइए।']
        for question in questions:
            result, _ = self.resolve(question, {'action': 'retrieve', 'exclusions':
                [{'subject': 'Cedar chair', 'history_index': 1}]})
            self.assertEqual(result.question, question + '\nbesides Cedar chair')

    def test_rejected_edit_preserves_exclusions_without_english_intent_words(self):
        question = 'Zeig mir weitere faltbare Stühle unter 150 Euro.'
        payload = self.reference('faltbare Stühle')
        payload['exclusions'] = [{'subject': 'Cedar chair', 'history_index': 1}]
        result, _ = self.resolve(question, payload)
        self.assertEqual(result.question, question + '\nbesides Cedar chair')

    def test_omitted_exclusions_are_not_invented(self):
        question = 'What other non-folding chairs under $100 are available? Leather is fine.'
        result, generate = self.resolve(question, {'action': 'retrieve'})
        self.assertEqual(result.question, question)
        data = json.loads(generate.call_args.args[1])
        self.assertTrue(data['request_checks']['may_request_alternatives'])
        self.assertTrue(planning.get_last_plan_metadata()['alternatives_without_exclusions'])

    def test_guard_supplies_indexes_without_native_answer_flag(self):
        _, generate = self.resolve('Is it foldable?', self.reference('it'))
        data = json.loads(generate.call_args.args[1])
        self.assertEqual([item['history_index'] for item in data['history']], [0, 1])
        self.assertNotIn('history_index', self.history[0])
        self.assertNotIn('request_checks', data)
        self.assertEqual(generate.call_args.args[2], planning.PROMPT + planning._EDIT_CONTRACT_REMINDER)

    def test_rejected_dependent_question_preserves_baseline_fallback(self):
        for question in ['Is it foldable?', 'Can it be used outdoors?', 'How much?', 'Which one?']:
            result, _ = self.resolve(question, 'not json')
            self.assertEqual(result.question, question)
            self.assertEqual(result.action, 'retrieve')
            self.assertEqual(planning.get_last_plan_metadata()['status'], 'rejected_search_original')

    def test_rejected_explicit_questions_search_original_without_clarifying(self):
        for question in ['Is this chair foldable?', 'Is Cedar chair foldable?', 'Can IT export data?',
                         'Is it possible to use Nimbus hosting without a credit card?',
                         'Is it really safe to wash the chair cover at 40C?']:
            result, _ = self.resolve(question, 'not json')
            self.assertEqual(result.question, question)

    def test_model_clarification_for_real_reference_still_works(self):
        question = 'Can it be used outdoors?'
        result, _ = self.resolve(question, {'action': 'clarify', 'unresolved_span': 'it',
            'clarification': 'Do you mean the chair or the desk?'})
        self.assertEqual(result.clarification, 'Do you mean the chair or the desk?')

    def test_feature_off_preserves_baseline_including_known_gap(self):
        question = 'Does Nimbus hosting support Linux?'
        result, generate = self.resolve(question, self.reference('Nimbus hosting'), guarded=False)
        self.assertEqual(result.question, 'Does Cedar chair support Linux?')
        data = json.loads(generate.call_args.args[1])
        self.assertNotIn('request_checks', data)
        self.assertNotIn('history_index', data['history'][0])
        self.assertEqual(generate.call_args.args[2], planning.PROMPT)
        fallback, _ = self.resolve('How much?', 'bad', guarded=False)
        self.assertEqual(fallback.question, 'How much?')

    def test_metadata_does_not_store_customer_text(self):
        question = 'Does Private Nimbus Premium support export?'
        self.resolve(question, self.reference('Private Nimbus Premium'))
        self.assertNotIn('Private', json.dumps(planning.get_last_plan_metadata()))


if __name__ == '__main__':
    unittest.main()
