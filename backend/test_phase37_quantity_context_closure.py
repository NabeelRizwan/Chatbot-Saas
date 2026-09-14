"""205 generic quantity/cost and catalog handoff regressions.

Real SQLite lifecycle predicates and runtime selection/reviewer/context code.
Only embedding/channel transport and reviewer LLM responses are deterministic.
"""
import copy
import json
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

from services import rag_service as rag, rag_planning as planning
from services.query_contract import QueryContract, extract_requested_fields, normalize_requested_fields
from services.observability_service import ChatTrace, evidence_key
from test_required_evidence_retention import fixture_database
from test_phase_l3_multi_entity_conversational_rag import document, chunk
from test_resource_discovery import ResourceFixture
import test_phase37_manual_regressions as previous

PRICES = [
    'How much does it cost?', 'How much is one bottle?', 'How much would I pay?',
    'How much is the monthly plan?', 'How much for a subscription?',
    'How much would three bottles cost?', 'How much is one container?',
    'How much is the course?', 'How much do you charge?', 'How much is one tub?',
    'How much is the annual service?', 'How much to buy the equipment?',
    'How much does the room cost?', 'How much is a packet?', 'How much for one-time purchase?',
    'How much does the detergent cost?', 'How much is the monthly subscription?',
    'How much does it cost to use the software?', 'How much is it?', 'How much per bottle?',
]
QUANTITIES = [
    'How much should I take?', 'How much would I use?', 'How much should I add?',
    'How much per serving?', 'How much detergent should I use?',
    'How much powder do I use?', 'How much should we mix?', 'How much should I apply?',
    'How much seasoning should I add?', 'How much oil should I use?',
    'How much paint should I apply?', 'How much flour do I add?',
    'How much gel should I use?', 'How much lubricant should I apply?',
    'How much fuel should I add?', 'How much salt per serving?',
    'How much syrup do I mix?', 'How much food should I use?',
    'How much solution should I prepare?', 'How much concentrate should I dilute?',
    'How much API quota should I allocate?', 'How much memory should I allocate?',
    'How much storage can I allocate?', 'How much capacity should I reserve?',
    'How much bandwidth should I allocate?', 'How much powder should I mix into 12 oz water?',
    'How much of the packet should I use?', 'How much of a dose should I take?',
    'How much should I use monthly?', 'How much should I add each day?',
]
LIQUIDS = [
    'How much water?', 'How much liquid?', 'How much water should I use?',
    'How much liquid do I mix?', 'How much water should I add?',
    'How much liquid would I need?', 'How much milk should I use?',
    'How much juice do I add?', 'How much water per serving?', 'How much liquid per packet?',
    'How much water for one dose?', 'How much fluid should I use?',
    'How much should I dilute with water?', 'How much water for mixing?',
    'How much liquid is needed?', 'How much water is required?',
    'How much water should we mix?', 'How much liquid should they add?',
    'How much water do I need for preparation?', 'How much liquid for two scoops?',
]
MIXED = [
    'How much powder do I use, and how much does one container cost?',
    'How much water should I add and what is the price?',
    'How much does the Pro plan cost and how many seats do I get?',
    'How much API quota should I allocate, and how much would I pay?',
    'How much powder do I use and how much is one tub?',
    'How much does the detergent cost, and how much should I use?',
    'How much liquid would I need and how much is one bottle?',
    'How much memory should I allocate and how much does the monthly plan cost?',
    'How much seasoning per serving, and what is its one-time price?',
    'How much water for a packet, and how much is that packet?',
    'How much should I take? What is the subscription price?',
    'How much does it cost? How much should I add?',
    'How much paint should I use, and what is the price per can?',
    'How much storage should I allocate and how much would I pay?',
    'How much fluid should I use, and what is the purchase price?',
    'How much lubricant should I apply, and how much is a bottle?',
    'How much fuel should I add and what does the equipment cost?',
    'How much concentrate should I dilute and how much does it cost?',
    'How much liquid per serving, and what is the bundle price?',
    'How much food should I use, and how much would three containers cost?',
]
DOMAINS = ['detergent','plan','course','food','software','service',
           'health leaflet','location','equipment','custom resource']


class Fields(unittest.TestCase):
    def test_bare_how_many_is_not_a_price_question(self):
        for question in ('How many are available?', 'How many should I buy?', 'How many are there?'):
            with self.subTest(question=question):
                self.assertNotIn('price',extract_requested_fields(question))

    def test_planner_price_cannot_reintroduce_quantity_confusion(self):
        self.assertEqual(normalize_requested_fields(['price','directions'],
            message='How much liquid would I need?'),['directions'])

    def test_normalization_preserves_actual_commercial_clause(self):
        self.assertEqual(normalize_requested_fields(['price','directions'],
            message='How much liquid would I need, and how much does it cost?'),['price','directions'])

    def test_ordinary_price_label_is_not_deleted(self):
        self.assertEqual(normalize_requested_fields(['price'],message='What is the price?'),['price'])

def price(self,n): self.assertIn('price',extract_requested_fields(PRICES[n]))

def quantity(self,n):
    actual=extract_requested_fields(QUANTITIES[n])
    self.assertNotIn('price',actual)
    self.assertIn('specifications' if 20<=n<25 else 'directions',actual)

def liquid(self,n):
    actual=extract_requested_fields(LIQUIDS[n])
    self.assertIn('directions',actual)
    self.assertNotIn('price',actual)

def mixed(self,n):
    actual=extract_requested_fields(MIXED[n])
    self.assertIn('price',actual)
    self.assertIn('specifications' if n in (2,3,7,13) else 'directions',actual)
    self.assertEqual(len(actual),len(set(actual)))


def field_pipeline(n,fields):
    """No injected required marker: it must originate in actual retrieval."""
    docs=[document(i,f'{color} {DOMAINS[n%10]}',metadata={'price':str(20+n+i),'currency':'USD'})
          for i,color in ((1,'Cedar'),(2,'Birch'),(3,'Cobalt'))]
    pairs=[]
    for d in docs:
        texts=[f'Price: {chr(36)}{20+n+d.id}. One-time purchase.',
               f'Directions: Mix {n+d.id+1} units in {8+d.id} oz water. Use daily.',
               f'Ingredients: substance {d.id}, compound {n+1}.',
               'Overview: optional catalog narrative. '*12]
        for index,text in enumerate(texts):
            ch=chunk(d.id*100+index,index,text);ch.document_id=d.id;pairs.append((ch,d))
    question='Which options do you offer? Tell me their '+', '.join(fields)+'.'
    c=QueryContract(question,question,question,'catalog_list','catalog',requested_fields=list(fields))
    tr=ChatTrace(1,'catalog-reservation')
    with fixture_database(docs,pairs) as db, \
         patch.object(rag,'get_knowledge_scope',return_value={'exists':True,'organization_id':1}), \
         patch.object(rag,'resolve_active_embedding_profile',return_value=NS(provider='fixture',model='fixture',version=1,dimensions=1)), \
         patch.object(rag,'generate_embedding',return_value=[0.0]), \
         patch.object(rag,'_vector_candidate_ids',return_value=[(ch.id,d.id,.01 if ch.chunk_index==0 else .2) for ch,d in pairs]), \
         patch.object(rag,'_lexical_candidate_ids',return_value=[(ch.id,d.id) for ch,d in pairs]):
        rows=rag.retrieve_relevant_chunks(db,1,question,mode='catalog',query_contract=c,trace=tr)
    def approved(_bot,payload,**kwargs):
        return json.dumps({'ranked_candidates':list(range(len(json.loads(payload)['candidates'])))})
    with patch.object(planning,'generate_auxiliary',side_effect=approved), \
         patch('services.llm_router.get_last_auxiliary_metadata',return_value={}):
        rows=planning.review_evidence(NS(id=1,organization_id=1,provider='gemini'),c,rows,tr)
    return docs,rows,c,tr


class Admission(unittest.TestCase):
    def test_reviewer_reject_all_still_prevents_context(self):
        _,rows,c,tr=field_pipeline(1,['directions'])
        with patch.object(planning,'generate_auxiliary',return_value='{"ranked_candidates":[],"reject_all":true}'), \
             patch('services.llm_router.get_last_auxiliary_metadata',return_value={}):
            result=planning.review_evidence(NS(id=1,organization_id=1,provider='gemini'),c,rows,tr)
        self.assertEqual(result,[])

    def test_fieldless_catalog_still_uses_one_optional_item_per_document(self):
        from services.conversational_engine import compress_and_rerank_chunks
        from test_phase35_live_repair import item
        rows=[item(d,d*10+i,f'Catalog overview option {d}, optional detail {i}.',score=.9-i*.1)
              for d in (1,2,3) for i in (0,1,2)]
        c=QueryContract('List options','List options','List options','catalog_list','catalog')
        retained,context=compress_and_rerank_chunks(rows,c.original_query,2000,'catalog',c)
        self.assertEqual(len(retained),3)
        self.assertEqual({r['document'].id for r in retained},{1,2,3})

    def test_reservations_do_not_disable_optional_catalog_depth(self):
        from services.conversational_engine import compress_and_rerank_chunks
        from test_phase35_live_repair import item
        rows=[item(d,d*10,'Directions: use 3 units daily.',['directions']) for d in (1,2,3)]
        rows += [item(d,d*10+i,f'Catalog overview option {d}, optional detail {i}.',score=.9-i*.1)
                 for d in (1,2,3) for i in (1,2,3)]
        c=QueryContract('List options and directions','list','list','catalog_list','catalog',
                        requested_fields=['directions'])
        retained,context=compress_and_rerank_chunks(rows,c.original_query,6000,'catalog',c)
        self.assertEqual(sum(bool(r.get('required_fields')) for r in retained),3)
        for d in (1,2,3):
            self.assertLessEqual(sum(r['document'].id==d and not r.get('required_fields') for r in retained),1)

def admission(self,n,fields):
    docs,rows,c,tr=field_pipeline(n,fields)
    before=[(evidence_key(r),copy.deepcopy(r.get('required_fields')),copy.deepcopy(r.get('evidence_bundles'))) for r in rows]
    for d in docs:
        for f in fields:
            required=[r for r in rows if r['document'].id==d.id and f in r.get('required_fields',())]
            self.assertTrue(required,(d.id,f))
            if f!='price':
                self.assertTrue(any(any(b['field']==f and b['document_id']==d.id for b in r.get('evidence_bundles',())) for r in required))
    retained,context,_,_=rag._bounded_generation_context(rows,c.original_query,3500,'catalog',c,tr)
    self.assertLessEqual(len(context),3500)
    for d in docs:
        if 'directions' in fields:self.assertIn(f'Mix {n+d.id+1} units in {8+d.id} oz water',context)
        if 'price' in fields:self.assertIn(f'{chr(36)}{20+n+d.id}',context)
        if 'ingredients' in fields:self.assertIn(f'substance {d.id}, compound {n+1}',context)
    self.assertEqual(before,[(evidence_key(r),r.get('required_fields'),r.get('evidence_bundles')) for r in rows])
    self.assertNotIn('Unavailable after',context)
    self.assertNotIn('No concrete value',context)

def directions(self,n): admission(self,n,['directions'])
def prices(self,n): admission(self,n,['price'])
def multiple(self,n): admission(self,n,['directions','price'] if n<10 else ['directions','ingredients'])
def optional(self,n):
    docs,rows,c,tr=field_pipeline(n,['directions'])
    optional_rows=[]
    for d in docs:
        ch=chunk(800+d.id,90,'Price: $9999. Optional metadata without requested instructions.')
        optional_rows.append(dict(chunk=ch,document=d,score=10,evidence_priority=.99))
    retained,context,_,_=rag._bounded_generation_context(optional_rows+rows,c.original_query,2300,'catalog',c,tr)
    self.assertLessEqual(len(context),2300)
    for d in docs:self.assertIn(f'Mix {n+d.id+1} units in {8+d.id} oz water',context)


class Discovery(ResourceFixture):
    turn=previous.RuntimeCases.turn
    setup_names=previous.RuntimeCases.setup_names
    assert_provenance=previous.RuntimeCases.assert_provenance
    previous=previous.RuntimeCases.previous


class OptionalPriceAnnotations(unittest.TestCase):
    def check_catalog(self,n,requested):
        from test_phase35_live_repair import item
        rows=[]
        for d in (1,2,3):
            raw=(f'One-time purchase: {chr(36)}{40+n+d}. Subscription price: {chr(36)}{30+n+d}.\n\n'
                 f'Product description\n\nDirections: Mix {n+d+1} units with 10 oz water. '
                 'This preparation also works with a hot beverage.\n\n'
                 'Use daily following the supplied preparation instructions.')
            r=item(d,d*100,raw,requested)
            r['document'].title=f'{DOMAINS[n%10]} variant {d}'
            rows.append(r)
        q='Which options can I prepare with a hot beverage? Give directions.'
        c=QueryContract(q,q,q,'catalog_list','catalog',requested_fields=requested)
        tr=ChatTrace(1,'optional-price')
        expected=rag.collect_price_facts(rows,c)
        retained,context,facts,_=rag._bounded_generation_context(rows,q,2500,'catalog',c,tr)
        self.assertEqual({(f.entity_document_id,f.price_type,f.value) for f in facts},
                         {(f.entity_document_id,f.price_type,f.value) for f in expected})
        self.assertTrue(tr.retrieval.monetary_evidence)
        self.assertLessEqual(len(context),2500)
        if 'price' not in requested:
            self.assertNotIn('## Typed prices',context)
            for d in (1,2,3):
                self.assertIn(f'Mix {n+d+1} units with 10 oz water',context)
                self.assertIn('works with a hot beverage',context)
        else:
            self.assertIn('## Typed prices',context)
            self.assertIn('subscription',context)
            self.assertIn('one_time',context)

for _n in range(10):
    def _quantity_annotation(self,n=_n): self.check_catalog(n,['directions'])
    setattr(OptionalPriceAnnotations,f'test_optional_prices_{_n:02d}',_quantity_annotation)
for _n in range(5):
    def _mixed_annotation(self,n=_n): self.check_catalog(n,['directions','price'])
    setattr(OptionalPriceAnnotations,f'test_explicit_prices_{_n:02d}',_mixed_annotation)

def ambiguous(self,n):
    noun,kind=previous.DOMAINS[n%10]
    self.add(1,f'Cedar Meridian {noun} (Standard)',kind=kind)
    self.add(2,f'Cedar Meridian Extended {noun}',kind=kind)
    self.project(1,2)
    c=self.turn(f'For Cedar Meridian {noun}, how much should I use?')
    self.assertTrue(c.requires_clarification)
    self.assertIsNone(c.permitted_document_ids)
    self.assertIn('directions',c.requested_fields)
    self.assertNotIn('price',c.requested_fields)

def discovery(self,n):
    names=self.setup_names(n);history,state=self.previous(names)
    q=f'I need {previous.CAPABILITIES[n%10]}. How much would I use, and how much liquid would I need?'
    c=self.turn(q,history,state)
    self.assertFalse(c.execution.scope_decision.exact_narrowing_applied)
    self.assertIsNone(c.permitted_document_ids)
    self.assertIn('directions',c.requested_fields)
    self.assertNotIn('price',c.requested_fields)
    self.assertNotIn(names[0],c.retrieval_query)
    self.assert_provenance(c,q)

CATEGORIES=[
 ('A_price',20,price,Fields),('B_quantity',30,quantity,Fields),
 ('C_liquid',20,liquid,Fields),('D_mixed',20,mixed,Fields),
 ('E_directions_admission',25,directions,Admission),('F_price_admission',15,prices,Admission),
 ('G_multiple_fields',20,multiple,Admission),('H_optional_metadata',20,optional,Admission),
 ('I_ambiguous_quantity',15,ambiguous,Discovery),('J_discovery_directions',20,discovery,Discovery),
]
for group,count,fn,cls in CATEGORIES:
    for n in range(count):
        def case(self,n=n,fn=fn): fn(self,n)
        setattr(cls,f'test_{group}_{n:02d}',case)
del cls,case

if __name__=='__main__': unittest.main()
