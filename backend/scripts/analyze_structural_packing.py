"""Phase 4.1G OFFLINE analysis, not a serializer or runtime policy.

Consumes immutable v1 batches. Returns hypothetical groups of EXISTING specs,
never Chunk rows, vectors, v2 DTOs or runtime configuration. Ambiguous identity
is not permission to merge. No database, HTTP, provider or application imports.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.structural_chunking import count_tokens

BASELINE = {'documents': 23, 'chunks': 3242, 'tokens': 278491, 'tiny': 1452,
            'heading': 754, 'theoretical_pairs': 3156}
KINDS = {'prose':1525,'heading':754,'price_block':405,'list':259,
         'directions':105,'review':86,'faq':78,'timeline_stage':30}
CRITICAL = {'warning','review','faq_question','faq_answer','timeline_stage',
            'directions','ingredients','price_block','product_card'}


@dataclass(frozen=True)
class EvidenceUnit:
    ordinal: int
    scope: str
    kind: str
    parent: tuple
    section: tuple
    subjects: tuple
    roles: tuple
    quality: tuple
    barrier: bool
    complete: bool
    tokens: int


def merge_reason(a, b):
    """Fail-closed compatibility; a returned reason means NOT eligible."""
    if a.scope != b.scope: return 'source_or_revision'
    if b.ordinal != a.ordinal+1: return 'not_adjacent'
    if a.kind != 'prose' or b.kind != 'prose': return 'atomic_kind'
    if not a.complete or not b.complete: return 'multipart'
    if a.parent != b.parent or not a.parent: return 'parent'
    if a.section != b.section or not a.section: return 'section'
    if not a.subjects or not b.subjects: return 'no_explicit_subject'
    if a.subjects != b.subjects: return 'subject'
    if a.roles != b.roles or set(a.roles) & CRITICAL: return 'role'
    if a.quality != b.quality: return 'quality'
    if a.barrier or b.barrier: return 'relationship_or_qualification'
    if a.tokens+b.tokens > 650: return 'budget'
    return None


def intervals(chunks):
    result=defaultdict(list)
    for chunk in chunks:
        for span in chunk.mappings:
            m=span.mapping
            result[m.node.canonical_json()].append((m.node_slice.start,m.node_slice.end))
    return {k:merge_intervals(v) for k,v in result.items()}


def merge_intervals(values):
    merged=[]
    for a,b in sorted(values):
        if merged and a<=merged[-1][1]: merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
        else: merged.append((a,b))
    return tuple(merged)


def covered(chunk, coverage):
    return all(any(lo<=s.mapping.node_slice.start and hi>=s.mapping.node_slice.end
                   for lo,hi in coverage.get(s.mapping.node.canonical_json(),())) for s in chunk.mappings)


def analyze_batch(batch):
    batch.verify()
    nodes={n.identity.node_key:n for n in batch.source_graph.nodes}
    chunks=batch.chunks
    def ancestors(key):
        keys=[]
        while key:
            keys.append(key);p=nodes[key].parent;key=p.node_key if p else None
        return keys
    def primary(c): return {s.mapping.node.node_key for s in c.mappings if s.usage=='primary'}
    def effective_quality(k):
        return next((nodes[a].quality for a in ancestors(k) if nodes[a].quality),batch.source_graph.revision.quality).canonical_json()
    units=[];tiny_axes=defaultdict(Counter);unknown=Counter();commercial=Counter()
    all_roots={};heading_flags=Counter();prefix_occurrences=Counter();unknown_text_hashes=[]
    for c in chunks:
        keys=primary(c)
        roots={k for k in keys if not keys.intersection(ancestors(k)[1:])}
        all_roots[c.ordinal]=roots
        lineage=set(a for k in roots for a in ancestors(k))
        relevant=[e for e in batch.source_graph.edges if e.from_node.node_key in lineage and e.relation.value in {'REFERS_TO','DESCRIBES','VARIANT_OF'}]
        subjects=tuple(sorted({e.to_node.canonical_json() for e in relevant}))
        barrier=any(e.relation.value not in {'CONTAINS','HEADING_FOR'} and (e.from_node.node_key in keys or e.to_node.node_key in keys) for e in batch.source_graph.edges)
        barrier=barrier or any(nodes[k].node_type.value!='paragraph' for k in roots)
        barrier=barrier or any(nodes[k].attributes.model_dump(exclude_defaults=True) for k in keys)
        # Conservative annotation-free qualification witness, analysis only.
        barrier=barrier or bool(re.search(r'\b(?:must|unless|except|not|may|only|warning|results vary)\b',c.text,re.I))
        unit=EvidenceUnit(c.ordinal,c.revision.canonical_json(),c.kind,
            tuple(sorted({nodes[k].parent.node_key if nodes[k].parent else '' for k in roots})),
            tuple(h.node_key for h in c.heading_path),subjects,
            tuple(sorted({nodes[k].semantic_role.value for k in keys})),
            tuple(sorted({effective_quality(k) for k in keys})),bool(barrier),
            c.complete_unit and c.part_count==1,c.token_count)
        units.append(unit)
        if c.token_count<50:
            for axis,value in [('kind',c.kind),('parent_count',len(unit.parent)),('section_depth',len(unit.section)),
                ('explicit_subject_count',len(subjects)),('roles','+'.join(unit.roles)),
                ('quality','+'.join(sorted({nodes[k].quality.disposition.value if nodes[k].quality else batch.source_graph.revision.quality.disposition.value for k in keys}))),
                ('relationship_barrier',bool(barrier))]:tiny_axes[axis][str(value)]+=1
        unknown_keys={k for k in keys if nodes[k].semantic_role.value=='unknown'}
        if unknown_keys:
            unknown['specs']+=1
            unknown['ordinary_prose_candidates' if c.kind=='prose' else 'typed_unit_or_heading_with_unknown_annotations']+=1
            unknown['unknown_node_types_'+','.join(sorted({nodes[k].node_type.value for k in unknown_keys}))]+=1
            if c.token_count<100 and sum(nodes[k].attributes.link is not None for k in keys)>=3:unknown['navigation_like_candidates']+=1
            if c.kind=='prose':
                unknown_text_hashes.append(hashlib.sha256('\n'.join(nodes[k].text for k in sorted(roots)).encode()).hexdigest())
        if c.kind=='price_block':
            money=[nodes[k].attributes.commercial for k in keys if nodes[k].attributes.commercial]
            commercial['specs']+=1;commercial['amount_annotations']+=len(money)
            commercial['multi_amount_specs']+=len(money)>1
            commercial['unknown_role_specs']+=any(m.role.value=='unknown' for m in money)
            commercial['mixed_role_specs']+=len({m.role.value for m in money})>1
            commercial['multipart_specs']+=c.part_count>1
            commercial['complete_source_block_specs']+=c.source_block_complete is True
            commercial['source_block_completeness_unknown']+=c.source_block_complete is None
            for m in money:commercial['amount_role_'+m.role.value]+=1
        for s in c.mappings:
            if s.usage=='inherited':prefix_occurrences[(s.mapping.node.canonical_json(),s.mapping.node_slice.start,s.mapping.node_slice.end)]+=1

    # Omit a standalone vector only where ALL exact mapped bytes also survive
    # in non-heading chunks. Original graph and original v1 specs are retained.
    nonheading=[c for c in chunks if c.kind!='heading']
    coverage=intervals(nonheading);suppressed=[]
    for c in chunks:
        if c.kind!='heading':continue
        keys=primary(c)
        body_followers=[d for d in nonheading if keys.intersection(h.node_key for h in d.heading_path)]
        heading_flags['with_body_descendant' if body_followers else 'without_body_descendant']+=1
        echoed=covered(c,coverage)
        heading_flags['fully_inherited' if echoed else 'not_fully_inherited']+=1
        heading_flags['independent_evidence_candidates']+=bool(re.search(r'\d|\?|\b(?:includes|contains|must|not|may|will|within)\b',c.text,re.I))
        heading_flags['navigation_title_candidates']+=bool(re.fullmatch(r'\s*(?:home|menu|account|cart|search|shop|resources)\s*',c.text,re.I))
        if echoed and body_followers and not any(nodes[k].semantic_role.value in CRITICAL or nodes[k].attributes.model_dump(exclude_defaults=True) for k in keys):suppressed.append(c.ordinal)

    reasons=Counter();eligible=[];theoretical=0
    for a,b in zip(chunks,chunks[1:]):
        theoretical+=a.complete_unit and b.complete_unit and a.part_count==b.part_count==1 and a.bundle_key!=b.bundle_key and a.token_count+b.token_count<=650
        reason=merge_reason(units[a.ordinal],units[b.ordinal])
        if reason:reasons[reason]+=1
        else:eligible.append((a.ordinal,b.ordinal))
    groups=[]
    for c in chunks:
        if c.ordinal in suppressed:continue
        if groups and (groups[-1][-1],c.ordinal) in eligible and count_tokens('\n'.join(chunks[i].text for i in (*groups[-1],c.ordinal)))<=650:
            groups[-1].append(c.ordinal)
        else:groups.append([c.ordinal])
    kept=[chunks[i] for group in groups for i in group]
    assert intervals(kept)==intervals(chunks),'simulation lost exact source slices'
    assert sorted([i for group in groups for i in group]+suppressed)==list(range(len(chunks)))
    assert len(kept)+len(suppressed)==len(chunks)
    token_counts=[count_tokens('\n'.join(chunks[i].text for i in group)) for group in groups]
    texts=Counter(c.text for c in chunks if c.kind=='heading')
    commercial['distinct_source_bundles']=len({c.bundle_key for c in chunks if c.kind=='price_block'})
    same_block=Counter(tuple(sorted(all_roots[c.ordinal])) for c in chunks if c.kind=='price_block')
    commercial['source_blocks_with_multiple_specs']=sum(n>1 for n in same_block.values())
    return {'v1':{'chunks':len(chunks),'tokens':sum(c.token_count for c in chunks),
            'tiny':sum(c.token_count<50 for c in chunks),'heading':sum(c.kind=='heading' for c in chunks),
            'theoretical_pairs':theoretical,'kinds':dict(Counter(c.kind for c in chunks))},
        'headings':{**heading_flags,'duplicate_text_occurrences':sum(n-1 for n in texts.values()),'conditional_metadata_only':len(suppressed)},
        'tiny_axes':{k:dict(v) for k,v in tiny_axes.items()},'unknown':dict(unknown),'commercial':dict(commercial),
        'merge_eligible_pairs':len(eligible),'merge_rejection_reasons':dict(reasons),
        'simulated':{'chunks':len(groups),'tokens':sum(token_counts),'tiny':sum(n<50 for n in token_counts),
            'heading_standalone':sum(c.kind=='heading' for c in kept),'groups_merged':sum(len(g)>1 for g in groups),
            'mapping_coverage_equal':True,'unaccounted_new_bytes':0,
            'kind_composition':dict(Counter(chunks[g[0]].kind for g in groups))},
        'prefix_mapping_occurrences':sum(prefix_occurrences.values()),
        'repeated_prefix_mapping_occurrences':sum(n-1 for n in prefix_occurrences.values()),
        'prefix_tokens':sum(c.prefix_tokens for c in chunks),'unknown_prose_hashes':unknown_text_hashes,
        'groups':groups,'metadata_only_spec_ordinals':suppressed,
        'graph_hash':batch.source_graph.canonical_hash(),'batch_hash':batch.canonical_hash()}


def run(snapshot, saved_metrics):
    from services.structural_shadow import ShadowSource, build_shadow
    payload=json.loads(snapshot.read_text(encoding='utf-8'))
    prior=json.loads(saved_metrics.read_text(encoding='utf-8'))
    rows=[]
    for doc in payload['documents']:
        source=ShadowSource(70001,70002,doc['id'],1,doc['raw_text'].encode(),'markdown','extracted_markdown')
        batch,_=build_shadow(source)
        row=analyze_batch(batch);row['document_id']=doc['id']
        row['nodes']=len(batch.source_graph.nodes);row['edges']=len(batch.source_graph.edges)
        row['batch_bytes']=len(batch.canonical_json().encode())
        row['graph_bytes']=len(batch.source_graph.canonical_json().encode())
        previous=next(r for r in prior['documents'] if r['document_id']==doc['id'])
        assert row['batch_hash']==previous['serialization_hash'] and row['graph_hash']==previous['structural_hash']
        row['legacy_chunks']=previous['legacy_chunks'];row['legacy_tokens']=previous['legacy_tokens']
        rows.append(row)
    totals={'documents':len(rows)}
    for key in ('chunks','tokens','tiny','heading','theoretical_pairs'):totals[key]=sum(r['v1'][key] for r in rows)
    assert totals==BASELINE,(totals,BASELINE)
    def counter(section):
        c=Counter()
        for r in rows:c.update(r[section])
        return dict(c)
    kinds=Counter()
    for r in rows:kinds.update(r['v1']['kinds'])
    assert dict(kinds)==KINDS
    sim={k:sum(r['simulated'][k] for r in rows) for k in ('chunks','tokens','tiny','heading_standalone','groups_merged')}
    axes={}
    for axis in rows[0]['tiny_axes']:
        c=Counter()
        for r in rows:c.update(r['tiny_axes'][axis])
        axes[axis]=dict(c)
    hash_docs=defaultdict(set)
    for r in rows:
        for h in r['unknown_prose_hashes']:hash_docs[h].add(r['document_id'])
    repeated_unknown=sum(len(ids)>1 for ids in hash_docs.values())
    repeated_occurrences=sum(sum(len(hash_docs[h])>1 for h in r['unknown_prose_hashes']) for r in rows)
    return {'analysis_only':True,'v1':totals,'kinds':dict(kinds),'simulated':sim,
        'headings':counter('headings'),'unknown':counter('unknown'),'commercial':counter('commercial'),
        'tiny_axes':axes,'merge_eligible_pairs':sum(r['merge_eligible_pairs'] for r in rows),
        'merge_rejection_reasons':counter('merge_rejection_reasons'),
        'mapping_coverage_equal':all(r['simulated']['mapping_coverage_equal'] for r in rows),
        'prefix_mapping_occurrences':sum(r['prefix_mapping_occurrences'] for r in rows),
        'repeated_prefix_mapping_occurrences':sum(r['repeated_prefix_mapping_occurrences'] for r in rows),
        'prefix_tokens':sum(r['prefix_tokens'] for r in rows),
        'cross_document_repeated_unknown_prose_hashes':repeated_unknown,
        'cross_document_repeated_unknown_prose_occurrences':repeated_occurrences,
        'snapshot_sha256':hashlib.sha256(snapshot.read_bytes()).hexdigest(),'documents':rows}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',type=Path,required=True);p.add_argument('--saved-metrics',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=run(a.snapshot,a.saved_metrics)
    a.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='documents'},sort_keys=True))
