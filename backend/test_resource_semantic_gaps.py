"""Frozen Phase 3.3 gap fixture: 128 questions / eight unrelated domains.

Reference templates split before runtime repair; SQL surrogates offline only.
No morphology/semantic synonym is an identity oracle. Remote runner reuses data.
"""
from dataclasses import dataclass
import unittest
from test_resource_discovery import ResourceFixture

DOMAINS = (
    ("repair laptops", "Laptop Repair Service", "website", "database", "register", "Registration", "devices"),
    ("design kitchens", "Kitchen Design Service", "design", "printing", "migrate", "Migration", "interiors"),
    ("manage payroll", "Payroll Management Service", "tax", "payroll", "integrate", "Integration", "finance"),
    ("train employees", "Employee Training Program", "camera", "installation", "schedule", "Scheduling", "learning"),
    ("book appointments", "Appointment Booking Service", "hosting", "backups", "insure", "Insurance", "appointments"),
    ("migrate servers", "Server Migration Service", "network", "monitoring", "automate", "Automation", "cloud"),
    ("register visitors", "Visitor Registration Service", "logistics", "inventory", "develop", "Development", "visitors"),
    ("integrate systems", "System Integration Service", "contracts", "licensing", "configure", "Configuration", "systems"),
)

@dataclass(frozen=True)
class GapCase:
    key: str
    question: str
    expected: tuple[int, ...]
    expectation: str
    family: str
    split: str

def resource_rows():
    rows=[]
    for i,(action,name,a,b,verb,nominal,domain) in enumerate(DOMAINS,1):
        n=80000+i*100
        values=[(n,name),(n+1,f"Cobalt {domain} Advisory"),(n+2,f"Managed {a} and {b} Service"),
                (n+3,f"Orchid {domain} {nominal} Service"),
                (n+4,f"Amber {domain} Choice Extended"),(n+5,f"Amber {domain} Choice Compact"),
                (n+6,f"Bronze {domain} Plan"),(n+7,f"Silver {domain} Plan"),(n+8,f"Gold {domain} Plan")]
        for number,title in values:
            # Arbitrary JSON order is deliberately NOT an authoritative relation
            # contract; current projector/discovery cannot consume it as truth.
            metadata={"resource_type":"plan" if number>=n+6 else "service"}
            if number>=n+6: metadata["tier_order"]=number-(n+6)
            rows.append(dict(id=number,title=title,metadata=metadata))
    return rows

def cases():
    rows=[]
    for i,(action,name,a,b,verb,nominal,domain) in enumerate(DOMAINS,1):
        n=80000+i*100;advisory=f"Cobalt {domain} Advisory";both=f"Managed {a} and {b} Service"
        templates=[
            (f"Do you {action}?",(),"safe","lexical_outcome"),
            (f"I'm looking for someone to {action}. Is that something you offer?",(),"safe","outcome_wrapper"),
            (f"Can you {verb} Orchid {domain}?",(),"safe","morphology"),
            (f"Show me Orchid {domain} {nominal} Service.",(n+3,),"resolved","nominal_exact"),
            (f"Which service would I need if I want both {a} and {b}?",(n+2,),"resolved","multi_concept"),
            (f"What service do I need if I need both {a} and {b}?",(n+2,),"resolved","multi_concept"),
            (f"Do you offer {name} or mostly do {advisory}?",(n,n+1),"resolved","residual_auxiliary"),
            (f"Do you provide {name} or only do {advisory}?",(n,n+1),"resolved","residual_auxiliary"),
            (f"Show me Amber {domain} Choice.",(),"ambiguous","collision"),
            (f"What is between Bronze {domain} Plan and Gold {domain} Plan?",(),"relation","order_with_json"),
            (f"What is between {name} and {advisory}?",(),"relation","order_without_json"),
            (f"Show me Interstellar Unlisted {domain} 90909.",(),"unknown","unknown"),
            (f"I need {advisory} to solve every problem.",(),"eligible","semantic_gap"),
            (f"Can {both} make everything effortless?",(),"eligible","semantic_gap"),
            (f"Tell me about {name}.",(n,),"resolved","direct"),
            (f"Compare {name} and {advisory}.",(n,n+1),"resolved","comparison"),
        ]
        for j,(q,expected,expectation,family) in enumerate(templates):
            rows.append(GapCase(f"{i}-{j}",q,expected,expectation,family,
                               "heldout" if j in (2,5,7,10,13) else "development"))
    return tuple(rows)

def populate(f):
    from database.models import Organization,Bot
    from services.resource_catalog import ResourceCatalogProjector
    from services.retrieval_contracts import HardKnowledgeScope
    f.db.add(Organization(id=2,name="Foreign",slug="foreign-gap"));f.db.flush()
    f.db.add_all([Bot(id=2,organization_id=1,customer_id=1,name="Other"),Bot(id=3,organization_id=2,customer_id=1,name="Foreign")]);f.db.flush()
    for row in resource_rows():
        f.add(row['id'],row['title'],metadata=row['metadata'])
    f.project(*[r['id'] for r in resource_rows()])
    for bot,org,offset in ((2,1,100000),(3,2,200000)):
        for row in resource_rows(): f.add(row['id']+offset,row['title'],metadata=row['metadata'],bot=bot,org=org)
        ResourceCatalogProjector().project(f.db,HardKnowledgeScope(org,bot),[r['id']+offset for r in resource_rows()])
    f.db.commit()

def record(case,c):
    soft=c.execution.soft_scope
    selected=set(soft.resolved_document_ids);expected=set(case.expected)
    reasons=set(soft.reason_codes)
    eligible='query_optimizer_eligible' in reasons
    unknown='unresolved_unknown_resource' in reasons
    relation='structured_relation_required' in reasons
    exact=c.execution.scope_decision.exact_narrowing_applied
    ok=(selected==expected and exact if case.expectation=='resolved' else
        c.requires_clarification and not selected if case.expectation=='ambiguous' else
        relation and not selected and not exact if case.expectation=='relation' else
        eligible and not selected and not exact if case.expectation=='eligible' else
        unknown and not selected and not exact if case.expectation=='unknown' else
        not selected and not exact)
    leaks=sum(r.resource.organization_id!=c.execution.hard_scope.organization_id or
              r.resource.bot_id!=c.execution.hard_scope.bot_id for r in soft.resource_candidates)
    return dict(key=case.key,question=case.question,expectation=case.expectation,family=case.family,
        expected=list(case.expected),selected=sorted(selected),state=soft.state.value,scope=c.execution.scope_decision.strategy.value,
        reasons=sorted(reasons),eligible=eligible,unknown=unknown,pass_=bool(ok),leaks=leaks,
        false_confident=bool(selected-expected),original_preserved=c.original_query==case.question,
        trace=c.execution.resource_discovery)

def evaluate(f,split):
    rows=[record(case,f.contract(case.question)) for case in cases() if case.split==split]
    positives=[r for r in rows if r['selected']]
    eligible=[r for r in rows if r['expectation']=='eligible']
    relations=[r for r in rows if r['expectation']=='relation']
    return dict(split=split,cases=len(rows),correct=sum(r['pass_'] for r in rows),
        precision=sum(not r['false_confident'] for r in positives)/max(1,len(positives)),
        optimizer_correctness=sum(r['pass_'] for r in eligible)/max(1,len(eligible)),
        relation_correctness=sum(r['pass_'] for r in relations)/max(1,len(relations)),
        false_confident=sum(r['false_confident'] for r in rows),leaks=sum(r['leaks'] for r in rows),
        rows=rows)

class GapTests(ResourceFixture):
    def test_frozen_gap_matrix(self):
        populate(self)
        for split in ('development','heldout'):
            r=evaluate(self,split)
            self.assertEqual(r['correct'],r['cases'],[(x['key'],x['state'],x['selected'],x['reasons']) for x in r['rows'] if not x['pass_']])
            self.assertEqual(r['false_confident'],0);self.assertEqual(r['leaks'],0)

    def test_gap_classification_not_a_model_or_scope_change(self):
        self.add(1,'Velvet Pine Advisory');self.project(1)
        c=self.contract('I need Velvet Pine Advisory to resolve everything.')
        self.assertIn('query_optimizer_eligible',c.execution.soft_scope.reason_codes)
        self.assertIsNone(c.permitted_document_ids)
        c=self.contract('Unlisted Interstellar Permit 90909')
        self.assertIn('unresolved_unknown_resource',c.execution.soft_scope.reason_codes)

    def test_multi_concept_collision_is_not_a_winner(self):
        self.add(1,'Managed Design and Printing Service',metadata={'resource_type':'service'})
        self.add(2,'Express Design and Printing Service',metadata={'resource_type':'service'})
        self.project(1,2)
        c=self.contract('Which service would I need if I want both design and printing?')
        self.assertTrue(c.requires_clarification)
        self.assertFalse(c.execution.scope_decision.exact_narrowing_applied)

    def test_original_identity_precedes_weaker_wrapper(self):
        self.add(1,'Mostly Do Velvet Pine Service')
        self.add(2,'Velvet Pine Service')
        self.project(1,2)
        c=self.contract('Mostly Do Velvet Pine Service')
        self.assertEqual(set(c.execution.soft_scope.resolved_document_ids),{1})

    def test_nonsemantic_failures_do_not_become_optimizer_eligible(self):
        from services.resource_channels import ResourceProbe
        from services.resource_discovery import ResourceDiscoveryService,ResourceDiscoveryResult,ResourceResolution,ResolutionState
        for reason in ('identity_channel_unavailable','candidate_limit_prevents_uniqueness','structured_relation_required','category_resource_set'):
            r=ResourceResolution(ResourceProbe('Unlisted Item'),ResolutionState.UNRESOLVED,reason_codes=(reason,))
            answer=ResourceDiscoveryService._classify_gaps(ResourceDiscoveryResult((),(r,),0))
            self.assertEqual(answer.resolutions[0].reason_codes,(reason,))

    def test_lexical_collision_is_eligible_but_remains_ambiguous(self):
        self.add(1,'Managed Logistics and Inventory Service',metadata={'resource_type':'service'})
        self.add(2,'Express Logistics and Inventory Service',metadata={'resource_type':'service'})
        self.project(1,2)
        c=self.contract('Which service would I need if I want both logistics and inventory?')
        self.assertTrue(c.requires_clarification)
        self.assertFalse(c.execution.scope_decision.exact_narrowing_applied)
        self.assertIn('query_optimizer_eligible',c.execution.soft_scope.reason_codes)

if __name__=='__main__':
    unittest.main()
