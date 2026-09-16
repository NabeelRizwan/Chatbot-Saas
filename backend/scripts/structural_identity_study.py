"""Phase I pure offline evidence annotations; NOT an authorization or selector.

No graph mutation, title/URL-prefix matching, query understanding, DB, network,
provider, embedding or live ingestion integration. H remains the frozen policy.
"""
from collections import defaultdict
import re
from typing import Literal
from urllib.parse import urlsplit

from markdown_it import MarkdownIt
from pydantic import Field
from services.structural_document import Value,SourceIdentity,NodeIdentity,StructuralDocument,Digest
from services.structural_selection_v2 import _Selection,SelectionPolicy,heading_label
from services.structural_text_rules import REVIEW_LABEL,REVIEW_SIGNATURE


class EvidenceError(ValueError):
    pass


class Resource(Value):
    key: str = Field(min_length=1,max_length=256)
    version: int = Field(gt=0)
    anchor: NodeIdentity
    canonical_url: str = Field(max_length=2048)
    mapped_sources: tuple[SourceIdentity,...] = Field(default=(),max_length=256)


class RootProof(Value):
    source: SourceIdentity
    resource_key: str
    semantics: Literal['source_document_only','single_resource']
    inventory_complete: bool = False


class Registry(Value):
    version: Literal['frozen-subject-registry-i-v1'] = 'frozen-subject-registry-i-v1'
    artifact_hash: Digest
    organization_id: int = Field(gt=0)
    bot_id: int = Field(gt=0)
    allowed_sources: tuple[SourceIdentity,...] = Field(max_length=10000)
    known_anchors: tuple[NodeIdentity,...] = Field(default=(),max_length=10000)
    resources: tuple[Resource,...] = Field(default=(),max_length=10000)
    root_proofs: tuple[RootProof,...] = Field(default=(),max_length=10000)


class SubjectEvidence(Value):
    state: Literal['RESOLVED','UNRESOLVED','MULTI_SUBJECT','PARTIAL']
    subjects: tuple[str,...]
    group: NodeIdentity | None = None
    basis: tuple[str,...] = ()
    evidence_nodes: tuple[NodeIdentity,...] = ()
    reason: str


def state(subjects,incomplete=False):
    return 'MULTI_SUBJECT' if len(subjects)>1 else ('PARTIAL' if subjects and incomplete else ('RESOLVED' if subjects else 'UNRESOLVED'))


def exact_safe_url(value):
    """Validate only. Never normalize identity, resolve URLs or strip conditions."""
    if not value or any(ord(c)<33 or ord(c)==127 for c in value):return False
    try:
        u=urlsplit(value)
        return u.scheme in {'http','https'} and bool(u.hostname) and not (u.username or u.password or u.query or u.fragment)
    except ValueError:return False


class IdentityStudy:
    def __init__(self,batch,registry):
        self.batch=batch.verify()
        self.doc=StructuralDocument.model_validate_json(batch.source_graph.canonical_json())
        self.registry=Registry.model_validate_json(registry.canonical_json())
        r=self.registry;scope=(r.organization_id,r.bot_id)
        if len(set(r.allowed_sources))!=len(r.allowed_sources):raise EvidenceError('duplicate source authority')
        allowed=set(r.allowed_sources)
        if any((s.organization_id,s.bot_id)!=scope for s in allowed):raise EvidenceError('foreign source authority')
        if self.doc.revision.identity.source not in allowed:raise EvidenceError('source/version/hash outside frozen authority')
        self.resources={x.key:x for x in r.resources}
        if len(self.resources)!=len(r.resources):raise EvidenceError('duplicate resource key')
        self.urls=defaultdict(set);self.targets=defaultdict(set)
        for a in r.known_anchors:
            if a.revision.source not in allowed:raise EvidenceError('foreign anchor')
        for x in r.resources:
            if x.anchor not in r.known_anchors or x.anchor.revision.source not in allowed or any(s not in allowed for s in x.mapped_sources):raise EvidenceError('unowned resource mapping')
            if x.canonical_url and not exact_safe_url(x.canonical_url):raise EvidenceError('unsafe registry URL')
            if x.canonical_url:self.urls[x.canonical_url].add(x.key)
            self.targets[x.anchor].add(x.key)
        for p in r.root_proofs:
            if p.source not in allowed or p.resource_key not in self.resources or p.source not in self.resources[p.resource_key].mapped_sources:raise EvidenceError('unowned root proof')
        self.nodes={n.identity.node_key:n for n in self.doc.nodes};self.children=defaultdict(list)
        for n in self.doc.nodes:
            if n.parent:self.children[n.parent.node_key].append(n.identity.node_key)
        self.references={};self.direct={};self.barriers=set();self.annotations={}
        self._collect()
        for n in self.doc.nodes:self.annotations[n.identity.node_key]=self._node(n.identity.node_key)

    def lineage(self,key):
        result=[]
        while key:
            result.append(key);p=self.nodes[key].parent;key=p.node_key if p else None
        return result

    def members(self,key):
        result=[];pending=[key]
        while pending:
            current=pending.pop();result.append(current)
            pending.extend(reversed(self.children[current]))
        return result

    def _add(self,key,subjects,basis,evidence=(),incomplete=False):
        self.barriers.add(key)
        row=self.direct.setdefault(key,{'subjects':set(),'basis':set(),'evidence':set(),'incomplete':False})
        row['subjects'].update(subjects);row['basis'].add(basis);row['evidence'].update(evidence)
        row['incomplete']|=incomplete

    def _collect(self):
        # Links initially supply references ONLY, never parent/section subjects.
        for n in self.doc.nodes:
            a=n.attributes.link
            if a:
                keys=self.urls.get(a.original_href,set()) if a.safety.value=='safe' and a.validated_href==a.original_href else set()
                self.references[n.identity.node_key]=SubjectEvidence(state=state(keys),subjects=tuple(sorted(keys)),
                    basis=('EXACT_REGISTERED_LINK',),evidence_nodes=(n.identity,),reason='reference_only_not_subject')
        typed={n.identity.node_key for n in self.doc.nodes if n.semantic_role.value in {'review','product_card'}}
        self.barriers.update(typed)
        for key in sorted(typed):
            n=self.nodes[key];links=[]
            for k in self.members(key):
                # A nested card/review owns its own references, even if unresolved.
                if any(a in typed for a in self.lineage(k)[:self.lineage(k).index(key)]):continue
                item=self.nodes[k]
                if n.semantic_role.value=='review':
                    # Same source-signature boundary as frozen C; unrelated nearby
                    # links are not review targets. No free-form review inference.
                    if item.node_type.value=='paragraph' and (REVIEW_LABEL.match(item.text) or REVIEW_SIGNATURE.match(item.text)):
                        links.extend(x for x in self.children[k] if x in self.references)
                elif item.attributes.link:
                    links.append(k)
            links=list(dict.fromkeys(links))
            subjects={s for k in links for s in self.references[k].subjects}
            # No link is absence of this proof, not a contradiction of a separate
            # validated REFERS_TO edge. The typed barrier still blocks inheritance.
            if links:
                incomplete=any(not self.references[k].subjects for k in links)
                self._add(key,subjects,'EXPLICIT_REVIEW_LINK' if n.semantic_role.value=='review' else 'EXPLICIT_CARD_LINK',
                    (self.nodes[k].identity for k in links),incomplete)
        for e in self.doc.edges:
            if e.validation_state.value!='validated':continue
            n=self.nodes[e.from_node.node_key]
            if n.parent is None:continue  # document roots require separate proof
            if e.relation.value=='DESCRIBES' or (e.relation.value=='REFERS_TO' and n.semantic_role.value in {'review','product_card'}):
                keys=self.targets.get(e.to_node,set())
                self._add(n.identity.node_key,keys,e.relation.value+'_EDGE',(n.identity,e.to_node),not keys)
            # CONTAINS alone establishes structure, not subject; the frozen tree
            # supplies bounded inheritance, never arbitrary graph reachability.
        root=self.doc.nodes[0].identity.node_key
        proofs=[p for p in self.registry.root_proofs if p.source==self.doc.revision.identity.source]
        single=[p for p in proofs if p.semantics=='single_resource' and p.inventory_complete]
        if single:
            keys={p.resource_key for p in single}
            competing={s for row in self.direct.values() for s in row['subjects']} - keys
            # Complete inventory is a trusted frozen descriptor, not inferred from
            # absence of detected cards. Any contradictory block fails closed.
            if competing:self._add(root,set(),'CONTRADICTORY_ROOT_PROOF',(),True)
            else:self._add(root,keys,'DOCUMENT_RESOURCE_MAPPING',(self.doc.nodes[0].identity,))

    def _node(self,key):
        for k in self.lineage(key):
            if k not in self.barriers:continue
            row=self.direct.get(k)
            if row is None:return SubjectEvidence(state='UNRESOLVED',subjects=(),group=self.nodes[k].identity,reason='unresolved_resource_boundary')
            subjects=tuple(sorted(row['subjects']))
            inherited=k!=key
            return SubjectEvidence(state=state(subjects,row['incomplete']),subjects=subjects,group=self.nodes[k].identity,
                basis=tuple(sorted(row['basis']|({'ANCESTOR_RESOURCE_GROUP'} if inherited else set()))),
                evidence_nodes=tuple(sorted(row['evidence'],key=lambda n:n.canonical_json())),
                reason='bounded_explicit_group' if subjects else 'no_registered_target')
        return SubjectEvidence(state='UNRESOLVED',subjects=(),reason='no_subject_proof')

    def for_spec(self,c):
        primary={s.mapping.node.node_key for s in c.mappings if s.usage=='primary'}
        rows=[self.annotations[k] for k in sorted(primary)]
        subjects=tuple(sorted({s for r in rows for s in r.subjects}))
        partial=not rows or any(r.state in {'UNRESOLVED','PARTIAL'} for r in rows)
        return SubjectEvidence(state=state(subjects,partial),subjects=subjects,
            basis=tuple(sorted({b for r in rows for b in r.basis})),
            evidence_nodes=tuple(sorted({n for r in rows for n in r.evidence_nodes},key=lambda n:n.canonical_json())),
            reason='all_primary_nodes_required')


LABELS=frozenset({'ingredients','directions','details','price','reviews','faq','overview','description',
    'features','benefits','specifications','pricing','contents','resources','additional information',
    'customer reviews','amenities','system requirements','prerequisites','cancellation terms','topics',
    'curriculum','usage directions','key ingredients','how to use','product details'})
SECTIONS=frozenset({'collection','catalog','modules','rooms','plans','courses','policies'})
WARNING=re.compile(r'\b(?:warning|warnings|caution)\b',re.I)
QUALIFIER=re.compile(r'\b(?:only|unless|except|must|not|may|vary|varies|consult|eligible|guaranteed)\b',re.I)
FACT=re.compile(r'\b(?:includes|requires|provides|contains|costs|allows|expires|entitles|included)\b',re.I)


def visible_heading_label(text):
    """Classification view only: href query '?' or filename digits are not facts.

    Existing pinned CommonMark grammar, no rendering/execution/URL resolution.
    Source text and all maps stay unchanged. Marked-up headings cannot become
    generic metadata-only labels, even if their visible label looks generic.
    """
    tokens=MarkdownIt('commonmark',{'html':False,'linkify':False}).parseInline(heading_label(text))
    return ''.join(t.content for root in tokens for t in (root.children or ())
        if t.type in {'text','code_inline','image'}).strip()


def classify_heading(batch,node,study=None,engine=None):
    engine=engine or _Selection(batch,SelectionPolicy())
    raw_label=heading_label(node.text);label=visible_heading_label(node.text);role=node.semantic_role.value
    c=next((c for c in batch.chunks if c.kind=='heading' and any(s.usage=='primary' and s.mapping.node==node.identity for s in c.mappings)),None)
    witness=engine.heading_targets(c) if c else None
    semantic=any(e.relation.value not in {'CONTAINS','HEADING_FOR'} and node.identity in (e.from_node,e.to_node) for e in batch.source_graph.edges)
    explicit=study and node.identity.node_key in study.direct and study.annotations[node.identity.node_key].state=='RESOLVED'
    if WARNING.search(label) or role=='warning':category='WARNING'
    elif '?' in label or role=='faq_question':category='QUESTION_HEADING'
    elif QUALIFIER.search(label):category='QUALIFICATION'
    elif any(c.isdigit() for c in label):category='NUMERIC_FACT'
    elif explicit:category='RESOURCE_IDENTITY'
    elif FACT.search(label):category='INDEPENDENT_FACT'
    elif label in SECTIONS:category='SECTION_IDENTITY'
    elif raw_label in LABELS and witness and not semantic and role in {'unknown','title'} and not node.attributes.model_dump(exclude_defaults=True):category='STRUCTURAL_LABEL_ONLY'
    else:category='AMBIGUOUS'
    proposed=category=='STRUCTURAL_LABEL_ONLY' and bool(witness)
    return {'node_key':node.identity.node_key,'spec_id':c.chunk_key if c else None,'category':category,
        'decision':'METADATA_ONLY_PROPOSED' if proposed else 'KEEP',
        'complete_descendant_witness':bool(witness),'witness':witness or [],'source_unchanged':True}


class StudyPeerEngine(_Selection):
    """Study adapter changes evidence input ONLY; every H peer guard is inherited.

    Never call run(): outputs must not impersonate an H/v2 Selection artifact.
    """
    def __init__(self,batch,study):
        self.study=study
        super().__init__(batch,SelectionPolicy())

    def boundary(self,c):
        roots,_,roles,quality=super().boundary(c)
        evidence=self.study.for_spec(c)
        subjects=tuple(self.study.resources[k].canonical_json() for k in evidence.subjects) if evidence.state in {'RESOLVED','MULTI_SUBJECT'} else ()
        return roots,subjects,roles,quality

    def run(self):
        raise EvidenceError('I study cannot publish an H selection')
