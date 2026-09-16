"""OFFLINE saved-snapshot evaluation. No database, provider, vector or HTTP I/O."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.analyze_structural_packing import intervals
from services.structural_selection_v2 import select_structural_candidates,QUALIFICATION


def cost(count,tokens,legacy_count=1092,legacy_tokens=212061,v1_count=3242,v1_tokens=278491,dimension=768):
    return {'candidates':count,'tokens':tokens,'candidate_ratio_legacy':count/legacy_count,
        'token_ratio_legacy':tokens/legacy_tokens,'candidate_reduction_v1_pct':100*(1-count/v1_count),
        'token_reduction_v1_pct':100*(1-tokens/v1_tokens),'candidate_increase_legacy_pct':100*(count/legacy_count-1),
        'token_increase_legacy_pct':100*(tokens/legacy_tokens-1),'vector_dimension_assumption':dimension,
        'float32_vector_lower_bound_bytes':count*dimension*4,'count_target_gap':max(0,count-1638),
        'token_target_gap':max(0,tokens-275679)}


def analyze(batch):
    selection=select_structural_candidates(batch)
    selected_keys={k for c in selection.candidates for k in c.members}
    old=intervals(batch.chunks)
    retained=intervals([c for c in batch.chunks if c.chunk_key in selected_keys])
    if retained!=old:raise AssertionError('source coverage changed')
    by_id={c.chunk_key:c for c in batch.chunks}
    source_bytes=sum(b-a for values in old.values() for a,b in values)
    # Every removed heading mapping must have both exact translated source bytes
    # and lexical presence in its own descendant candidate (not another page).
    candidate_by_id={c.candidate_id:c for c in selection.candidates}
    heading_proxies=0
    for d in selection.ledger:
        if d.outcome!='metadata_only':continue
        original=by_id[d.v1_spec_id]
        for w in d.witnesses:
            r=original.mappings[w.mapping_index].mapping.output_slice
            text=original.text.encode()[r.start:r.end].decode()
            if text not in candidate_by_id[w.candidate_id].text:raise AssertionError('heading discoverability lost')
            heading_proxies+=1
    tiny=[]
    nodes={n.identity.node_key:n for n in batch.source_graph.nodes}
    def lineage(key):
        result=[]
        while key:
            result.append(key);parent=nodes[key].parent;key=parent.node_key if parent else None
        return result
    for d in selection.ledger:
        c=by_id[d.v1_spec_id]
        if c.token_count<50:
            primary={s.mapping.node.node_key for s in c.mappings if s.usage=='primary'}
            scope={a for k in primary for a in lineage(k)}
            tiny.append({'v1_spec_id':c.chunk_key,'kind':c.kind,'tokens':c.token_count,'outcome':d.outcome,
                'reason':d.reason,'heading_dependencies':d.heading_dependencies,
                'roles':sorted({nodes[k].semantic_role.value for k in primary}),
                'parents':sorted({nodes[k].parent.node_key for k in primary if nodes[k].parent}),
                'explicit_subjects':sorted({e.to_node.node_key for e in batch.source_graph.edges if e.from_node.node_key in scope and e.relation.value=='DESCRIBES' and e.validation_state.value=='validated'}),
                'quality':sorted({next((nodes[a].quality for a in lineage(k) if nodes[a].quality),batch.source_graph.revision.quality).canonical_json() for k in primary}),
                'qualification':bool(QUALIFICATION.search(c.text)),
                'relationships':sorted({e.relation.value for e in batch.source_graph.edges if e.from_node.node_key in primary or e.to_node.node_key in primary}),
                'prefix_disposition':d.prefix_disposition})
    return {'v1_count':len(batch.chunks),'v1_tokens':sum(c.token_count for c in batch.chunks),
        'v2_count':len(selection.candidates),'v2_tokens':sum(c.token_count for c in selection.candidates),
        'outcomes':dict(Counter(d.outcome for d in selection.ledger)),
        'packed_groups':sum(len(c.members)>1 for c in selection.candidates),
        'deduplicated_prefixes':sum(c.deduplicated_prefixes for c in selection.candidates),
        'v1_prefix_tokens':sum(c.prefix_tokens for c in batch.chunks),
        'v2_prefix_tokens':sum(c.prefix_tokens for c in selection.candidates),
        'v1_tiny':len(tiny),'v2_tiny':sum(c.token_count<50 for c in selection.candidates),
        'kinds':dict(Counter(c.kind for c in selection.candidates)),
        'peer_status':dict(Counter(p.status for p in selection.peers)),
        'peer_reasons':dict(Counter(p.reason for p in selection.peers)),
        'tiny_reasons':dict(Counter(t['reason'] for t in tiny)),
        'nodes':len(batch.source_graph.nodes),'edges':len(batch.source_graph.edges),
        'graph_only_nodes':len(selection.graph_only_nodes),'source_bytes':source_bytes,
        'v1_mapping_occurrences':sum(len(c.mappings) for c in batch.chunks),
        'selected_translations':sum(len(c.translations) for c in selection.candidates),
        'metadata_witnesses':sum(len(d.witnesses) for d in selection.ledger),
        'source_coverage_equal':True,'evidence_bytes_dropped':0,'heading_proxy_pass':heading_proxies,
        'batch_hash':batch.canonical_hash(),'graph_hash':batch.source_graph.canonical_hash(),
        'selection_hash':selection.canonical_hash(),'recipe_hash':selection.recipe_hash,
        'selection':selection.model_dump(mode='json'),'tiny_ledger':tiny}


def run(snapshot,prior_path):
    from services.structural_shadow import ShadowSource,build_shadow
    payload=json.loads(snapshot.read_text(encoding='utf-8'))
    prior=json.loads(prior_path.read_text(encoding='utf-8'))
    rows=[]
    for doc in payload['documents']:
        source=ShadowSource(70001,70002,doc['id'],1,doc['raw_text'].encode(),'markdown','extracted_markdown')
        batch,_=build_shadow(source)
        row=analyze(batch);row['document_id']=doc['id']
        old=next(r for r in prior['documents'] if r['document_id']==doc['id'])
        assert row['batch_hash']==old['serialization_hash'] and row['graph_hash']==old['structural_hash'],'frozen v1 replay changed'
        row['legacy_chunks']=old['legacy_chunks'];row['legacy_tokens']=old['legacy_tokens'];rows.append(row)
    totals={k:sum(r[k] for r in rows) for k in ('v1_count','v1_tokens','v2_count','v2_tokens','packed_groups',
        'deduplicated_prefixes','v1_prefix_tokens','v2_prefix_tokens','v1_tiny','v2_tiny','nodes','edges','graph_only_nodes',
        'source_bytes','v1_mapping_occurrences','selected_translations','metadata_witnesses','evidence_bytes_dropped','heading_proxy_pass')}
    for key in ('outcomes','kinds','peer_status','peer_reasons','tiny_reasons'):
        counter=Counter()
        for row in rows:counter.update(row[key])
        totals[key]=dict(counter)
    assert len(rows)==23 and (totals['v1_count'],totals['v1_tokens'])==(3242,278491)
    return {'offline_only':True,'snapshot_sha256':hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        'documents':rows,'totals':totals,'cost':cost(totals['v2_count'],totals['v2_tokens']),
        'source_coverage_equal':all(r['source_coverage_equal'] for r in rows)}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',type=Path,required=True);p.add_argument('--prior',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    result=run(args.snapshot,args.prior)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='documents'},sort_keys=True))
