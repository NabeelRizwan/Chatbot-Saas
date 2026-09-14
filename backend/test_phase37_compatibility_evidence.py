"""220 generic usage-capability/required-context cases, plus boundary checks.

Transport and LLM responses are deterministic. Integration cases exercise real
SQLite scope predicates, field selection, reviewer handling and context admission.
"""
import copy
import json
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

from services import rag_service as rag, rag_planning as planning
from services.query_contract import QueryContract, extract_requested_fields
from services.conversational_engine import _required_field_parts
from services.observability_service import ChatTrace
from test_phase_l3_multi_entity_conversational_rag import document, chunk
from test_required_evidence_retention import fixture_database

DOMAINS = [
    ('Food additive','broth'), ('Surface cleaner','glass'), ('Workspace connector','mobile app'),
    ('Charging adapter','USB-C laptops'), ('Study toolkit','offline lessons'),
    ('Support service','video meetings'), ('Laboratory tool','cold liquids'),
    ('Care leaflet','assistive readers'), ('Studio space','indoor activities'),
    ('Custom module','sealed enclosures'),
]
RELATIONS = [
    'mixes easily into {target}', 'can be mixed into {target}', 'mixes into {target}',
    'can be added to {target}', 'works with {target}', 'is compatible with {target}',
    'can be used with {target}', 'can be taken with {target}', 'can be applied to {target}',
    'is suitable for {target}', 'may be used in {target}', 'can be stirred into {target}',
    'blends into {target}', 'dissolves in {target}', 'pairs with {target}',
    'may be added to {target}', 'can be connected to {target}', 'is used in {target}',
    'is mixed with {target}', 'is blended into {target}', 'is dissolved in {target}',
    'can be paired with {target}', 'may be applied to {target}', 'is suitable for {target}',
    'stirs easily into {target}', 'works with hot or cold {target}', 'can be used on {target}',
    'is compatible with the {target}', 'can be added directly to {target}',
    'mixes smoothly into {target}',
]
FALSE = [
    'This works really well.', 'Use the best option.', 'The team uses it often.',
    'The color mix looks attractive.', 'Our mix won an award.', 'Works by a local artist.',
    'The team works tirelessly.', 'The use of color is interesting.', 'A clever use of space.',
    'Users report excellent quality.', 'The mixture is popular.', 'Used equipment is available.',
    'Suitable candidates will be contacted.', 'Compatibility matters to everyone.',
    'This works with.', 'This is compatible with.', 'It can be added.',
    'The team works with enthusiasm.', 'This mixes easily.', 'Use with care.',
]
ACTIONS = [
    'Take 2 capsules daily.', 'Mix 2 scoops with 8 oz liquid.', 'Add one packet to water.',
    'Apply twice daily.', 'Connect cable to port.', 'Use 3 units each morning.',
    'Dilute 2 ml before application.', 'Install 1 module before connecting.',
    'Submit 1 form before arrival.', 'Read 2 sections each session.',
    'Take 1 tablet with a meal.', 'Mix 3 parts into 12 oz liquid.',
    'Apply 1 layer before drying.', 'Connect 2 accounts before syncing.',
    'Use 4 ml for each cycle.', 'Add 2 packets per batch.', 'Stir 1 portion thoroughly.',
    'Blend 2 portions each time.', 'Pair 1 receiver before use.', 'Set up 1 room before arrival.',
]


def make_rows(n, count=2, field='directions', relation=None, noisy=False):
    noun,target=DOMAINS[n%10]
    rows=[]
    for d in range(1,count+1):
        doc=document(d,f'{noun} {chr(64+d)}')
        cap=f'This option {(relation or RELATIONS[n%len(RELATIONS)]).format(target=target)}.'
        action=f'Mix {d+n+1} units with {8+d} oz liquid.'
        raw=f'[resource.txt]\n\nProduct description\n\n{cap}\n\nHow to use\n\n{action}'
        if noisy: raw += '\n\nCaution: Use only as directed. ' + 'Additional cautionary detail. '*20
        ch=chunk(d*100,0,raw);ch.document_id=d
        rows.append(dict(chunk=ch,document=doc,score=1/d,required_fields=[field],
            evidence_bundles=[dict(field=field,primary_chunk_id=ch.id,chunk_ids=[ch.id])],
            field_coverage={field:'SUPPORTED'}))
    q=f'I need something I can use with {target}. How much would I use, and how much liquid do I need?'
    c=QueryContract(q,q,q,'catalog_list','catalog',requested_fields=[field])
    return rows,c


def assemble(rows,c,budget=2000):
    tr=ChatTrace(1,'compatibility')
    result,text,_,_=rag._bounded_generation_context(rows,c.original_query,budget,c.mode,c,tr)
    return result,text,tr


class Compatibility(unittest.TestCase):
    def test_no_unrelated_compatibility_target_is_reserved(self):
        rows,c=make_rows(0,count=1,relation='works with another destination')
        _,text,_=assemble(rows,c)
        self.assertNotIn('another destination',text)
        self.assertIn('Mix 2 units',text)

    def test_negative_compatibility_keeps_its_qualification(self):
        rows,c=make_rows(0,count=1,relation='cannot be used with {target}')
        _,text,_=assemble(rows,c)
        self.assertIn('cannot be used with broth',text)

    def test_whole_bundle_or_no_fact_under_impossible_budget(self):
        rows,c=make_rows(0)
        result,text,_=assemble(rows,c,100)
        self.assertEqual(result,[])
        self.assertLessEqual(len(text),100)

    def test_existing_nonusage_field_does_not_gain_compatibility(self):
        rows,c=make_rows(0,count=1)
        parts=_required_field_parts(rows,'ingredients')
        self.assertFalse(any('broth' in p for p in parts))


def prescriptive(self,n):
    rows,c=make_rows(n,1)
    rows[0]['chunk'].content='How to use\n\n'+ACTIONS[n]
    _,text,_=assemble(rows,c)
    self.assertIn(ACTIONS[n],text)


def compatibility(self,n):
    rows,c=make_rows(n,1)
    cap='This option '+RELATIONS[n].format(target=DOMAINS[n%10][1])+'.'
    rows[0]['chunk'].content='Product description\n\n'+cap
    _,text,_=assemble(rows,c)
    self.assertIn(cap,text)


def both(self,n):
    rows,c=make_rows(n,1)
    before=copy.deepcopy(rows[0]['chunk'].content)
    _,text,_=assemble(rows,c)
    self.assertIn(f'Mix {n+2} units with 9 oz liquid.',text)
    self.assertIn(RELATIONS[n%30].format(target=DOMAINS[n%10][1]),text)
    self.assertEqual(before,rows[0]['chunk'].content)


def false_positive(self,n):
    rows,c=make_rows(n,1)
    rows[0]['chunk'].content='Product description\n\n'+FALSE[n]
    _,text,_=assemble(rows,c)
    self.assertNotIn(FALSE[n],text)


def variants(self,n):
    rows,c=make_rows(n,2)
    result,text,_=assemble(rows,c)
    self.assertEqual({r['document'].id for r in result},{1,2})
    for d in (1,2):
        self.assertIn(rows[d-1]['document'].title,text)
        self.assertIn(f'Mix {d+n+1} units with {8+d} oz liquid.',text)
    self.assertEqual(text.count(RELATIONS[n%30].format(target=DOMAINS[n%10][1])),2)


def different_amounts(self,n):
    rows,c=make_rows(n,2)
    _,text,_=assemble(rows,c)
    for d in (1,2):
        section=text.split('### Source: '+rows[d-1]['document'].title)[1].split('### Source:')[0]
        self.assertIn(f'Mix {d+n+1} units with {8+d} oz liquid.',section)
        self.assertIn(RELATIONS[n%30].format(target=DOMAINS[n%10][1]),section)
        self.assertNotIn(f'Mix {n+(3-d)+1} units',section)


def runtime_pipeline(self,n):
    raw,c=make_rows(n,2)
    docs=[r['document'] for r in raw]
    pairs=[(r['chunk'],r['document']) for r in raw]
    tr=ChatTrace(1,'compatibility-pipeline')
    with fixture_database(docs,pairs) as db, \
         patch.object(rag,'get_knowledge_scope',return_value={'exists':True,'organization_id':1}), \
         patch.object(rag,'resolve_active_embedding_profile',return_value=NS(provider='fixture',model='fixture',version=1,dimensions=1)), \
         patch.object(rag,'generate_embedding',return_value=[0.0]), \
         patch.object(rag,'_vector_candidate_ids',return_value=[(ch.id,d.id,.1) for ch,d in pairs]), \
         patch.object(rag,'_lexical_candidate_ids',return_value=[(ch.id,d.id) for ch,d in pairs]):
        rows=rag.retrieve_relevant_chunks(db,1,c.original_query,mode='catalog',query_contract=c,trace=tr)
    def approved(_bot,payload,**kw):
        return json.dumps({'ranked_candidates':list(range(len(json.loads(payload)['candidates'])))})
    with patch.object(planning,'generate_auxiliary',side_effect=approved), \
         patch('services.llm_router.get_last_auxiliary_metadata',return_value={}):
        rows=planning.review_evidence(NS(id=1,organization_id=1,provider='gemini'),c,rows,tr)
    self.assertTrue(all('directions' in r.get('required_fields',[]) for r in rows))
    result,text,_=assemble(rows,c)
    self.assertEqual({r['document'].id for r in result},{1,2})
    for d in (1,2):
        self.assertIn(f'Mix {d+n+1} units',text)
    self.assertEqual(text.count(RELATIONS[n%30].format(target=DOMAINS[n%10][1])),2)


def condensation(self,n):
    rows,c=make_rows(n,1)
    result,text,_=assemble(rows,c)
    self.assertTrue(result)
    supplied=result[0].get('context_field_evidence',{}).get('directions',[])
    self.assertTrue(any(DOMAINS[n%10][1] in p for p in supplied))
    self.assertIn(f'Mix {n+2} units',text)


def budget(self,n):
    rows,c=make_rows(n,2,noisy=True)
    result,text,_=assemble(rows,c,1000)
    self.assertLessEqual(len(text),1000)
    for d in (1,2):
        self.assertIn(f'Mix {d+n+1} units with {8+d} oz liquid.',text)
        self.assertIn(rows[d-1]['document'].title,text)
    self.assertEqual(text.count(RELATIONS[n%30].format(target=DOMAINS[n%10][1])),2)


def other_domains(self,n):
    noun,target=DOMAINS[n%10]
    q=f'Can the {noun} be used with {target}?'
    self.assertTrue(set(extract_requested_fields(q)) & {'directions','specifications'})
    self.assertNotIn('price',extract_requested_fields(q))
    rows,c=make_rows(n,1,field='specifications')
    _,text,_=assemble(rows,c)
    self.assertIn(RELATIONS[n%30].format(target=target),text)


CATEGORIES=[
 ('A_prescriptive',20,prescriptive),('B_compatibility',30,compatibility),
 ('C_action_and_compatibility',30,both),('D_false_positive',20,false_positive),
 ('E_multiple_variants',20,variants),('F_different_amounts',20,different_amounts),
 ('G_discovery_pipeline',20,runtime_pipeline),('H_field_condensation',20,condensation),
 ('I_budget',20,budget),('J_other_domains',20,other_domains),
]
for group,count,fn in CATEGORIES:
    for n in range(count):
        def case(self,n=n,fn=fn): fn(self,n)
        setattr(Compatibility,f'test_{group}_{n:02d}',case)
del case

if __name__=='__main__': unittest.main()
