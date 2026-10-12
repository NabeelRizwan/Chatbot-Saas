"""Bound conversation resolution without trusting a generated search question."""
import atexit
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

_temp = TemporaryDirectory(prefix='question-plan-tests-')
atexit.register(_temp.cleanup)
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
os.environ.setdefault('DATABASE_URL', 'sqlite:///' + (Path(_temp.name) / 'bootstrap.sqlite').as_posix())
os.environ['APP_ENV'] = 'development'

from services.llama_rag import planning


class QuestionPlanTests(unittest.TestCase):
    history = [
        {'role': 'user', 'content': 'Tell me about the Atlas desk.'},
        {'role': 'assistant', 'content': 'The Atlas desk has a wooden top. The Cedar chair is foldable.'},
    ]

    def resolve(self, question, payload, history=None):
        raw = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        with patch.object(planning, 'generate_auxiliary', return_value=raw) as generate:
            result = planning.resolve(object(), question, history or self.history)
        generate.assert_called_once()
        self.assertFalse(generate.call_args.kwargs['use_auxiliary_model'])
        return result

    def unchanged(self, question, payload, history=None):
        result = self.resolve(question, payload, history)
        self.assertEqual(result.model_dump(), {'action': 'retrieve', 'question': question, 'clarification': None})
        self.assertEqual(planning.get_last_plan_metadata()['status'], 'rejected_search_original')

    def test_no_history_bypasses_provider(self):
        with patch.object(planning, 'generate_auxiliary') as generate:
            result = planning.resolve(object(), 'A new named subject?', [])
        self.assertEqual(result.question, 'A new named subject?')
        self.assertEqual(planning.get_last_plan_metadata(), {'status': 'not_needed'})
        generate.assert_not_called()

    def test_explicit_history_labels_preserve_grounding_and_one_call(self):
        history = [dict(message) for message in self.history]
        raw = json.dumps({'action': 'retrieve', 'references': [
            {'span': 'it', 'subject': 'Cedar chair', 'history_index': 1}]})
        with patch.dict(os.environ, {'LLAMA_ANSWER_NATIVE_MESSAGES': '1'}), patch.object(
                planning, 'generate_auxiliary', return_value=raw) as generate:
            result = planning.resolve(object(), 'Is it foldable?', history)
        generate.assert_called_once()
        payload = json.loads(generate.call_args.args[1])
        self.assertEqual([message['history_index'] for message in payload['history']], [0, 1])
        self.assertEqual(payload['question'], 'Is it foldable?')
        self.assertEqual(result.question, 'Is Cedar chair foldable?')
        self.assertEqual(history, self.history)

    def test_self_contained_question_is_immutable(self):
        question = 'Compare the copper pan and steel pan: 20 cm, no nonstick coatings.'
        self.assertEqual(self.resolve(question, {'action': 'retrieve'}).question, question)
        self.assertEqual(planning.get_last_plan_metadata()['status'], 'validated')

    def test_reference_replaces_only_exact_span(self):
        question = 'How can I clean it without damaging the finish?'
        result = self.resolve(question, {'action': 'retrieve', 'references': [
            {'span': 'it', 'subject': 'Atlas desk', 'history_index': 1}]})
        self.assertEqual(result.question, 'How can I clean Atlas desk without damaging the finish?')
        self.assertEqual(planning.get_last_plan_metadata()['reference_count'], 1)

    def test_multilingual_reference_preserves_numbers_and_negation(self):
        result = self.resolve('क्या इसे 90 सेमी चौड़े दरवाज़े से बिना खोले ले जा सकते हैं?',
            {'action': 'retrieve', 'references': [{'span': 'इसे', 'subject': 'Atlas desk', 'history_index': 1}]})
        self.assertEqual(result.question, 'क्या Atlas desk 90 सेमी चौड़े दरवाज़े से बिना खोले ले जा सकते हैं?')

    def test_multiple_references_use_original_positions(self):
        result = self.resolve('Compare this one with that one.', {'action': 'retrieve', 'references': [
            {'span': 'this one', 'subject': 'Atlas desk', 'history_index': 1},
            {'span': 'that one', 'subject': 'Cedar chair', 'history_index': 1}]})
        self.assertEqual(result.question, 'Compare Atlas desk with Cedar chair.')

    def test_repeated_references_use_explicit_occurrence_indexes(self):
        result = self.resolve('Is it folding and is it heavy?', {'action': 'retrieve', 'references': [
            {'span': 'it', 'occurrence': index, 'subject': 'Cedar chair', 'history_index': 1}
            for index in [1, 0]]})
        self.assertEqual(result.question, 'Is Cedar chair folding and is Cedar chair heavy?')
        for indexes in [[0, 0], [0, 2], [-1], ['0']]:
            self.unchanged('Is it folding and is it heavy?', {'action': 'retrieve', 'references': [
                {'span': 'it', 'occurrence': index, 'subject': 'Cedar chair', 'history_index': 1}
                for index in indexes]})

    def test_repeated_identical_mapping_can_resolve_all_and_repair_case(self):
        for spans in [['it'], ['It', 'it']]:
            result = self.resolve('Is it folding and is it heavy?', {'action': 'retrieve', 'references': [
                {'span': span, 'subject': 'Cedar chair', 'history_index': 1} for span in spans]})
            self.assertEqual(result.question, 'Is Cedar chair folding and is Cedar chair heavy?')
        self.unchanged('Can IT export it?', {'action': 'retrieve', 'references': [
            {'span': 'it', 'subject': 'Atlas desk', 'history_index': 1}]})
        self.unchanged('Is it folding and is it heavy?', {'action': 'retrieve', 'references': [
            {'span': 'it', 'subject': subject, 'history_index': 1} for subject in ['Atlas desk', 'Cedar chair']]})

    def test_plural_reference_can_use_separate_history_mentions(self):
        history = [{'role': 'assistant', 'content': 'First option: Atlas desk.\n\nSecond option: Cedar chair.'}]
        result = self.resolve('Which of them is cheaper?', {'action': 'retrieve', 'references': [
            {'span': 'them', 'subjects': [{'subject': 'Atlas desk', 'history_index': 0},
                                        {'subject': 'Cedar chair', 'history_index': 0}]}]}, history)
        self.assertEqual(result.question, 'Which of Atlas desk and Cedar chair is cheaper?')

    def test_plural_reference_cannot_mix_shapes_or_invent_one_subject(self):
        subjects = [{'subject': 'Atlas desk', 'history_index': 1},
                    {'subject': 'Invented stool', 'history_index': 1}]
        self.unchanged('Compare them.', {'action': 'retrieve', 'references': [{'span': 'them', 'subjects': subjects}]})
        self.unchanged('Compare them.', {'action': 'retrieve', 'references': [{'span': 'them',
            'subject': 'Atlas desk', 'history_index': 1, 'subjects': subjects[:1]}]})

    def test_ellipsis_appends_separate_grounded_context(self):
        result = self.resolve('How much?', {'action': 'retrieve', 'ellipsis':
            {'subject': 'Atlas desk', 'history_index': 1}})
        self.assertEqual(result.question, 'How much?\nContext subject: Atlas desk')

    def test_alternatives_keep_question_and_deduplicate_grounded_exclusions(self):
        mention = {'subject': 'Cedar chair', 'history_index': 1}
        result = self.resolve('Any other folding chairs under $150? No leather.',
            {'action': 'retrieve', 'exclusions': [mention, mention]})
        self.assertEqual(result.question, 'Any other folding chairs under $150? No leather.\nbesides Cedar chair')

    def test_observed_old_subject_prefix_insertion_is_not_a_valid_plan(self):
        question = 'Compare the plain and chocolate collagen products.'
        history = [{'role': 'assistant', 'content': 'NutriMax Essentials is taken with a meal.'}]
        self.unchanged(question, {'action': 'retrieve', 'question': 'Compare the NutriMax plain and chocolate collagen products.'}, history)
        self.unchanged(question, {'action': 'retrieve', 'references': [
            {'span': '', 'subject': 'NutriMax', 'history_index': 0}]}, history)

    def test_synthesized_product_name_is_not_a_history_mention(self):
        self.unchanged('How should I use it?', {'action': 'retrieve', 'references': [
            {'span': 'it', 'subject': 'Atlas wooden-top Deluxe desk', 'history_index': 1}]})

    def test_quote_must_belong_to_indicated_message(self):
        self.unchanged('Is it folding?', {'action': 'retrieve', 'references': [
            {'span': 'it', 'subject': 'Cedar chair', 'history_index': 0}]})

    def test_unmatched_duplicate_and_overlapping_spans_are_rejected(self):
        for spans in [['missing'], ['it', 'it']]:
            with self.subTest(spans=spans):
                self.unchanged('How do I clean it?', {'action': 'retrieve', 'references': [
                    {'span': span, 'subject': 'Atlas desk', 'history_index': 1} for span in spans]})
        self.unchanged('Compare that one now.', {'action': 'retrieve', 'references': [
            {'span': span, 'subject': 'Atlas desk', 'history_index': 1} for span in ['that one', 'one']]})

    def test_whole_question_cannot_be_a_replacement_span(self):
        self.unchanged('How much?', {'action': 'retrieve', 'references': [
            {'span': 'How much?', 'subject': 'Atlas desk', 'history_index': 1}]})

    def test_indexes_are_strict_and_in_range(self):
        for index in [-1, 2, True, '1']:
            with self.subTest(index=index):
                self.unchanged('How much?', {'action': 'retrieve', 'ellipsis':
                    {'subject': 'Atlas desk', 'history_index': index}})

    def test_clarification_requires_unique_nonempty_current_span(self):
        result = self.resolve('Can it be used outdoors?', {'action': 'clarify', 'unresolved_span': 'it',
            'clarification': 'Do you mean the desk or the chair?'})
        self.assertEqual(result.action, 'clarify')
        for span in ['', 'NutriMax']:
            with self.subTest(span=span):
                self.unchanged('Can it be used outdoors?', {'action': 'clarify',
                    'unresolved_span': span, 'clarification': 'Which one?'})

    def test_whole_question_clarification_is_allowed_without_rewriting(self):
        result = self.resolve('Which one?', {'action': 'clarify', 'unresolved_span': 'Which one?',
            'clarification': 'Do you mean the desk or the chair?'})
        self.assertEqual(result.action, 'clarify')

    def test_mixed_actions_and_duplicate_context_are_rejected(self):
        mention = {'subject': 'Atlas desk', 'history_index': 1}
        self.unchanged('How do I clean it?', {'action': 'retrieve', 'references': [dict(mention, span='it')],
            'ellipsis': mention})
        self.unchanged('How do I clean it?', {'action': 'retrieve', 'clarification': 'Which one?'})
        self.unchanged('How do I clean it?', {'action': 'clarify', 'unresolved_span': 'it',
            'clarification': 'Which one?', 'ellipsis': mention})

    def test_malformed_output_falls_back_without_second_call(self):
        for payload in ['not json', '[]', '{}', {'action': 'retrieve', 'references': 'it'}]:
            with self.subTest(payload=payload):
                self.unchanged('How much?', payload)

    def test_expansion_over_limit_preserves_original(self):
        question = 'x' * 1990 + ' it?'
        self.unchanged(question, {'action': 'retrieve', 'references': [
            {'span': 'it', 'subject': 'Atlas desk', 'history_index': 1}]})

    def test_metadata_contains_no_question_or_history(self):
        self.resolve('Private customer question?', {'action': 'retrieve'})
        metadata = planning.get_last_plan_metadata()
        self.assertNotIn('Private', json.dumps(metadata))
        metadata['status'] = 'tampered'
        self.assertEqual(planning.get_last_plan_metadata()['status'], 'validated')


if __name__ == '__main__':
    unittest.main()
