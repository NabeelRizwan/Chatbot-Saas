"""Offline J evidence/boundary measurement. Writes only ignored J study output.

Run under external socket/DNS denial. No database, acquisition, provider or
serving integration. H/I artifacts remain byte-for-byte frozen.
"""
from collections import Counter
import json
from pathlib import Path

from scripts.structural_descriptor_corpus import read, file_hash, load_corpus
from scripts.structural_resource_descriptors import DescriptorStudy, DescriptorPeerEngine, BoundaryProof, pair_state, Subject
from scripts.structural_identity_study import classify_heading
from scripts.evaluate_structural_identity_study import simulate
from services.structural_selection_v2 import _Selection, SelectionPolicy, select_structural_candidates
from services.structural_shadow import ShadowSource, build_shadow


GOLD=Path(__file__).resolve().parents[1]/'fixtures/structural_resource_descriptor_gold_v1'


def inventory(study,did):
    graph=study.batches[did].source_graph;result=[]
    def add(n,kind,target=None):
        result.append({'kind':kind,'node':n.identity.model_dump(mode='json'),
            'source_spans':[s.model_dump(mode='json') for s in n.provenance.spans],
            'structural_members':[k.node_key for k in study.descendants(n.identity)],
            'boundary_proven':any(d.proof.root==n.identity for d in study.descriptors),
            'target':target.model_dump(mode='json') if target else None})
    for n in graph.nodes:
        if n.parent is None:add(n,'document_root')
        elif n.semantic_role.value=='review':add(n,'review_group')
        elif n.semantic_role.value=='product_card':add(n,'explicit_card')
        elif n.node_type.value=='section' and any(study.nodes[k].attributes.link for k in study.children[n.identity]):
            add(n,'linked_section_candidate_not_proof')
        elif n.node_type.value=='heading' and any(study.nodes[k].attributes.link for k in study.children[n.identity]):
            add(n,'linked_heading_candidate_not_card_proof')
        if n.attributes.link:
            t=study.target(n.attributes.link.original_href,n.identity)
            # "Unclassified" is deliberate: a source link without an explicit
            # navigation role cannot be declared navigation by URL shape.
            kind='navigation_link' if n.semantic_role.value=='navigation' else (
                'ambiguous_link' if t.state=='AMBIGUOUS' else 'cross_document_reference'
                if t.state in {'EXACT_RESOURCE','VERIFIED_FRAGMENT'} and any(study.resources[k].pin!=study.pins[did] for k in t.resources)
                else 'unclassified_reference')
            add(n,kind,t)
    return result


def simulation(batch,study,headings):
    # Existing I simulation already translates/verifies EVERY logical mapping.
    # Its H adapter has identical identity equality semantics to J; do not copy
    # or loosen the selector. Relabel only this new result, never its input graph.
    value=simulate(batch,study,headings)
    value['version']='J_MANUAL_GOLD_STUDY' if study.manual else 'J_AUTO_STUDY'
    states=Counter(combine_candidate(study,batch,c).state for c in value['candidates'])
    value['subject_states']=dict(states)
    return value


def combine_candidate(study,batch,c):
    from scripts.structural_resource_descriptors import combine
    lookup={s.chunk_key:s for s in batch.chunks}
    return combine(study.for_spec(lookup[k]) for k in c['members'])


def compare_reconstruction(old,new):
    """Bijection by exact parser path/order/content/ranges, NOT relabeling H."""
    assert len(old.source_graph.nodes)==len(new.source_graph.nodes)
    mapping={}
    for a,b in zip(old.source_graph.nodes,new.source_graph.nodes):
        def payload(n):
            row=n.model_dump(mode='json')
            row.pop('identity');row['parent']=n.parent.node_key if n.parent else None
            row['provenance']['spans']=[{'location':s['location']} for s in row['provenance']['spans']]
            return row
        left,right=payload(a),payload(b)
        left['parent']=mapping.get(left['parent']) if left['parent'] else None
        assert left==right,'native parser payload changed'
        mapping[a.identity.node_key]=b.identity.node_key
    assert len(old.source_graph.edges)==len(new.source_graph.edges)
    def edge_payload(e, translate):
        return json.dumps({'from':translate[e.from_node.node_key], 'to':translate[e.to_node.node_key],
            'relation':e.relation.value,'field':e.field,'role':e.role.value if e.role else None,
            'validation':e.validation_state.value,'method':e.provenance.method,
            'locations':[s.location.model_dump(mode='json') for s in e.provenance.spans]},sort_keys=True)
    native_keys={n.identity.node_key:n.identity.node_key for n in new.source_graph.nodes}
    # Canonical edge sorting uses identity hashes; a NEW version/namespace can
    # legitimately reorder edges. Compare the exact translated multiset instead.
    assert Counter(edge_payload(e,mapping) for e in old.source_graph.edges)==Counter(edge_payload(e,native_keys) for e in new.source_graph.edges)
    assert len(old.chunks)==len(new.chunks)
    for a,b in zip(old.chunks,new.chunks):
        assert (a.text,a.kind,a.token_count,a.ordinal,a.part_count,a.complete_unit)==(b.text,b.kind,b.token_count,b.ordinal,b.part_count,b.complete_unit)
        assert len(a.mappings)==len(b.mappings)
        for x,y in zip(a.mappings,b.mappings):
            assert (mapping[x.mapping.node.node_key],x.usage,x.mapping.node_slice,x.mapping.output_slice,x.mapping.role)==(
                y.mapping.node.node_key,y.usage,y.mapping.node_slice,y.mapping.output_slice,y.mapping.role)
    return mapping


def run(root):
    frozen=read(root/'.codex_structural_4_1j/preservation_before.json')
    assert all(file_hash(root/p)==h for p,h in frozen.items()),'preservation before evaluation'
    gold=read(GOLD/'manifest.json')
    assert file_hash(GOLD/'cases.json')==gold['synthetic_cases_sha256']
    assert file_hash(GOLD/'manual_saved.json')==gold['manual_saved_sha256']
    snapshot=read(root/'.codex_real_corpus_v1/SOURCE_PRODUCTION_SNAPSHOT.json')
    assert file_hash(root/'.codex_real_corpus_v1/SOURCE_PRODUCTION_SNAPSHOT.json')==gold['saved_snapshot_sha256']
    prior=read(root/'.codex_structural_4_1h/selection_final.json')
    previous_i=read(root/'.codex_structural_4_1i/study_final.json')
    batches,pins,resources,reconciliation=load_corpus(root)
    auto=DescriptorStudy(batches,pins,resources)
    manual=DescriptorStudy(batches,pins,resources,manual=True)
    for did in batches:
        auto.automatic(did);manual.automatic(did)
    for row in read(GOLD/'manual_saved.json')['descriptors']:
        manual.add(BoundaryProof.model_validate(row['proof']))
    rows=[];pairs=[];broader=[];oracle=[];heading_hypotheses=[]
    for source_doc in snapshot['documents']:
        did=source_doc['id'];b=batches[did]
        old,_=build_shadow(ShadowSource(70001,70002,did,1,source_doc['raw_text'].encode(),'markdown','extracted_markdown'))
        h=select_structural_candidates(old)
        saved=next(d for d in prior['documents'] if d['document_id']==did)
        assert old.canonical_hash()==saved['batch_hash'] and h.canonical_hash()==saved['selection_hash']
        node_mapping=compare_reconstruction(old,b)
        engine=_Selection(b,SelectionPolicy())
        headings=[dict(classify_heading(b,n,engine=engine),text=n.text) for n in b.source_graph.nodes if n.node_type.value=='heading'
            and any(c.kind=='heading' and any(m.usage=='primary' and m.mapping.node==n.identity for m in c.mappings) for c in b.chunks)]
        previous=[r for r in previous_i['headings'] if r['document_id']==did]
        assert len(previous)==len(headings)
        for before,after in zip(previous,headings):
            assert (node_mapping[before['node_key']],before['category'],before['decision'])==(after['node_key'],after['category'],after['decision'])
            if manual.subject(next(n.identity for n in b.source_graph.nodes if n.identity.node_key==after['node_key'])).state=='RESOLVED':
                heading_hypotheses.append({'document_id':did,'node':after['node_key'],'decision_unchanged':after['decision'],'hypothesis':'bounded_context_only_NOT_applied'})
        engines={'auto':DescriptorPeerEngine(b,auto),'manual':DescriptorPeerEngine(b,manual)}
        old_by={c.chunk_key:c for c in old.chunks}
        # Diagnostic identity oracle: NOT evidence, NOT a descriptor, never used
        # in AUTO/MANUAL simulation. All other H decisions remain in force.
        class Oracle(DescriptorPeerEngine):
            def boundary(self,c):
                roots,_,roles,quality=_Selection.boundary(self,c)
                return roots,('COUNTERFACTUAL_SAME_SUBJECT_NOT_PROVEN',),roles,quality
        hypothetical=Oracle(b,auto)
        for p in h.peers:
            a=b.chunks[old_by[p.left].ordinal];z=b.chunks[old_by[p.right].ordinal]
            row={'document_id':did,'historical_left':p.left,'historical_right':p.right,
                'native_left':a.chunk_key,'native_right':z.chunk_key,'h_first_failure':p.reason,'h_first_status':p.status}
            for mode,study in [('auto',auto),('manual',manual)]:
                sa,sz=study.for_spec(a),study.for_spec(z)
                decision=engines[mode].peer(a,z)
                row[mode]={'identity':pair_state(sa,sz),'peer_status':decision.status,'peer_reason':decision.reason}
            if p.status=='unknown_identity':
                pairs.append(row)
                d=hypothetical.peer(a,z)
                oracle.append({'document_id':did,'left':a.chunk_key,'right':z.chunk_key,'status':d.status,'reason':d.reason})
            else:broader.append(row)
        simulations={mode:simulation(b,s,headings) for mode,s in [('auto',auto),('manual',manual)]}
        rows.append({'document_id':did,'inventory':inventory(auto,did),'simulations':simulations,
            'v1_subjects':{mode:dict(Counter(s.for_spec(c).state for c in b.chunks)) for mode,s in [('auto',auto),('manual',manual)]},
            'h_graph_payload_bijection':True,'source_version':pins[did].revision.source.source_version})
    totals={}
    for mode,study in [('auto',auto),('manual',manual)]:
        sims=[r['simulations'][mode] for r in rows]
        totals[mode]={k:sum(s[k] for s in sims) for k in ('count','tokens','metadata_only','heading_candidates','packed_groups','tiny','mapping_translations','heading_mapping_witnesses','evidence_bytes_dropped')}
        for key in ['subject_states']:
            c=Counter()
            for s in sims:c.update(s[key])
            totals[mode][key]=dict(c)
        totals[mode]['descriptor_states']=dict(Counter(d.state for d in study.descriptors))
        totals[mode]['unknown_pairs']=dict(Counter(r[mode]['identity'] for r in pairs))
        totals[mode]['newly_eligible']=sum(r[mode]['peer_status']=='eligible' for r in pairs)
        totals[mode]['peer_decisions']=dict(Counter(r[mode]['peer_status'] for r in pairs))
    kinds=Counter();links=Counter();fragment=Counter()
    for row in rows:
        for item in row['inventory']:
            kinds[item['kind']]+=1
            if item['target']:
                t=item['target'];links[t['state']]+=1
                if t['fragment'] is not None:fragment[t['state']]+=1
    assert len(pairs)==46
    assert all(file_hash(root/p)==h for p,h in frozen.items()),'frozen inputs changed'
    manual_only=[d for d in manual.descriptors if 'MANUAL_FROZEN_GOLD' in d.proof.basis]
    return {'version':'PHASE_4_1J_OFFLINE_DESCRIPTOR_STUDY_V1','checkpoint':gold['checkpoint'],
        'preservation_files':len(frozen),'preservation_unchanged':True,'source_native_reconciliation':reconciliation,
        'namespace':'phase-j-native: explicit source->development mapping; no H graph relabel',
        'source_count':len(rows),'catalog_lineage_targets':len(resources),'single_resource_roots_proven':0,
        'single_resource_roots_refused':len(rows),'root_refusal':'No saved primary-subject assertion and complete noncontradictory inventory proof.',
        'inventory_counts':dict(kinds),'link_states':dict(links),'fragment_states':dict(fragment),
        'totals':totals,'auto_descriptors':[dict(d.model_dump(mode='json'),descriptor_hash=d.canonical_hash()) for d in auto.descriptors],
        'manual_frozen_descriptors':[dict(d.model_dump(mode='json'),descriptor_hash=d.canonical_hash()) for d in manual_only],
        'manual_limit':'Two reviewed blocks only. Not an exhaustive perfect-descriptor upper bound.',
        'h_unknown_pairs':pairs,'broader_peers':broader,'broader_first_failures':dict(Counter(r['h_first_failure'] for r in broader)),
        'broader_identity_diagnostics':{mode:dict(Counter(r[mode]['identity'] for r in broader)) for mode in ('auto','manual')},
        'counterfactual_unknown_pair_guards':dict(Counter(r['status'] for r in oracle)),
        'counterfactual_unknown_pair_reasons':dict(Counter(r['reason'] for r in oracle)),
        'counterfactual_unknown_pairs':oracle,'absolute_unknown_edge_savings_ceiling':46,
        'counterfactual_note':'Same identity assumed only to inspect later H guards. No source proof and no accepted packing result.',
        'heading_hypotheses_not_applied':heading_hypotheses,'heading_decisions_match_I':True,'documents':rows}


if __name__=='__main__':
    root=Path(__file__).resolve().parents[2]
    result=run(root)
    (root/'.codex_structural_4_1j/study_final.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    keys=('source_count','preservation_files','inventory_counts','link_states','fragment_states','totals',
          'broader_first_failures','broader_identity_diagnostics','counterfactual_unknown_pair_guards','counterfactual_unknown_pair_reasons')
    print(json.dumps({k:result[k] for k in keys},sort_keys=True))
