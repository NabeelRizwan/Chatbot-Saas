"""Generic RED reproductions from the held-out acceptance, no live I/O."""
import unittest

from services.semantic_scope import comparison_mentions
from services.query_contract import extract_requested_fields
from test_resource_discovery import ResourceFixture


class ComparisonClauseTests(unittest.TestCase):
    def test_with_and_later_field_comparison(self):
        names = ['Cedar Service', 'Birch Service']
        q = ('Please compare Cedar Service with Birch Service for a daily routine: '
             'how should I use each, what happens in months one and two versus months three and four, '
             'and does the guarantee cover a subscription? Link both and keep the timeline qualified.')
        self.assertEqual(comparison_mentions(q, names), ('cedar service', 'birch service'))

    def test_and_members_end_before_requested_fields(self):
        self.assertEqual(comparison_mentions('Compare Cedar Service and Birch Service on price and duration, then link both.',
                                            ['Cedar Service','Birch Service']), ('cedar service','birch service'))

    def test_unknown_member_must_survive(self):
        self.assertEqual(comparison_mentions('Compare Cedar Service with Unknown Meridian for my routine: how do I use each?',
                                            ['Cedar Service']), ('cedar service','unknown meridian'))

    def test_internal_conjunction_and_preposition_preserved(self):
        names = ['Cedar Research and Design', 'Birch Center for Learning']
        self.assertEqual(comparison_mentions('Compare Cedar Research and Design with Birch Center for Learning on price and duration.', names),
                         ('cedar research and design','birch center for learning'))

    def test_dotted_version_not_sentence_boundary(self):
        self.assertEqual(comparison_mentions('Compare Cedar v3.1 with Birch v3.2: what are their limits?',
                                            ['Cedar v3.1','Birch v3.2']), ('cedar v3.1','birch v3.2'))

    def test_plain_with_is_not_a_comparison(self):
        self.assertEqual(comparison_mentions('Use Cedar Service with water after meals.', ['Cedar Service']), ())

    def test_link_request_is_additive(self):
        fields = extract_requested_fields('Compare price and directions. Link both and the relevant guarantee terms.')
        self.assertTrue({'price','directions','link','guarantee','policy'} <= set(fields))

    def test_connecting_objects_not_navigation(self):
        self.assertNotIn('link', extract_requested_fields('How do I link both devices together?'))


class ComparisonRuntimeTests(ResourceFixture):
    def test_actual_prepare_probe_discovery_scope_handoff(self):
        self.add(1, 'Cedar Service'); self.add(2, 'Birch Service'); self.project(1,2)
        q = ('Please compare Cedar Service with Birch Service for a daily routine: '
             'how should I use each, what happens in months one and two versus months three and four, '
             'and does the guarantee cover a subscription? Link both and keep the results timelines qualified.')
        c = self.contract(q)
        self.assertEqual(set(c.permitted_document_ids or ()), {1,2})
        self.assertEqual(set(c.execution.soft_scope.resolved_document_ids), {1,2})
        self.assertFalse(c.execution.soft_scope.unresolved_mentions)
        self.assertEqual(len(c.execution.resource_discovery['resolutions']), 2)
        self.assertIn('link', c.requested_fields)

    def test_unknown_member_cannot_be_narrowed_away(self):
        self.add(1, 'Cedar Service'); self.project(1)
        c = self.contract('Compare Cedar Service with Unknown Meridian for a daily routine: what are their limits?')
        self.assertIsNone(c.permitted_document_ids)
        self.assertIn('unknown meridian', c.execution.soft_scope.unresolved_mentions)


class AdmittedReferenceTests(unittest.TestCase):
    def assemble(self, body, fields=('policy', 'link'), budget=4000):
        from services import rag_service as rag
        from services.observability_service import ChatTrace
        from test_phase35_live_repair import contract, item
        c = contract(fields)
        rows = [item(d, d * 100, body, ['policy']) for d in (1, 2)]
        for row in rows:
            row['document'].canonical_url = f"https://fixture.test/items/{row['document'].id}"
        retained, context, _, _ = rag._bounded_generation_context(
            rows, c.original_query, budget, 'comparison', c, ChatTrace(1, 'reference'))
        self.assertLessEqual(len(context), budget)
        return retained, context

    def test_requested_inline_terms_survive_context_sources_and_validation(self):
        from services import rag_service as rag
        url = 'https://fixture.test/policies/terms'
        rows, context = self.assemble(f'Policy: cancellation is permitted before renewal. Read the [full terms]({url}).')
        self.assertIn(url, context)
        sources = rag._format_sources(rows)
        self.assertEqual(len(sources), 2)
        self.assertTrue(all(url in [link['url'] for link in s['cta_links']] for s in sources))
        self.assertIn(url, rag._validate_answer_links(f'[Terms]({url})', rows))

    def test_link_not_requested_keeps_existing_condensation(self):
        rows, context = self.assemble('Policy: cancellation is permitted. Read [terms](https://fixture.test/terms).', ('policy',))
        self.assertNotIn('https://fixture.test/terms', context)

    def test_unsafe_or_foreign_reference_never_admitted(self):
        from services import rag_service as rag
        for url in ('https://foreign.test/terms', 'https://fixture.test.evil/terms',
                    'https://name:secret@fixture.test/terms', 'https://fixture.test/terms?token=private',
                    'javascript:alert', 'http://fixture.test/terms'):
            with self.subTest(url=url):
                rows, context = self.assemble(f'Policy: cancellation is permitted. Read [terms]({url}).')
                self.assertNotIn(url, context)
                self.assertFalse(any(s['cta_links'] for s in rag._format_sources(rows)))

    def test_navigation_and_unrelated_paragraph_are_not_reference_sources(self):
        from services import rag_service as rag
        rows, context = self.assemble('Policy: cancellation is permitted before renewal.\n\n'
            '[Other policy](https://fixture.test/other-policy)\n\n'
            'Explore [another item](https://fixture.test/policy/other-item).')
        self.assertNotIn('/other-policy', context)
        self.assertNotIn('/other-item', context)
        self.assertFalse(any(s['cta_links'] for s in rag._format_sources(rows)))

    def test_raw_chunk_or_metadata_cannot_forge_admission(self):
        from services import rag_service as rag
        from test_phase35_live_repair import item
        url = 'https://fixture.test/terms'
        row = item(1, 1, f'Policy: read [terms]({url}).', ['policy'])
        row['document'].canonical_url = 'https://fixture.test/items/1'
        row['chunk'].metadata_json = {'context_field_evidence': {'policy': [f'[terms]({url})']}}
        self.assertNotIn(url, str(rag._format_sources([row])))

    def test_omitted_required_paragraph_cannot_authorize_link(self):
        from services import rag_service as rag
        url = 'https://fixture.test/deep-terms'
        rows, context = self.assemble('Policy: cancel before renewal.\n\nPolicy: ' +
            'A lengthy separate condition. ' * 300 + f'Read [terms]({url}).', budget=1800)
        self.assertTrue(rows)
        self.assertNotIn(url, context)
        self.assertNotIn(url, str(rag._format_sources(rows)))


class PrimaryFieldAdmissionTests(unittest.TestCase):
    def test_primary_field_body_precedes_early_promotional_header(self):
        from services.conversational_engine import _required_field_parts
        from test_phase35_live_repair import item
        banner = item(1, 1, 'Limited guarantee on eligible purchases. ' * 16, ['guarantee'])
        primary = item(1, 50, '30 Day Guarantee\n\nThe guarantee covers the first individual purchase only. '
            'Subscription orders and repeated purchases are excluded. Requests must be made within 30 days of delivery.', ['guarantee'])
        primary['evidence_bundles'] = [{'field': 'guarantee', 'primary_chunk_id': 50, 'chunk_ids': [50], 'quality': 'field_value'}]
        parts = _required_field_parts([banner, primary], 'guarantee', {})
        self.assertIn('Subscription orders and repeated purchases are excluded.', parts[0])

    def test_both_entities_keep_primary_conditions_before_optional_depth(self):
        from services import rag_service as rag
        from services.observability_service import ChatTrace
        from services.requested_propositions import bind_field_obligations
        from test_phase35_live_repair import contract, item
        c = contract(('directions', 'guarantee', 'link'))
        bind_field_obligations(c)
        rows = []
        for d in (1, 2):
            banner = item(d, d * 100, 'Limited guarantee on eligible purchases. ' * 16, ['guarantee'])
            body = item(d, d * 100 + 50, '30 Day Guarantee\n\nThe guarantee covers the first individual purchase only. '
                f'Subscription orders for Resource {d} are excluded. Requests must be made within 30 days of delivery.', ['guarantee'])
            body['evidence_bundles'] = [{'field': 'guarantee', 'primary_chunk_id': d * 100 + 50,
                'chunk_ids': [d * 100 + 50], 'quality': 'field_value'}]
            rows += [banner, body, item(d, d * 100 + 1, 'Directions: install one unit daily with protective gloves.', ['directions'])]
        retained, context, _, _ = rag._bounded_generation_context(rows, c.original_query, 2300,
            'comparison', c, ChatTrace(1, 'primary-field'))
        self.assertLessEqual(len(context), 2300)
        self.assertEqual({r['document'].id for r in retained}, {1, 2})
        for d in (1, 2):
            self.assertIn(f'Subscription orders for Resource {d} are excluded.', context)


if __name__ == '__main__':
    unittest.main()
