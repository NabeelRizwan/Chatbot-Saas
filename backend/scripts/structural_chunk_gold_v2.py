"""Frozen hand-authored v2 expectations and source-identity query witnesses.

Normal cases use the frozen v1 serializer unchanged. Tiny peer cases split the
already-merged v1 prose into verified lossless unit DTOs, deliberately exercising
the v2 interface. They are not claimed to be emitted separately by v1 today.
"""
import json
from pathlib import Path

from scripts.evaluate_structural_text_adapter import parse_source
from services.structural_document import StructuralDocument, StructuralEdge, SemanticRole, NodeAttributes, ByteRange
from services.structural_chunking import serialize_structural_document, count_tokens, digest

ROOT=Path(__file__).resolve().parents[1]/'fixtures/structural_chunk_gold_v2'


def cases():
    return json.loads((ROOT/'cases.json').read_text(encoding='utf-8'))['cases']


def build(case):
    units=case.get('shape')=='units'
    duplicate=case.get('duplicate_heading',False)
    text=case.get('text') or ('# Manual\n\n## Details\n\nQuiet study space.\n\n'+
        ('## Details\n\n' if duplicate else '')+'Registration opens daily.')
    doc=parse_source(text)
    nodes=[];stage=0
    for n in doc.nodes:
        updates={}
        if case.get('annotate')=='review' and n.node_type.value=='section':updates['semantic_role']=SemanticRole.REVIEW
        if case.get('annotate')=='timeline' and n.node_type.value=='section' and n.preorder>2:
            stage+=1
            updates.update(semantic_role=SemanticRole.TIMELINE_STAGE,attributes=NodeAttributes.model_validate({
                'timeline':{'stage_order':stage,'stage_label':f'Stage {stage}','qualifiers':['Results vary.'] if stage==1 else []}}))
        nodes.append(n.model_copy(update=updates))
    edges=list(doc.edges)
    if units and case.get('subject'):
        title=next(n for n in nodes if n.node_type.value=='heading')
        for parent in {n.parent for n in nodes if n.node_type.value=='paragraph'}:
            n=next(n for n in nodes if n.identity==parent)
            edges.append(StructuralEdge(from_node=n.identity,to_node=title.identity,relation='DESCRIBES',
                provenance=title.provenance,validation_state='validated'))
    doc=StructuralDocument.model_validate_json(doc.model_copy(update={'nodes':tuple(nodes),'edges':tuple(edges)}).canonical_json())
    batch=serialize_structural_document(doc)
    if not units:return batch
    # All mappings refer to real source nodes, ranges and roles. No v1 cap or
    # implementation changes: partition an existing prose spec by primary node.
    chunks=[]
    for c in batch.chunks:
        primary=[s for s in c.mappings if s.usage=='primary']
        groups=[[s] for s in primary] if c.kind=='prose' else [primary]
        for group in groups:
            selected=[s for s in c.mappings if s.usage!='primary']+group
            selected.sort(key=lambda s:s.mapping.output_slice.start)
            parts=[];maps=[];offset=0
            key=digest({'gold_units':c.chunk_key,'ordinal':len(chunks)})
            for i,s in enumerate(selected):
                m=s.mapping;node=next(n for n in nodes if n.identity==m.node)
                value=node.text.encode()[m.node_slice.start:m.node_slice.end].decode()
                if parts:offset+=1
                maps.append(s.model_copy(update={'mapping':m.model_copy(update={'chunk_id':key,'ordinal':i,
                    'output_slice':ByteRange(start=offset,end=offset+len(value.encode()))})}))
                parts.append(value);offset+=len(value.encode())
            value='\n'.join(parts)
            chunks.append(c.model_copy(update={'chunk_key':key,'ordinal':len(chunks),'text':value,'mappings':tuple(maps),
                'byte_count':len(value.encode()),'token_count':count_tokens(value),
                'source_nodes':tuple(s.mapping.node for s in group),'members':tuple(s.mapping.node for s in group)}))
    return batch.model_copy(update={'chunks':tuple(chunks)}).verify()


def discoverability(case,batch,selection):
    """Phrase presence AND exact mapped source identity, including duplicate headings.

    Queries are evaluation labels; phrases/source-node matches were authored in
    GOLD, not inferred by a retrieval model. This is NOT embedding recall/ranking.
    """
    rows=[]
    for q in case['queries']:
        phrase=q['phrase']
        targets=[n for n in batch.source_graph.nodes if phrase.casefold() in n.text.casefold() and n.text]
        if not targets:raise AssertionError('GOLD phrase has no source witness')
        for node in targets:
            originals=[c for c in batch.chunks if phrase.casefold() in c.text.casefold() and any(s.mapping.node==node.identity for s in c.mappings)]
            selected=[]
            for c in selection.candidates:
                if phrase.casefold() not in c.text.casefold():continue
                for t in c.translations:
                    old=next(o for o in batch.chunks if o.chunk_key==t.v1_spec_id)
                    if old.mappings[t.mapping_index].mapping.node==node.identity:
                        selected.append(c.candidate_id);break
            rows.append({'query':q['query'],'source_node':node.identity.node_key,'v1':bool(originals),'v2':bool(selected)})
    return rows
