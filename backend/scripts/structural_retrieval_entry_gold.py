"""Frozen-input L fixtures and independent witness checks, never runtime policy."""
import json
from pathlib import Path
from hashlib import sha256

from scripts.evaluate_structural_text_adapter import parse_source
from scripts.structural_chunk_gold_v1 import build, specs
from scripts.structural_gold_v1 import load_gold
from services.structural_document import (
    StructuralDocument, SemanticRole, SourceQuality, QualityClass, StructuralEdge,
    Relation, ValidationState, SourceLocation, CoordinateSystem, PageBox,
)
from services.structural_chunking import serialize_structural_document

ROOT=Path(__file__).resolve().parents[1]


def cases(folder):
    directory=ROOT/'fixtures'/folder
    # JSON formatting newlines are not fixture evidence. Keep the frozen LF
    # manifest valid after a Windows autocrlf checkout without changing cases.
    raw=(directory/'cases.json').read_bytes().replace(b'\r\n',b'\n')
    manifest=json.loads((directory/'manifest.json').read_text())
    if sha256(raw).hexdigest()!=manifest['cases_sha256']:
        raise AssertionError('frozen L GOLD hash mismatch')
    data=json.loads(raw)
    return data.get('cases',data.get('witnesses'))


def synthetic(name):
    bodies={
        'tiny_prose':('A short opening.','Use one item daily.','An ordinary ending.'),
        'navigation':('A useful statement.','Home | About | Contact','A useful closing.'),
        'quality':('A clear paragraph.','A paragraph with different quality.','A final paragraph.'),
        'known_resource':('Resource alpha.','Resource beta.'),
        'unresolved_resource':('A first personal review.','A second personal review.'),
        'multiple_faq':('Can I enter?','Entry is permitted.','When is it open?','Opening varies.'),
        'review':('A visitor described velvet silence.',),
        'faq':('What illuminates the hall?','A copper lantern illuminates the hall.'),
        'price':('Admission is 37.91 credits.',),
        'directions':('Use 11 millilitres daily.',),
        'timeline':('After 13–19 days, changes may appear. Results vary.',),
        'warning':('Warning: never invert the vessel.',),
        'quarantine':('A clear paragraph.','Untrusted quarantined text.','Another clear paragraph.'),
    }
    doc=parse_source('# Guide\n\n'+'\n\n'.join(bodies[name]))
    paragraphs=[n for n in doc.nodes if n.node_type.value=='paragraph']
    roles={
        'tiny_prose':['unknown','directions','unknown'],
        'navigation':['unknown','navigation','unknown'],
        'unresolved_resource':['review','review'],
        'multiple_faq':['faq_question','faq_answer','faq_question','faq_answer'],
        'review':['review'],'faq':['faq_question','faq_answer'],
        'price':['price_block'],'directions':['directions'],
        'timeline':['timeline_stage'],'warning':['warning'],
    }
    changes={}
    for i,n in enumerate(paragraphs):
        updates={}
        if name in roles: updates['semantic_role']=SemanticRole(roles[name][i])
        if name in ('quality','quarantine') and i==1:
            q=doc.revision.quality.model_dump()
            q.update(classification='mixed' if name=='quality' else 'blocked',
                     disposition='accept' if name=='quality' else 'quarantine',reason_codes=('fixture_quality',))
            updates['quality']=SourceQuality.model_validate(q)
        changes[n.identity.node_key]=n.model_copy(update=updates)
    edges=list(doc.edges)
    if name in ('faq','multiple_faq'):
        for i in range(0,len(paragraphs),2):
            a,b=paragraphs[i:i+2]
            edges.append(StructuralEdge(from_node=a.identity,to_node=b.identity,relation=Relation.QA_PAIR,
                provenance=a.provenance,validation_state=ValidationState.VALIDATED))
    if name=='known_resource':
        for n in paragraphs:
            edges.append(StructuralEdge(from_node=n.identity,to_node=n.identity,relation=Relation.DESCRIBES,
                provenance=n.provenance,validation_state=ValidationState.VALIDATED))
    return StructuralDocument.model_validate_json(doc.model_copy(update={
        'nodes':tuple(changes.get(n.identity.node_key,n) for n in doc.nodes),'edges':tuple(edges)}).canonical_json())


def document(spec):
    if 'fixture' in spec: return build(next(x for x in specs() if x['name']==spec['fixture']))
    if 'gold' in spec: return load_gold()[spec['gold']]
    if 'synthetic' in spec: return synthetic(spec['synthetic'])
    if 'docling' in spec:
        # Frozen structural DTO shapes, not a new binary/Docling extraction.
        d=load_gold()['table']; fmt=spec['docling']; nodes=[]
        for n in d.nodes:
            spans=tuple(s.model_copy(update={'location':SourceLocation(
                system=CoordinateSystem.PAGE_BBOX,page_bbox=PageBox(page=1,x0=0,y0=n.preorder,
                    x1=100,y1=n.preorder+1,unit='points',origin='top_left'))}) for s in n.provenance.spans)
            nodes.append(n.model_copy(update={'provenance':n.provenance.model_copy(update={'spans':spans})}))
        return StructuralDocument.model_validate_json(d.model_copy(update={
            'nodes':tuple(nodes),'revision':d.revision.model_copy(update={'source_format':fmt,'fidelity':'layout'})}).canonical_json())
    d=parse_source(spec['text'])
    if spec.get('format')=='txt':
        d=StructuralDocument.model_validate_json(d.model_copy(update={'revision':d.revision.model_copy(
            update={'source_format':'text','fidelity':'extracted_text'})}).canonical_json())
    return d


def evidence(spec): return serialize_structural_document(document(spec))
