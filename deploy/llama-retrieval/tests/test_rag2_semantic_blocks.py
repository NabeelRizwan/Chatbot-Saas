"""Synthetic cross-domain contract tests; no corpora, gold fixtures or models."""
from collections import Counter
from copy import deepcopy
import unittest

from rag2.context_block_rerank import prepare_candidates, assemble, readable_block
from rag2.context_blocks_six_span_control import prepare_block_index
from rag2_test_helpers import node, scored, document, existing, empty, encode


class PairTokenizer:
    def __init__(self, fixed=None):
        self.fixed, self.calls = fixed, []

    def __call__(self, query, text, *, truncation, add_special_tokens):
        assert truncation is False and add_special_tokens is True
        self.calls.append((query, text))
        size = self.fixed if self.fixed is not None else len(query.split())+len(text.split())+3
        return {'input_ids': list(range(size))}


def fixtures(texts):
    nodes, docs = {}, {}
    for source, text in texts.items():
        nodes[source] = node(source, source, text, 0, len(text))
        docs[source] = document(source, text)
    return nodes, docs


def base_question(question='Which supported details answer this request?'):
    base = empty()
    base['question'] = question
    return base


class SemanticBlockTests(unittest.TestCase):
    def test_pair_budget_is_shared_fairly_before_scoring(self):
        texts = {f'source-{i}': 'This source states a complete fact with its qualifying condition.' for i in range(48)}
        nodes, docs = fixtures(texts)
        groups = {f'group-{g}': [scored(nodes[f'source-{i}'], 100-i) for i in range(g*12, (g+1)*12)]
                  for g in range(4)}
        base = base_question()
        base['audit']['scoped_queries'] = {g: f'Original recorded task for {g}' for g in groups}
        result = prepare_candidates(base, groups, nodes, docs, encode,
                                    prepare_block_index(nodes, docs), pair_tokenizer=PairTokenizer())
        self.assertEqual(len(result['proposals']), 32)
        self.assertEqual(Counter(p['group'] for p in result['proposals']), {g: 8 for g in groups})
        self.assertEqual(len({p['key'] for p in result['proposals']}), 32)
        self.assertTrue(all(p['query'] == base['audit']['scoped_queries'][p['group']]
                            for p in result['proposals']))

    def test_unfilled_group_quota_is_reused(self):
        texts = {f'policy-{i}': 'The archive keeps this complete record until its stated retention date.' for i in range(7)}
        nodes, docs = fixtures(texts)
        groups = {'one': [scored(nodes['policy-0'])],
                  'many': [scored(nodes[f'policy-{i}']) for i in range(1, 7)]}
        base = base_question()
        base['audit']['scoped_queries'] = {'one': 'The first task', 'many': 'The second task'}
        result = prepare_candidates(base, groups, nodes, docs, encode,
                                    pair_tokenizer=PairTokenizer(), max_pairs=6)
        self.assertEqual(Counter(p['group'] for p in result['proposals']), {'one': 1, 'many': 5})

    def test_readable_pair_removes_media_and_unrelated_metadata(self):
        text = ('## Connection\n![A decorative photo with an unsupported marketing claim.](https://example.test/picture)\n\n'
                'The adapter supports two display ports. It does not charge the attached computer.\n')
        nodes, docs = fixtures({'adapter': text})
        nodes['adapter'].metadata['section'] = 'Unrelated gallery metadata'
        result = prepare_candidates(base_question(), {'global': [scored(nodes['adapter'])]}, nodes, docs,
                                    encode, pair_tokenizer=PairTokenizer())
        proposal = result['proposals'][0]
        self.assertIn('does not charge', proposal['model_text'])
        self.assertNotIn('unsupported marketing', proposal['model_text'])
        self.assertNotIn('https://', proposal['model_text'])
        self.assertNotIn('Unrelated gallery', proposal['model_text'])
        self.assertEqual(proposal['item']['text'], text)

    def test_actual_pair_limit_rejects_whole_input_without_truncation(self):
        nodes, docs = fixtures({'manual': 'The complete procedure includes a qualification that must remain visible.'})
        result = prepare_candidates(base_question(), {'global': [scored(nodes['manual'])]}, nodes, docs,
                                    encode, pair_tokenizer=PairTokenizer(fixed=513))
        self.assertEqual(result['proposals'], [])
        self.assertTrue(any(r['reason'] == 'pair_token_limit' for r in result['audit']['rejected']))
        with self.assertRaises(ValueError):
            prepare_candidates(base_question(), {'global': [scored(nodes['manual'])]}, nodes, docs, encode)

    def test_assemble_preserves_base_and_contradiction(self):
        old = 'The starter plan retains audit logs for thirty days.'
        new = 'The starter plan does not retain audit logs after seven days.'
        nodes, docs = fixtures({'revised-policy': new})
        base = existing('original-policy', old)
        base['question'] = 'What retention period does the starter plan document?'
        before = deepcopy(base)
        prepared = prepare_candidates(base, {'global': [scored(nodes['revised-policy'])]}, nodes, docs,
                                      encode, pair_tokenizer=PairTokenizer())
        original_proposals = deepcopy(prepared['proposals'])
        result = assemble(base, prepared['proposals'], [3.5], encode)
        self.assertEqual(base, before)
        self.assertEqual(prepared['proposals'], original_proposals)
        self.assertTrue(result['context'].startswith(base['context']))
        self.assertEqual(result['evidence'][0], base['evidence'][0])
        self.assertIn(new, result['context'])

    def test_group_fairness_does_not_compare_unrelated_logit_scales(self):
        texts = {'camp-a': 'The tent requires two separate anchors when the ground is soft.',
                 'camp-b': 'The stove must remain outdoors while the burner is operating.',
                 'account': 'The account export includes event records but excludes private credentials.'}
        nodes, docs = fixtures(texts)
        groups = {'camp': [scored(nodes['camp-a'], 9), scored(nodes['camp-b'], 8)],
                  'software': [scored(nodes['account'], -9)]}
        base = base_question()
        base['audit']['scoped_queries'] = {'camp': 'Explain the camping equipment constraints.',
                                         'software': 'Explain the account export constraints.'}
        proposals = prepare_candidates(base, groups, nodes, docs, encode,
                                       pair_tokenizer=PairTokenizer())['proposals']
        scores = [100 if p['group'] == 'camp' else -100 for p in proposals]
        result = assemble(base, proposals, scores, encode, max_spans=2)
        self.assertEqual(Counter(a['group'] for a in result['audit']['semantic_block_supplement']['accepted']),
                         {'camp': 1, 'software': 1})

    def test_table_model_view_preserves_cell_relations_and_raw_evidence(self):
        text = '| Operation | Limit |\n|---|---|\n| Bulk export | At most twelve jobs |\n'
        self.assertIn('Operation | Limit', readable_block(text))
        self.assertIn('Bulk export | At most twelve jobs', readable_block(text))
        nodes, docs = fixtures({'software': text})
        proposals = prepare_candidates(base_question(), {'global': [scored(nodes['software'])]}, nodes, docs,
                                       encode, pair_tokenizer=PairTokenizer())['proposals']
        self.assertEqual(proposals[0]['item']['text'], text)

    def test_only_original_scored_pool_can_supply_a_block(self):
        texts = {'parking': 'Parking is permitted after noon except during the posted maintenance window.',
                 'recipe': 'This recipe includes sesame seeds and does not claim to be allergen free.'}
        nodes, docs = fixtures(texts)
        proposals = prepare_candidates(base_question(), {'global': [scored(nodes['parking'])]}, nodes, docs,
                                       encode, pair_tokenizer=PairTokenizer())['proposals']
        self.assertEqual({p['node_id'] for p in proposals}, {'parking'})
        self.assertTrue(all('sesame' not in p['model_text'] for p in proposals))

    def test_linked_cards_and_fully_covered_units_are_not_rescored(self):
        text = 'The source states the opening hours and the weekly closure clearly.'
        nodes, docs = fixtures({'hours': text, 'host': text})
        nodes['host'].metadata['subject_source_id'] = 'linked-subject'
        base = existing('hours', text)
        base['question'] = 'What hours are documented?'
        result = prepare_candidates(base, {'global': [scored(nodes['hours']), scored(nodes['host'])]},
                                    nodes, docs, encode, pair_tokenizer=PairTokenizer())
        self.assertEqual(result['proposals'], [])
        self.assertEqual({r['reason'] for r in result['audit']['rejected']}, {'linked_subject', 'already_covered'})

    def test_invalid_scores_mutated_proposals_and_bounds_fail(self):
        nodes, docs = fixtures({'manual': 'Use this complete procedure only with the specified cable connected.'})
        base = base_question()
        proposals = prepare_candidates(base, {'global': [scored(nodes['manual'])]}, nodes, docs,
                                       encode, pair_tokenizer=PairTokenizer())['proposals']
        for scores in ([], [float('nan')], [float('inf')]):
            with self.assertRaises(ValueError):
                assemble(base, proposals, scores, encode)
        changed = deepcopy(proposals)
        changed[0]['item']['text'] = 'Mutated after inference input was frozen.'
        with self.assertRaises(ValueError):
            assemble(base, changed, [1], encode)
        for limits in ({'max_spans': 7}, {'extra_tokens': 1201}, {'max_total_tokens': 5201}):
            with self.assertRaises(ValueError):
                assemble(base, proposals, [1], encode, **limits)
        with self.assertRaises(ValueError):
            prepare_candidates(base, {'global': [scored(nodes['manual'])]}, nodes, docs,
                               encode, pair_tokenizer=PairTokenizer(), max_pairs=33)

    def test_fake_injected_scorer_receives_frozen_pairs_once(self):
        nodes, docs = fixtures({'support': 'Appointments can be moved before the specified cancellation deadline.'})
        base = base_question()
        prepared = prepare_candidates(base, {'global': [scored(nodes['support'])]}, nodes, docs,
                                      encode, pair_tokenizer=PairTokenizer())
        calls = []
        def fake_predict(pairs):
            calls.append(pairs)
            return [0.75 for _ in pairs]
        proposals = prepared['proposals']
        scores = fake_predict([(p['query'], p['model_text']) for p in proposals])
        result = assemble(base, proposals, scores, encode)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['audit']['semantic_block_supplement']['additional_scored_pairs'], len(proposals))
        self.assertEqual(prepared['audit']['inference_calls'], 0)


if __name__ == '__main__':
    unittest.main()
