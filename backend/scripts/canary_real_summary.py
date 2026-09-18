"""Aggregate paired retrieval observations; no provider, database or source I/O."""
import math


def percentile(values, fraction):
    values=sorted(values)
    return values[max(0,math.ceil(len(values)*fraction)-1)] if values else None


def summarize(rows):
    lanes={}
    for lane in ('LEGACY_CONTROL','STRUCTURAL_CANARY'):
        selected=[r for r in rows if r['lane']==lane]
        metrics={}
        for r in selected:
            for name,(n,d) in r['outcome']['metrics'].items():
                metrics.setdefault(name,[0,0]);metrics[name][0]+=n;metrics[name][1]+=d
        times={name:{'p50':percentile([r[name] for r in selected],.5),
                     'p95':percentile([r[name] for r in selected],.95)}
               for name in ('dense_ms','fts_ms','rrf_ms','materialization_ms','total_ms')}
        lanes[lane]=dict(cases=len(selected),metrics=metrics,timings=times,
            query_understanding_failures=sum(r['outcome']['query_understanding_failure'] for r in selected),
            gold_mapping_gaps=sum(r['outcome']['gold_mapping_gaps'] for r in selected),
            incomplete_budget=sum(r['outcome']['incomplete_budget'] for r in selected),
            atom_only=sum(r['outcome']['atom_only'] for r in selected),
            lexical_collapse_cases=sum(r['outcome']['lexical_collapse']>0 for r in selected),
            candidate_diversity_total=sum(r['outcome']['candidate_diversity'] for r in selected))
    paired={}
    for row in rows:paired.setdefault(row['case'],{})[row['lane']]=row['outcome']['metrics']['materialized_span_hit_recall']
    regressions=[case for case,v in paired.items() if v['STRUCTURAL_CANARY'][0]<v['LEGACY_CONTROL'][0]]
    # A requires human interpretation of source-backed recall, not just a green
    # transport run. Any measured paired span loss conservatively returns B.
    understanding_failure=any(v['query_understanding_failures'] for v in lanes.values())
    found,required=lanes['STRUCTURAL_CANARY']['metrics']['materialized_span_hit_recall']
    unreturned=required-found
    return dict(decision='B' if regressions or understanding_failure or unreturned else 'A',metrics=lanes,
        structural_unreturned_mapped_span_count=unreturned,
        paired_materialized_regression_count=len(regressions),
        regression_cases=regressions[:64],foreign_stale_count=0,
        scoring_limitations='Span-hit recall only; 90 field assignments unreviewed; no generated answers or false-absence claims.')
