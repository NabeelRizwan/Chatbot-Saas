"""Offline Phase I GOLD and adversarial evidence/packing checks."""
import ast
import hashlib
import inspect
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from scripts import structural_identity_study as study
from scripts import structural_identity_gold as gold
from services.structural_selection_v2 import _Selection, SelectionPolicy
from services.structural_document import SemanticRole

ROOT=Path(__file__).resolve().parent.parent


class HeadingGold(unittest.TestCase):
    def check_case(self,case):
        b,r,headings=gold.heading_case(case);s=study.IdentityStudy(b,r)
        self.assertTrue(headings)
        for n in headings:
            row=study.classify_heading(b,n,s)
            self.assertEqual(row['category'],case['category'])
            self.assertEqual(row['decision']=='METADATA_ONLY_PROPOSED',case['safe'])


class ResourceGold(unittest.TestCase):
    def check_case(self,case):
        b,r,probes=gold.identity_case(case)
        if case.get('reject'):
            with self.assertRaises(study.EvidenceError):study.IdentityStudy(b,r)
            return
        s=study.IdentityStudy(b,r)
        if case['mode']=='partial':
            # A candidate with one proven primary node and one unproven node may
            # not borrow the first node's identity for all of its evidence.
            chunks=[c for c in b.chunks if c.kind=='prose']
            combined=chunks[0].model_copy(update={'mappings':tuple(m for c in chunks for m in c.mappings)})
            rows=[s.for_spec(combined)]
        else:rows=[s.annotations[n.identity.node_key] for n in probes]
        actual=[r.subjects[0] if r.state=='RESOLVED' else r.state for r in rows]
        self.assertEqual(actual,case['expected'])


for c in gold.cases('heading_answerability_gold_v1'):
    setattr(HeadingGold,'test_'+c['name'],lambda self,c=c:self.check_case(c))
for c in gold.cases('structural_resource_identity_gold_v1'):
    setattr(ResourceGold,'test_'+c['name'],lambda self,c=c:self.check_case(c))


class EvidenceSafety(unittest.TestCase):
    def setUp(self):self.b,self.r=gold.peer_case()
    def test_no_input_mutation(self):
        before=self.b.canonical_json(),self.r.canonical_json()
        study.IdentityStudy(self.b,self.r)
        self.assertEqual(before,(self.b.canonical_json(),self.r.canonical_json()))
    def test_deterministic(self):
        self.assertEqual(study.IdentityStudy(self.b,self.r).annotations,study.IdentityStudy(self.b,self.r).annotations)
    def test_duplicate_authority(self):
        with self.assertRaises(study.EvidenceError):study.IdentityStudy(self.b,self.r.model_copy(update={'allowed_sources':self.r.allowed_sources*2}))
    def test_duplicate_key(self):
        with self.assertRaises(study.EvidenceError):study.IdentityStudy(self.b,self.r.model_copy(update={'resources':self.r.resources*2}))
    def test_unowned_anchor(self):
        with self.assertRaises(study.EvidenceError):study.IdentityStudy(self.b,self.r.model_copy(update={'known_anchors':()}))
    def test_foreign_source(self):
        r=self.r.model_copy(update={'allowed_sources':self.r.allowed_sources+(self.r.allowed_sources[0].model_copy(update={'bot_id':123}),)})
        with self.assertRaises(study.EvidenceError):study.IdentityStudy(self.b,r)
    def test_version_pinned(self):
        self.reject_source_change(source_version=99)
    def test_hash_pinned(self):self.reject_source_change(source_sha256='f'*64)
    def test_document_version_pinned(self):self.reject_source_change(document_version_id='different')
    def reject_source_change(self,**updates):
        sources=(self.r.allowed_sources[0].model_copy(update=updates),)+self.r.allowed_sources[1:]
        with self.assertRaises(study.EvidenceError):study.IdentityStudy(self.b,self.r.model_copy(update={'allowed_sources':sources}))
    def test_contradictory_root_proof(self):
        b,r,probes=gold.identity_case({'mode':'nested'})
        proof=study.RootProof(source=b.source_graph.revision.identity.source,resource_key='r1',semantics='single_resource',inventory_complete=True)
        s=study.IdentityStudy(b,r.model_copy(update={'root_proofs':(proof,)}))
        self.assertEqual(s.annotations[b.source_graph.nodes[0].identity.node_key].state,'UNRESOLVED')
        self.assertEqual([s.annotations[n.identity.node_key].subjects for n in probes],[('r1',),('r2',)])
    def test_explicit_refers_to(self):
        b,r,probes=gold.identity_case({'mode':'review'})
        parent=next(n for n in b.source_graph.nodes if n.identity==probes[0].parent)
        b=gold.with_graph(b,edges=b.source_graph.edges+(gold.edge(parent,r.resources[0].anchor,'REFERS_TO'),))
        self.assertEqual(study.IdentityStudy(b,r).annotations[probes[0].identity.node_key].subjects,('r1',))
    def test_explicit_refers_to_without_inline_link(self):
        nodes={n.identity.node_key:n for n in self.b.source_graph.nodes}
        parent=next(n for n in nodes.values() if n.node_type.value=='paragraph').parent
        typed=[n.model_copy(update={'semantic_role':SemanticRole.REVIEW}) if n.identity==parent else n for n in nodes.values()]
        b=gold.with_graph(self.b,nodes=typed,edges=self.b.source_graph.edges+(gold.edge(nodes[parent.node_key],self.r.resources[0].anchor,'REFERS_TO'),))
        s=study.IdentityStudy(b,self.r)
        self.assertEqual(s.annotations[parent.node_key].state,'RESOLVED')
    def test_unvalidated_refers_to_no_inheritance(self):
        nodes={n.identity.node_key:n for n in self.b.source_graph.nodes}
        parent=next(n for n in nodes.values() if n.node_type.value=='paragraph').parent
        typed=[n.model_copy(update={'semantic_role':SemanticRole.REVIEW}) if n.identity==parent else n for n in nodes.values()]
        b=gold.with_graph(self.b,nodes=typed,edges=self.b.source_graph.edges+(gold.edge(nodes[parent.node_key],self.r.resources[0].anchor,'REFERS_TO',False),))
        self.assertEqual(study.IdentityStudy(b,self.r).annotations[parent.node_key].state,'UNRESOLVED')
    def test_contains_cannot_overrule_tree(self):
        b,r,probes=gold.identity_case({'mode':'sibling'})
        first=next(n for n in b.source_graph.nodes if n.identity==probes[0].parent)
        b=gold.with_graph(b,edges=b.source_graph.edges+(gold.edge(first,probes[-1].identity,'CONTAINS'),))
        self.assertEqual(study.IdentityStudy(b,r).annotations[probes[-1].identity.node_key].state,'UNRESOLVED')
    def test_nearby_reference_is_not_subject(self):
        b,r,p=gold.identity_case({'mode':'nearby'});s=study.IdentityStudy(b,r)
        self.assertTrue(any(x.state=='RESOLVED' for x in s.references.values()))
        self.assertTrue(all(x.state=='UNRESOLVED' for x in s.annotations.values()))
    def test_fragment_not_guessed_into_exact_registered_target(self):
        from scripts.evaluate_structural_text_adapter import parse_source
        from services.structural_chunking import serialize_structural_document
        doc=parse_source('# Reviews\n\nReview: Quiet room. [View resource]('+gold.URL1+'#reviews)')
        s=study.IdentityStudy(serialize_structural_document(doc),gold.registry(doc))
        self.assertTrue(s.references)
        self.assertTrue(all(x.state=='UNRESOLVED' for x in s.references.values()))
    def test_same_name_fixture_has_distinct_sources(self):
        b,r,p=gold.identity_case({'mode':'same_name'})
        self.assertTrue(any(n.text=='# Named resource' for n in b.source_graph.nodes))
        self.assertNotEqual(r.resources[0].anchor.revision.source,b.source_graph.revision.identity.source)
        self.assertTrue(all(x.state=='UNRESOLVED' for x in study.IdentityStudy(b,r).annotations.values()))
    def test_resource_annotation_keeps_heading(self):
        b,r,n=gold.heading_case({'heading':'Details','body':'Quiet room.','explicit_identity':True})
        self.assertEqual(study.classify_heading(b,n[0],study.IdentityStudy(b,r))['decision'],'KEEP')
    def test_href_question_is_not_question_heading(self):
        b,r,n=gold.heading_case({'heading':'[Reference](https://example.org/r?query=1)','body':'A reference.'})
        self.assertEqual(study.classify_heading(b,n[0])['category'],'AMBIGUOUS')
    def test_image_filename_number_not_numeric_fact(self):
        b,r,n=gold.heading_case({'heading':'![Tested](https://example.org/file123.svg)','body':'Test record.'})
        self.assertEqual(study.classify_heading(b,n[0])['category'],'AMBIGUOUS')
    def test_linked_generic_label_retained(self):
        b,r,n=gold.heading_case({'heading':'[Details](https://example.org/r)','body':'A reference.'})
        self.assertEqual(study.classify_heading(b,n[0])['decision'],'KEEP')
    def test_visible_question_retained(self):
        b,r,n=gold.heading_case({'heading':'[What is included?](https://example.org/r)','body':'A desk.'})
        self.assertEqual(study.classify_heading(b,n[0])['category'],'QUESTION_HEADING')
    def test_use_caution(self):
        b,r,n=gold.heading_case({'heading':'Use Caution','body':'Consult an adviser.'})
        self.assertEqual(study.classify_heading(b,n[0])['category'],'WARNING')
    def test_missing_witness(self):
        b,r,n=gold.heading_case({'heading':'Details','body':'Quiet room.'})
        e=_Selection(b,SelectionPolicy());e.inherited.clear()
        self.assertEqual(study.classify_heading(b,n[0],engine=e)['decision'],'KEEP')
    def test_scattered_witness(self):
        b,r,n=gold.heading_case({'heading':'Details','body':'Quiet room.'})
        e=_Selection(b,SelectionPolicy());c=next(c for c in b.chunks if c.kind=='heading' and any(m.mapping.node==n[0].identity for m in c.mappings))
        self.assertGreater(len(c.mappings),1)
        for i,m in enumerate(c.mappings):
            key=(m.mapping.node,m.mapping.node_slice,m.mapping.role)
            e.inherited[key]=[(other.model_copy(update={'chunk_key':str(i)*64}),j) for other,j in e.inherited.get(key,())]
        self.assertIsNone(e.heading_targets(c))
        self.assertEqual(study.classify_heading(b,n[0],engine=e)['decision'],'KEEP')
    def test_complete_witness_source_bytes(self):
        b,r,n=gold.heading_case({'heading':'Details','body':'Quiet room.'})
        d=study.classify_heading(b,n[0]);original=next(c for c in b.chunks if c.chunk_key==d['spec_id'])
        self.assertEqual(len({k for k,_ in d['witness']}),1)
        for old,(k,i) in zip(original.mappings,d['witness']):
            new=next(c for c in b.chunks if c.chunk_key==k).mappings[i]
            self.assertEqual((old.mapping.node,old.mapping.node_slice),(new.mapping.node,new.mapping.node_slice))


for name,url in {'credentials':'https://a:b@example.org/r','query':'https://example.org/r?q=1',
    'fragment':'https://example.org/r#x','relative':'/r','javascript':'javascript:alert(1)','space':'https://example.org/a b'}.items():
    def bad_url(self,url=url):
        resources=(self.r.resources[0].model_copy(update={'canonical_url':url}),)+self.r.resources[1:]
        with self.assertRaises(study.EvidenceError):study.IdentityStudy(self.b,self.r.model_copy(update={'resources':resources}))
    setattr(EvidenceSafety,'test_unsafe_url_'+name,bad_url)


class PackingSafety(unittest.TestCase):
    def setUp(self):
        self.b,self.r=gold.peer_case();self.s=study.IdentityStudy(self.b,self.r);self.e=study.StudyPeerEngine(self.b,self.s)
        self.a,self.z=[c for c in self.b.chunks if c.kind=='prose']
    def test_unknown_becomes_eligible(self):
        self.assertEqual(_Selection(self.b,SelectionPolicy()).peer(self.a,self.z).status,'unknown_identity')
        self.assertEqual(self.e.peer(self.a,self.z).status,'eligible')
    def test_unresolved_remains_unknown(self):
        s=study.IdentityStudy(self.b,self.r.model_copy(update={'root_proofs':()}))
        self.assertEqual(study.StudyPeerEngine(self.b,s).peer(self.a,self.z).status,'unknown_identity')
    def test_multi_subject_refused(self):
        b,r=gold.peer_case('single_conflict');s=study.IdentityStudy(b,r)
        self.assertEqual(study.StudyPeerEngine(b,s).peer(self.a,self.z).reason,'subject')
    def test_different_resources_refused(self):
        nodes={n.identity.node_key:n for n in self.b.source_graph.nodes}
        edges=list(self.b.source_graph.edges)
        for c,res in zip((self.a,self.z),self.r.resources):edges.append(gold.edge(nodes[self.e.roots[c.chunk_key][0]],res.anchor))
        b=gold.with_graph(self.b,edges=edges);s=study.IdentityStudy(b,self.r)
        self.assertEqual(study.StudyPeerEngine(b,s).peer(self.a,self.z).reason,'subject')
    def test_revision(self):self.assertEqual(self.e.peer(self.a,self.z.model_copy(update={'revision':self.z.revision.model_copy(update={'structure_revision_id':'other'})})).reason,'source_revision')
    def test_source_version(self):
        rev=self.z.revision.model_copy(update={'source':self.z.revision.source.model_copy(update={'source_version':2})})
        self.assertEqual(self.e.peer(self.a,self.z.model_copy(update={'revision':rev})).reason,'source_revision')
    def test_token_cap(self):self.assertEqual(self.e.peer(self.a,self.z.model_copy(update={'text':self.z.text+'more '*1000})).reason,'token_or_mapping_budget')
    def test_warning_role(self):
        key=self.e.roots[self.a.chunk_key][0]
        b=gold.with_graph(self.b,nodes=[n.model_copy(update={'semantic_role':SemanticRole.WARNING}) if n.identity.node_key==key else n for n in self.b.source_graph.nodes])
        self.assertEqual(study.StudyPeerEngine(b,study.IdentityStudy(b,self.r)).peer(self.a,self.z).reason,'role')
    def test_cannot_publish_h(self):
        with self.assertRaises(study.EvidenceError):self.e.run()
    def test_exact_mapping_and_zero_loss(self):
        packed=self.e.pack((self.a,self.z));old={c.chunk_key:c for c in (self.a,self.z)}
        self.assertEqual(len(packed.translations),sum(len(c.mappings) for c in old.values()))
        for t in packed.translations:
            c=old[t.v1_spec_id];m=c.mappings[t.mapping_index].mapping
            self.assertEqual(c.text.encode()[m.output_slice.start:m.output_slice.end],packed.text.encode()[t.output_slice.start:t.output_slice.end])
    def test_deterministic_pack(self):self.assertEqual(self.e.pack((self.a,self.z)),self.e.pack((self.a,self.z)))
    def test_guards_inherited_not_reimplemented(self):
        self.assertIs(study.StudyPeerEngine.peer,_Selection.peer);self.assertIs(study.StudyPeerEngine.pack,_Selection.pack)


for kind in ('review','faq','timeline_stage','price_block','list','table','directions'):
    setattr(PackingSafety,'test_atomic_'+kind,lambda self,k=kind:self.assertEqual(self.e.peer(self.a,self.z.model_copy(update={'kind':k})).reason,'atomic_kind'))


class OfflinePreservation(unittest.TestCase):
    def test_gold_frozen(self):
        for folder in ('heading_answerability_gold_v1','structural_resource_identity_gold_v1'):
            manifest=json.loads((gold.ROOT/folder/'manifest.json').read_text())
            for name,sha in manifest['sha256'].items():self.assertEqual(hashlib.sha256((gold.ROOT/folder/name).read_bytes()).hexdigest(),sha)
    def test_network_denied(self):
        with patch.object(socket.socket,'connect',side_effect=AssertionError('network')),patch.object(socket,'getaddrinfo',side_effect=AssertionError('DNS')):
            b,r=gold.peer_case();self.assertTrue(study.IdentityStudy(b,r).annotations)
    def test_no_io_provider_database_import(self):
        tree=ast.parse(inspect.getsource(study))
        modules=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]+[a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
        self.assertFalse(any(m.startswith(('database','sqlalchemy','requests','httpx','google','openai','socket','pathlib','os')) for m in modules))
    def test_no_runtime_consumer(self):
        for folder in ('services','routes','workers'):
            for p in (ROOT/'backend'/folder).rglob('*.py'):self.assertNotIn('structural_identity_study',p.read_text(encoding='utf-8-sig'))
    def test_saved_h_frozen(self):
        p=ROOT/'.codex_structural_4_1h/selection_final.json'
        if not p.exists():self.skipTest('local saved corpus absent')
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),'83d8c98dd7de9c82a6c65c309d4ed2367016612990ab6ee43aa3789e0e47fcd8')
    def test_saved_sample_frozen(self):
        p=ROOT/'.codex_structural_4_1i/heading_sample_frozen.json'
        if not p.exists():self.skipTest('local saved corpus absent')
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),'756dae53035252246c7aad3007ef2e9cc4893e12b67c8d812f6124e8aa9a70ff')
    def test_ledger(self):
        text=(ROOT/'docs/PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md').read_text(encoding='utf-8')
        self.assertIn('## Phase 4.1I',text)
        text=text.split('## Phase 4.1I')[-1]
        for name in ('Docling','RAGFlow','LlamaIndex','Haystack','Onyx','literal code reused: NO','pattern adapted: YES'):self.assertIn(name,text)


class StudySimulation(unittest.TestCase):
    def setUp(self):
        from scripts.evaluate_structural_identity_study import simulate
        self.simulate=simulate;self.b,self.r=gold.peer_case()
    def run_sim(self):
        s=study.IdentityStudy(self.b,self.r)
        headings=[study.classify_heading(self.b,n,s) for n in self.b.source_graph.nodes if n.node_type.value=='heading']
        return self.simulate(self.b,s,headings)
    def test_deterministic_simulation(self):self.assertEqual(self.run_sim(),self.run_sim())
    def test_simulation_distinct_not_v2(self):self.assertEqual(self.run_sim()['version'],'I_SIMULATION_NOT_ACCEPTED_V2')
    def test_simulation_mapping_total(self):
        r=self.run_sim();self.assertEqual(r['mapping_translations']+r['heading_mapping_witnesses'],sum(len(c.mappings) for c in self.b.chunks))
    def test_simulation_lossless(self):self.assertEqual(self.run_sim()['evidence_bytes_dropped'],0)
    def test_simulation_packs_proven_peers(self):self.assertEqual(self.run_sim()['packed_groups'],1)
    def test_sample_uses_no_classification(self):
        from scripts.structural_identity_features import heading_features,freeze_sample
        rows=heading_features(self.b);self.assertTrue(rows)
        self.assertTrue(all('category' not in r for r in rows))
        self.assertEqual(freeze_sample(rows),freeze_sample(list(reversed(rows))))


class FrozenCatalogBoundary(unittest.TestCase):
    def setUp(self):
        from scripts.evaluate_structural_identity_study import saved_registry
        self.load=saved_registry;self.b,_=gold.peer_case()
        self.snapshot={'documents':[{'id':1,'organization_id':11,'bot_id':12,'status':'ready',
            'processing_status':'completed','version':1,'crawl_id':2,'canonical_url':gold.URL1}]}
        self.mapping={'organization':{'11':21},'bot':{'12':22},'corpus':{'documents':{'1':101},'website_crawls':{'2':102}}}
        self.fingerprint={'fingerprint':'a'*64,'source_organization_id':11,'source_bot_id':12,'development_organization_id':21,'development_bot_id':22}
        resource={'id':5,'organization_id':21,'bot_id':22,'status':'ready','resource_type':'document','source_key':'document:101',
            'metadata_json':{'primary_document_id':101},'url':gold.URL1,'version':1}
        link={'organization_id':21,'bot_id':22,'resource_id':5,'document_id':101,'relation_type':'primary','document_version':1,'document_crawl_id':102}
        self.projection={'source_corpus_unchanged':True,'source_corpus_fingerprint':'a'*64,
            'catalog':{'knowledge_resources':[resource],'knowledge_resource_documents':[link]}}
    def result(self):return self.load(self.snapshot,self.projection,self.mapping,self.fingerprint,{1:self.b},'f'*64)[0]
    def test_explicit_rebase(self):
        r=self.result();self.assertEqual((r.organization_id,r.bot_id),(70001,70002))
        self.assertEqual(r.resources[0].anchor.revision.source,self.b.source_graph.revision.identity.source)
    def test_catalog_document_not_subject(self):
        s=study.IdentityStudy(self.b,self.result())
        self.assertTrue(all(v.state=='UNRESOLVED' for v in s.annotations.values()))
    def test_fingerprint_refusal(self):
        self.projection['source_corpus_fingerprint']='b'*64
        with self.assertRaises(AssertionError):self.result()
    def test_foreign_catalog(self):
        self.projection['catalog']['knowledge_resources'][0]['bot_id']=99
        with self.assertRaises(AssertionError):self.result()
    def test_crawl_refusal(self):
        self.projection['catalog']['knowledge_resource_documents'][0]['document_crawl_id']=7
        with self.assertRaises(AssertionError):self.result()
    def test_document_version_refusal(self):
        self.projection['catalog']['knowledge_resource_documents'][0]['document_version']=7
        with self.assertRaises(AssertionError):self.result()
    def test_matching_catalog_cannot_relabel_stale_study_source(self):
        self.snapshot['documents'][0]['version']=2
        self.projection['catalog']['knowledge_resource_documents'][0]['document_version']=2
        registry,refused=self.load(self.snapshot,self.projection,self.mapping,self.fingerprint,{1:self.b},'f'*64)
        self.assertEqual(registry.resources,());self.assertEqual(registry.root_proofs,())
        self.assertEqual(refused,[{'resource_id':5,'document_id':1,'catalog_document_version':2,
            'study_source_version':1,'reason':'source_version_mismatch'}])
        self.assertTrue(all(v.state=='UNRESOLVED' for v in study.IdentityStudy(self.b,registry).annotations.values()))
    def test_canonical_not_prefix_matching(self):
        self.projection['catalog']['knowledge_resources'][0]['url']+='/nearby'
        with self.assertRaises(AssertionError):self.result()
    def test_multi_mapping_refusal(self):
        self.projection['catalog']['knowledge_resource_documents']*=2
        with self.assertRaises(AssertionError):self.result()
    def test_not_single_resource_inference(self):
        self.projection['catalog']['knowledge_resources'][0]['resource_type']='product'
        with self.assertRaises(AssertionError):self.result()


if __name__=='__main__':unittest.main()
