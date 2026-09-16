"""Phase I frozen-file evaluator. No DB, URL resolution or provider imports.

I_SIMULATION is a study result, not an accepted or replacement H selection.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path

from scripts.analyze_structural_packing import intervals
from scripts.structural_identity_study import (
    IdentityStudy, Registry, Resource, RootProof, StudyPeerEngine, classify_heading,
)
from services.structural_selection_v2 import select_structural_candidates
from services.structural_shadow import ShadowSource, build_shadow


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def saved_registry(snapshot, projection, mapping, fingerprint, batches, artifact_hash):
    """Verify the existing explicit source->development map before study rebasing.

    The rebasing changes DTO study namespace only, exactly as frozen H replay;
    it does not authorize any live document or invent a business-subject mapping.
    Only document-primary records from this captured projector are accepted.
    """
    assert projection['source_corpus_unchanged'] is True
    assert projection['source_corpus_fingerprint']==fingerprint['fingerprint']
    source_scope=(fingerprint['source_organization_id'],fingerprint['source_bot_id'])
    dev_scope=(fingerprint['development_organization_id'],fingerprint['development_bot_id'])
    assert mapping['organization'][str(source_scope[0])]==dev_scope[0]
    assert mapping['bot'][str(source_scope[1])]==dev_scope[1]
    catalog=projection['catalog']
    for table in catalog.values():
        assert all((row['organization_id'],row['bot_id'])==dev_scope for row in table),'foreign frozen catalog row'
    docs={mapping['corpus']['documents'][str(d['id'])]:d for d in snapshot['documents']}
    assert len(docs)==len(snapshot['documents'])==len(batches)
    resources=[];proofs=[];refused=[]
    for row in catalog['knowledge_resources']:
        assert row['status']=='ready' and row['resource_type']=='document','unsupported catalog semantics'
        links=[x for x in catalog['knowledge_resource_documents'] if x['resource_id']==row['id']]
        assert len(links)==1 and links[0]['relation_type']=='primary','non-unique document mapping'
        link=links[0];doc=docs[link['document_id']];batch=batches[doc['id']]
        assert (doc['organization_id'],doc['bot_id'])==source_scope
        assert doc['status']=='ready' and doc['processing_status']=='completed'
        assert link['document_version']==doc['version']
        crawl=mapping['corpus']['website_crawls'].get(str(doc['crawl_id'])) if doc['crawl_id'] is not None else None
        assert link['document_crawl_id']==crawl,'stale crawl mapping'
        assert row['source_key']==f"document:{link['document_id']}"
        assert row['metadata_json']=={'primary_document_id':link['document_id']}
        assert row['url']==doc['canonical_url'],'canonical URL mismatch; do not guess or normalize'
        source=batch.source_graph.revision.identity.source
        if source.source_version!=doc['version']:
            # H's historical replay used a synthetic version label. Never relabel
            # its immutable graph or pretend that a differently versioned catalog
            # descriptor is exact authority. The source stays in the study, with
            # this resource mapping explicitly withheld (not silently remapped).
            refused.append({'resource_id':row['id'],'document_id':doc['id'],
                'catalog_document_version':doc['version'],'study_source_version':source.source_version,
                'reason':'source_version_mismatch'})
            continue
        key='catalog:'+str(row['id'])
        resources.append(Resource(key=key,version=row['version'],anchor=batch.source_graph.nodes[0].identity,
            canonical_url=row['url'] or '',mapped_sources=(source,)))
        # This is a SOURCE_DOCUMENT descriptor, not proof of single-subject scope.
        proofs.append(RootProof(source=source,resource_key=key,semantics='source_document_only'))
    assert len(resources)+len(refused)==len(docs) and len(catalog['knowledge_resource_documents'])==len(docs)
    registry=Registry(artifact_hash=artifact_hash,organization_id=70001,bot_id=70002,
        allowed_sources=tuple(b.source_graph.revision.identity.source for b in batches.values()),
        known_anchors=tuple(b.source_graph.nodes[0].identity for b in batches.values()),
        resources=tuple(resources),root_proofs=tuple(proofs))
    return registry,refused


def simulate(batch, identity, headings):
    """Reuse every H peer/pack guard; new answerability only in I_SIMULATION.

    Verify each original logical mapping, including suppressed heading witnesses,
    against exact translated source bytes. Never call H run() on the study adapter.
    """
    engine=StudyPeerEngine(batch,identity);by_id={c.chunk_key:c for c in batch.chunks}
    remove={r['spec_id']:r for r in headings if r['decision']=='METADATA_ONLY_PROPOSED'}
    for row in remove.values():
        assert row['witness'] and all(k not in remove and by_id[k].kind!='heading' for k,_ in row['witness'])
    retained=[c for c in batch.chunks if c.chunk_key not in remove]
    groups=[]
    for c in retained:
        if groups and engine.peer(groups[-1][-1],c).status=='eligible' and engine.pack(tuple(groups[-1]+[c])):
            groups[-1].append(c)
        else:groups.append([c])
    candidates=[];translated={}
    for group in groups:
        p=engine.pack(tuple(group));assert p is not None
        # Do not expose H-derived candidate IDs as a new accepted version.
        row={'members':[c.chunk_key for c in group],'kind':group[0].kind,'tokens':p.token_count,
            'text':p.text,'translations':[t.model_dump(mode='json') for t in p.translations]}
        candidates.append(row)
        for t in p.translations:
            c=by_id[t.v1_spec_id];m=c.mappings[t.mapping_index].mapping
            value=c.text.encode()[m.output_slice.start:m.output_slice.end]
            assert value==p.text.encode()[t.output_slice.start:t.output_slice.end]
            translated[(t.v1_spec_id,t.mapping_index)]=value
    witnesses=0
    for key,row in remove.items():
        original=by_id[key];assert len(original.mappings)==len(row['witness'])
        assert len({k for k,_ in row['witness']})==1
        for i,(target,j) in enumerate(row['witness']):
            old=original.mappings[i].mapping;new=by_id[target].mappings[j].mapping
            assert (old.node,old.node_slice,old.role)==(new.node,new.node_slice,new.role)
            assert original.text.encode()[old.output_slice.start:old.output_slice.end]==translated[(target,j)]
            witnesses+=1
    assert intervals(batch.chunks)==intervals(retained),'mapped source evidence lost'
    assert sum(len(c.mappings) for c in batch.chunks)==len(translated)+witnesses
    primary={m.mapping.node.node_key for c in retained for m in c.mappings if m.usage=='primary'}
    return {'version':'I_SIMULATION_NOT_ACCEPTED_V2','candidates':candidates,
        'count':len(candidates),'tokens':sum(c['tokens'] for c in candidates),
        'heading_candidates':sum(c['kind']=='heading' for c in candidates),'metadata_only':len(remove),
        'packed_groups':sum(len(c['members'])>1 for c in candidates),'tiny':sum(c['tokens']<50 for c in candidates),
        'graph_only':len(batch.source_graph.nodes)-len(primary),'mapping_translations':len(translated),
        'heading_mapping_witnesses':witnesses,'evidence_bytes_dropped':0,'source_coverage_equal':True}


def run(root):
    corpus=root/'.codex_real_corpus_v1';out=root/'.codex_structural_4_1i'
    paths={'source':corpus/'SOURCE_PRODUCTION_SNAPSHOT.json','projection':corpus/'PHASE37_PROJECTION.json',
        'mapping':corpus/'SOURCE_TO_DEVELOPMENT_ID_MAPPING.json','fingerprint':corpus/'REAL_CORPUS_V1_FINGERPRINT.json',
        'h':root/'.codex_structural_4_1h/selection_final.json','sample':out/'heading_sample_frozen.json'}
    hashes={k:sha(p) for k,p in paths.items()}
    assert hashes['h']=='83d8c98dd7de9c82a6c65c309d4ed2367016612990ab6ee43aa3789e0e47fcd8'
    assert hashes['sample']=='756dae53035252246c7aad3007ef2e9cc4893e12b67c8d812f6124e8aa9a70ff'
    snapshot=read(paths['source']);prior=read(paths['h']);sample=read(paths['sample'])
    assert hashes['source']==prior['snapshot_sha256']
    batches={};h_results={}
    for doc in snapshot['documents']:
        source=ShadowSource(70001,70002,doc['id'],1,doc['raw_text'].encode(),'markdown','extracted_markdown')
        batch,_=build_shadow(source);old=next(r for r in prior['documents'] if r['document_id']==doc['id'])
        h=select_structural_candidates(batch)
        assert batch.canonical_hash()==old['batch_hash'] and batch.source_graph.canonical_hash()==old['graph_hash']
        assert h.canonical_hash()==old['selection_hash'],'H frozen replay changed'
        batches[doc['id']]=batch;h_results[doc['id']]=h
    registry,refused=saved_registry(snapshot,read(paths['projection']),read(paths['mapping']),read(paths['fingerprint']),batches,hashes['projection'])
    rows=[];heading_rows=[];pairs=[];sample_ids={r['spec_id'] for r in sample['sample']}
    for doc_id,batch in batches.items():
        identity=IdentityStudy(batch,registry);engine=StudyPeerEngine(batch,identity);h=h_results[doc_id]
        headings=[dict(classify_heading(batch,n,identity,engine),document_id=doc_id,text=n.text)
            for n in batch.source_graph.nodes if n.node_type.value=='heading' and any(c.kind=='heading' and any(m.usage=='primary' and m.mapping.node==n.identity for m in c.mappings) for c in batch.chunks)]
        heading_rows.extend(headings);specs={c.chunk_key:c for c in batch.chunks}
        for p in h.peers:
            if p.status!='unknown_identity':continue
            a,z=identity.for_spec(specs[p.left]),identity.for_spec(specs[p.right])
            same=a.state==z.state=='RESOLVED' and a.subjects==z.subjects
            different=a.state==z.state=='RESOLVED' and a.subjects!=z.subjects
            decision=engine.peer(specs[p.left],specs[p.right])
            pairs.append({'document_id':doc_id,'left':p.left,'right':p.right,'left_evidence':a.model_dump(mode='json'),
                'right_evidence':z.model_dump(mode='json'),'identity_result':'same' if same else ('different' if different else 'unresolved'),
                'peer_status':decision.status,'peer_reason':decision.reason})
        annotations={c.chunk_key:identity.for_spec(c).model_dump(mode='json') for c in batch.chunks}
        # H saved corpus has no packed groups; assert rather than silently treating
        # a multi-spec candidate as if it had only its first spec's identity.
        assert all(len(c.members)==1 for c in h.candidates)
        simulation=simulate(batch,identity,headings)
        rows.append({'document_id':doc_id,'graph_hash':batch.source_graph.canonical_hash(),
            'v1_subjects':dict(Counter(v['state'] for v in annotations.values())),
            'h_subjects':dict(Counter(annotations[c.members[0]]['state'] for c in h.candidates)),
            'reference_states':dict(Counter(v.state for v in identity.references.values())),
            'node_subjects':dict(Counter(v.state for v in identity.annotations.values())),
            'graph_only_subjects':dict(Counter(identity.annotations[k].state for k in h.graph_only_nodes)),
            'annotations':annotations,'bounded_groups':{k:v for k,v in identity.direct.items()},
            'simulation':simulation})
    totals={}
    for key in ('v1_subjects','h_subjects','reference_states','node_subjects','graph_only_subjects'):
        c=Counter()
        for row in rows:c.update(row[key])
        totals[key]=dict(c)
    totals['heading_categories']=dict(Counter(r['category'] for r in heading_rows))
    totals['heading_decisions']=dict(Counter(r['decision'] for r in heading_rows))
    totals['h_unknown_pairs']=dict(Counter(r['identity_result'] for r in pairs))
    totals['newly_eligible_pairs']=sum(r['peer_status']=='eligible' for r in pairs)
    totals['simulation']={k:sum(r['simulation'][k] for r in rows) for k in ('count','tokens','heading_candidates','metadata_only','packed_groups','tiny','graph_only','mapping_translations','heading_mapping_witnesses','evidence_bytes_dropped')}
    sim=totals['simulation'];sim['vector_lower_bound_bytes_768_float32']=sim['count']*768*4
    sim['candidate_gap']=max(0,sim['count']-1638);sim['token_gap']=max(0,sim['tokens']-275679)
    selected=[r for r in heading_rows if r['spec_id'] in sample_ids]
    assert len(selected)==len(sample_ids)==56 and len(heading_rows)==754 and len(pairs)==46
    assert hashes=={k:sha(p) for k,p in paths.items()},'frozen inputs changed'
    # Avoid duplicating corpus metadata; only source-backed audit DTOs are emitted.
    for row in rows:
        row['bounded_groups']={k:{'subjects':sorted(v['subjects']),'basis':sorted(v['basis']),
            'evidence_nodes':[n.model_dump(mode='json') for n in sorted(v['evidence'],key=lambda x:x.canonical_json())],
            'incomplete':v['incomplete']} for k,v in row['bounded_groups'].items()}
    return {'version':'PHASE_4_1I_OFFLINE_STUDY_V1','input_hashes':hashes,'registry_hash':registry.canonical_hash(),
        'catalog_resources':len(registry.resources),'refused_catalog_mappings':refused,
        'single_resource_proofs':sum(p.semantics=='single_resource' for p in registry.root_proofs),
        'sample_categories':dict(Counter(r['category'] for r in selected)),'sample_size':len(selected),'sample':selected,
        'totals':totals,'documents':rows,'headings':heading_rows,'unknown_pairs':pairs,'h_replay_identical':True}


if __name__=='__main__':
    root=Path(__file__).resolve().parents[2]
    result=run(root)
    (root/'.codex_structural_4_1i/study_final.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(result['totals'],sort_keys=True))
