"""File-only Q1 replay. No channels, ranking, network, DB, providers or generation.

Reconstruct ONLY saved route children using frozen Phase-M memberships. Re-run
the original materializer first and require exact saved unit/byte equality.
GOLD is passed to the unchanged evaluator only after both selections finish.
Output is a new ignored Q1 family of identifiers/aggregates, never source text.
"""
import argparse
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter
from types import SimpleNamespace
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.canary_semantic_inventory import freeze
from scripts.canary_real_evaluation import snapshots, score_case
from scripts.canary_real_summary import percentile
from services.canary_contracts import Lane, Policy, Route
from services.canary_representation import atomic_projection, evidence_view
from services.canary_retrieval import Hit, materialize, reserve_witnesses
from services.compact_evidence_pack import (compact_unit, encoded, materialize_compact,
    requested_atoms, require)
from services.structural_chunking import digest


@dataclass(frozen=True)
class SavedManifest:
    """Replay-only identity carrier, NOT a live read lease or authorization."""
    identity: str
    hard_identity: str
    permitted: tuple
    documents: tuple
    run_id: str
    generation: str
    profile_hash: str
    policy: Policy = Policy()
    lane: Lane = Lane.STRUCTURAL_CANARY

    def canonical_hash(self): return self.identity

    def effective(self, hard):
        require(hard.identity() == self.hard_identity, 'REPLAY_HARD_SCOPE_CHANGED')
        return self.permitted


class SavedRepository:
    """Bounded local snapshot double. Live security is tested separately."""
    def __init__(self, batches, originals, manifest):
        self.batches, self.originals, self.manifest = batches, originals, manifest
        self.members = {(d,e.entry_key):tuple(sorted({m.atom_key for m in e.memberships}))
                        for d,b in batches.items() for e in b.entries}

    def read_gate(self, manifest, hard, *, now, expected_epoch=None):
        require(manifest == self.manifest, 'REPLAY_MANIFEST_CHANGED')
        manifest.effective(hard)
        require(expected_epoch in (None, 'SAVED_SOURCE_ONLY'), 'REPLAY_EPOCH_CHANGED')
        return 'SAVED_SOURCE_ONLY'

    def _route_pin(self, mf, hard, route, now):
        self.read_gate(mf,hard,now=now)
        doc=route.source.revision.source.document_id
        pin=next((p for p in mf.documents if p.scope==route.source),None)
        require(pin is not None and doc in mf.effective(hard), 'REPLAY_FOREIGN_SOURCE')
        require(route.manifest==mf.identity and route.run_id==mf.run_id and route.lane==mf.lane
                and route.generation==mf.generation and route.profile==mf.profile_hash,
                'REPLAY_FOREIGN_ROUTE')
        require((route.kind=='ENTRY' and route.key in pin.entries) or
                (route.kind=='ATOM_ONLY' and route.key in pin.atoms), 'REPLAY_UNDECLARED_ROUTE')
        return pin

    def children(self, mf, hard, route, *, now):
        self._route_pin(mf,hard,route,now)
        keys=(route.key,) if route.kind=='ATOM_ONLY' else self.members[
            route.source.revision.source.document_id,route.key]
        require(0<len(keys)<=32,'REPLAY_CHILD_BOUND')
        return keys

    def original(self, mf, hard, route, key, *, now):
        pin=self._route_pin(mf,hard,route,now)
        require(key in pin.atoms,'REPLAY_FOREIGN_ATOM')
        return self.originals[route.source.revision.source.document_id,key]

    def evidence(self, mf, hard, route, key, *, now):
        return evidence_view(self.original(mf,hard,route,key,now=now))


def replay_reader(repo,mf,hard,route,key,*,now):
    return repo.original(mf,hard,route,key,now=now)


def hashes(folder):
    return {str(p.relative_to(folder)).replace('\\','/'):sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob('*')) if p.is_file()}


def save(path,value):
    # Exclusive create: never overwrite a prior result or any Phase-P artifact.
    with path.open('xb') as stream: stream.write(encoded(value)+b'\n')


def byte_composition(payload):
    def category(path):
        if path[-1]=='text':return 'source_part_text' if path[0]=='source_parts' else 'node_text'
        if 'mappings' in path:return 'span_mapping_values'
        if 'provenance' in path:return 'provenance_values'
        if path[0]=='atom':return 'atom_source_identity_values'
        if path[-1] in ('chunk_key','bundle_key','heading_path','table_cells','identity','parent','original_payload_hash'):
            return 'structural_reference_values'
        if 'attributes' in path:return 'semantic_attribute_values'
        return 'structural_other_values'
    def walk(value,path=()):
        result=Counter()
        if isinstance(value,dict):
            for k,v in value.items():result.update(walk(v,path+(k,)))
        elif isinstance(value,list):
            for v in value:result.update(walk(v,path+('[]',)))
        else:result[category(path)]+=len(encoded(value))
        return result
    count=walk(payload);total=len(encoded(payload))
    count['json_keys_separators_container_syntax']=total-sum(count.values())
    count.update(total=total,units=1)
    return count


def replay(root,baseline):
    require(baseline.parent==root/'.codex_phase4p' and baseline.is_dir(), 'PHASE_P_BASELINE_REQUIRED')
    output=root/'.codex_phase4q'/('compact-replay-'+uuid.uuid4().hex)
    output.mkdir(parents=True,exist_ok=False)
    start=perf_counter();before=hashes(baseline)
    save(output/'phase-p-artifact-hashes.json',before)
    receipt=json.loads(next(baseline.glob('final-checkpoint-*.json')).read_text())
    require(receipt['pairs']==90 and receipt['lanes']==180 and receipt['canonical_tests']==3923,
            'PHASE_P_NOT_FINAL')
    report=root/receipt['report']
    require(sha256(report.read_bytes()).hexdigest()==receipt['report_working_bytes_sha256'],
            'PHASE_P_REPORT_CHANGED')
    cases={i:json.loads((baseline/f'case-{i:02d}-STRUCTURAL_CANARY.json').read_text()) for i in range(1,91)}
    batches,frozen=freeze(root)
    originals={(d,a.atom_key):atomic_projection(b,a) for d,b in batches.items() for a in b.atoms}
    groups={name:Counter() for name in ('all_atoms','included_in_any_case','byte_cap_lost_requested')}
    included={(u['route']['document'],u['key']) for r in cases.values() for u in r['trace']['materialized']}
    losses=[s|{'case':i} for i in cases for s in json.loads((baseline/f'final-analysis-case-{i:02d}.json').read_text())['structural_unreturned_support']]
    lost_requested={(s['document'],a) for s in losses if s['cause']=='WHOLE_EVIDENCE_BYTE_CAP' for a in s['requested_atoms']}
    for identity,payload in originals.items():
        count=byte_composition(evidence_view(payload))
        for name,include in [('all_atoms',True),('included_in_any_case',identity in included),
                             ('byte_cap_lost_requested',identity in lost_requested)]:
            if include:groups[name].update(count)
        # Every source and node string and semantic field is kept literally.
        compact=compact_unit(payload,'0'*64);view=evidence_view(payload)
        for rows_old,rows_new in [(view['source_parts'],compact['parts']),(view['nodes'],compact['nodes'])]:
            require(len(rows_old)==len(rows_new),'COMPACT_SEMANTIC_LOSS')
            require(all(all(old[k]==v for k,v in new.items()) for old,new in zip(rows_old,rows_new)),
                    'COMPACT_SEMANTIC_LOSS')
    save(output/'byte-composition.json',dict(groups=groups,frozen=frozen['counts'],verified_atoms=len(originals)))
    plan=json.loads((root/'backend/fixtures/canary_real_embedding_v1/plan.json').read_text())
    common={snapshot['id']:(snapshot,hard) for snapshot,hard in snapshots(root,plan)}
    gold={int(c['case_id']):c for c in json.loads((root/'backend/fixtures/canary_mechanics_v1/real_corpus_retrieval_gold.json').read_text())['cases']}
    pins=tuple(SimpleNamespace(scope=b.scope,entries=tuple(e.entry_key for e in b.entries),
        atoms=tuple(a.atom_key for a in b.atoms)) for b in batches.values())
    run_id=json.loads((baseline/'resume.json').read_text())['run_id']
    rows=[];old_totals=Counter();new_totals=Counter();removed_support=[];gain_support=[]
    recovered_byte_losses=[];remaining_byte_losses=[]
    def identity(u):return (u['route']['source']['revision']['source']['document_id'],u['key'])
    for i,saved in cases.items():
        st=saved['trace'];snapshot,hard=common[i]
        require(saved['snapshot_hash']==snapshot['snapshot_hash'] and st['hard_scope']==hard.identity(),
                'REPLAY_SNAPSHOT_CHANGED')
        generation=st['rrf'][0]['route']['generation']
        mf=SavedManifest(st['manifest'],hard.identity(),tuple(st['effective_scope']),pins,
                         run_id,generation,saved['query']['profile_hash'])
        repo=SavedRepository(batches,originals,mf)
        def full_route(r):
            result=Route(manifest=mf.identity,run_id=mf.run_id,lane=mf.lane,generation=r['generation'],
                profile=mf.profile_hash,source=batches[r['document']].scope,kind=r['kind'],key=r['key'])
            repo._route_pin(mf,hard,result,0)
            return result
        fused=[dict(row,route=full_route(row['route'])) for row in st['rrf']]
        lexical=tuple(Hit(full_route(h['route']),h['atom'],h['rank'],h['score']) for h in st['raw_fts'])
        witnesses=reserve_witnesses(lexical,mf.policy)
        requests,_=requested_atoms(fused,witnesses,repo,mf,hard,0)
        sequence=[dict(route=r.model_dump(mode='json'),key=k,reason=why) for r,k,why in requests]
        old=materialize(fused,witnesses,repo,mf,hard,0)
        def brief(u):
            r=u['route'];return dict(route=dict(document=r['source']['revision']['source']['document_id'],
                kind=r['kind'],key=r['key'],generation=r['generation']),key=u['key'])
        require([brief(u) for u in old['units']]==st['materialized'] and old['bytes']==st['bytes'],
                'PHASE_P_PACK_REPRODUCTION_FAILED')
        new=materialize_compact(fused,witnesses,repo,mf,hard,0,reader=replay_reader)
        for model,unit in zip(json.loads(new['model_bytes'])['units'],new['units']):
            record=new['sidecar'].resolve(model['provenance_ref'],repo,mf,hard,now=0,
                expected_atom=unit['key'],reader=replay_reader)
            require(encoded(record['original_payload'])==encoded(originals[identity(unit)]),
                    'REPLAY_PROVENANCE_CHANGED')
        # All GOLD/scoring occurs after selection, never in a materializer input.
        trace=dict(raw_dense=[dict(h,route=full_route(h['route']).model_dump(mode='json')) for h in st['raw_dense']],
            raw_fts=[dict(h,route=full_route(h['route']).model_dump(mode='json'),evidence_key=h['atom']) for h in st['raw_fts']],
            rrf=[dict(row,route=row['route'].model_dump(mode='json')) for row in fused],
            route_collapse_ratio=saved['outcome']['lexical_collapse'])
        scored=[]
        for result in (old,new):
            value=score_case(dict(trace,materialized=result,final_status='INCOMPLETE_BUDGET' if result['exclusions'] else 'COMPLETE'),
                gold[i],mf.lane.value,mf.effective(hard),repo.members)
            scored.append(value)
        require(scored[0]['metrics']==saved['outcome']['metrics'],'PHASE_P_SCORER_REPRODUCTION_FAILED')
        for counter,value in [(old_totals,scored[0]),(new_totals,scored[1])]:
            for name,(n,d) in value['metrics'].items():counter[name+'_n']+=n;counter[name+'_d']+=d
        support=[s for s in gold[i]['support'] if s['span_mapping']=='EXACT_UNIQUE_OCCURRENCE' and s['candidate_atoms'] and s['legacy_exact']]
        oldset={identity(u) for u in old['units']};newset={identity(u) for u in new['units']}
        deltas=[]
        for ordinal,s in enumerate(support,1):
            candidates={(s['development_document_id'],a['atom']) for a in s['candidate_atoms']}
            old_hit=bool(oldset&candidates);new_hit=bool(newset&candidates)
            value=dict(case=i,obligation=ordinal,document=s['development_document_id'],before=old_hit,after=new_hit)
            if old_hit and not new_hit: removed_support.append(value)
            if new_hit and not old_hit: gain_support.append(value)
            if old_hit!=new_hit:deltas.append(value)
            if any(v['case']==i and v['obligation']==ordinal and v['cause']=='WHOLE_EVIDENCE_BYTE_CAP' for v in losses):
                (recovered_byte_losses if new_hit else remaining_byte_losses).append(value)
        cap_counts=Counter(v.get('cap') for v in new['exclusions'])
        row=dict(case=i,old_bytes=old['bytes'],new_bytes=new['bytes'],old_units=len(old['units']),new_units=len(new['units']),
            old_metrics=scored[0]['metrics'],new_metrics=scored[1]['metrics'],support_deltas=deltas,
            old_exclusions=len(old['exclusions']),new_exclusions=dict(cap_counts),
            requested_sequence_hash=digest(sequence),requested_count=len(sequence),
            old_pack_exact_reproduction=True,provenance_recovery=True,
            upstream_saved_trace_hash=digest({k:st[k] for k in ('raw_dense','raw_fts','rrf','hard_scope')}),
            materialized=[brief(u) for u in new['units']],model_bytes_sha256=sha256(new['model_bytes']).hexdigest(),
            timings=new['timings'])
        save(output/f'case-{i:02d}.json',row);rows.append(row)
        if i%10==0:print(json.dumps(dict(progress=i,of=90)),flush=True)
    after=hashes(baseline)
    require(before==after and sha256(report.read_bytes()).hexdigest()==receipt['report_working_bytes_sha256'],
            'IMMUTABLE_PHASE_P_CHANGED')
    gate=(not removed_support and new_totals['materialized_span_hit_recall_n']>=old_totals['materialized_span_hit_recall_n']
          and new_totals['required_document_recall_n']>=old_totals['required_document_recall_n'])
    summary=dict(measurement='OFFLINE_SAVED_REQUEST_REPLAY_ONLY',real_rerun_gate='PASS' if gate else 'FAIL',
        baseline_checkpoint=receipt['checkpoint'],phase_p_artifacts_unchanged=len(before),phase_p_report_unchanged=True,
        old_pack_exact_reproduction=90,full_atom_text_semantics_verified=len(originals),scoped_sidecar_recovery=True,
        old_totals=dict(old_totals),new_totals=dict(new_totals),lost_previous_support=removed_support,gained_support=gain_support,
        original_byte_cap_losses_recovered=recovered_byte_losses,original_byte_cap_losses_remaining=remaining_byte_losses,
        old_byte_exclusions=sum(r['old_exclusions'] for r in rows),
        new_byte_exclusions=sum(r['new_exclusions'].get('BYTES',0) for r in rows),
        new_unit_exclusions=sum(r['new_exclusions'].get('UNITS',0) for r in rows),
        incomplete_cases=sum(bool(r['new_exclusions']) for r in rows),
        budget_unit_full_cases=sum(r['new_units']==48 for r in rows),
        ranges={k:[min(r[k] for r in rows),max(r[k] for r in rows)] for k in ('old_bytes','new_bytes','old_units','new_units')},
        times={k:dict(p50=percentile([r['timings'][k] for r in rows],.5),p95=percentile([r['timings'][k] for r in rows],.95),
            total=sum(r['timings'][k] for r in rows)) for k in rows[0]['timings']},
        materialization_database_ms=0,database_access=False,provider_calls=0,channel_calls=0,rrf_calls=0,
        total_replay_seconds=perf_counter()-start,output_folder=str(output.relative_to(root)))
    save(output/'summary.json',summary)
    print(json.dumps(summary),flush=True)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',required=True,help='Name of the retained Phase-P artifact directory')
    args=parser.parse_args();root=Path(__file__).resolve().parents[2]
    replay(root,(root/'.codex_phase4p'/args.baseline).resolve())
