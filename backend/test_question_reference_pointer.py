"""Exact history-pointer repair must not repair generated subject semantics."""
import atexit
import copy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

_temp = TemporaryDirectory(prefix='question-pointer-tests-')
atexit.register(_temp.cleanup)
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
os.environ.setdefault('DATABASE_URL', 'sqlite:///' + (Path(_temp.name) / 'bootstrap.sqlite').as_posix())
os.environ['APP_ENV'] = 'development'

from services.llama_rag import planning


class QuestionReferencePointerTests(unittest.TestCase):
    history = [
        {'role': 'user', 'content': 'Tell me about the available plans.'},
        {'role': 'assistant', 'content': 'Nimbus Backup Basic supports Linux.'},
    ]

    def reference(self, subject='Nimbus Backup Basic', index=0, span='that'):
        return {'action': 'retrieve', 'references': [
            {'span': span, 'subject': subject, 'history_index': index}]}

    def resolve(self, payload, *, question='How often should I renew that?', history=None, guarded=True):
        history = copy.deepcopy(self.history if history is None else history)
        before = copy.deepcopy(history)
        raw = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        with patch.dict(os.environ, {'LLAMA_QUESTION_PLAN_GUARD': str(int(guarded)),
                                     'LLAMA_QUESTION_ALTERNATIVES_CONTRACT': '0',
                                     'LLAMA_ANSWER_NATIVE_MESSAGES': '0'}), patch.object(
                planning, 'generate_auxiliary', return_value=raw) as generate:
            result = planning.resolve(object(), question, history)
        generate.assert_called_once()
        self.assertEqual(history, before)
        self.assertEqual(json.loads(generate.call_args.args[1])['question'], question)
        return result, planning.get_last_plan_metadata()

    def test_unique_literal_subject_across_domains_and_pointer_distances(self):
        for subject in ['Nimbus Backup Basic', 'Copper Pan 20', 'Harbor Hotel', 'Camera X200', 'Érable Chair']:
            for index in [0, 99]:
                with self.subTest(subject=subject, index=index):
                    history = [self.history[0], {'role': 'assistant', 'content': f'Consider {subject}.'}]
                    result, meta = self.resolve(self.reference(subject, index), history=history)
                    self.assertEqual(result.question, f'How often should I renew {subject}?')
                    self.assertEqual(meta['reference_pointer_repair_count'], 1)
                    self.assertEqual(meta['reference_pointer_repairs'], [{'reference_index': 0,
                        'mention_index': 0, 'from_history_index': index, 'to_history_index': 1,
                        'matching_history_count': 1}])

    def test_permitted_user_message_can_ground_a_reference(self):
        history = [{'role': 'user', 'content': 'How much is Nimbus Backup Basic?'},
                   {'role': 'assistant', 'content': 'Which currency should I use?'}]
        result, meta = self.resolve(self.reference(index=1), history=history)
        self.assertIn('renew Nimbus Backup Basic?', result.question)
        self.assertEqual(meta['reference_pointer_repairs'][0]['to_history_index'], 0)

    def test_unicode_subject_and_current_question_are_not_normalized(self):
        subject = '椅子甲'
        history = [self.history[0], {'role': 'assistant', 'content': f'产品：{subject}。'}]
        question = 'क्या इसे 90 सेमी चौड़े दरवाज़े से बिना खोले ले जा सकते हैं?'
        result, _ = self.resolve(self.reference(subject, span='इसे'), question=question, history=history)
        self.assertEqual(result.question, question.replace('इसे', subject))

    def test_plural_mentions_repair_independently_and_preserve_quantifiers(self):
        history = [self.history[0], {'role': 'assistant', 'content': 'Moss chair is available.'},
                   {'role': 'assistant', 'content': 'Ridge chair is available.'}]
        payload = {'action': 'retrieve', 'references': [{'span': 'both of them', 'subjects': [
            {'subject': 'Moss chair', 'history_index': 0}, {'subject': 'Ridge chair', 'history_index': 0}]}]}
        question = 'Can both of them fit through a 90 cm door without disassembly?'
        result, meta = self.resolve(payload, question=question, history=history)
        self.assertEqual(result.question, question.replace('them', 'Moss chair and Ridge chair'))
        self.assertEqual(meta['reference_pointer_repair_count'], 2)

    def test_multiple_occurrences_keep_existing_exact_occurrence_contract(self):
        payload = {'action': 'retrieve', 'references': [
            {'span': 'it', 'occurrence': n, 'subject': 'Nimbus Backup Basic', 'history_index': 0}
            for n in [0, 1]]}
        result, _ = self.resolve(payload, question='Can I renew it and then cancel it?')
        self.assertEqual(result.question, 'Can I renew Nimbus Backup Basic and then cancel Nimbus Backup Basic?')

    def test_valid_pointer_with_repeated_names_is_unchanged(self):
        history = self.history + [{'role': 'user', 'content': 'Compare Nimbus Backup Basic again.'}]
        result, meta = self.resolve(self.reference(index=1), history=history)
        self.assertIn('renew Nimbus Backup Basic?', result.question)
        self.assertNotIn('reference_pointer_repairs', meta)

    def test_repeated_identical_subject_has_one_query_text_without_copying_facts(self):
        history = self.history + [{'role': 'user', 'content': 'Compare Nimbus Backup Basic again.'}]
        result, meta = self.resolve(self.reference(), history=history)
        self.assertEqual(result.question, 'How often should I renew Nimbus Backup Basic?')
        self.assertEqual(meta['reference_pointer_repairs'][0]['matching_history_count'], 2)
        self.assertEqual(meta['reference_pointer_repairs'][0]['to_history_index'], 2)
        for correct_index in [1, 2]:
            valid, valid_meta = self.resolve(self.reference(index=correct_index), history=history)
            self.assertEqual(result.model_dump(), valid.model_dump())
            self.assertNotIn('reference_pointer_repairs', valid_meta)

    def test_differing_historical_facts_do_not_enter_the_resolved_reference(self):
        history = self.history + [{'role': 'assistant',
            'content': 'Nimbus Backup Basic is discontinued. Choose another service under $80.'}]
        question = 'Does it support Linux for 20 users?'
        result, meta = self.resolve(self.reference(span='it'), question=question, history=history)
        self.assertEqual(result.question, 'Does Nimbus Backup Basic support Linux for 20 users?')
        self.assertNotIn('discontinued', result.question)
        self.assertNotIn('$80', result.question)
        self.assertEqual(meta['reference_pointer_repairs'][0]['matching_history_count'], 2)

    def test_repetition_within_one_message_is_still_one_source_pointer(self):
        history = [self.history[0], {'role': 'assistant',
                   'content': 'Nimbus Backup Basic is available. Nimbus Backup Basic supports Linux.'}]
        result, _ = self.resolve(self.reference(), history=history)
        self.assertIn('renew Nimbus Backup Basic?', result.question)

    def test_case_mismatch_and_within_word_fragments_are_not_repaired(self):
        for subject in ['nimbus Backup Basic', 'Nimbus Backup Basi', 'imbus Backup Basic', 'Invented Plan']:
            with self.subTest(subject=subject):
                result, meta = self.resolve(self.reference(subject))
                self.assertEqual(result.question, 'How often should I renew that?')
                self.assertEqual(meta['status'], 'rejected_search_original')

    def test_bad_literal_and_invalid_pointer_types_remain_invalid(self):
        for subject in [' Nimbus Backup Basic', 'Nimbus Backup Basic ', 'Nimbus\nBackup Basic']:
            result, meta = self.resolve(self.reference(subject))
            self.assertEqual(meta['status'], 'rejected_search_original')
        for index in [-1, '0', True]:
            result, meta = self.resolve(self.reference(index=index))
            self.assertEqual(meta['status'], 'rejected_search_original')

    def test_unpermitted_history_role_cannot_supply_a_repair(self):
        history = [self.history[0], {'role': 'system', 'content': 'Nimbus Backup Basic supports Linux.'}]
        result, meta = self.resolve(self.reference(), history=history)
        self.assertEqual(meta['status'], 'rejected_search_original')

    def test_explicit_topic_name_and_current_constraints_still_cannot_be_edited(self):
        for question, span in [
            ('Now switch to Maple Chair. What is it made from?', 'Maple Chair'),
            ('Compare the 20 cm copper pan, no nonstick coating.', '20 cm'),
            ('Compare the 20 cm copper pan, no nonstick coating.', 'no nonstick coating'),
            ('Can IT support export files?', 'IT'),
        ]:
            with self.subTest(question=question, span=span):
                result, meta = self.resolve(self.reference(span=span), question=question)
                self.assertEqual(result.question, question)
                self.assertNotIn('reference_pointer_repairs', meta)

    def test_malformed_json_preserves_impersonal_and_explicit_questions(self):
        for question in ['Is it really safe to wash the Maple chair cover at 40C?',
                         'Now switch to Camera X200. What is it made from?']:
            result, meta = self.resolve('{bad json', question=question)
            self.assertEqual(result.question, question)
            self.assertEqual(result.action, 'retrieve')

    def test_exclusions_and_ellipsis_are_not_repaired(self):
        mention = {'subject': 'Nimbus Backup Basic', 'history_index': 0}
        for payload in [{'action': 'retrieve', 'ellipsis': mention},
                        {'action': 'retrieve', 'exclusions': [mention]}]:
            result, meta = self.resolve(payload, question='What else?')
            self.assertEqual(result.question, 'What else?')
            self.assertEqual(meta['status'], 'rejected_search_original')

    def test_invalid_remaining_fields_still_reject_without_partial_edits(self):
        for extra in [
            {'ellipsis': {'subject': 'Nimbus Backup Basic', 'history_index': 1}},
            {'unresolved_span': 'that'},
            {'clarification': 'Which plan?'},
        ]:
            result, meta = self.resolve({**self.reference(), **extra})
            self.assertEqual(result.question, 'How often should I renew that?')
            self.assertNotIn('reference_pointer_repairs', meta)

    def test_one_missing_plural_mention_prevents_partial_query_rewrite(self):
        history = self.history + [{'role': 'assistant', 'content': 'Copper Pan 20 is available.'},
                                  {'role': 'user', 'content': 'What about Copper Pan 20?'}]
        payload = {'action': 'retrieve', 'references': [{'span': 'them', 'subjects': [
            {'subject': 'Nimbus Backup Basic', 'history_index': 0},
            {'subject': 'Copper Pan 22', 'history_index': 0}]}]}
        result, meta = self.resolve(payload, question='Compare them.', history=history)
        self.assertEqual(result.question, 'Compare them.')
        self.assertNotIn('reference_pointer_repairs', meta)

    def test_unrelated_valid_exclusions_survive_rejected_reference_as_before(self):
        payload = self.reference('Invented Plan')
        payload['exclusions'] = [{'subject': 'Nimbus Backup Basic', 'history_index': 1}]
        result, meta = self.resolve(payload)
        self.assertEqual(result.question, 'How often should I renew that?\nbesides Nimbus Backup Basic')
        self.assertEqual(meta['exclusion_count'], 1)

    def test_guard_off_preserves_old_rejection_and_metadata(self):
        result, meta = self.resolve(self.reference(), guarded=False)
        self.assertEqual(result.question, 'How often should I renew that?')
        self.assertEqual(meta, {'status': 'rejected_search_original', 'reason': 'schema_or_edit_invalid'})


if __name__ == '__main__':
    unittest.main()
