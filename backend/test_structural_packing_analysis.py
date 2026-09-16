"""Offline design-helper tests only; no persistent DB or model providers."""
import ast
from dataclasses import replace
import inspect
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from scripts import analyze_structural_packing as analysis
from services.structural_shadow import ShadowSource, build_shadow


def unit(ordinal=0, **changes):
    return replace(analysis.EvidenceUnit(ordinal,'source-v1/rev1','prose',('parent',),('section',),
        ('explicit-subject',),('unknown',),('accept',),False,True,40),**changes)


class Eligibility(unittest.TestCase):
    def rejected(self, reason, **changes):
        self.assertEqual(analysis.merge_reason(unit(),replace(unit(1),**changes)),reason)
    def test_compatible_explicit_peers(self):self.assertIsNone(analysis.merge_reason(unit(),unit(1)))
    def test_cross_document_version(self):self.rejected('source_or_revision',scope='different')
    def test_nonadjacent(self):self.rejected('not_adjacent',ordinal=3)
    def test_review_boundary(self):self.rejected('atomic_kind',kind='review')
    def test_faq_boundary(self):self.rejected('atomic_kind',kind='faq')
    def test_timeline_boundary(self):self.rejected('atomic_kind',kind='timeline_stage')
    def test_commercial_roles(self):self.rejected('atomic_kind',kind='price_block')
    def test_list_boundary(self):self.rejected('atomic_kind',kind='list')
    def test_table_boundary(self):self.rejected('atomic_kind',kind='table')
    def test_directions_boundary(self):self.rejected('atomic_kind',kind='directions')
    def test_incomplete_unit(self):self.rejected('multipart',complete=False)
    def test_parent_boundary(self):self.rejected('parent',parent=('different',))
    def test_section_boundary(self):self.rejected('section',section=('different',))
    def test_unknown_subject_not_equal_identity(self):self.rejected('no_explicit_subject',subjects=())
    def test_subject_boundary(self):self.rejected('subject',subjects=('different',))
    def test_role_boundary(self):self.rejected('role',roles=('warning',))
    def test_quality_boundary(self):self.rejected('quality',quality=('quarantine',))
    def test_relationship_qualifier_boundary(self):self.rejected('relationship_or_qualification',barrier=True)
    def test_budget(self):self.rejected('budget',tokens=620)
    def test_same_warning_also_forbidden(self):
        self.assertEqual(analysis.merge_reason(unit(roles=('warning',)),unit(1,roles=('warning',))),'role')


class Simulation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.batch,_=build_shadow(ShadowSource(70001,70002,99,1,
            b'# Manual\n\n## Description\n\nA plain introductory paragraph.\n\n## Details\n\nAnother useful paragraph.\n\n## Empty section',
            'markdown','extracted_markdown'))
    def test_actual_batch_path(self):
        r=analysis.analyze_batch(self.batch)
        self.assertEqual(r['v1']['chunks'],len(self.batch.chunks))
    def test_kind_counts(self):
        r=analysis.analyze_batch(self.batch);self.assertEqual(sum(r['v1']['kinds'].values()),len(self.batch.chunks))
    def test_tiny_count(self):
        r=analysis.analyze_batch(self.batch);self.assertEqual(r['v1']['tiny'],sum(c.token_count<50 for c in self.batch.chunks))
    def test_heading_count(self):
        r=analysis.analyze_batch(self.batch);self.assertEqual(r['v1']['heading'],sum(c.kind=='heading' for c in self.batch.chunks))
    def test_stricter_than_adjacency(self):
        r=analysis.analyze_batch(self.batch);self.assertLess(r['merge_eligible_pairs'],r['v1']['theoretical_pairs'])
    def test_exact_mapping_coverage(self):
        r=analysis.analyze_batch(self.batch);self.assertTrue(r['simulated']['mapping_coverage_equal'])
        self.assertEqual(r['simulated']['unaccounted_new_bytes'],0)
    def test_all_original_specs_retained_logically(self):
        r=analysis.analyze_batch(self.batch)
        self.assertEqual(sorted([i for g in r['groups'] for i in g]+r['metadata_only_spec_ordinals']),list(range(len(self.batch.chunks))))
    def test_empty_heading_not_deleted(self):
        r=analysis.analyze_batch(self.batch)
        empty=next(c.ordinal for c in self.batch.chunks if c.kind=='heading' and 'Empty section' in c.text)
        self.assertNotIn(empty,r['metadata_only_spec_ordinals'])
    def test_deterministic(self):self.assertEqual(analysis.analyze_batch(self.batch),analysis.analyze_batch(self.batch))
    def test_no_batch_mutation(self):
        before=self.batch.canonical_json();analysis.analyze_batch(self.batch);self.assertEqual(before,self.batch.canonical_json())
    def test_network_denied(self):
        with patch.object(socket.socket,'connect',side_effect=AssertionError('network')),patch.object(socket,'getaddrinfo',side_effect=AssertionError('DNS')):
            self.assertTrue(analysis.analyze_batch(self.batch)['simulated']['mapping_coverage_equal'])
    def test_no_database_provider_or_runtime_imports(self):
        tree=ast.parse(inspect.getsource(analysis))
        modules=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        modules += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
        self.assertFalse(any(m.startswith(('database','sqlalchemy','requests','httpx','google','openai')) for m in modules))
    def test_no_runtime_consumers(self):
        root=Path(__file__).parent
        for folder in ('services','routes','workers'):
            for path in (root/folder).glob('*.py'):self.assertNotIn('analyze_structural_packing',path.read_text(encoding='utf-8-sig'))
    def test_v1_baseline_not_reset(self):
        self.assertEqual(analysis.BASELINE,{'documents':23,'chunks':3242,'tokens':278491,'tiny':1452,'heading':754,'theoretical_pairs':3156})
    def test_union_overlap(self):self.assertEqual(analysis.merge_intervals([(3,6),(0,4),(9,11)]),((0,6),(9,11)))
    def test_shadow_still_not_active(self):
        from services.structural_shadow_config import ShadowConfig
        with self.assertRaises(ValueError):ShadowConfig(mode='active')


if __name__=='__main__':unittest.main()
