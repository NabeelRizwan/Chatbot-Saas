"""Frozen Phase 3.6 cases: 133 development / 57 held-out, no live I/O.

Ten domains, seven failure classes. Held-out partition is fixed by case index,
not by observed results. SQL-channel tests execute projection/discovery/scope
with the established SQLite lexical surrogate (not PostgreSQL acceptance).
"""
import unittest
from types import SimpleNamespace as NS

from services import rag_service as rag
from services.requested_propositions import bind_field_obligations, annotate_candidates
from services.retrieval_selection import POLICY
from services.observability_service import ChatTrace, evidence_key
from test_resource_discovery import ResourceFixture
from test_phase35_live_repair import contract, item, VALUES

DOMAINS = [('Cedar Adapter','device'), ('Birch Workshop','course'),
    ('Silver Suite','software'), ('Amber Policy','policy'), ('Quartz Permit','form'),
    ('Indigo Package','plan'), ('Willow Lodge','location'), ('Copper Visit','appointment'),
    ('Maple Service','service'), ('Violet Blend','product')]
FIELDS = [('directions','results_timeframe'), ('price','features'), ('duration','syllabus'),
    ('policy','returns'), ('directions','eligibility'), ('price','policy'),
    ('amenities','check_in'), ('directions','duration'), ('features','price'),
    ('ingredients','directions')]


def numeric(self, n):
    name, kind = DOMAINS[n // 4]
    # Two informative words are required by the pre-existing specificity
    # guard. Generic type nouns alone are intentionally not a second word.
    name += ' Meridian'
    mode = n % 4
    self.add(1, name+' 3', kind=kind)
    if mode == 3:
        self.add(2, name+' 6', kind=kind)
    self.project(*((1,2) if mode == 3 else (1,)))
    query = name + (' 3' if mode == 1 else ' 6' if mode == 2 else '')
    result = self.discover(query)
    state = result.resolutions[0].state.value
    self.assertEqual(state, 'resolved' if mode in (0,1) else 'ambiguous' if mode==3 else 'unresolved')
    if mode in (0,1):
        self.assertEqual(result.resolutions[0].candidate.resource.document_ids,(1,))
    candidates = result.resolutions[0].alternatives
    self.assertTrue(candidates)
    self.assertTrue(any('numeric_relation:' in r for c in candidates for r in c.reason_codes))


def obligations(self, n):
    fields = FIELDS[n % 10]
    c = contract(fields,DOMAINS[n%10][1])
    if n >= 20:
        c.requested_fields = list(fields)*10
    bind_field_obligations(c)
    bind_field_obligations(c)
    cells = [p for p in c.requested_propositions if p.type=='requested_field']
    self.assertEqual({(p.applicable_entity,p.requested_field) for p in cells},
                     {(d,f) for d in (1,2) for f in fields})
    self.assertEqual(len(cells),4)
    self.assertEqual(c.explicit_document_ids(),[1,2])


def incomplete(self, n):
    c = contract(FIELDS[n%10], DOMAINS[n%10][1])
    c.resolved_entities = c.resolved_entities[:1] if n < 10 else []
    original = list(c.comparison_entities)
    bind_field_obligations(c)
    cells = [p for p in c.requested_propositions if p.type=='requested_field']
    self.assertEqual({(p.applicable_entity,p.requested_field) for p in cells},
                     {(1,f) for f in FIELDS[n%10]} if n<10 else set())
    self.assertEqual(c.comparison_entities,original)
    self.assertEqual(c.requested_fields,list(FIELDS[n%10]))
    self.assertTrue(all(p.applicable_entity is not None for p in cells))


def evidence(self, n):
    # Same chunk is allowed to support multiple obligations; a dependent body
    # must survive with its heading ahead of optional high-scoring detail.
    c=contract(('directions','results_timeframe'),DOMAINS[n%10][1])
    rows=[]
    for d in (1,2):
        a=item(d,d*100,'## What to expect\n\n2–5 months',['results_timeframe'],.01)
        b=item(d,d*100+1,'### Early comfort support\n\nGradual comfort may develop with consistent use. Individual experiences vary.', ['results_timeframe'],.01)
        bundle={'document_id':d,'field':'results_timeframe','primary_chunk_id':d*100,
                'chunk_ids':[d*100,d*100+1], 'quality':'numeric_section','reason':'requested_field_section'}
        a['evidence_bundles']=[bundle];b['evidence_bundles']=[bundle]
        rows += [a,b,item(d,d*100+2,VALUES['directions'],['directions'],.01)]
        rows += [item(d,d*100+10+i,'Overview: generic '+str(i),score=1) for i in range(5)]
        rows.append(item(d,d*100+20,'## How soon are results?\nResults vary over time.',['results_timeframe'],1))
    tr=ChatTrace(1,'phase36')
    selected=POLICY.select(annotate_candidates(c,rows),6,3,(1,2),tr.retrieval)
    expected={(d,d*100+i) for d in (1,2) for i in (0,1,2)}
    self.assertEqual({evidence_key(r) for r in selected},expected)
    self.assertLessEqual(len(selected),6)
    retained,context,_,_=rag._bounded_generation_context(selected,c.original_query,4000,'comparison',c,tr)
    self.assertIn('2–5 months',context)
    self.assertIn('Early comfort support',context)
    self.assertIn('Individual experiences vary',context)
    self.assertEqual({evidence_key(r) for r in retained},expected)
    self.assertLessEqual(len(context),4000)
    if n>=20:
        tight=POLICY.select(rows,2,1,(1,2),tr.retrieval)
        self.assertLessEqual(len(tight),2)
        # A group that cannot fit must not pretend its fragments are complete.
        self.assertFalse(any(r.get('evidence_bundles') for r in tight))


def quality(self,n):
    field='directions' if n<10 else 'results_timeframe'
    vague='## Directions\n\nUse as part of your routine.' if n<10 else '## How soon are results?\n\nResults vary over time.'
    useful='Take 1 unit 2–3 times daily with meals.' if n<10 else '## What to expect\n\n2–5 months'
    rows=[item(1,1,vague),item(1,2,useful),item(1,3,'### Early support\n\nComfort may develop with consistent use; individual results vary.')]
    actual=rag._select_complete_field_evidence([r['chunk'] for r in rows],field,rows[0]['document'])
    self.assertEqual(actual[0].id,2)
    self.assertLessEqual(len(actual),3)
    if n>=10:self.assertIn(3,[c.id for c in actual])


def adjacency(self,n):
    doc=item(1,1,'')['document']
    a=item(1,10,'## What to expect\n\n2–5 months')['chunk']
    b=item(1,11,'### Early support\n\nComfort may develop gradually and experiences vary.')['chunk']
    distract=item(1,12,'## Another section\n\nUnrelated obligations.')['chunk']
    if n>=10:b.chunk_index=50
    actual=rag._select_complete_field_evidence([a,b,distract],'results_timeframe',doc,max_chunks=2)
    self.assertLessEqual(len(actual),2)
    self.assertNotIn(12,[c.id for c in actual])
    self.assertEqual(11 in [c.id for c in actual],n<10)


URL_CASES=[
 ('https://fixture.test/items/cedar-oil',True),
 ('https://fixture.test/items/cedar_oil',True),
 ('https://fixture.test/items/cedar-oil/',True),
 ('https://FIXTURE.test/items/cedar-oil',True),
 ('https://fixture.test/items/cedar%2Doil',True),
 ('/items/cedar-oil',True),
 ('https://fixture.test/items/cedar-oil#directions',True),
 ('https://fixture.test/items/cedar-oil?size=large',False),
 ('https://fixture.test/items/cedar-oils',False),
 ('https://foreign.test/items/cedar-oil',False),
 ('https://fixture.test.evil/items/cedar-oil',False),
 ('https://fixture.test/items/birch-oil',False),
 ('http://fixture.test/items/cedar-oil',False),
 ('https://fixture.test/items/CEDAR-oil',False),
 ('https://fixture.test/items/cedar%2Foil',False),
 ('//foreign.test/items/cedar-oil',False),
 ('javascript:alert(1)',False),
 ('https://name:secret@fixture.test/items/cedar-oil',False),
 ('https://fixture.test:999/items/cedar-oil',False),
 ('https://fixture.test/items/../items/cedar-oil',False),
]


def links(self,n):
    rows=[item(1,1,'Directions: use daily.')]
    canonical='https://fixture.test/items/cedar-oil'
    rows[0]['document'].canonical_url=canonical
    rows[0]['document'].source_url=canonical
    if n<20:
        candidate,valid=URL_CASES[n]
        answer=f'Use daily. [Read more]({candidate})'
        actual=rag._validate_answer_links(answer,rows)
        self.assertIn('Use daily.',actual)
        self.assertEqual(canonical in actual,valid)
        if not valid:self.assertNotIn(candidate,actual)
    else:
        other=item(2,2,'Directions: use nightly.')
        other['document'].canonical_url=canonical.replace('-oil','_oil')
        # Exact canonical identities take precedence, but slash-normalized
        # ambiguous variants are never assigned to the highest-ranked page.
        actual=rag._validate_answer_links('[Read]('+canonical+'/)',rows+[other])
        self.assertNotIn('https://',actual)


class Development(ResourceFixture): pass
class HeldOut(ResourceFixture): pass

for category,count,fn in [('numeric',40,numeric),('obligation',30,obligations),
        ('reservation',30,evidence),('quality',20,quality),('adjacency',20,adjacency),
        ('urls',30,links),('incomplete',20,incomplete)]:
    for n in range(count):
        target=HeldOut if n%10 in (7,8,9) else Development
        def case(self,n=n,fn=fn):fn(self,n)
        setattr(target,f'test_{category}_{n:03}',case)

del target, case  # Do not expose a duplicate TestCase alias to unittest discovery.

if __name__=='__main__':unittest.main()
