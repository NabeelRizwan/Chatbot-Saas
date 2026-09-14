"""Offline replay of unmodified Phase 3.1 fixture, after generic freeze only."""
import json
from scripts.phase31_fixture import NATURAL,GOLDEN
from test_resource_discovery import ResourceFixture

def replay():
    f=ResourceFixture();f.setUp()
    try:
        for number,name,kind,aliases in NATURAL:
            f.add(number,name,kind=kind,aliases=aliases)
        f.project(*[row[0] for row in NATURAL])
        records=[]
        for i,(q,expected,old_kind) in enumerate(GOLDEN,1):
            c=f.contract(q)
            soft=c.execution.soft_scope
            selected=set(soft.resolved_document_ids)
            candidate_ids={d for a in soft.resource_candidates for d in a.resource.document_ids}
            semantic=i in (1,2,3)
            relation=i==10
            original_ok=(set(expected)<=candidate_ids if old_kind=="category" else
                         c.requires_clarification if old_kind=="ambiguous" else
                         not selected if old_kind=="unresolved" else selected==set(expected))
            # Oracle corrections made before replay: semantic paraphrases are not
            # synonyms; fixture has no middle-tier ordering. Preserve old score.
            reviewed_ok=(not c.execution.scope_decision.exact_narrowing_applied and
                (soft.state.value=="incomplete_comparison" or "deterministic_discovery_insufficient" in soft.reason_codes)
                if semantic else "structured_relation_required" in soft.reason_codes and not selected if relation else original_ok)
            records.append(dict(id=i,question=q,original_expected=list(expected),original_kind=old_kind,
                original_ok=original_ok,reviewed_ok=reviewed_ok,
                oracle="semantic_required" if semantic else "missing_ordering" if relation else "unchanged",
                state=soft.state.value,scope=c.execution.scope_decision.strategy.value,
                selected=sorted(selected),candidates=sorted(candidate_ids),
                probes=c.execution.resource_discovery.get("resolutions",())))
        return records
    finally:
        f.doCleanups()

if __name__=="__main__":
    rows=replay()
    print(json.dumps([{**r,"probes":[{k:v for k,v in p.items() if k!="candidates"} for p in r["probes"]]} for r in rows]))
