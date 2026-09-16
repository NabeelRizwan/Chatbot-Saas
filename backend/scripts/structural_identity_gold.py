"""Synthetic, explicitly annotated source registries for the frozen Phase I GOLD.

Annotations are fixture facts, never inferred from names or copied to live data.
"""
import json
from pathlib import Path

from scripts.evaluate_structural_text_adapter import parse_source
from scripts.structural_chunk_gold_v2 import build as units
from scripts.structural_identity_study import Resource, Registry, RootProof
from services.structural_document import StructuralDocument, StructuralEdge, SemanticRole
from services.structural_chunking import serialize_structural_document

ROOT = Path(__file__).resolve().parents[1] / 'fixtures'
URL1 = 'https://example.org/resources/one'
URL2 = 'https://example.org/resources/two'


def cases(folder):
    return json.loads((ROOT / folder / 'cases.json').read_text(encoding='utf-8'))['cases']


def registry(doc, mode='', urls=(URL1, URL2)):
    name='Named resource' if mode=='same_name' else 'Registered resource'
    targets = [parse_source('# '+name+'\n\nExplicit registry record.', document_id=i) for i in (90, 91)]
    resources = tuple(Resource(key=f'r{i+1}', version=1, anchor=t.nodes[0].identity,
        canonical_url=urls[i], mapped_sources=(doc.revision.identity.source, t.revision.identity.source)) for i, t in enumerate(targets))
    proofs = []
    if mode in {'single', 'single_conflict', 'catalog_only', 'no_inventory', 'unresolved_nested'}:
        keys = ('r1', 'r2') if mode == 'single_conflict' else ('r1',)
        proofs = [RootProof(source=doc.revision.identity.source, resource_key=k,
            semantics='source_document_only' if mode == 'catalog_only' else 'single_resource',
            inventory_complete=mode != 'no_inventory') for k in keys]
    return Registry(artifact_hash='1'*64, organization_id=70001, bot_id=70002,
        allowed_sources=(doc.revision.identity.source,)+(tuple(t.revision.identity.source for t in targets)),
        known_anchors=tuple(t.nodes[0].identity for t in targets), resources=resources, root_proofs=tuple(proofs))


def edge(node, target, relation='DESCRIBES', validated=True):
    return StructuralEdge(from_node=node.identity, to_node=target, relation=relation,
        provenance=node.provenance, validation_state='validated' if validated else 'unvalidated')


def with_graph(batch, nodes=None, edges=None):
    doc=batch.source_graph.model_copy(update={'nodes':tuple(nodes) if nodes is not None else batch.source_graph.nodes,
        'edges':tuple(edges) if edges is not None else batch.source_graph.edges})
    doc=StructuralDocument.model_validate_json(doc.canonical_json())
    return batch.model_copy(update={'source_graph':doc}).verify()


def heading_case(case):
    text='# Fixture\n\n## '+case['heading']+'\n\n'+case['body']
    if case.get('duplicate'):text+='\n\n## Separate parent\n\n### '+case['heading']+'\n\nOther body.'
    doc=parse_source(text)
    headings=[n for n in doc.nodes if n.node_type.value=='heading' and n.text.lstrip('# ').strip()==case['heading']]
    r=registry(doc);nodes=list(doc.nodes);edges=list(doc.edges)
    for heading in headings:
        if case.get('role'):
            nodes=[n.model_copy(update={'semantic_role':SemanticRole(case['role'])}) if n.identity==heading.identity else n for n in nodes]
        if case.get('explicit_identity'):edges.append(edge(heading,r.resources[0].anchor))
    doc=StructuralDocument.model_validate_json(doc.model_copy(update={'nodes':tuple(nodes),'edges':tuple(edges)}).canonical_json())
    return serialize_structural_document(doc),r,[n for n in doc.nodes if n.identity in {h.identity for h in headings}]


def identity_case(case):
    mode=case['mode']
    text='# Named resource\n\n## Details\n\nFirst evidence.\n\nSecond evidence.'
    if mode in {'sibling','partial','nearby'}:
        text='# Named resource\n\n## First section\n\nFirst evidence.\n\n## Second section\n\nSecond evidence.'
        if mode=='nearby':text+=f'\n\n[An unrelated resource]({URL1}).'
    if mode in {'nested','unresolved_nested'}:
        text='# Named resource\n\n## Outer section\n\nFirst evidence.\n\n### Inner section\n\nSecond evidence.'
    if mode in {'card','prefix','ambiguous_link','missing'}:
        url=URL1 if mode not in {'prefix','missing'} else URL1+'/unregistered'
        text=f'# Catalog\n\n## Card\n\nFirst evidence. [View resource]({url})'
    if mode in {'review','two_reviews','collection'}:
        text=f'# Catalog\n\nCollection introduction.\n\n## Review one\n\nReview: First evidence. [View resource]({URL1})'
        if mode in {'two_reviews','collection'}:text+=f'\n\n## Review two\n\nReview: Second evidence. [View resource]({URL2})'
    if mode=='repeated':text=text.replace('evidence.','Named resource. Named resource.')
    if case.get('domain'):
        # These are hand-authored fixture facts, not runtime domain dictionaries.
        domains={'hotel':('Hotel room package','A quiet room with a desk.'),
            'software':('Software plan','The feature group includes export tools.'),
            'course':('Course and module','The module covers prerequisites and exercises.'),
            'legal':('Legal policy','The cancellation section defines notice requirements.'),
            'document':('Named document resource','This source contains reference material.')}
        name,body=domains[case['domain']]
        text=text.replace('Named resource',name).replace('First evidence.','First evidence. '+body)
    doc=parse_source(text);r=registry(doc,mode,urls=(URL1,URL1) if mode=='ambiguous_link' else (URL1,URL2))
    nodes=list(doc.nodes);edges=list(doc.edges)
    probes=[n for n in nodes if n.node_type.value=='paragraph' and ('First ' in n.text or 'Second ' in n.text)]
    parents=[next(n for n in nodes if n.identity==p.parent) for p in probes]
    if mode=='collection':probes=[next(n for n in nodes if n.text=='Collection introduction.')]+probes
    if mode in {'card','prefix','ambiguous_link','missing'}:
        nodes=[n.model_copy(update={'semantic_role':SemanticRole.PRODUCT_CARD}) if n.identity==parents[0].identity else n for n in nodes]
    if mode in {'block','relation','conflict','unvalidated','sibling','partial','nested'}:
        edges.append(edge(parents[0],r.resources[0].anchor,validated=mode!='unvalidated'))
    if mode=='conflict':edges.append(edge(parents[0],r.resources[1].anchor))
    if mode=='nested':edges.append(edge(parents[-1],r.resources[1].anchor))
    if mode=='unresolved_nested':
        nodes=[n.model_copy(update={'semantic_role':SemanticRole.PRODUCT_CARD}) if n.identity==parents[-1].identity else n for n in nodes]
    if mode=='contains':edges.append(edge(doc.nodes[0],probes[0].identity,'CONTAINS'))
    doc=StructuralDocument.model_validate_json(doc.model_copy(update={'nodes':tuple(nodes),'edges':tuple(edges)}).canonical_json())
    if mode=='foreign':r=r.model_copy(update={'organization_id':999})
    return serialize_structural_document(doc),r,probes


def peer_case(mode='single'):
    batch=units({'shape':'units','subject':False})
    return batch,registry(batch.source_graph,mode)
