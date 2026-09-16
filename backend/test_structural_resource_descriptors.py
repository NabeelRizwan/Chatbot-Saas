"""Phase J deterministic proof contracts, real parser/serializer/H policy paths."""
from collections import Counter
from hashlib import sha256
import ast
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from scripts.structural_descriptor_corpus import native_batch, read, file_hash
from scripts.structural_resource_descriptors import (DescriptorStudy, SourcePin, ResourceTarget,
    AnchorProof, RelativeBinding, Refusal, Subject, BoundaryProof, DescriptorPeerEngine,
    StructuralResourceDescriptor, pair_state)
from scripts.structural_chunk_gold_v2 import build
from scripts.structural_identity_study import classify_heading
from scripts.evaluate_structural_resource_descriptors import simulation, compare_reconstruction
from services.structural_selection_v2 import _Selection, SelectionPolicy

ROOT=Path(__file__).resolve().parent
GOLD=ROOT/'fixtures/structural_resource_descriptor_gold_v1'
URL='https://example.test/a';OTHER='https://example.test/b'
TEXT=f'# Manual\n\n## Resource\n\nThis block describes [Azure Resource]({URL}).\n\nQuiet study space.\n\n### Nested\n\nNested content.\n\n## Neighbor\n\nUnrelated text.'


def cp(value,**changes): return value.model_copy(update=changes)


def fixture(text=TEXT,*,manual=False,version=1):
    texts={1:text,2:'# Azure Resource\n\nOwned source.\n\n<span id="part">Saved target.</span>',3:'# Bronze Resource\n\nAnother source.'}
    bs={i:native_batch(t,org=7,bot=9,document=i,version=version) for i,t in texts.items()}
    ps={i:SourcePin(revision=b.source_graph.revision.identity,source_document_id=i,source_organization_id=1,source_bot_id=1,
        crawl_id=10,crawl_version=1,canonical_url=URL if i==2 else OTHER if i==3 else 'https://example.test/manual') for i,b in bs.items()}
    rs=tuple(ResourceTarget(key=k,pin=ps[i],root=bs[i].source_graph.nodes[0].identity,canonical_url=ps[i].canonical_url)
        for i,k in ((1,'owner'),(2,'a'),(3,'b')))
    return DescriptorStudy(bs,ps,rs,manual=manual)


def block(s,scope='SECTION',resource='a'):
    ns=s.batches[1].source_graph.nodes
    root=next(n for n in ns if n.node_type.value=='heading' and n.text=='## Resource').parent
    members=s.descendants(root)
    evidence=next(n.identity for n in ns if n.text.startswith('This block describes'))
    return s.proof(1,root,members,scope=scope,basis=('EXPLICIT_RESOURCE_GROUP',),evidence=(evidence,),resource_key=resource)


def answer(case):
    scenario=case['scenario'];s=fixture();p=block(s)
    if scenario in {'valid','deterministic','section','group','card','review','linked','nested','ancestor','hotel','software','course','legal','generic','native-two'}:
        if scenario=='native-two':s=fixture(version=2);p=block(s)
        if scenario in {'hotel','software','course','legal','generic'}:
            labels={'hotel':'Harbor Room Package','software':'Nimbus Plan','course':'History Module','legal':'Arbitration Section','generic':'Archive Resource'}
            s=fixture(TEXT.replace('Azure Resource',labels[scenario]));p=block(s)
        if scenario in {'group','card','linked'}:p=cp(p,scope={'group':'GROUP','card':'CARD','linked':'LINKED_BLOCK'}[scenario])
        if scenario=='review':
            s=fixture(f'# Reviews\n\n## Helpful\n\nQuiet space.\n\nVerified Reviewer | [View]({URL})')
            s.automatic(1);return s.descriptors[0].state
        d=s.add(p)
        if scenario=='deterministic':
            assert d.canonical_hash()==StructuralResourceDescriptor.model_validate_json(d.canonical_json()).canonical_hash()
        if scenario in {'nested','ancestor'}:
            n=next(n for n in s.batches[1].source_graph.nodes if n.text=='Nested content.')
            assert s.subject(n.identity).state=='RESOLVED'
        return d.state
    if scenario in {'hash','version','org','bot','document','revision','crawl','old-new'}:
        pin=p.pin;rev=pin.revision;source=rev.source
        if scenario in {'hash','version','org','bot','document','old-new'}:
            field,val={'hash':('source_sha256','0'*64),'version':('source_version',2),'org':('organization_id',88),
                'bot':('bot_id',88),'document':('document_id',88),'old-new':('source_version',3)}[scenario]
            rev=cp(rev,source=cp(source,**{field:val}))
        if scenario=='revision':rev=cp(rev,structure_revision_id='stale-revision')
        pin=cp(pin,revision=rev)
        if scenario=='crawl':pin=cp(pin,crawl_id=11)
        return s.add(cp(p,pin=pin)).state
    if scenario in {'sibling','hole','missing','missing-root','start','end','evidence-outside','duplicate'}:
        ns=s.batches[1].source_graph.nodes
        other=next(n.identity for n in ns if n.text=='Unrelated text.')
        if scenario=='sibling':p=cp(p,members=p.members+(other,))
        if scenario=='hole':p=cp(p,members=p.members[:2]+p.members[3:])
        if scenario=='missing':p=cp(p,members=(cp(p.members[0],node_key='0'*64),)+p.members[1:])
        if scenario=='missing-root':p=cp(p,root=cp(p.root,node_key='0'*64))
        if scenario=='start':p=cp(p,start=p.start+1)
        if scenario=='end':p=cp(p,byte_end=p.byte_end+1)
        if scenario=='evidence-outside':p=cp(p,evidence_nodes=(other,))
        if scenario=='duplicate':p=cp(p,members=p.members+(p.members[-1],))
        return s.add(p).state
    if scenario in {'conflict','ambiguous','partial','unresolved','multi-subject','title','mapping-only','override','nested-unresolved'}:
        if scenario in {'title','mapping-only','unresolved'}:
            return s.add(cp(p,basis=('CANONICAL_DOCUMENT_MAPPING',))).state
        s.add(p)
        if scenario in {'conflict','ambiguous'}:
            s.add(cp(p,resource_key='b'));return s.subject(p.evidence_nodes[0]).state
        if scenario in {'override','nested-unresolved'}:
            nested=next(n for n in s.batches[1].source_graph.nodes if n.text=='Nested content.')
            proof=s.proof(1,nested.identity,(nested.identity,),scope='LINKED_BLOCK',basis=('EXPLICIT_RESOURCE_GROUP',),
                evidence=(nested.identity,),resource_key='b' if scenario=='override' else '')
            s.add(proof);return s.subject(nested.identity).state
        from scripts.structural_resource_descriptors import combine
        if scenario=='partial':return combine([s.subject(p.evidence_nodes[0]),Subject(state='UNRESOLVED')]).state
        s.add(cp(p,resource_key='b'));return s.for_spec(next(c for c in s.batches[1].chunks if c.kind=='prose')).state
    if scenario in {'root','competing-root','incomplete-root','canonical-root','unresolved-root','two-primary'}:
        self_url='https://example.test/manual'
        s=fixture(f'# Manual\n\nThis document describes [Manual]({self_url}).\n\nQuiet study space.')
        root=s.batches[1].source_graph.nodes[0]
        p=s.proof(1,root.identity,s.descendants(root.identity),scope='DOCUMENT',basis=('DOCUMENT_RESOURCE_ASSERTION','CANONICAL_DOCUMENT_MAPPING'),
            evidence=(next(n.identity for n in s.batches[1].source_graph.nodes if n.text.startswith('This document')),),
            resource_key='owner',inventory_complete=True,primary_assertions=1)
        inventory=[]
        if scenario=='incomplete-root':p=cp(p,inventory_complete=False)
        if scenario=='canonical-root':p=cp(p,resource_key='a')
        if scenario=='two-primary':p=cp(p,primary_assertions=2)
        if scenario in {'competing-root','unresolved-root'}:
            inventory=[StructuralResourceDescriptor(proof=p,state='RESOLVED' if scenario=='competing-root' else 'UNRESOLVED',
                resource_keys=('b',) if scenario=='competing-root' else (),reason='frozen_inventory')]
        return s.add(p,inventory=inventory).state
    if scenario in {'base','anchor','unresolved-anchor','reviews-name','ambiguous-target','ambiguous-anchor','unsafe','relative','relative-bound',
                    'missing-target','stale-target','stale-target-crawl','stale-target-hash','prefix','query','empty-fragment'}:
        href=URL
        if scenario in {'anchor','ambiguous-anchor','unresolved-anchor'}:href+='#part'
        if scenario=='reviews-name':href+='#reviews'
        if scenario=='unsafe':href='javascript:alert(1)'
        if scenario in {'relative','relative-bound'}:href='/a'
        if scenario=='missing-target':href='https://example.test/absent'
        if scenario=='prefix':href=URL+'/other'
        if scenario=='query':href+='?view=other'
        if scenario=='empty-fragment':href+='#'
        if scenario in {'anchor','ambiguous-anchor'}:
            r=s.resources['a'];node=next(n.identity for n in s.batches[2].source_graph.nodes if 'id="part"' in n.text)
            a=AnchorProof(pin=r.pin,resource_key='a',fragment='part',node=node,literal='id="part"')
            s=DescriptorStudy(s.batches,s.pins,tuple(s.resources.values()),anchors=(a,)*(2 if scenario=='ambiguous-anchor' else 1))
        if scenario=='ambiguous-target':
            r=cp(s.resources['a'],key='duplicate')
            s=DescriptorStudy(s.batches,s.pins,(*s.resources.values(),r))
        if scenario.startswith('stale-target'):
            r=s.resources['a'];pin=r.pin
            if scenario=='stale-target-crawl':pin=cp(pin,crawl_id=99)
            else:pin=cp(pin,revision=cp(pin.revision,source=cp(pin.revision.source,**(
                {'source_sha256':'f'*64} if scenario.endswith('hash') else {'source_version':99}))))
            r=cp(r,pin=pin,root=cp(r.root,revision=pin.revision))
            s=DescriptorStudy(s.batches,s.pins,(r,))
        if scenario=='relative-bound':
            s=fixture(TEXT.replace(URL,'/a'))
            n=next(n.identity for n in s.batches[1].source_graph.nodes if n.attributes.link)
            binding=RelativeBinding(pin=s.pins[1],node=n,original_href='/a',exact_absolute_href=URL)
            s=DescriptorStudy(s.batches,s.pins,tuple(s.resources.values()),relative=(binding,))
            return s.target('/a',n).state
        return s.target(href).state
    if scenario.startswith('review-') or scenario=='two-reviews':
        href=URL+'#reviews' if scenario=='review-fragment' else URL
        text=f'# Reviews\n\n## Helpful\n\nQuiet space.\n\nVerified Reviewer | [View]({href})'
        if scenario=='review-nearby':text=f'# Reviews\n\n## Helpful\n\nQuiet space.\n\nVerified Reviewer | Ann\n\n[Unrelated]({URL})'
        if scenario=='review-tail':text+='\n\nTrailing navigation.'
        if scenario=='two-reviews':text+=f'\n\n## Second\n\nDifferent experience.\n\nVerified Reviewer | [View]({OTHER})'
        s=fixture(text);s.automatic(1)
        if scenario=='review-tail':
            tail=next(n for n in s.batches[1].source_graph.nodes if n.text=='Trailing navigation.')
            assert s.subject(tail.identity).state=='UNRESOLVED'
        if scenario=='two-reviews':assert {d.resource_keys for d in s.descriptors}=={('a',),('b',)}
        return s.descriptors[0].state
    if scenario in {'card-auto','card-unbounded','two-cards'}:
        # Explicit capture supplied as frozen boundary proof. Parser heuristics
        # cannot invent a card boundary from a linked heading.
        s.automatic(1)
        if scenario=='card-unbounded':return s.subject(p.evidence_nodes[0]).state
        link=next(n.identity for n in s.batches[1].source_graph.nodes if n.attributes.link)
        p=cp(p,scope='CARD',basis=('EXPLICIT_CARD_LINK',),target_href=URL,evidence_nodes=(link,))
        d=s.add(p)
        if scenario=='two-cards':
            sibling=next(n for n in s.batches[1].source_graph.nodes if n.text=='Unrelated text.')
            other=s.proof(1,sibling.identity,(sibling.identity,),scope='CARD',basis=('EXPLICIT_RESOURCE_GROUP',),evidence=(sibling.identity,),resource_key='b')
            s.add(other);assert s.subject(sibling.identity).subjects==('b',)
            assert s.subject(link).subjects==('a',)
        return d.state
    if scenario in {'manual','manual-auto'}:
        s=fixture(manual=scenario=='manual');p=cp(block(s),basis=('MANUAL_FROZEN_GOLD',))
        return s.add(p).state
    raise AssertionError('unimplemented frozen GOLD scenario: '+scenario)


class GoldTests(unittest.TestCase): pass


def gold_test(case):
    def test(self):
        if case['expected']=='REFUSED':
            with self.assertRaises(Refusal):answer(case)
        else:self.assertEqual(answer(case),case['expected'])
    return test


for case in read(GOLD/'cases.json')['cases']:
    setattr(GoldTests,'test_'+case['id'].replace('-','_'),gold_test(case))


class PackingTests(unittest.TestCase):
    def setUp(self):
        self.b=build({'shape':'units','subject':False})
        p=SourcePin(revision=self.b.source_graph.revision.identity,source_document_id=1,source_organization_id=1,source_bot_id=1,canonical_url=URL)
        r=ResourceTarget(key='a',pin=p,root=self.b.source_graph.nodes[0].identity,canonical_url=URL)
        self.s=DescriptorStudy({1:self.b},{1:p},(r,))
        self.prose=[c for c in self.b.chunks if c.kind=='prose']

    def bind(self,which=0,key='a',basis=('EXPLICIT_RESOURCE_GROUP',)):
        n=self.prose[which].source_nodes[0]
        p=self.s.proof(1,n,(n,),scope='LINKED_BLOCK',basis=basis,evidence=(n,),resource_key=key)
        return self.s.add(p)

    def test_same_subject_eligible(self):
        self.bind(0);self.bind(1)
        self.assertEqual(DescriptorPeerEngine(self.b,self.s).peer(*self.prose).status,'eligible')

    def test_different_subject_refused(self):
        self.bind(0)
        self.s.resources['b']=cp(self.s.resources['a'],key='b');self.bind(1,'b')
        self.assertNotEqual(DescriptorPeerEngine(self.b,self.s).peer(*self.prose).status,'eligible')

    def test_no_identity_still_refused(self):
        self.assertEqual(DescriptorPeerEngine(self.b,self.s).peer(*self.prose).status,'unknown_identity')

    def test_mapping_preservation(self):
        self.bind(0);self.bind(1)
        headings=[classify_heading(self.b,n) for n in self.b.source_graph.nodes if n.node_type.value=='heading']
        value=simulation(self.b,self.s,headings)
        self.assertEqual(value['evidence_bytes_dropped'],0)
        self.assertEqual(value['packed_groups'],1)
        self.assertTrue(value['source_coverage_equal'])

    def test_never_publishes_H(self):
        with self.assertRaises(Refusal):DescriptorPeerEngine(self.b,self.s).run()

    def test_h_peer_function_not_replaced(self):
        self.assertIs(DescriptorPeerEngine.peer,_Selection.peer)
        self.assertIs(DescriptorPeerEngine.pack,_Selection.pack)

    def test_manual_never_automatic(self):
        with self.assertRaises(Refusal):self.bind(0,basis=('MANUAL_FROZEN_GOLD',))

    def test_stale_pair_explicit(self):
        self.assertEqual(pair_state(Subject(state='STALE'),Subject(state='RESOLVED',subjects=('a',))),'STALE_DESCRIPTOR')

    def test_partial_pair_explicit(self):
        self.assertEqual(pair_state(Subject(state='RESOLVED',subjects=('a',)),Subject(state='UNRESOLVED')),'PARTIAL')

    def test_ambiguous_pair_explicit(self):
        self.assertEqual(pair_state(Subject(state='AMBIGUOUS'),Subject(state='UNRESOLVED')),'AMBIGUOUS')

    def test_partial_identity_cannot_pack(self):
        self.bind(0)
        self.s.for_spec=lambda c: Subject(state='PARTIAL',subjects=('a',))
        self.assertEqual(DescriptorPeerEngine(self.b,self.s).peer(*self.prose).status,'unknown_identity')

    def test_ambiguous_identity_cannot_pack(self):
        self.s.for_spec=lambda c: Subject(state='AMBIGUOUS',subjects=('a','b'))
        self.assertEqual(DescriptorPeerEngine(self.b,self.s).peer(*self.prose).status,'unknown_identity')

    def test_actual_warning_boundary(self):
        b=build({'shape':'units','subject':False,'text':'# Manual\n\n## Details\n\nWarning: use care.\n\nQuiet study space.'})
        self.s.for_spec=lambda c: Subject(state='RESOLVED',subjects=('a',))
        prose=[c for c in b.chunks if c.kind=='prose']
        self.assertEqual(len(prose),2)
        self.assertNotEqual(DescriptorPeerEngine(b,self.s).peer(*prose).status,'eligible')

    def test_actual_qualification_boundary(self):
        b=build({'shape':'units','subject':False,'text':'# Manual\n\n## Details\n\nResults may vary.\n\nQuiet study space.'})
        self.s.for_spec=lambda c: Subject(state='RESOLVED',subjects=('a',))
        prose=[c for c in b.chunks if c.kind=='prose']
        self.assertEqual(len(prose),2)
        self.assertEqual(DescriptorPeerEngine(b,self.s).peer(*prose).reason,'qualification')


def atomic_test(kind):
    def test(self):
        self.bind(0);self.bind(1)
        a=cp(self.prose[0],kind=kind)
        base=_Selection(self.b,SelectionPolicy()).peer(a,self.prose[1])
        new=DescriptorPeerEngine(self.b,self.s).peer(a,self.prose[1])
        self.assertEqual(base.status,new.status)
        self.assertNotEqual(new.status,'eligible')
    return test


for kind in ('review','faq','timeline','commercial','list','table','heading','code'):
    setattr(PackingTests,'test_atomic_'+kind,atomic_test(kind))


class SafetyTests(unittest.TestCase):
    def test_gold_hash_frozen(self):
        m=read(GOLD/'manifest.json')
        self.assertEqual(file_hash(GOLD/'cases.json'),m['synthetic_cases_sha256'])
        self.assertEqual(file_hash(GOLD/'manual_saved.json'),m['manual_saved_sha256'])

    def test_local_preservation_when_artifacts_present(self):
        path=ROOT.parent/'.codex_structural_4_1j/preservation_before.json'
        if not path.exists():self.skipTest('local frozen corpus artifacts not distributed')
        rows=read(path)
        self.assertGreaterEqual(len(rows),300)
        for name,h in rows.items():self.assertEqual(file_hash(ROOT.parent/name),h,name)

    def test_source_native_two_not_h_version(self):
        a=native_batch(TEXT,org=7,bot=9,document=13,version=1)
        b=native_batch(TEXT,org=7,bot=9,document=13,version=2)
        self.assertNotEqual(a.source_graph.nodes[0].identity,b.source_graph.nodes[0].identity)
        self.assertEqual(a.source_graph.revision.identity.source.source_sha256,b.source_graph.revision.identity.source.source_sha256)
        self.assertEqual(len(compare_reconstruction(a,b)),len(a.source_graph.nodes))

    def test_manual_fixture_exact_versions_and_boundaries(self):
        rows=read(GOLD/'manual_saved.json')['descriptors']
        self.assertEqual(len(rows),2)
        for row in rows:
            p=BoundaryProof.model_validate(row['proof'])
            self.assertEqual(p.basis,('MANUAL_FROZEN_GOLD',))
            self.assertEqual(p.end-p.start,len(p.members))
            self.assertTrue(p.pin.revision.source.source_sha256)

    def test_no_forbidden_dependency(self):
        for name in ('structural_resource_descriptors.py','structural_descriptor_corpus.py','evaluate_structural_resource_descriptors.py'):
            tree=ast.parse((ROOT/'scripts'/name).read_text(encoding='utf-8'))
            imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
            imports += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
            for prefix in ('database','sqlalchemy','requests','httpx','google','openai','anthropic','redis','urllib.request'):
                self.assertFalse(any(m.startswith(prefix) for m in imports),(name,prefix))

    def test_no_runtime_consumer(self):
        for folder in ('services','routes','workers'):
            for path in (ROOT/folder).rglob('*.py'):
                value=path.read_text(encoding='utf-8')
                self.assertNotIn('scripts.structural_resource_descriptors',value)

    def test_network_denied_pure_path(self):
        with patch('socket.create_connection',side_effect=AssertionError('network')),patch('socket.getaddrinfo',side_effect=AssertionError('DNS')):
            self.assertEqual(answer({'scenario':'base'}),'EXACT_RESOURCE')

    def test_review_name_does_not_verify_anchor(self):
        self.assertEqual(answer({'scenario':'reviews-name'}),'UNRESOLVED_FRAGMENT')

    def test_unsafe_registry_is_refused(self):
        s=fixture();r=cp(s.resources['a'],canonical_url='https://user:password@example.test/a')
        with self.assertRaises(Refusal):DescriptorStudy(s.batches,s.pins,(r,))

    def test_fake_anchor_heading_is_refused(self):
        s=fixture();r=s.resources['a'];n=s.batches[2].source_graph.nodes[1]
        a=AnchorProof(pin=r.pin,resource_key='a',fragment='part',node=n.identity,literal='id="part"')
        with self.assertRaises(Refusal):DescriptorStudy(s.batches,s.pins,tuple(s.resources.values()),(a,))

    def test_anchor_text_attribute_example_not_markup(self):
        s=fixture('The example says id="part" but defines no element.')
        r=s.resources['owner'];n=next(n for n in s.batches[1].source_graph.nodes if n.text)
        a=AnchorProof(pin=r.pin,resource_key='owner',fragment='part',node=n.identity,literal='id="part"')
        with self.assertRaises(Refusal):DescriptorStudy(s.batches,s.pins,tuple(s.resources.values()),(a,))

    def test_anchor_fenced_example_not_target(self):
        s=fixture('```html\n<span id="part">example</span>\n```')
        r=s.resources['owner'];n=next(n for n in s.batches[1].source_graph.nodes if n.text)
        a=AnchorProof(pin=r.pin,resource_key='owner',fragment='part',node=n.identity,literal='id="part"')
        with self.assertRaises(Refusal):DescriptorStudy(s.batches,s.pins,tuple(s.resources.values()),(a,))

    def test_cross_org_target_refused(self):
        s=fixture();r=s.resources['a'];pin=cp(r.pin,revision=cp(r.pin.revision,source=cp(r.pin.revision.source,organization_id=88)))
        with self.assertRaises(Refusal):DescriptorStudy(s.batches,s.pins,(cp(r,pin=pin),))

    def test_ledger_records_current_oss(self):
        text=(ROOT.parent/'docs/PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md').read_text(encoding='utf-8')
        self.assertIn('Phase 4.1J',text)
        for pin in ('7bc159d64e565d7fa93cd56b866772dad66edf31','4ea423849cb0dc7e0df69096fbc650572bc08579'):
            self.assertIn(pin,text)


if __name__=='__main__':unittest.main()
