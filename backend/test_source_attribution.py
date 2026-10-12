"""Source attribution must never alter evidence or expose private stream metadata."""

import unittest
from types import SimpleNamespace

from services.llama_rag.citations import AttributionStream, select_sources, retain_answer_links
from services.llama_rag.client import RetrievalError
from services.llama_rag.streaming import EvidenceStream


def evidence(count=3):
    return [{'document': SimpleNamespace(id=index),
             'chunk': SimpleNamespace(metadata_json={'citation_id': str(index)})}
            for index in range(1, count + 1)]


class SourceAttributionTests(unittest.TestCase):
    def test_only_selected_passages_are_returned_in_model_order(self):
        items = evidence()
        text, selected, audit = select_sources(
            'Compare **A** and **B**.\n\n- A: 12 cm.\n- B: 15 cm.\n'
            '<source_refs>["3", "1", "3"]</source_refs>', items)
        self.assertEqual(text, 'Compare **A** and **B**.\n\n- A: 12 cm.\n- B: 15 cm.')
        self.assertEqual(selected, [items[2], items[0]])
        self.assertEqual(audit['selected_ids'], ['3', '1'])
        self.assertEqual(audit['status'], 'valid')
        self.assertEqual(len(items), 3)

    def test_missing_references_do_not_guess_from_retrieval_or_links(self):
        text = 'The desk is 120 cm wide. See https://example.test/desk.\n'
        answer, selected, audit = select_sources(text, evidence())
        self.assertEqual(answer, text)
        self.assertEqual(selected, [])
        self.assertEqual(audit['status'], 'missing')

    def test_invalid_and_foreign_ids_are_rejected_but_valid_ids_survive(self):
        items = evidence()
        answer, selected, audit = select_sources(
            'The desk is 120 cm wide.\n<source_refs>'
            '["900", "1", true, 1.0, {}, "https://foreign.test", 2]</source_refs>', items)
        self.assertEqual(answer, 'The desk is 120 cm wide.')
        self.assertEqual(selected, items[:2])
        self.assertEqual(audit['invalid_count'], 5)
        self.assertEqual(audit['status'], 'invalid_ids')

    def test_no_support_is_a_valid_empty_selection(self):
        answer, selected, audit = select_sources(
            'I cannot confirm that detail.\n<source_refs>[]</source_refs>', evidence())
        self.assertEqual(answer, 'I cannot confirm that detail.')
        self.assertEqual(selected, [])
        self.assertEqual(audit['status'], 'valid')

    def test_malformed_metadata_does_not_break_answer_or_become_visible(self):
        for trailer in ('<source_refs>["1"]', '<source_refs>{"ids":["1"]}</source_refs>',
                        '<source_refs>["1",]</source_refs>', '<source_refs>["1"]</source_refs> extra',
                        '<source_refs>["1"]</source_refs><source_refs>["2"]</source_refs>',
                        '</source_refs>', '<source_refs' + ' ' * 5000,
                        '<source_refs>' + str([1] * 65) + '</source_refs>'):
            with self.subTest(trailer=trailer[:70]):
                answer, selected, audit = select_sources('Answer.\n' + trailer, evidence())
                self.assertEqual(answer, 'Answer.')
                self.assertEqual(selected, [])
                self.assertEqual(audit['status'], 'malformed')

    def test_metadata_alone_is_not_a_customer_answer(self):
        answer, _, _ = select_sources('<source_refs>["1"]</source_refs>', evidence())
        self.assertEqual(answer, '')

    def test_document_ids_cannot_replace_context_ids(self):
        items = [{'document': SimpleNamespace(id=123),
                  'chunk': SimpleNamespace(metadata_json={'citation_id': '1'})}]
        _, selected, audit = select_sources('Answer.\n<source_refs>[123]</source_refs>', items)
        self.assertEqual(selected, [])
        self.assertEqual(audit['invalid_count'], 1)

    def test_buffered_response_has_same_size_bound_as_stream(self):
        with self.assertRaisesRegex(RetrievalError, 'generation_response_too_large'):
            select_sources('x' * 200001, evidence())

    def test_cited_page_does_not_advertise_unmentioned_related_product_links(self):
        source = {'source_url': 'https://example.test/catalog', 'cta_links': [
            {'label': 'Desk', 'url': 'https://example.test/desk'},
            {'label': 'Chair', 'url': 'https://example.test/chair'},
            {'label': 'Lookalike', 'url': 'https://example.test/desk?unrelated=true'}]}
        answer = 'You can [buy the desk](https://example.test/desk).'
        rendered = retain_answer_links([source], answer)
        self.assertEqual(rendered[0]['source_url'], source['source_url'])
        self.assertEqual(rendered[0]['cta_links'], source['cta_links'][:1])
        self.assertEqual(len(source['cta_links']), 3)
        self.assertEqual(retain_answer_links([source], 'The desk is 120 cm wide.')[0]['cta_links'], [])


class AttributionStreamingTests(unittest.TestCase):
    def run_stream(self, chunks):
        events = []
        delivery = EvidenceStream(events.append, lambda text: text, lambda: None)
        stream = AttributionStream(delivery.feed)
        for chunk in chunks:
            stream.feed(chunk)
        final, _, _ = select_sources(''.join(chunks), evidence())
        delivery.finish(final)
        self.assertEqual(''.join(events), final)
        self.assertNotIn('source_refs', ''.join(events))
        return final

    def test_every_split_position_keeps_metadata_private(self):
        answer = '**Desk**\n\n- Width: 120 cm.\n- Care: dry cloth.'
        response = answer + '\n\n<source_refs>["1", "2"]</source_refs>\n'
        for index in range(len(response) + 1):
            with self.subTest(index=index):
                self.assertEqual(self.run_stream([response[:index], response[index:]]), answer)
        self.assertEqual(self.run_stream(list(response)), answer)

    def test_missing_metadata_preserves_normal_paragraphs_and_whitespace(self):
        for response in ('A short answer.', 'One.\n\nTwo.\n\n', 'Value < 3.',
                         'Read [details](https://example.test/a).\n\nThen return.'):
            with self.subTest(response=response):
                self.assertEqual(self.run_stream(list(response)), response)

    def test_all_partial_tag_terminations_are_hidden(self):
        marker = '<source_refs>'
        for end in range(1, len(marker) + 1):
            with self.subTest(end=end):
                self.assertEqual(self.run_stream(list('Answer.\n' + marker[:end])), 'Answer.')

    def test_missing_or_bad_metadata_never_emits_private_tail_paragraphs(self):
        response = 'Answer.\n\n<source_refs>\n\n["1"]\n\nwrong closing tag\n\n'
        self.assertEqual(self.run_stream(list(response)), 'Answer.')

    def test_scope_revocation_and_cancellation_still_propagate(self):
        events = []
        def cancelled():
            raise RuntimeError('cancelled')
        delivery = EvidenceStream(events.append, lambda text: text, cancelled)
        stream = AttributionStream(delivery.feed)
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            stream.feed('First.\n\nSecond.')
        self.assertEqual(events, [])

    def test_sink_cancellation_is_not_swallowed(self):
        def cancelled(_):
            raise RuntimeError('cancelled')
        stream = AttributionStream(cancelled)
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            stream.feed('Answer.')


if __name__ == '__main__':
    unittest.main()
