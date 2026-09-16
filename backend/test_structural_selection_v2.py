"""Offline v2 contract, GOLD and source-association tests; no serving writes."""
import ast
from collections import Counter
import hashlib
import inspect
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from scripts import structural_chunk_gold_v2 as gold
from scripts.evaluate_structural_selection_v2 import analyze,cost
from services import structural_selection_v2 as v2
from services.structural_chunking import serialize_structural_document,count_tokens
from services.structural_document import StructuralDocument,StructuralEdge,SemanticRole,ValidationState

ROOT=Path(__file__).resolve().parent.parent
CASES={c['name']:c for c in gold.cases()}


def batch(name='peer_explicit'):
    return gold.build(CASES[name])


def edit_graph(b,transform):
    doc=b.source_graph.model_copy(update={'nodes':tuple(transform(n) for n in b.source_graph.nodes)})
    doc=StructuralDocument.model_validate_json(doc.canonical_json())
    return b.model_copy(update={'source_graph':doc}).verify()


class Gold(unittest.TestCase):
    def check_decision(self,case):
        b=gold.build(case);s=v2.select_structural_candidates(b)
        nodes={n.identity.node_key:n for n in b.source_graph.nodes}
        headings=[v2.heading_label(nodes[m.mapping.node.node_key].text) for c,d in zip(b.chunks,s.ledger)
            if d.outcome=='metadata_only' for m in c.mappings if m.usage=='primary']
        if 'metadata_headings' in case:self.assertEqual(headings,[x.casefold() for x in case['metadata_headings']])
        if 'expected_packed_groups' in case:self.assertEqual(sum(len(c.members)>1 for c in s.candidates),case['expected_packed_groups'])
        if 'expected_unresolved' in case:self.assertEqual(sum(d.outcome=='unresolved' for d in s.ledger),case['expected_unresolved'])
        s.verify()

    def check_proxy(self,case):
        b=gold.build(case);s=v2.select_structural_candidates(b)
        rows=gold.discoverability(case,b,s)
        self.assertTrue(rows)
        self.assertTrue(all(r['v1'] and r['v2'] for r in rows))


for name,case in CASES.items():
    setattr(Gold,'test_decision_'+name,lambda self,c=case:self.check_decision(c))
    setattr(Gold,'test_discoverability_'+name,lambda self,c=case:self.check_proxy(c))


class PeerBoundaries(unittest.TestCase):
    def setUp(self):
        self.b=batch();self.engine=v2._Selection(self.b,v2.SelectionPolicy())
        self.a,self.bspec=[c for c in self.b.chunks if c.kind=='prose']

    def check(self,reason,**changes):
        result=self.engine.peer(self.a,self.bspec.model_copy(update=changes))
        self.assertEqual(result.status,'ineligible');self.assertEqual(result.reason,reason)

    def test_explicit_subject(self):self.assertEqual(self.engine.peer(self.a,self.bspec).status,'eligible')
    def test_cross_revision(self):
        self.check('source_revision',revision=self.bspec.revision.model_copy(update={'structure_revision_id':'different-revision'}))
    def test_nonadjacent(self):self.check('spec_adjacency',ordinal=100)
    def test_part_count(self):self.check('multipart',part_count=2)
    def test_incomplete(self):self.check('multipart',complete_unit=False)
    def test_cross_section(self):self.check('section',heading_path=self.bspec.heading_path[:1])
    def test_empty_section(self):
        self.assertEqual(self.engine.peer(self.a.model_copy(update={'heading_path':()}),self.bspec.model_copy(update={'heading_path':()})).reason,'section')
    def test_cross_parent(self):
        b=batch('equal_text_distinct_source');e=v2._Selection(b,v2.SelectionPolicy());a,z=[c for c in b.chunks if c.kind=='prose']
        self.assertEqual(e.peer(a,z.model_copy(update={'ordinal':a.ordinal+1})).reason,'parent')
    def test_quality_mismatch(self):
        key=self.engine.roots[self.bspec.chunk_key][0]
        quality=self.b.source_graph.revision.quality.model_copy(update={'reason_codes':('different_quality_witness',)})
        b=edit_graph(self.b,lambda n:n.model_copy(update={'quality':quality}) if n.identity.node_key==key else n)
        e=v2._Selection(b,v2.SelectionPolicy());self.assertEqual(e.peer(self.a,self.bspec).reason,'quality')
    def test_warning_role(self):
        key=self.engine.roots[self.a.chunk_key][0]
        b=edit_graph(self.b,lambda n:n.model_copy(update={'semantic_role':SemanticRole.WARNING}) if n.identity.node_key==key else n)
        self.assertEqual(v2._Selection(b,v2.SelectionPolicy()).peer(self.a,self.bspec).reason,'role')
    def test_qualification(self):self.check('qualification',text=self.bspec.text+'\nResults vary.')
    def test_budget(self):self.check('token_or_mapping_budget',text=self.bspec.text+'\n'+('addition '*900))
    def test_semantic_edge(self):
        nodes=self.engine.nodes
        a=nodes[self.engine.roots[self.a.chunk_key][0]];b=nodes[self.engine.roots[self.bspec.chunk_key][0]]
        edge=StructuralEdge(from_node=a.identity,to_node=b.identity,relation='REFERS_TO',provenance=a.provenance,validation_state='validated')
        doc=self.b.source_graph.model_copy(update={'edges':self.b.source_graph.edges+(edge,)})
        e=v2._Selection(self.b.model_copy(update={'source_graph':doc}),v2.SelectionPolicy())
        self.assertEqual(e.peer(self.a,self.bspec).reason,'semantic_edge')
    def test_unvalidated_subject_not_authority(self):
        doc=self.b.source_graph.model_copy(update={'edges':tuple(e.model_copy(update={'validation_state':ValidationState.UNVALIDATED}) if e.relation.value=='DESCRIBES' else e for e in self.b.source_graph.edges)})
        doc=StructuralDocument.model_validate_json(doc.canonical_json())
        e=v2._Selection(self.b.model_copy(update={'source_graph':doc}),v2.SelectionPolicy())
        self.assertEqual(e.peer(self.a,self.bspec).status,'unknown_identity')
    def test_conflicting_subjects(self):
        first=next(e for e in self.b.source_graph.edges if e.relation.value=='DESCRIBES')
        other=next(n.identity for n in self.b.source_graph.nodes if n.node_type.value=='heading' and n.identity!=first.to_node)
        edge=first.model_copy(update={'to_node':other})
        doc=self.b.source_graph.model_copy(update={'edges':self.b.source_graph.edges+(edge,)})
        e=v2._Selection(self.b.model_copy(update={'source_graph':doc}),v2.SelectionPolicy())
        self.assertEqual(e.peer(self.a,self.bspec).reason,'subject')
    def test_intervening_source_sibling(self):
        b=gold.build({'shape':'units','subject':True,'text':'# Manual\n\n## Details\n\nFirst room.\n\nMiddle room.\n\nLast room.'})
        e=v2._Selection(b,v2.SelectionPolicy());a,_,z=[c for c in b.chunks if c.kind=='prose']
        self.assertEqual(e.peer(a,z.model_copy(update={'ordinal':a.ordinal+1})).reason,'source_sibling_adjacency')


for kind in ('review','faq','timeline_stage','price_block','list','table','directions','heading'):
    setattr(PeerBoundaries,'test_atomic_'+kind,lambda self,k=kind:self.check('atomic_kind',kind=k))


class Preservation(unittest.TestCase):
    def setUp(self):self.b=batch();self.s=v2.select_structural_candidates(self.b)
    def test_frozen_v1_file(self):
        data=(ROOT/'backend/services/structural_chunking.py').read_text(encoding='utf-8').replace('\r\n','\n').encode()
        self.assertEqual(hashlib.sha256(data).hexdigest(),'faaa9088ba523cbdc51f35fee79698ed71f407bba7ee343fb00e1ab2d18cddd4')
    def test_version_distinct(self):
        self.assertEqual(self.s.policy.version,'structure-chunk-v2');self.assertNotEqual(self.s.recipe_hash,self.b.recipe_hash)
    def test_no_new_token_caps(self):
        self.assertEqual((self.s.policy.target,self.s.policy.merge_min,self.s.policy.merge_max,self.s.policy.hard_max,self.s.policy.prefix_max,self.s.policy.overlap_max),(450,250,650,800,80,60))
    def test_no_input_mutation(self):
        before=self.b.canonical_json();v2.select_structural_candidates(self.b);self.assertEqual(before,self.b.canonical_json())
    def test_deterministic_json(self):self.assertEqual(self.s.canonical_json(),v2.select_structural_candidates(self.b).canonical_json())
    def test_deterministic_keys(self):self.assertEqual([c.candidate_id for c in self.s.candidates],[c.candidate_id for c in v2.select_structural_candidates(self.b).candidates])
    def test_ledger_total(self):self.assertEqual([d.v1_spec_id for d in self.s.ledger],[c.chunk_key for c in self.b.chunks])
    def test_graph_identity(self):self.assertEqual(self.s.graph_hash,self.b.source_graph.canonical_hash())
    def test_graph_only_not_deleted(self):
        keys={n.identity.node_key for n in self.b.source_graph.nodes}
        self.assertTrue(self.s.graph_only_nodes);self.assertTrue(set(self.s.graph_only_nodes)<=keys)
    def test_exact_prefix_sharing(self):
        packed=next(c for c in self.s.candidates if len(c.members)>1)
        self.assertEqual(packed.deduplicated_prefixes,1);self.assertEqual(packed.text.count('## Details'),1)
        self.assertEqual(len(packed.translations),sum(len(c.mappings) for c in self.b.chunks if c.chunk_key in packed.members))
    def test_distinct_sources_not_shared(self):
        b=batch('equal_text_distinct_source');s=v2.select_structural_candidates(b)
        self.assertEqual(sum(c.deduplicated_prefixes for c in s.candidates),0)
        ids={n.identity.node_key for n in b.source_graph.nodes if n.text=='## Details'};self.assertEqual(len(ids),2)
        mapped={b.chunks[next(i for i,x in enumerate(b.chunks) if x.chunk_key==t.v1_spec_id)].mappings[t.mapping_index].mapping.node.node_key for c in s.candidates for t in c.translations}
        self.assertTrue(ids<=mapped)
    def test_qualifier_prefix_not_shared(self):
        e=v2._Selection(self.b,v2.SelectionPolicy());a,z=[c for c in self.b.chunks if c.kind=='prose']
        def qualifier(c):
            return c.model_copy(update={'mappings':tuple(s.model_copy(update={'mapping':s.mapping.model_copy(update={'role':'qualifier'})}) if s.usage=='inherited' else s for s in c.mappings)})
        self.assertEqual(e.pack((qualifier(a),qualifier(z))).deduplicated_prefixes,0)
    def test_unknown_remains_candidate(self):
        s=v2.select_structural_candidates(batch('peer_unknown'))
        ds=[d for d in s.ledger if d.outcome=='unresolved'];self.assertEqual(len(ds),2)
        self.assertTrue(all(d.candidate_id for d in ds))
    def test_heading_witness_exact(self):
        self.assertTrue(any(d.witnesses for d in self.s.ledger));self.s.verify()
    def test_heading_context_one_descendant(self):
        s=v2.select_structural_candidates(batch('duplicate'))
        for d in s.ledger:
            if d.outcome=='metadata_only':self.assertEqual(len({w.retained_spec_id for w in d.witnesses}),1)
    def test_zero_bytes_dropped(self):self.assertEqual(analyze(self.b)['evidence_bytes_dropped'],0)
    def test_tiny_all_classified(self):
        r=analyze(self.b);self.assertEqual(sum(r['tiny_reasons'].values()),r['v1_tiny'])
        self.assertTrue({'embedded','metadata_only','packed'}<=set(r['outcomes']))
    def test_list_completeness(self):
        b=batch('list');s=v2.select_structural_candidates(b)
        self.assertEqual([(c.list_item_indices,c.source_block_complete,c.part_count) for c in b.chunks if c.kind=='list'],[(c.list_item_indices,c.source_block_complete,c.part_count) for c in s.v1.chunks if c.kind=='list'])
        self.assertTrue(any(c.kind=='list' for c in s.candidates));s.verify()
    def test_table_header_association(self):
        b=batch('table');s=v2.select_structural_candidates(b)
        self.assertTrue(any(n.attributes.cell and n.attributes.cell.is_header for n in b.source_graph.nodes));self.assertEqual(s.v1.source_graph,b.source_graph)
    def test_review_attribution_edges(self):
        b=batch('review');s=v2.select_structural_candidates(b)
        self.assertTrue(any(n.semantic_role.value=='review' for n in b.source_graph.nodes));self.assertEqual(s.v1.source_graph.edges,b.source_graph.edges)
        self.assertTrue(all(len(c.members)==1 for c in s.candidates))
    def test_different_review_resources_stay_separate(self):
        b=gold.build({'text':'# Guide\n\n## First review\n\nA quiet room.\n\n## Second review\n\nA busy room.'})
        b=edit_graph(b,lambda n:n.model_copy(update={'semantic_role':SemanticRole.REVIEW}) if n.node_type.value=='section' and n.preorder>2 else n)
        doc=b.source_graph;edges=list(doc.edges)
        for n in doc.nodes:
            if n.node_type.value=='paragraph':
                target=next(x for x in doc.nodes if x.parent==n.parent and x.node_type.value=='heading')
                edges.append(StructuralEdge(from_node=n.identity,to_node=target.identity,relation='REFERS_TO',provenance=n.provenance,validation_state='validated'))
        doc=StructuralDocument.model_validate_json(doc.model_copy(update={'edges':tuple(edges)}).canonical_json())
        b=serialize_structural_document(doc);s=v2.select_structural_candidates(b)
        self.assertEqual(sum(c.kind=='review' for c in s.candidates),2)
        self.assertFalse(any('A quiet room.' in c.text and 'A busy room.' in c.text for c in s.candidates))
        self.assertEqual(sum(e.relation.value=='REFERS_TO' for e in s.v1.source_graph.edges),2)
    def test_non_title_independent_heading(self):
        b=gold.build({'text':'# Manual\n\n## Service includes priority access\n\nRegistration required.'})
        s=v2.select_structural_candidates(b)
        self.assertFalse(any(d.outcome=='metadata_only' for d in s.ledger))
    def test_non_title_numeric_heading(self):
        b=gold.build({'text':'# Manual\n\n## 3–4 months\n\nExperiences differ.'})
        s=v2.select_structural_candidates(b)
        self.assertFalse(any(d.outcome=='metadata_only' for d in s.ledger))
    def test_non_title_qualification_heading(self):
        b=gold.build({'text':'# Manual\n\n## Results vary by person\n\nExperiences differ.'})
        s=v2.select_structural_candidates(b)
        self.assertFalse(any(d.outcome=='metadata_only' for d in s.ledger))
    def test_timeline_stages_separate(self):
        s=v2.select_structural_candidates(batch('timeline'))
        stages=[c for c in s.candidates if c.kind=='timeline_stage'];self.assertEqual(len(stages),2)
        self.assertFalse(any('After 3' in c.text and 'Later support' in c.text for c in stages))
    def test_commercial_unknown_not_inferred(self):
        b=batch('commercial');s=v2.select_structural_candidates(b)
        money=[n.attributes.commercial for n in b.source_graph.nodes if n.attributes.commercial]
        self.assertTrue(money);self.assertTrue(any(m.role.value=='unknown' for m in money));self.assertEqual(s.v1.source_graph,b.source_graph)
        self.assertEqual(sum(c.kind=='price_block' for c in s.candidates),2)
    def test_all_unknown_commercial_blocks_stay_independent(self):
        b=gold.build({'text':'# Tickets\n\nAmount $35.\n\nAmount $19.'});s=v2.select_structural_candidates(b)
        self.assertTrue(all(n.attributes.commercial.role.value=='unknown' for n in b.source_graph.nodes if n.attributes.commercial))
        self.assertEqual(sum(c.kind=='price_block' for c in s.candidates),2)
    def test_quantity_frequency_preserved(self):
        b=batch('quantities');s=v2.select_structural_candidates(b)
        self.assertTrue(any('2 capsules daily with 8 oz water' in c.text and 'Do not exceed' in c.text for c in s.candidates));s.verify()
    def test_links_stay_in_graph(self):
        c={'text':'# Guide\n\nRead [the guide](https://example.org/guide).'};b=gold.build(c);s=v2.select_structural_candidates(b)
        self.assertTrue(any(n.attributes.link for n in b.source_graph.nodes));self.assertEqual(s.v1.source_graph,b.source_graph)
    def test_utf8_exact(self):
        b=gold.build({'text':'# 世界\n\n## Details\n\nCafé 👩🏽‍💻 漢字.'});s=v2.select_structural_candidates(b)
        self.assertTrue(any('Café 👩🏽‍💻 漢字.' in c.text for c in s.candidates));s.verify()
    def test_ledger_missing_refused(self):
        with self.assertRaises(v2.SelectionError):self.s.model_copy(update={'ledger':self.s.ledger[:-1]}).verify()
    def test_candidate_tampering_refused(self):
        c=self.s.candidates[0].model_copy(update={'text':'invented'})
        with self.assertRaises(v2.SelectionError):self.s.model_copy(update={'candidates':(c,)+self.s.candidates[1:]}).verify()
    def test_graph_only_tampering_refused(self):
        with self.assertRaises(v2.SelectionError):self.s.model_copy(update={'graph_only_nodes':()}).verify()
    def test_missing_heading_witness_refused(self):
        ds=tuple(d.model_copy(update={'witnesses':()}) if d.outcome=='metadata_only' else d for d in self.s.ledger)
        with self.assertRaises(v2.SelectionError):self.s.model_copy(update={'ledger':ds}).verify()


class OfflineAndCost(unittest.TestCase):
    def test_frozen_gold(self):
        manifest=json.loads((gold.ROOT/'manifest.json').read_text())
        for name,sha in manifest['sha256'].items():self.assertEqual(hashlib.sha256((gold.ROOT/name).read_bytes()).hexdigest(),sha)
    def test_no_network(self):
        with patch.object(socket.socket,'connect',side_effect=AssertionError('network')),patch.object(socket,'getaddrinfo',side_effect=AssertionError('DNS')):
            self.assertTrue(analyze(batch())['source_coverage_equal'])
    def test_no_database_or_provider_imports(self):
        tree=ast.parse(inspect.getsource(v2))
        modules=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]+[a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
        self.assertFalse(any(m.startswith(('database','sqlalchemy','requests','httpx','google','openai','socket','pathlib')) for m in modules))
    def test_no_runtime_consumers(self):
        for folder in ('services','routes','workers'):
            for p in (ROOT/'backend'/folder).rglob('*.py'):
                if p.name!='structural_selection_v2.py':self.assertNotIn('structural_selection_v2',p.read_text(encoding='utf-8-sig'))
    def test_cost_ratio(self):self.assertEqual(cost(2184,424122)['candidate_ratio_legacy'],2)
    def test_token_ratio(self):self.assertEqual(cost(2184,424122)['token_ratio_legacy'],2)
    def test_vector_lower_bound(self):self.assertEqual(cost(2000,200000)['float32_vector_lower_bound_bytes'],6144000)
    def test_target_gap(self):self.assertEqual(cost(2000,200000)['count_target_gap'],362)
    def test_token_target_gap(self):self.assertEqual(cost(2000,278000)['token_target_gap'],2321)
    def test_reduction_math(self):self.assertEqual(cost(1621,278491)['candidate_reduction_v1_pct'],50)
    def test_local_saved_analysis(self):
        p=ROOT/'.codex_structural_4_1h/selection_final.json'
        if not p.exists():self.skipTest('saved corpus unavailable; run the offline evaluator when authorized')
        r=json.loads(p.read_text(encoding='utf-8'));t=r['totals']
        self.assertEqual(len(r['documents']),23);self.assertEqual(t['v1_count'],3242);self.assertEqual(t['v1_tokens'],278491)
        self.assertEqual(sum(t['outcomes'].values()),3242);self.assertEqual(t['evidence_bytes_dropped'],0)
        self.assertTrue(r['source_coverage_equal']);self.assertEqual(t['v1_mapping_occurrences'],t['selected_translations']+t['metadata_witnesses'])
    def test_oss_ledger(self):
        text=(ROOT/'docs/PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md').read_text(encoding='utf-8').split('## Phase 4.1H')[-1]
        for name in ('Docling','RAGFlow','LlamaIndex','Haystack','Onyx','literal code reused: NO','pattern adapted: YES'):
            self.assertIn(name,text)


if __name__=='__main__':unittest.main()
