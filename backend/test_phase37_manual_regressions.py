"""Phase 3.7 general manual regressions: real contract/discovery/context path.

290 separately discoverable cases across ten synthetic domains; no provider or
application database access. SQL FTS/trigram use the established SQLite fixture.
No historical customer names or document/chunk IDs appear in this file.
"""
from unittest.mock import patch
import unittest

from services import rag_planning, rag_service as rag
from services.query_contract import extract_requested_fields, field_evidence_pattern
from services.semantic_scope import comparison_mentions
from services.resource_scope_adapter import apply_resource_discovery
from services.observability_service import ChatTrace, evidence_key
from services.retrieval_selection import POLICY
from test_resource_discovery import ResourceFixture
from test_phase35_live_repair import contract, item


DOMAINS = [('Package','plan'), ('Workshop','course'), ('Lodge','location'),
           ('Adapter','device'), ('Policy','policy'), ('Permit','form'),
           ('Suite','software'), ('Service','service'), ('Room','room'), ('Blend','product')]


class RuntimeCases(ResourceFixture):
    def setup_names(self, n):
        noun, kind = DOMAINS[n % len(DOMAINS)]
        names = [f'{color} Meridian {noun}' for color in ('Cedar','Birch','Cobalt')]
        for i, name in enumerate(names, 1):
            self.add(i, name, kind=kind, aliases=[f'{name.split()[0]} {noun}'])
        self.project(1,2,3)
        return names

    def turn(self, query, history=(), state=None, plan=None):
        with patch.object(rag_planning, 'plan_query', return_value=plan), patch.dict(
                'os.environ', {'RAG_RESOURCE_DISCOVERY':'off'}):
            c = rag_planning.prepare_query(self.db, self.bot, query, list(history), state or {},
                                           rag._build_turn_query_contract, hard_scope=self.hard)
        return apply_resource_discovery(self.db,c,state or {},service=self.service)

    def previous(self, names):
        q=f'Compare {names[0]} and {names[1]} on price and directions.'
        c=self.turn(q)
        return [{'role':'user','content':q}, {'role':'assistant','content':f'{names[0]} and {names[1]} have different routines.'}], rag_planning.next_state(c,{})

    def assert_provenance(self, c, question):
        from services.resource_normalization import normalize_resource_text
        current=normalize_resource_text(question)
        for resolution in c.execution.resource_discovery.get('resolutions',[]):
            if resolution['provenance'] in {'explicit_user','explicit_current_user'}:
                self.assertIn(resolution['probe'], current)


def current_entity(self,n):
    names=self.setup_names(n); history,state=self.previous(names)
    name=names[2]
    q=(f'For {name}, when should I renew them?',
       f'How do I use {name}? Are they available online?',
       f'Tell me about {name}. What are their directions?')[n//10]
    c=self.turn(q,history,state)
    self.assertEqual(c.permitted_document_ids,[3])
    self.assertEqual([e.document_id for e in c.resolved_entities],[3])
    self.assertFalse(c.execution.soft_scope.comparison_requested)
    self.assert_provenance(c,q)


def pronouns(self,n):
    names=self.setup_names(n); history,state=self.previous(names)
    if n<10:
        q=f'For {names[0]}, how should I use them and what are their limits?'
        expected={1}
    else:
        q='What about them? What are their directions?'
        expected={1,2}
    c=self.turn(q,history,state)
    self.assertEqual(set(c.permitted_document_ids or ()),expected)
    self.assert_provenance(c,q)
    if n>=10:
        self.assertTrue(all(r['provenance'] in {'conversation_state','history_comparison'}
                            for r in c.execution.resource_discovery['resolutions']))


def alternation(self,n):
    noun,_=DOMAINS[n%10]; names=[f'Cedar Meridian {noun}',f'Birch Meridian {noun}']
    variants=[(f'For {names[0]}, does it include phone or email support?',()),
              (f'Would {names[0]} or {names[1]} work better?',tuple(x.lower() for x in names)),
              (f'For {names[0]}, is monthly or yearly billing offered?',())]
    q,expected=variants[n//10]
    self.assertEqual(comparison_mentions(q,names),expected)


def colon(self,n):
    noun,_=DOMAINS[n%10]; names=[f'Cedar Meridian {noun}',f'Birch Meridian {noun}']
    prefix='Which is easier' if n<10 else 'Which of these two is better for a busy routine'
    self.assertEqual(comparison_mentions(f'{prefix}: {names[0]} or {names[1]}?',names),
                     tuple(x.lower() for x in names))


CAPABILITIES=['a plan with SSO','a course I can finish on weekends','a location open late',
              'something that connects two displays','a policy that covers international travel',
              'a form I can submit online','a package that runs offline','a service with weekend support',
              'a room with a kitchenette','something I can mix into a beverage']


def discovery(self,n):
    names=self.setup_names(n); history,state=self.previous(names)
    # The current goal must win even if the question later uses a pronoun.
    q=f"I {'need' if n<10 else 'want'} {CAPABILITIES[n%10]}. Which option makes sense, and how would I use it?"
    c=self.turn(q,history,state)
    self.assertIsNone(c.permitted_document_ids)
    self.assertFalse(c.execution.scope_decision.exact_narrowing_applied)
    self.assertFalse(c.execution.soft_scope.comparison_requested)
    self.assertFalse(c.resolved_entities)
    self.assertNotIn(names[0],c.retrieval_query)
    self.assertNotIn(names[1],c.retrieval_query)
    self.assert_provenance(c,q)


SYNONYMS=['daily capsule schedule','daily serving schedule','daily dosage schedule',
          'daily use','dosage schedule','serving instructions','how many capsules',
          'how often to take','when to take','with meals']


def fields(self,n):
    phrase=SYNONYMS[n%10]
    q=(f'What is the {phrase}?', f'Compare Cedar and Birch on {phrase} and price.',
       f'For Cobalt, tell me the {phrase} and whether to use it after meals.')[n//10]
    actual=extract_requested_fields(q)
    self.assertIn('directions',actual)
    self.assertNotIn(phrase,actual)
    if n//10==1:self.assertIn('price',actual)
    self.assertEqual(len(actual),len(set(actual)))


def clock(self,n):
    q=['What exact time at night should I take it?', 'At what clock time should I use this?',
       'What specific time of day should I take it?'][n%3]
    if n>=5:q='What is the daily serving schedule? '+q
    actual=extract_requested_fields(q)
    self.assertIn('clock_time',actual)
    if n>=5:self.assertIn('directions',actual)
    p=field_evidence_pattern('clock_time')
    self.assertFalse(p.search('Take 3 units daily, preferably with a meal.'))
    self.assertTrue(p.search('Use at 8:30 pm each evening.'))


def bundle_rows(n, independent):
    doc=1+n%2
    a=item(doc,10,'## What to expect\n\n2–5 months',['results_timeframe'],.9)
    b=item(doc,11,'### Early support\n\nSteady improvement may develop with consistent use.', ['results_timeframe'],.8)
    c=item(doc,12,'## Later stage\n\nAdditional gradual improvement may follow.', ['results_timeframe'],.1)
    rows=[a,b,c]
    if independent:
        rows.append(item(doc,13,f'### When might changes appear?\n\nMost users report gradual changes within {3+n%4}–{7+n%4} weeks with consistent use. Individual results vary.', ['results_timeframe'],1.0))
    bundle={'document_id':doc,'field':'results_timeframe','primary_chunk_id':10,
            'chunk_ids':[evidence_key(x)[1] for x in rows], 'quality':'numeric_section','reason':'requested_field_section'}
    for row in rows:row['evidence_bundles']=[dict(bundle)]
    return rows


def independent(self,n):
    rows=bundle_rows(n,True)
    if n>=10:rows=rows[:2]+rows[3:]  # Optional later section unavailable.
    trace=ChatTrace(1,'independent')
    chosen=POLICY.select(rows,1,1,trace=trace.retrieval)
    self.assertEqual([r['chunk'].id for r in chosen],[13])
    self.assertIn('weeks',chosen[0]['chunk'].content)
    self.assertNotIn('### Early support',chosen[0]['chunk'].content)
    self.assertEqual(rows[0]['evidence_bundles'][0]['chunk_ids'],[10,11,12,13])


def atomic(self,n):
    rows=bundle_rows(n,False)
    if n>=10:rows=rows[:1]+rows[2:]
    chosen=POLICY.select(rows,1,1)
    self.assertEqual(chosen,[])
    if n<10:
        self.assertEqual({r['chunk'].id for r in POLICY.select(rows,3,3)},{10,11,12})


def prompt_contract(self,n):
    c=contract(('directions','price'))
    label=SYNONYMS[n%10]
    c.requested_fields=['directions',label,'price']
    rows=[item(d,d*100,'Directions: use 3 units daily with a meal.', ['directions']) for d in (1,2)]
    for row in rows:row['field_coverage']={'directions':'SUPPORTED',label:'ABSENT_AFTER_ADEQUATE_SEARCH','price':'ABSENT_AFTER_ADEQUATE_SEARCH'}
    tr=ChatTrace(1,'prompt')
    retained,context,_,_=rag._bounded_generation_context(rows,c.original_query,4000,'comparison',c,tr)
    prompt=rag.build_rag_prompt(c.original_query,retained,compressed_context=context,query_contract=c)
    self.assertIn('3 units daily',prompt)
    self.assertNotIn(label+': Unavailable',prompt)
    self.assertNotIn(label+': No concrete',prompt)
    self.assertNotIn(label,c.requested_fields)
    self.assertIn('price',prompt)  # Genuine missing fields must remain expressible.
    if n>=10:
        self.assertIn('Unavailable after the field search',prompt)


def variants(self,n):
    noun,kind=DOMAINS[n%10]
    self.add(1,f'Cedar Meridian {noun} (Standard)',kind=kind)
    self.add(2,f'Cedar Meridian Extended {noun}',kind=kind)
    self.project(1,2)
    if n<10:
        q=f'For Cedar Meridian {noun}, what are the directions?'
        c=self.turn(q)
        self.assertIsNone(c.permitted_document_ids)
        self.assertTrue(c.requires_clarification)
    else:
        q=f'For Cedar Meridian {noun} (Standard), what are the directions?'
        c=self.turn(q)
        self.assertEqual(c.permitted_document_ids,[1])


class UnitCases(unittest.TestCase): pass


def trailing_comparison(self,n):
    names=self.setup_names(n)
    q=f'How do {names[0]} and {names[1]} compare for daily serving size and meal timing?'
    self.assertEqual(comparison_mentions(q,names),tuple(x.lower() for x in names[:2]))
    plan=rag_planning.QueryPlan(resolved_user_meaning=q,retrieval_query=q,intent='comparison',
        active_subjects=names[:2],subject_confidence=.9,requested_fields=['directions','specifications','timing','form'],
        scope_mode='multi_entity',comparison_requested=True)
    c=self.turn(q,plan=plan)
    self.assertEqual(set(c.permitted_document_ids or []),{1,2})
    self.assertEqual(c.execution.soft_scope.unresolved_mentions,())
    # Preserve additive explicit fields (including an existing ontology word in
    # a name); reject the planner-only specification/timing duplicates.
    self.assertEqual(c.requested_fields,extract_requested_fields(q))
    self.assert_provenance(c,q)


def contextual_timing(self,n):
    from services.query_contract import normalize_requested_fields
    q=['Compare Cedar and Birch on serving size and meal timing.',
       'What is the daily serving schedule and exact time of day?',
       'Compare the packages on directions and delivery timing.'][n%3]
    actual=normalize_requested_fields(['directions','timing','serving_size'],message=q)
    if n%3==0:
        self.assertEqual(actual,['directions'])
        self.assertEqual(extract_requested_fields('meal timing'),['directions'])
    elif n%3==1:self.assertEqual(actual,['directions','clock_time'])
    else:self.assertEqual(actual,['directions','timing'])


def supported_cross_field(self,n):
    field,statement=[('form',f'Format: modular units, edition {n+1}.'),('duration',f'Assembly takes {n+3} hours.'),
                     ('features',f'Includes offline operation and {n+1} local tools.'),('price',f'Price: ${n+20} per unit.')][n%4]
    c=contract(('directions',field));rows=[]
    for doc in (1,2):
        rows.extend([item(doc,doc*100,'Directions: use 3 units daily. '+statement,['directions']),
                     item(doc,doc*100+1,'Overview',[''+field])])
    for row in rows:row['field_coverage']={'directions':'SUPPORTED',field:'SUPPORTED'}
    tr=ChatTrace(1,'cross-field')
    retained,context,_,_=rag._bounded_generation_context(rows,c.original_query,4000,'comparison',c,tr)
    prompt=rag.build_rag_prompt(c.original_query,retained,compressed_context=context,query_contract=c)
    self.assertIn(statement,prompt)
    self.assertNotIn(field+': No concrete value supplied',prompt)
    self.assertNotIn(field+': Unavailable',prompt)
    self.assertNotIn(field+': missing',prompt)


CATEGORIES=[('A_current_entity',30,current_entity,RuntimeCases),
            ('B_pronoun',20,pronouns,RuntimeCases),('C_alternation',30,alternation,UnitCases),
            ('D_colon',20,colon,UnitCases),('E_discovery',20,discovery,RuntimeCases),
            ('F_fields',30,fields,UnitCases),('G_clock',15,clock,UnitCases),
            ('H_independent',20,independent,UnitCases),('I_atomic',20,atomic,UnitCases),
            ('J_prompt',20,prompt_contract,UnitCases),('K_variant',20,variants,RuntimeCases),
            ('L_trailing_comparison',10,trailing_comparison,RuntimeCases),
            ('M_contextual_timing',15,contextual_timing,UnitCases),
            ('N_supported_cross_field',20,supported_cross_field,UnitCases)]
for category,count,fn,target in CATEGORIES:
    for n in range(count):
        def case(self,n=n,fn=fn):fn(self,n)
        setattr(target,f'test_{category}_{n:03}',case)
del target,case


if __name__=='__main__':unittest.main()
