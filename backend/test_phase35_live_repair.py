"""Phase 3.5 frozen generalization cases; synthetic data and mocked providers only.

112 development + 48 held-out cases, frozen before runtime repair. The held-out
class is not evaluated until development passes. No customer names or vectors.
"""
import contextlib
import json
import time
import unittest
from threading import Event
from types import SimpleNamespace as NS
from unittest.mock import patch

from services import rag_service as rag, rag_planning as planning, llm_router as router
from services.query_contract import QueryContract, ResolvedEntity, extract_requested_fields
from services.requested_propositions import annotate_candidates, update_support
from services.retrieval_selection import POLICY
from services.observability_service import ChatTrace, RetrievalTrace, evidence_key
from test_resource_probe_understanding import probes


DEV_COMPARE = [
    ('Between Basic and Professional, which is cheaper?', ('basic', 'professional')),
    ('Between Course Cedar and Course Birch, which takes less time?', ('course cedar', 'course birch')),
    ('Between Atlas Service and Beacon Service, which fits a small team?', ('atlas service', 'beacon service')),
    ('Between Entry Form and Renewal Form, which has fewer steps?', ('entry form', 'renewal form')),
    ('Between River Lodge and Hill Lodge, which would suit families?', ('river lodge', 'hill lodge')),
    ('Between Cedar Oil and Birch Capsules, which is easier to use?', ('cedar oil', 'birch capsules')),
    ('Between Arrival Policy and Departure Policy, which works for visitors?', ('arrival policy', 'departure policy')),
    ('Between Morning Appointment and Evening Appointment, which is shorter?', ('morning appointment', 'evening appointment')),
    ('Between Orion Resource and Vega Resource which has a warranty?', ('orion resource', 'vega resource')),
    ('My team is small. Between Quartz and Slate, which would you choose?', ('quartz', 'slate')),
    ('Between North Hall and South Hall: which is better for meetings?', ('north hall', 'south hall')),
    ('Between Indigo Permit and Violet Permit, which is harder to obtain?', ('indigo permit', 'violet permit')),
    ('Between Maple Course and Spruce Course, which takes fewer hours?', ('maple course', 'spruce course')),
    ('Between Early Slot and Late Slot, which would work on Tuesday?', ('early slot', 'late slot')),
    ('Between Harbor Service and Valley Service, which offers training?', ('harbor service', 'valley service')),
    ('Between Copper and Silver, which one has more storage?', ('copper', 'silver')),
    ('What comes between Basic and Enterprise?', None),
    ('Which tier is between Bronze and Gold?', None),
    ('What is between North Station and South Station?', None),
    ('What plan comes after Starter?', None),
    ('What course comes before Advanced?', None),
    ('Which appointment is between dawn and noon?', None),
    ('What form comes after Registration?', None),
    ('Which resource comes between Alpha and Gamma?', None),
]
DEV_USAGE = [(q, True) for q in [
    'How do I take it?', 'How often do I take it?', 'When do I take it?',
    'With meals?', 'Before food?', 'How many times a day?', 'Daily use?',
    'Which is easier to take?', 'Which is less fiddly to take?',
    'Which has the simpler schedule?', 'Can I take it at lunch?', 'How is it taken?',
    'What is the dosing schedule?', 'How often should we apply the sealant?',
    'When should I use the device?', 'Is the daily routine simpler?',
    'Which requires fewer steps to use?', 'Can I use this before breakfast?',
    'How many servings per day?', 'Do the capsules go with food?',
    'Should the softgel be taken after dinner?', 'How often is this used?',
    'Can I take one with my evening meal?', 'How many doses each day?',
    'Is this easier to apply every morning?', 'Which has a less complicated usage schedule?',
    'How should we install the adapter?', 'What are the setup instructions?',
    'How do I use the booking form?', 'What are the service usage directions?',
]] + [(q, False) for q in [
    'Take a look at the price.', 'Does the journey take three hours?',
    'What is your take on this policy?', 'Can I take a refund?',
    'Does the course take place in town?', 'Where do I take the bus?',
    'Do you take credit cards?', 'Will this take my job?',
    'Which plan takes less storage?', 'Can you schedule an appointment?',
]]
HELD_COMPARE = [
    ('Between Flint Program and Opal Program, which suits beginners?', ('flint program','opal program')),
    ('Between Dawn Tincture and Dusk Tablets, which needs less effort to use?', ('dawn tincture','dusk tablets')),
    ('Between Bay Studio and Ridge Studio, which has a kitchen?', ('bay studio','ridge studio')),
    ('Between First Visit and Return Visit, which would fit Friday?', ('first visit','return visit')),
    ('Between Travel Waiver and Entry Permit, which is simpler?', ('travel waiver','entry permit')),
    ('Between Delta Workshop and Kappa Workshop, which works remotely?', ('delta workshop','kappa workshop')),
    ('Between Indigo Policy and Saffron Policy, which offers cancellation?', ('indigo policy','saffron policy')),
    ('Between Solar Tile and Lunar Tile, which is easier to install?', ('solar tile','lunar tile')),
    ('Which package is between Economy and Premium?', None),
    ('What module comes after Orientation?', None),
    ('What is between West Pier and East Pier?', None),
    ('Which permit comes before Residency?', None),
]
HELD_USAGE = [(q, True) for q in [
    'Must this be used with an evening meal?', 'Which is harder to apply each night?',
    'How frequently should I use it?', 'Could I take that with breakfast?',
    'What is the simplest daily routine?', 'Does it need several servings per day?',
    'Should it be taken before meals?', 'Is once a day enough for this dose?',
]] + [(q,False) for q in ['Does it take effect immediately?', 'Take me to the form.',
    'Do you take reservations?', 'How long does approval take?']]

# Different domain/field matrices, not repetitions of the historical products.
DEV_MATRICES = [
    ('products', ('directions','results_timeframe')), ('plans', ('price','features')),
    ('courses', ('duration','syllabus')), ('services', ('directions','eligibility')),
    ('forms', ('directions','policy')), ('policies', ('returns','shipping')),
    ('appointments', ('duration','directions')), ('locations', ('amenities','check_in')),
    ('custom resources', ('specifications','directions')), ('products', ('ingredients','benefits')),
    ('plans', ('policy','price')), ('courses', ('eligibility','duration')),
    ('services', ('features','price')), ('forms', ('eligibility','duration')),
    ('policies', ('guarantee','returns')), ('appointments', ('check_in','price')),
    ('locations', ('directions','amenities')), ('custom resources', ('features','policy')),
    ('products', ('directions','ingredients','results_timeframe')),
    ('plans', ('price','features','policy')), ('courses', ('duration','syllabus','eligibility')),
    ('services', ('price','directions','duration')), ('forms', ('policy','directions','eligibility')),
    ('custom resources', ('directions','specifications','duration')),
]
HELD_MATRICES = [
    ('appointments', ('policy','directions','duration')), ('locations', ('amenities','policy','price')),
    ('products', ('benefits','directions','results_timeframe')), ('plans', ('duration','features','price')),
    ('courses', ('directions','syllabus','duration')), ('custom resources', ('policy','directions','features')),
    ('forms', ('price','directions')), ('services', ('policy','results_timeframe')),
    ('policies', ('guarantee','shipping')), ('appointments', ('price','duration')),
    ('locations', ('directions','price')), ('custom resources', ('ingredients','specifications')),
]
VALUES = dict(directions='Directions: Use two units daily with a meal.',
    results_timeframe='Results may develop in 3-6 weeks; individual results vary.',
    price='Price: $27.00 per unit.', features='Features include offline access.',
    duration='Duration: 6 weeks.', syllabus='Syllabus: safety and navigation.',
    eligibility='Eligibility requires prior registration.', policy='Cancellation policy allows seven days.',
    returns='Returns: refunds within fourteen days.', shipping='Shipping takes three business days.',
    amenities='Amenities include parking and wifi.', check_in='Check-in starts at 3 PM.',
    specifications='Specifications: 8 GB memory.', ingredients='Ingredients: Cedar and Willow.',
    benefits='Benefits: supports comfortable operation.', guarantee='Guarantee covers the first purchase only.')


def contract(fields, domain='resource'):
    return QueryContract(original_query=f'Compare the two {domain} on ' + ', '.join(fields),
        normalized_query='compare', resolved_query='compare', intent='comparison', mode='comparison',
        requested_fields=list(fields), resolved_entities=[ResolvedEntity('Cedar '+domain,1,1),ResolvedEntity('Birch '+domain,2,1)],
        comparison_entities=['Cedar '+domain,'Birch '+domain])


def item(doc, number, content, fields=(), score=0.9):
    return dict(document=NS(id=doc,title=f'Resource {doc}',filename=f'Resource {doc}',source_url=f'https://fixture.test/{doc}',canonical_url=f'https://fixture.test/{doc}',metadata_json={}),
        chunk=NS(id=number,document_id=doc,chunk_index=number,content=content,metadata_json={},token_count=10),
        score=score, required_fields=list(fields))


def comparison_case(self, case):
    question, members = case
    actual = probes(question)
    if members is None:
        self.assertEqual(actual[0].relation_intent,'structured_relation_required')
    else:
        self.assertEqual(tuple(p.text.lower() for p in actual),members)
        self.assertTrue(all(not p.relation_intent for p in actual))


def usage_case(self, case):
    question, expected = case
    self.assertEqual('directions' in extract_requested_fields(question),expected,question)
    if expected:
        self.assertIn('price',extract_requested_fields(question+' Also include the price.'))


def obligation_case(self, case):
    domain, fields = case
    c=contract(fields,domain)
    rows=[item(d,d*100+i,VALUES[f],[f]) for d in (1,2) for i,f in enumerate(fields)]
    annotated=annotate_candidates(c,rows)
    actual={(p.applicable_entity,getattr(p,'requested_field',None)) for p in c.requested_propositions if p.type=='requested_field'}
    self.assertEqual(actual,{(d,f) for d in (1,2) for f in fields})
    self.assertEqual(len({p.id for p in c.requested_propositions}),len(c.requested_propositions))
    update_support(c,annotated[:-1])
    for p in c.requested_propositions:
        if p.type=='requested_field':
            self.assertTrue(all(ref[0]==p.applicable_entity for ref in p.supporting_candidate_ids))
    missing=next(p for p in c.requested_propositions if p.type=='requested_field' and p.applicable_entity==2 and p.requested_field==fields[-1])
    self.assertEqual(missing.support_state,'missing')
    self.assertTrue(all('requested_propositions' not in row for row in rows))


def retention_case(self, case):
    domain,fields=case
    c=contract(fields,domain)
    noise=[item(d,d*1000+i,'Overview: optional detail number '+str(i),score=1.0) for d in (1,2) for i in range(20)]
    required=[item(d,d*100+i,VALUES[f],[f],score=0.01) for d in (1,2) for i,f in enumerate(fields)]
    pool=annotate_candidates(c,noise+required)
    tr=ChatTrace(1,'test')
    selected=rag._diverse_chunk_selection(pool,top_k=2*len(fields),max_per_doc=len(fields),preferred_doc_ids=[1,2],trace=tr)
    self.assertEqual({evidence_key(r) for r in selected},{evidence_key(r) for r in required})
    self.assertLessEqual(len(selected),2*len(fields))
    self.assertTrue(all(sum(evidence_key(r)[0]==d for r in selected)<=len(fields) for d in (1,2)))
    retained,context,_,_=rag._bounded_generation_context(selected,c.original_query,4000,'comparison',c,tr)
    self.assertLessEqual(len(context),4000)
    self.assertEqual({evidence_key(r) for r in retained},{evidence_key(r) for r in required})
    self.assertTrue(tr.retrieval.context_assembly['required_proposition_representatives_admitted'])


class Development(unittest.TestCase): pass
class HeldOut(unittest.TestCase): pass


for cls,groups in [(Development,[(comparison_case,DEV_COMPARE),(usage_case,DEV_USAGE),(obligation_case,DEV_MATRICES),(retention_case,DEV_MATRICES)]),
                   (HeldOut,[(comparison_case,HELD_COMPARE),(usage_case,HELD_USAGE),(obligation_case,HELD_MATRICES),(retention_case,HELD_MATRICES)])]:
    for check,cases in groups:
        for index,case in enumerate(cases):
            def test(self, check=check, case=case): check(self,case)
            setattr(cls,f'test_{check.__name__}_{index:02}',test)
del cls  # unittest must not discover a duplicate alias of the held-out class.


class AuxiliaryDeadlines(unittest.TestCase):
    def run_aux(self, purpose, *, setup=0.08, accounting=0.08, provider_delay=0.005, error=None):
        done=Event()
        @contextlib.contextmanager
        def guard(*args,**kwargs):
            time.sleep(setup)
            try: yield True
            finally: time.sleep(accounting)
        def generate(**kw):
            time.sleep(provider_delay)
            if error: raise error
            text='{"ranked_candidates":[0],"reject_all":false}' if purpose=='reviewer' else json.dumps(dict(
                resolved_user_meaning='Requested details',retrieval_query='Cedar details',intent='comparison',
                active_subjects=[],subject_confidence=0.0,requested_fields=['directions'],scope_mode='uncertain',
                comparison_requested=True,needs_global_discovery=False))
            return NS(text=text,usage=NS(total_tokens=12))
        def usage(*args):
            time.sleep(accounting)
            done.set()
        bot=NS(id=1,organization_id=1,provider='fixture',model_name='fixture',provider_api_key=None)
        trace=ChatTrace(1,'test')
        real=router.generate_auxiliary
        with patch.dict(router.PROVIDERS,fixture=NS(generate_with_metadata=generate)), \
             patch.object(router,'_resolve_api_key',return_value=('synthetic-not-a-secret',True)), \
             patch.object(router,'_track_usage',side_effect=usage), \
             patch('services.llm_client.distributed_concurrency_guard',guard), \
             patch('services.llm_client.global_circuit_breaker'), \
             patch.object(planning,'generate_auxiliary',side_effect=lambda *a,**kw:real(*a,**(kw|{'timeout':0.04}))):
            try:
                if purpose=='reviewer':
                    planning.review_evidence(bot,contract(['directions','duration']),[item(1,1,VALUES['directions'])],trace)
                else:
                    planning.plan_query(bot,'Which is simpler to use?',[],{},[],trace)
            finally:
                if error is None: self.assertTrue(done.wait(2),'Accounting must finish; no orphan worker')
                else: time.sleep(setup+accounting+provider_delay+0.05)
        return trace

    def test_planner_overhead_not_inference_timeout(self):
        tr=self.run_aux('planner')
        self.assertEqual(tr.diagnostics['planner']['status'],'success')

    def test_reviewer_overhead_not_inference_timeout(self):
        tr=self.run_aux('reviewer')
        self.assertFalse(tr.retrieval.reviewer_outcome.get('fallback_used',True))

    def test_genuine_provider_timeout_still_falls_back(self):
        tr=self.run_aux('reviewer',setup=0,accounting=0,provider_delay=0.10)
        self.assertTrue(tr.retrieval.reviewer_outcome.get('fallback_used'))

    def test_provider_429_is_not_wrapper_timeout(self):
        from services.providers.base_provider import ProviderError,ProviderErrorKind
        error=ProviderError('synthetic quota',status_code=429,kind=ProviderErrorKind.RATE_LIMIT)
        tr=self.run_aux('reviewer',setup=0,accounting=0,error=error)
        self.assertTrue(tr.retrieval.reviewer_outcome.get('fallback_used'))
        self.assertNotIn('Timeout',tr.retrieval.reviewer_outcome.get('status',''))


if __name__=='__main__': unittest.main()
