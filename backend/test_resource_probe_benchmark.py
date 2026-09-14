"""Phase 3.2 frozen natural-language fixture. All names/data synthetic.
Membership and expectations established before runtime edits. SQLite candidate
surrogates are inherited from Phase 3, not a claim of PostgreSQL acceptance.
"""
from dataclasses import dataclass
import hashlib

SEEDS = (
    ("Falcon Elm", "product", "ecommerce"),
    ("Aspen Forge", "service", "consulting"),
    ("Topaz Haven", "plan", "saas"),
    ("Sequoia Fern", "course", "education"),
    ("Opal Finch", "form", "admissions"),
    ("Acacia Shield", "policy", "support"),
    ("Indigo Scroll", "pdf", "documents"),
    ("Birch Coast", "location", "locations"),
    ("Hazel Grove", "department", "departments"),
    ("Citrine Care", "guide", "healthcare_information"),
    ("Laurel Visit", "appointment", "appointments"),
    ("Garnet Permit", "certificate", "custom"),
)

@dataclass(frozen=True)
class NaturalCase:
    key: str
    question: str
    expected: tuple[int, ...]
    state: str
    category: str
    resource_type: str
    context: tuple[int, ...] = ()
    justification: str = ""

    @property
    def split(self):
        # Seven of every ten template slots; no post-result membership changes.
        return "heldout" if int(self.key.split("-")[1]) % 10 in (2, 6, 9) else "development"

def cases():
    result = []
    for i, (stem, kind, domain) in enumerate(SEEDS, 1):
        n = i * 100
        a = f"{stem} {kind}"
        x, y = stem.split()
        b_stem = f"Nimbus {x} Plus"
        b = f"{b_stem} {kind}"
        c = f"Russet {y} Mini {kind}"
        plural = kind[:-1]+"ies" if kind.endswith("y") else kind+"s"
        rows = [
            (a, (n,), "resolved_single", "direct"),
            (f"Where is the {a}?", (n,), "resolved_single", "where"),
            (f"Where can I find your {a}?", (n,), "resolved_single", "navigation"),
            (f"Can you send me the {a}?", (n,), "resolved_single", "auxiliary"),
            (f"Show me your {a}.", (n,), "resolved_single", "entity_category"),
            (f"Tell me about {a}.", (n,), "resolved_single", "tell"),
            (f"Do you offer {a}?", (n,), "resolved_single", "offer"),
            (f"Does your {a} have directions?", (n,), "resolved_single", "does"),
            (f"I'm looking for the {a}.", (n,), "resolved_single", "looking"),
            (f"I think it was called {a}.", (n,), "resolved_single", "called"),
            (f"Please could you show me the {a} for me?", (n,), "resolved_single", "polite"),
            (f"How do I contact your {a}?", (n,), "resolved_single", "possessive"),
            (f"I was looking for something called {a}.", (n,), "resolved_single", "nested_wrapper"),
            (f"{a} or {b}", (n,n+1), "resolved_multi", "comparison"),
            (f"Compare {a} versus {b}.", (n,n+1), "resolved_multi", "versus"),
            (f"{a} or the {b_stem} one", (n,n+1), "resolved_multi", "ellipsis"),
            (f"Should I look at {a} or {b_stem} one?", (n,n+1), "resolved_multi", "inheritance"),
            (f"Compare {a} and Auxiliary {stem} service.", (n,n+3), "resolved_multi", "conflicting_type"),
            (f"What {plural} do you have?", (n,n+1,n+2), "category", "plural_category"),
            (f"Show me all {kind}.", (n,n+1,n+2), "category", "singular_category"),
            (f"Show me the {a}.", (n,), "resolved_single", "specific_type"),
            (f"Send me the {kind} for {stem}.", (n,), "resolved_single", "x_for_y"),
            (f"{y} {x} {kind}", (n,), "resolved_single", "reordered"),
            ("Show me Duo.", (), "ambiguous", "ambiguous"),
            (a[:3]+"x"+a[4:], (n,), "resolved_single", "typo"),
            (f"{x[:-1]}x {y[:-1]}x {kind}", (n,), "resolved_single", "multiple_typo"),
            (a.replace(" ", " / "), (n,), "resolved_single", "punctuation"),
            (f"Tell me about Café {stem} 東京.", (n,), "resolved_single", "unicode"),
            ("How much is this one?", (n,), "resolved_single", "followup"),
            (f"Tell me about {b}.", (n+1,), "resolved_single", "switch"),
            (f"I need something to make my workload vanish in {domain}.", (), "optimizer", "semantic"),
            (f"What is between {a} and {b}?", (), "relation", "ordering"),
            ("Tell me about interstellar teleportation.", (), "unresolved", "unrelated"),
            (f"Show me the Unlisted {kind} 90909.", (), "unresolved", "impossible"),
            (f"Compare {a} and {b} and {c}.", (n,n+1,n+2), "resolved_multi", "three_member"),
            (f"Tell me about {a} and its price and directions.", (n,), "resolved_single", "fields"),
        ]
        for j,(q,expected,state,category) in enumerate(rows):
            if state == "category":
                expected = tuple(sorted([k*100+o for k,(_,t,_) in enumerate(SEEDS,1) if t==kind for o in range(3)]
                                        + ([k*100+3 for k in range(1,13)] if kind=="service" else [])))
            justification = ("No persisted term expresses this outcome; semantic equivalence cannot be invented." if state=="optimizer"
                else "Catalog names have no ordered tier relation." if state=="relation" else "")
            result.append(NaturalCase(f"{i:02d}-{j:02d}",q,expected,state,category,kind,
                (n,) if category in {"followup","switch"} else (),justification))
    return tuple(result)

def populate(f):
    from database.models import Bot, Organization
    from services.resource_catalog import ResourceCatalogProjector
    from services.retrieval_contracts import HardKnowledgeScope
    f.db.add(Organization(id=2,name="Foreign synthetic",slug="foreign-probes"))
    f.db.flush()
    f.db.add_all([Bot(id=2,organization_id=1,customer_id=1,name="Other"),
                  Bot(id=3,organization_id=2,customer_id=1,name="Foreign")])
    f.db.flush()
    own=[]
    for i,(stem,kind,_) in enumerate(SEEDS,1):
        n=i*100
        x,y=stem.split()
        for offset,name,k in ((0,f"{stem} {kind}",kind),(1,f"Nimbus {x} Plus {kind}",kind),
                              (2,f"Russet {y} Mini {kind}",kind),(3,f"Auxiliary {stem} service","service")):
            f.add(n+offset,name,kind=k,aliases=["Duo",f"Café {stem} 東京"] if not offset else ["Duo"])
            own.append(n+offset)
        for bot,org,offset in ((2,1,10000),(3,2,20000)):
            f.add(n+offset,f"{stem} {kind}",kind=kind,org=org,bot=bot)
    f.project(*own)
    for bot,org,offset in ((2,1,10000),(3,2,20000)):
        ResourceCatalogProjector().project(f.db,HardKnowledgeScope(org,bot),[i*100+offset for i in range(1,13)])
    f.db.commit()


def evaluate(f, split):
    from services.retrieval_contracts import ScopeStrategy
    records=[]
    for case in (c for c in cases() if c.split==split):
        state={"active_subjects":[{"name":f.db.get(__import__('database.models',fromlist=['Document']).Document,n).title,
                                   "document_id":n,"confidence":1.0} for n in case.context]}
        c=f.contract(case.question,state=state)
        soft=c.execution.soft_scope
        selected=set(soft.resolved_document_ids)
        top={d for r in c.execution.resource_discovery.get("resolutions",()) for a in r["candidates"][:5] for d in a["document_ids"]}
        category=any(r.get("category_intent") for r in c.execution.resource_discovery.get("resolutions",()))
        catalog_candidates={d for r in soft.resource_candidates for d in r.resource.document_ids}
        optimizer_eligible=not selected and "deterministic_discovery_insufficient" in soft.reason_codes
        actual=("category" if category else "relation" if "structured_relation_required" in soft.reason_codes else soft.state.value)
        expected=set(case.expected)
        state_correct=(actual==case.state or (case.state=="optimizer" and actual=="unresolved" and optimizer_eligible))
        correct=state_correct and (expected==catalog_candidates if case.state=="category" else selected==expected)
        leakage=sum(x.resource.organization_id!=1 or x.resource.bot_id!=1 for x in soft.resource_candidates)
        records.append(dict(key=case.key,question=case.question,category=case.category,kind=case.resource_type,
            expected_state=case.state,state=actual,expected=sorted(expected),selected=sorted(selected),
            optimizer_eligible=optimizer_eligible,
            top=sorted(top),correct=correct,leakage=leakage,original_preserved=c.original_query==case.question,
            scope=c.execution.scope_decision.strategy.value,probes=c.execution.resource_discovery.get("resolutions",())))
    def metrics(rows):
        positives=[r for r in rows if r['expected_state'] in {'resolved_single','resolved_multi'}]
        total=sum(len(r['expected']) for r in positives)
        emitted=sum(len(r['selected']) for r in rows)
        good=sum(len(set(r['expected'])&set(r['selected'])) for r in positives)
        def acc(kind):
            group=[r for r in rows if r['expected_state']==kind]
            return sum(r['correct'] for r in group)/len(group) if group else None
        return dict(cases=len(rows),state_accuracy=sum(r['correct'] for r in rows)/max(1,len(rows)),
            precision=good/emitted if emitted else None,recall=good/max(1,total),
            multi_member_recall=sum(len(set(r['selected'])&set(r['expected'])) for r in positives if r['expected_state']=='resolved_multi')/
                max(1,sum(len(r['expected']) for r in positives if r['expected_state']=='resolved_multi')),
            category_correctness=acc('category'),ambiguity_correctness=acc('ambiguous'),
            optimizer_correctness=acc('optimizer'),relation_correctness=acc('relation'),
            false_confident_rate=sum(bool(set(r['selected'])-set(r['expected'])) for r in rows)/max(1,len(rows)),
            candidate_recall_5=sum(len(set(r['top'])&set(r['expected'])) for r in positives)/max(1,total),
            leakage=sum(r['leakage'] for r in rows))
    gates={"preservation":all(r['original_preserved'] for r in records),"zero_leakage":not any(r['leakage'] for r in records),
        "protected":all(r['correct'] for r in records if r['category'] in {'direct','entity_category','singular_category','plural_category','specific_type','ellipsis','inheritance','ambiguous','impossible','ordering'}),
        "resolvable_98":sum(r['correct'] for r in records if r['expected_state'].startswith('resolved'))/max(1,sum(r['expected_state'].startswith('resolved') for r in records))>=.98,
        "no_false_confidence":not any(set(r['selected'])-set(r['expected']) for r in records)}
    return dict(split=split,metrics=metrics(records),gates=gates,
        groups={k:{v:metrics([r for r in records if r[k]==v]) for v in sorted({r[k] for r in records})} for k in ('category','kind')},
        records=records)


def load_tests(loader, tests, pattern):
    import unittest
    from test_resource_discovery import ResourceFixture
    class NaturalBenchmarkTests(ResourceFixture):
        def test_frozen_432_natural_cases(self):
            populate(self)
            for split in ('development','heldout'):
                result=evaluate(self,split)
                self.assertTrue(all(result['gates'].values()),{'gates':result['gates'],'metrics':result['metrics']})
    tests.addTests(loader.loadTestsFromTestCase(NaturalBenchmarkTests))
    return tests


if __name__=='__main__':
    import sys,json
    from contextlib import ExitStack
    from unittest.mock import patch
    from database import connection
    from test_resource_discovery import ResourceFixture
    split=sys.argv[1]
    assert split in {'development','heldout'}
    with ExitStack() as stack:
        stack.enter_context(patch.object(connection.engine,'connect',side_effect=AssertionError('External DB forbidden')))
        stack.enter_context(patch('requests.sessions.Session.request',side_effect=AssertionError('HTTP forbidden')))
        stack.enter_context(patch('httpx.Client.send',side_effect=AssertionError('HTTP forbidden')))
        f=ResourceFixture(); f.setUp()
        try:
            populate(f); result=evaluate(f,split)
            result['records']=[{k:v for k,v in r.items() if k!='probes'} for r in result['records']]
            print(json.dumps(result,ensure_ascii=True))
            raise SystemExit(0 if all(result['gates'].values()) else 1)
        finally:
            f.doCleanups()
