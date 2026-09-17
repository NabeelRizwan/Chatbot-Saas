"""M allocation tests: same frozen evidence, exact witnesses, no serving imports."""
import ast
from hashlib import sha256
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from pydantic import ValidationError
from scripts.structural_retrieval_heading_gold import cases, base, evidence, assert_reachability, GOLD, ROOT
from scripts.structural_retrieval_entry_gold import cases as old_cases, evidence as old_evidence
from scripts.evaluate_structural_retrieval_entries import namespace_evidence
from services import structural_retrieval_entries as v1
from services import structural_retrieval_entries_v2 as v2
from services.structural_chunking import digest, serialize_structural_document
from scripts.evaluate_structural_text_adapter import parse_source


def fixture(name):
    return next(s for s in cases() if s['name'] == name)


class GoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = {}
        for s in cases():
            b = base(s)
            cls.results[s['name']] = (b, v2.revise_heading_allocation(b, scope=b.scope))

    def check(self, s):
        before, result = self.results[s['name']]
        self.assertEqual(result.evidence, before.evidence)
        self.assertEqual(result.atoms, before.atoms)
        self.assertEqual(result.coverage.unaccounted_bytes, 0)
        result.verify(scope=result.scope)
        assert_reachability(result)
        self.assertTrue(all(e.token_count <= 800 and e.context_token_count <= 80
                            and e.logical_child_count <= 32 and e.mapping_count <= 256 for e in result.entries))
        if s['expect'] in ('STANDALONE', 'CONTEXTUAL_ONLY'):
            self.assertTrue(result.heading_allocations)
            self.assertEqual({r.disposition for r in result.heading_allocations}, {s['expect']})
        elif s['expect'] == 'TYPED_BODY':
            self.assertFalse(result.heading_allocations)
            self.assertIn('faq', {a.kind for a in result.atoms})
            self.assertTrue(any(s['heading'] in e.text and s['body'] in e.text for e in result.entries))
        else:
            self.assertFalse(result.heading_allocations)
            empty = {n.identity for n in result.evidence.source_graph.nodes if n.node_type.value == 'heading'}
            self.assertTrue(empty)
            self.assertTrue(all(r.disposition == 'GRAPH_ONLY' for r in result.coverage.nodes if r.node in empty))
        # All non-heading body packing is byte/membership-identical; only identity
        # recipes and ordinals change. No non-price/non-heading text disappears.
        def bodies(r):
            kinds = {a.atom_key: a.kind for a in r.atoms}
            return [(e.text, e.mappings, e.memberships, e.boundary_key) for e in r.entries
                    if any(m.usage == 'body' and kinds[m.atom_key] != 'heading' for m in e.memberships)]
        self.assertEqual(bodies(before), bodies(result))


for spec in cases():
    def check(self, s=spec): self.check(s)
    setattr(GoldTests, 'test_gold_' + spec['name'], check)
    def repeat(self, s=spec):
        before, first = self.results[s['name']]
        self.assertEqual(first.canonical_hash(), v2.revise_heading_allocation(before, scope=before.scope).canonical_hash())
    setattr(GoldTests, 'test_repeat_' + spec['name'], repeat)


class BaselineTests(unittest.TestCase):
    pass


for spec in old_cases('structural_retrieval_entry_gold_v1'):
    def check(self, s=spec):
        expected = json.loads((GOLD / 'v1_baseline_hashes.json').read_text())[s['name']]
        b = old_evidence(s)
        result = v1.build_retrieval_entries(b, scope=v1.RetrievalEntryScope(revision=b.source_graph.revision.identity))
        self.assertEqual(result.canonical_hash(), expected['batch_hash'])
        self.assertEqual(result.recipe_hash, expected['recipe_hash'])
        self.assertEqual(len(result.entries), expected['entries'])
        self.assertEqual(sum(e.token_count for e in result.entries), expected['tokens'])
        revised = v2.revise_heading_allocation(result, scope=result.scope)
        self.assertEqual(revised.evidence, result.evidence)
        self.assertEqual(revised.atoms, result.atoms)
        assert_reachability(revised)
    setattr(BaselineTests, 'test_v1_exact_baseline_' + spec['name'], check)


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.old = base(fixture('section_1'))
        self.r = v2.revise_heading_allocation(self.old, scope=self.old.scope)

    def test_explicit_version(self): self.assertEqual(self.r.policy.version, 'structural-retrieval-entry-v2')
    def test_new_recipe(self): self.assertNotEqual(self.old.recipe_hash, self.r.recipe_hash)
    def test_new_keys(self): self.assertTrue(set(e.entry_key for e in self.old.entries).isdisjoint(e.entry_key for e in self.r.entries))
    def test_budgets_unchanged(self): self.assertEqual(v2._old_policy(self.r.policy), self.old.policy)
    def test_wrong_version_rejected(self):
        with self.assertRaises(ValidationError): v2.RetrievalEntryPolicy(version='structural-retrieval-entry-v1')
    def test_frozen(self):
        with self.assertRaises(ValidationError): self.r.heading_allocations = ()
    def test_scope_required(self):
        with self.assertRaises(TypeError): v2.build_retrieval_entries(self.old.evidence)
    def test_body_selection_stays_lexical(self):
        old = base(fixture('lexical_descendant')); new = v2.revise_heading_allocation(old, scope=old.scope)
        keys = {a.atom_key for a in new.atoms if a.kind != 'heading'}
        self.assertTrue(keys)
        self.assertTrue(all(a.disposition == 'LEXICAL_ONLY' for a in new.coverage.atoms if a.atom_key in keys))
    def test_wrong_witness_key(self):
        row = self.r.heading_allocations[0].model_copy(update={'witness_entry': '0'*64})
        with self.assertRaises(v1.EntryError): self.r.model_copy(update={'heading_allocations': (row,)}).verify(scope=self.r.scope)
    def test_partial_not_witness(self):
        old = base(fixture('partial_context'))
        self.assertEqual(v2.complete_heading_witnesses(old, scope=old.scope), {})
    def test_two_partial_entries_cannot_form_one_witness(self):
        entry = self.r.entries[0]
        heading = next(m for m in entry.mappings if m.origin_usage == 'inherited' and m.usage == 'heading')
        middle = (heading.node_slice.start + heading.node_slice.end)//2
        entries = []
        for start,end in ((heading.node_slice.start,middle),(middle,heading.node_slice.end)):
            span = heading.model_copy(update={'node_slice':heading.node_slice.model_copy(update={'start':start,'end':end}),
                'entry_slice':heading.entry_slice.model_copy(update={
                    'start':heading.entry_slice.start+start-heading.node_slice.start,
                    'end':heading.entry_slice.start+end-heading.node_slice.start})})
            entries.append(entry.model_copy(update={'mappings':tuple(span if m==heading else m for m in entry.mappings)}))
        forged = self.r.model_copy(update={'entries':tuple(entries)})
        self.assertEqual(v2.complete_heading_witnesses(forged,scope=self.r.scope),{})
        with self.assertRaises(v1.EntryError): forged.verify(scope=self.r.scope)
    def test_foreign_context_entry_refused(self):
        scope=self.r.scope.model_copy(update={'crawl_id':1,'crawl_version':2})
        entry=self.r.entries[0].model_copy(update={'scope':scope})
        forged=self.r.model_copy(update={'entries':(entry,)})
        with self.assertRaises(v1.EntryError):v2.complete_heading_witnesses(forged,scope=self.r.scope)
    def test_three_tenants_same_heading_and_url(self):
        b=serialize_structural_document(parse_source('# Shared 7\n\nVisit https://example.org/shared for details.'))
        results=[]
        for org,bot in ((701,1),(701,2),(702,1)):
            selected=namespace_evidence(b,organization_id=org,bot_id=bot)
            results.append(v2.build_retrieval_entries(selected,scope=v1.RetrievalEntryScope(revision=selected.source_graph.revision.identity)))
        self.assertEqual(len({r.entries[0].text for r in results}),1)
        self.assertEqual(len({r.heading_allocations[0].atom_key for r in results}),3)
        self.assertEqual(len({r.heading_allocations[0].witness_entry for r in results}),3)
        for a in results:
            for b in results:
                if a is not b:
                    with self.assertRaises(v1.EntryError):a.make_index().atoms_for_entry(a.entries[0].entry_key,scope=b.scope)
    def test_lexical_does_not_witness(self):
        old = base(fixture('lexical_descendant'))
        self.assertEqual(v2.complete_heading_witnesses(old, scope=old.scope), {})
    def test_budget_omission_does_not_witness(self):
        old = base(fixture('budget_omitted'))
        self.assertEqual(v2.complete_heading_witnesses(old, scope=old.scope), {})
    def test_prior_suppression_restored_at_barrier(self):
        old = base(fixture('barrier'))
        self.assertFalse(any(e.kind == 'heading' for e in old.entries))
        new = v2.revise_heading_allocation(old, scope=old.scope)
        self.assertTrue(any(e.kind == 'heading' for e in new.entries))
    def test_no_unrepresented_standalone_disappears(self):
        old = base(fixture('numbered_orphan')); new = v2.revise_heading_allocation(old, scope=old.scope)
        forged = new.model_copy(update={'entries': ()})
        with self.assertRaises(v1.EntryError): forged.verify(scope=new.scope)
    def test_context_map_cannot_move_to_another_heading(self):
        e = self.r.entries[0]
        m = e.mappings[0].model_copy(update={'atom_key': '0'*64})
        forged = e.model_copy(update={'mappings': (m, *e.mappings[1:])})
        with self.assertRaises(v1.EntryError): self.r.model_copy(update={'entries': (forged,)}).verify(scope=self.r.scope)
    def test_no_text_dedup(self):
        old = base(fixture('duplicate_sections')); new = v2.revise_heading_allocation(old, scope=old.scope)
        self.assertEqual(len(new.heading_allocations), 2)
        self.assertEqual(len({a.atom_key for a in new.heading_allocations}), 2)
        self.assertEqual(len({a.witness_entry for a in new.heading_allocations}), 2)
    def test_link_annotation_not_mistaken_for_heading_path_node(self):
        old=base({'heading':'[Clause 7](https://example.org/terms)','body':'The ordinary condition is exact.'})
        new=v2.revise_heading_allocation(old,scope=old.scope)
        self.assertEqual([x.disposition for x in new.heading_allocations],['CONTEXTUAL_ONLY'])
        self.assertEqual(assert_reachability(new),1)
        self.assertTrue(any(n.attributes.link for n in new.evidence.source_graph.nodes))
    def test_multiple_descendant_reverse_lookup(self):
        old = base(fixture('multiple_descendants')); new = v2.revise_heading_allocation(old, scope=old.scope)
        first = new.heading_allocations[0]
        self.assertGreater(len(new.make_index().entries_for_atom(first.atom_key, scope=new.scope)), 1)
        assert_reachability(new)
    def test_lexical_only_heading_term_retained(self):
        old = base(fixture('heading_witness')); new = v2.revise_heading_allocation(old, scope=old.scope)
        atom = next(a for a in new.atoms if a.kind == 'heading')
        parts = [c for c in new.evidence.chunks if c.chunk_key in atom.source_parts]
        self.assertTrue(any('Zephyrite-only' in c.text for c in parts))
        self.assertEqual(next(a for a in new.coverage.atoms if a.atom_key == atom.atom_key).disposition, 'DENSE_AND_LEXICAL')
        self.assertFalse(any(m.usage == 'body' and m.atom_key == atom.atom_key for e in new.entries for m in e.memberships))
    def test_unicode_full_bytes(self):
        old = base(fixture('unicode')); new = v2.revise_heading_allocation(old, scope=old.scope)
        self.assertEqual(assert_reachability(new), 1)
    def test_policy_change_creates_new_identity(self):
        p = v2.RetrievalEntryPolicy(target=501)
        new = v2.build_retrieval_entries(self.old.evidence, scope=self.old.scope, policy=p)
        self.assertNotEqual(new.recipe_hash, self.r.recipe_hash)
    def test_revision_refuses_other_packing_rules(self):
        with self.assertRaises(v1.EntryError): v2.revise_heading_allocation(self.old, scope=self.old.scope, policy=v2.RetrievalEntryPolicy(target=501))
    def test_no_network(self):
        def deny(*a, **kw): raise AssertionError('network forbidden')
        with patch.object(socket.socket, 'connect', deny), patch.object(socket, 'getaddrinfo', deny):
            v2.build_retrieval_entries(self.old.evidence, scope=self.old.scope)
    def test_import_isolation(self):
        t = ast.parse((ROOT/'backend/services/structural_retrieval_entries_v2.py').read_text())
        allowed = {'collections','functools','hashlib','pathlib','typing','services','services.structural_document','services.structural_chunking'}
        for n in ast.walk(t):
            if isinstance(n, ast.ImportFrom): self.assertIn(n.module, allowed)
            if isinstance(n, ast.Import): self.assertTrue(all(a.name in allowed for a in n.names))
    def test_no_text_shape_allocation_rule(self):
        t = (ROOT/'backend/services/structural_retrieval_entries_v2.py').read_text()
        self.assertNotIn('import re', t)
        for term in ('WOWMD', 'REAL_CORPUS', 'Section 0', '1638', '1120', 'Turmeric', 'collagen'):
            self.assertNotIn(term, t)
    def test_all_previous_hashes(self):
        path = ROOT/'.codex_structural_4_1m/preservation_before.json'
        if not path.exists(): self.skipTest('local inventory not in checkout')
        saved = json.loads(path.read_text())
        self.assertEqual(len(saved), 740)
        for f,h in saved.items(): self.assertEqual(sha256((ROOT/f).read_bytes()).hexdigest(), h, f)
    def test_new_gold_frozen(self):
        self.assertEqual(sha256((GOLD/'cases.json').read_bytes().replace(b'\r\n',b'\n')).hexdigest(),
                         'de23126b411568c142c837fdb8b2f4e71e13821ac0995c96ec9cdde1036ac0f6')
    def test_v1_source_frozen(self):
        self.assertEqual(v1._implementation_hash(), '0b32a7b29e930e72923ad43b7fbae167390a164d96e4b80a9f27fd1fe28aeaa8')
    def test_oss_ledger(self):
        text = (ROOT/'docs/PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md').read_text(encoding='utf-8').split('## Phase 4.1M')[1]
        for term in ('Docling','LlamaIndex','Haystack','RAGFlow','Onyx','coverage','orphan','Literal code reused: NO'):
            self.assertIn(term, text)


def scope_case(field, value):
    def check(self):
        changed = namespace_evidence(self.old.evidence, **{field: value})
        scope = v1.RetrievalEntryScope(revision=changed.source_graph.revision.identity)
        new = v2.build_retrieval_entries(changed, scope=scope)
        self.assertNotEqual(new.batch_key, self.r.batch_key)
        self.assertTrue(set(e.entry_key for e in self.r.entries).isdisjoint(e.entry_key for e in new.entries))
        with self.assertRaises(v1.EntryError): v2.complete_heading_witnesses(self.r, scope=scope)
        with self.assertRaises(v1.EntryError): self.r.verify(scope=scope)
        with self.assertRaises(v1.EntryError): self.r.make_index().entries_for_atom(self.r.atoms[0].atom_key, scope=scope)
        with self.assertRaises(v1.EntryError): v2.build_retrieval_entries(changed, scope=self.r.scope)
    return check
for field, value in [('organization_id',80001),('bot_id',80002),('document_id',80003),('source_version',2),('revision_name','revision-B')]:
    setattr(SafetyTests, 'test_foreign_' + field, scope_case(field,value))


def scale_case(size):
    def check(self):
        hashes = set(); entries = 0
        for i in range(size):
            b = namespace_evidence(self.old.evidence, organization_id=90000+i, bot_id=100000+i)
            r = v2.build_retrieval_entries(b, scope=v1.RetrievalEntryScope(revision=b.source_graph.revision.identity))
            self.assertNotIn(r.batch_key, hashes); hashes.add(r.batch_key)
            entries += len(r.entries); self.assertEqual(assert_reachability(r), 1)
        self.assertEqual(entries, len(self.r.entries)*size)
    return check
for scale in (1,10,100): setattr(SafetyTests, 'test_independent_scopes_' + str(scale), scale_case(scale))


def document_case(size, label):
    def check(self):
        text = '# Guide\n\n' + '\n\n'.join(f'## {label} {i}\n\nAn ordinary passage remains exact.\n\n- First item\n- Second item' for i in range(size))
        b = serialize_structural_document(parse_source(text))
        r = v2.build_retrieval_entries(b, scope=v1.RetrievalEntryScope(revision=b.source_graph.revision.identity))
        self.assertFalse(any(e.kind == 'heading' for e in r.entries))
        self.assertEqual(assert_reachability(r), size+1)
        self.assertEqual(r.coverage.unaccounted_bytes, 0)
        self.assertEqual(len(r.atoms), size*3+1)
        self.assertEqual(len(r.entries), size)
    return check
for size in (10,100,500,1000): setattr(SafetyTests, 'test_document_scale_' + str(size), document_case(size,'Section'))
for label in ('Clause','Chapter','Article','Module','Step','Version'):
    setattr(SafetyTests, 'test_ordinal_variant_' + label, document_case(10,label))


if __name__ == '__main__': unittest.main()
