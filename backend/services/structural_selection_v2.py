"""OFFLINE structure-chunk-v2 selection/packing, never imported by ingestion.

The complete frozen v1 batch is retained as the input/provenance graph. Selection
only creates immutable local candidate values and a total translation ledger.
No database, filesystem, network, providers, runtime flags or vector operations.
"""
from collections import defaultdict
from typing import Literal
import re

from pydantic import Field
from services.structural_document import Value, ByteRange, Digest, StructuralDocument
from services.structural_chunking import SerializationBatch, count_tokens, digest

# Closed, domain-independent hierarchy labels. Unrecognized names are retained,
# not guessed to be empty of independently answerable meaning.
CONTEXT_LABELS = frozenset({'overview','description','details','ingredients',
    'features','benefits','specifications','pricing','price','reviews',
    'customer reviews','contents','resources','additional information'})
PROTECTED = frozenset({'warning','review','faq_question','faq_answer','timeline_stage',
    'directions','ingredients','price_block','product_card'})
QUALIFICATION = re.compile(r'\b(?:warning|caution|unless|except|only|must|not|may|vary|varies|consult|eligible|guaranteed)\b',re.I)


def heading_label(text):
    # Classification only; original Markdown syntax/bytes remain in mappings.
    return re.sub(r'^#{1,6}\s+', '', text.strip()).casefold()


class SelectionError(ValueError):
    pass


class SelectionPolicy(Value):
    version: Literal['structure-chunk-v2'] = 'structure-chunk-v2'
    rule_version: Literal['conservative-selection-1'] = 'conservative-selection-1'
    target: Literal[450] = 450
    merge_min: Literal[250] = 250
    merge_max: Literal[650] = 650
    hard_max: Literal[800] = 800
    prefix_max: Literal[80] = 80
    overlap_max: Literal[60] = 60
    max_candidates: Literal[10000] = 10000
    max_candidate_mappings: Literal[256] = 256
    max_ledger_mappings: Literal[100000] = 100000


class Translation(Value):
    v1_spec_id: Digest
    mapping_index: int = Field(ge=0)
    output_slice: ByteRange


class Candidate(Value):
    candidate_id: Digest
    members: tuple[Digest,...]
    kind: str
    text: str
    token_count: int = Field(ge=0,le=800)
    prefix_tokens: int = Field(ge=0,le=80)
    translations: tuple[Translation,...]
    deduplicated_prefixes: int = Field(ge=0)


class Witness(Value):
    mapping_index: int = Field(ge=0)
    candidate_id: Digest
    output_slice: ByteRange
    retained_spec_id: Digest
    retained_mapping_index: int = Field(ge=0)


class Decision(Value):
    v1_spec_id: Digest
    outcome: Literal['embedded','metadata_only','packed','unresolved']
    reason: str
    candidate_id: Digest | None
    prefix_disposition: Literal['retained','shared_exact_heading','inherited_by_descendant']
    heading_dependencies: tuple[Digest,...]
    witnesses: tuple[Witness,...]


class PeerDecision(Value):
    left: Digest
    right: Digest
    status: Literal['eligible','ineligible','unknown_identity']
    reason: str


class Selection(Value):
    # Stored in memory, not redundantly copied into the selection JSON. Exporters
    # must retain the immutable v1 artifact or recreate it by the verified hash.
    v1: SerializationBatch = Field(exclude=True)
    policy: SelectionPolicy
    input_hash: Digest
    graph_hash: Digest
    recipe_hash: Digest
    candidates: tuple[Candidate,...]
    ledger: tuple[Decision,...]
    peers: tuple[PeerDecision,...]
    graph_only_nodes: tuple[Digest,...]

    def verify(self):
        self.v1.verify()
        if self.input_hash!=self.v1.canonical_hash() or self.graph_hash!=self.v1.source_graph.canonical_hash():
            raise SelectionError('input graph changed')
        if self.recipe_hash!=recipe(self.v1,self.policy):raise SelectionError('recipe changed')
        specs={c.chunk_key:c for c in self.v1.chunks}
        if len(specs)!=len(self.v1.chunks):raise SelectionError('duplicate input identity')
        nodes={n.identity.node_key:n for n in self.v1.source_graph.nodes}
        candidates={c.candidate_id:c for c in self.candidates}
        if len(candidates)!=len(self.candidates) or len(candidates)>self.policy.max_candidates:raise SelectionError('candidate identity/bound')
        if tuple(d.v1_spec_id for d in self.ledger)!=tuple(specs):raise SelectionError('ledger must reconcile every v1 spec in order')
        member_owner={};mapping_total=0
        for c in self.candidates:
            if not c.members or len(set(c.members))!=len(c.members) or any(k not in specs for k in c.members):raise SelectionError('invalid candidate members')
            if c.candidate_id!=candidate_key(self.recipe_hash,c.members,c.text,c.translations):raise SelectionError('candidate key mismatch')
            if count_tokens(c.text)!=c.token_count or c.prefix_tokens>80:raise SelectionError('candidate tokens')
            if len(c.translations)>256:raise SelectionError('candidate mapping bound')
            if len(c.members)>1 and c.token_count>650:raise SelectionError('packed token bound')
            expected={(k,i) for k in c.members for i in range(len(specs[k].mappings))}
            actual={(t.v1_spec_id,t.mapping_index) for t in c.translations}
            if expected!=actual or len(actual)!=len(c.translations):raise SelectionError('candidate mapping membership')
            represented=set();raw=c.text.encode()
            for k in c.members:
                if k in member_owner:raise SelectionError('duplicate selected member')
                member_owner[k]=c.candidate_id
            for t in c.translations:
                m=specs[t.v1_spec_id].mappings[t.mapping_index].mapping
                value=nodes[m.node.node_key].text.encode()[m.node_slice.start:m.node_slice.end]
                r=t.output_slice
                if r.end>len(raw) or raw[r.start:r.end]!=value:raise SelectionError('translated source bytes mismatch')
                represented.update(range(r.start,r.end))
            if any(b!=10 and i not in represented for i,b in enumerate(raw)):raise SelectionError('unmapped output bytes')
            mapping_total+=len(c.translations)
        if mapping_total>self.policy.max_ledger_mappings:raise SelectionError('ledger mapping bound')
        for d in self.ledger:
            original=specs[d.v1_spec_id]
            if d.heading_dependencies!=tuple(h.node_key for h in original.heading_path):raise SelectionError('heading dependency changed')
            if d.outcome=='metadata_only':
                if d.candidate_id is not None or d.v1_spec_id in member_owner or original.kind!='heading':raise SelectionError('metadata selection identity')
                if tuple(w.mapping_index for w in d.witnesses)!=tuple(range(len(original.mappings))):raise SelectionError('missing heading witnesses')
                if len({(w.candidate_id,w.retained_spec_id) for w in d.witnesses})!=1:raise SelectionError('heading context association split')
                for w in d.witnesses:
                    target=candidates[w.candidate_id];prior=specs[w.retained_spec_id]
                    match=next((t for t in target.translations if (t.v1_spec_id,t.mapping_index)==(w.retained_spec_id,w.retained_mapping_index)),None)
                    m=original.mappings[w.mapping_index].mapping;pm=prior.mappings[w.retained_mapping_index].mapping
                    if match is None or match.output_slice!=w.output_slice or prior.kind=='heading' or m.node!=pm.node or m.node_slice!=pm.node_slice or m.role!=pm.role or prior.mappings[w.retained_mapping_index].usage!='inherited':
                        raise SelectionError('heading witness identity mismatch')
                    if m.node.node_key not in {h.node_key for h in prior.heading_path} and original.mappings[w.mapping_index].usage=='primary':
                        raise SelectionError('not a heading descendant')
            elif d.candidate_id!=member_owner.get(d.v1_spec_id):raise SelectionError('selected decision missing candidate')
            if d.outcome!='metadata_only' and d.witnesses:raise SelectionError('unexpected metadata witnesses')
        primary={s.mapping.node.node_key for k in member_owner for s in specs[k].mappings if s.usage=='primary'}
        if self.graph_only_nodes!=tuple(n.identity.node_key for n in self.v1.source_graph.nodes if n.identity.node_key not in primary):
            raise SelectionError('graph selection accounting')
        return self


def recipe(batch,policy):
    return digest({'version':policy.model_dump(),'v1_recipe':batch.recipe_hash,
        'labels':sorted(CONTEXT_LABELS),'protected':sorted(PROTECTED),'qualification':QUALIFICATION.pattern})


def candidate_key(recipe_hash,members,text,translations):
    return digest({'recipe':recipe_hash,'members':members,'text':text,
                   'translations':[t.model_dump(mode='json') for t in translations]})


class _Selection:
    def __init__(self,batch,policy):
        StructuralDocument.model_validate_json(batch.source_graph.canonical_json())
        self.batch=batch.verify();self.p=SelectionPolicy.model_validate_json(policy.canonical_json())
        self.nodes={n.identity.node_key:n for n in batch.source_graph.nodes}
        self.specs={c.chunk_key:c for c in batch.chunks};self.children=defaultdict(list)
        for n in sorted(self.nodes.values(),key=lambda n:n.preorder):
            if n.parent:self.children[n.parent.node_key].append(n.identity.node_key)
        self.roots={};self.boundaries={};self.inherited=defaultdict(list)
        for c in batch.chunks:
            primary={s.mapping.node.node_key for s in c.mappings if s.usage=='primary'}
            self.roots[c.chunk_key]=tuple(sorted((k for k in primary if not primary.intersection(self.lineage(k)[1:])),key=lambda k:self.nodes[k].preorder))
            if c.kind!='heading':
                for i,s in enumerate(c.mappings):
                    if s.usage=='inherited':
                        m=s.mapping
                        self.inherited[(m.node,m.node_slice,m.role)].append((c,i))
        self.r=recipe(batch,self.p)

    def lineage(self,k):
        result=[]
        while k:
            result.append(k);p=self.nodes[k].parent;k=p.node_key if p else None
        return result

    def heading_reason(self,c):
        if c.kind!='heading':return 'atomic_'+c.kind if c.kind!='prose' else 'prose_without_proven_peer'
        primary={s.mapping.node.node_key for s in c.mappings if s.usage=='primary'}
        if not primary:return 'uncertain_answerability'
        if any(self.nodes[k].semantic_role.value!='unknown' or self.nodes[k].attributes.model_dump(exclude_defaults=True) for k in primary):return 'protected_heading'
        if any(re.search(r'\d|\?',self.nodes[k].text) or QUALIFICATION.search(self.nodes[k].text) for k in primary):return 'independent_heading'
        if any(self.nodes[k].node_type.value!='heading' or heading_label(self.nodes[k].text) not in CONTEXT_LABELS for k in primary):return 'uncertain_answerability'
        if any(e.relation.value not in {'CONTAINS','HEADING_FOR'} and (e.from_node.node_key in primary or e.to_node.node_key in primary) for e in self.batch.source_graph.edges):return 'heading_semantic_relationship'
        return None

    def heading_targets(self,c):
        """All exact heading/context mappings must coexist in ONE descendant.

        A global union of equal bytes is insufficient: it could detach an
        ancestor qualifier or bind a same-text heading under the wrong parent.
        """
        choices=[]
        for span in c.mappings:
            m=span.mapping
            matches={}
            for other,i in self.inherited.get((m.node,m.node_slice,m.role),()):
                if span.usage=='primary' and m.node.node_key not in {h.node_key for h in other.heading_path}:continue
                matches.setdefault(other.chunk_key,i)
            if not matches:return None
            choices.append(matches)
        if not choices:return None
        for key in choices[0]:
            if all(key in options for options in choices):return [(key,options[key]) for options in choices]
        return None

    def boundary(self,c):
        if c.chunk_key in self.boundaries:return self.boundaries[c.chunk_key]
        roots=self.roots[c.chunk_key]
        lineage=set(k for r in roots for k in self.lineage(r))
        subjects=tuple(sorted({e.to_node.canonical_json() for e in self.batch.source_graph.edges
            if e.from_node.node_key in lineage and e.relation.value=='DESCRIBES' and e.validation_state.value=='validated'}))
        roles=tuple(sorted({self.nodes[k].semantic_role.value for k in lineage}))
        quality=tuple(sorted({next((self.nodes[a].quality for a in self.lineage(k) if self.nodes[a].quality),self.batch.source_graph.revision.quality).canonical_json() for k in roots}))
        self.boundaries[c.chunk_key]=(roots,subjects,roles,quality)
        return self.boundaries[c.chunk_key]

    def peer(self,a,b):
        def result(status,reason):return PeerDecision(left=a.chunk_key,right=b.chunk_key,status=status,reason=reason)
        if a.revision!=b.revision:return result('ineligible','source_revision')
        if a.ordinal+1!=b.ordinal:return result('ineligible','spec_adjacency')
        if a.kind!='prose' or b.kind!='prose':return result('ineligible','atomic_kind')
        if not (a.complete_unit and b.complete_unit and a.part_count==b.part_count==1):return result('ineligible','multipart')
        ar,asu,aro,aq=self.boundary(a);br,bsu,bro,bq=self.boundary(b)
        parents={self.nodes[k].parent for k in ar+br}
        if len(parents)!=1 or None in parents:return result('ineligible','parent')
        siblings=self.children[next(iter(parents)).node_key]
        ai=[siblings.index(k) for k in ar];bi=[siblings.index(k) for k in br]
        if ai!=list(range(ai[0],ai[-1]+1)) or bi!=list(range(bi[0],bi[-1]+1)) or ai[-1]+1!=bi[0]:return result('ineligible','source_sibling_adjacency')
        if a.heading_path!=b.heading_path or not a.heading_path:return result('ineligible','section')
        if not asu or not bsu:return result('unknown_identity','no_explicit_subject')
        if asu!=bsu or len(asu)!=1:return result('ineligible','subject')
        if aro!=bro or set(aro)&PROTECTED:return result('ineligible','role')
        if aq!=bq:return result('ineligible','quality')
        keys={s.mapping.node.node_key for c in (a,b) for s in c.mappings if s.usage=='primary'}
        if any(self.nodes[k].node_type.value!='paragraph' for k in ar+br):return result('ineligible','typed_container')
        if any(self.nodes[k].attributes.model_dump(exclude_defaults=True) for k in keys):return result('ineligible','typed_attributes')
        if QUALIFICATION.search(a.text) or QUALIFICATION.search(b.text):return result('ineligible','qualification')
        if any(e.relation.value not in {'CONTAINS','HEADING_FOR'} and (e.from_node.node_key in keys or e.to_node.node_key in keys) for e in self.batch.source_graph.edges):return result('ineligible','semantic_edge')
        trial=self.pack((a,b))
        if trial is None:return result('ineligible','token_or_mapping_budget')
        return result('eligible','explicit_adjacent_peers')

    def pack(self,group):
        """Exact concatenation except identical inherited heading-prefix sharing.

        Qualifier/header/overlap spans are never deduplicated. Every original
        mapping keeps its own translation even when output bytes are shared.
        """
        raw=bytearray();translated=[];seen={};dedup=0;prefix_text=[]
        for c in group:
            original=c.text.encode();primary=[s.mapping.output_slice.start for s in c.mappings if s.usage!='inherited']
            end=min(primary) if primary else 0
            pref=[(i,s) for i,s in enumerate(c.mappings) if s.mapping.output_slice.end<=end]
            safe=bool(end and pref) and all(s.usage=='inherited' and s.mapping.role=='heading' and
                self.nodes[s.mapping.node.node_key].node_type.value=='heading' and
                self.nodes[s.mapping.node.node_key].semantic_role.value in {'unknown','title'} and
                not self.nodes[s.mapping.node.node_key].attributes.model_dump(exclude_defaults=True) and
                not QUALIFICATION.search(self.nodes[s.mapping.node.node_key].text) for _,s in pref)
            signature=tuple((s.mapping.node.canonical_json(),s.mapping.node_slice.start,s.mapping.node_slice.end,s.mapping.role,s.usage,
                s.mapping.output_slice.start,s.mapping.output_slice.end) for _,s in pref)
            key=(original[:end],signature)
            shared=safe and key in seen
            if raw:raw.extend(b'\n')
            offset=len(raw);skip=end if shared else 0
            raw.extend(original[skip:])
            if shared:dedup+=1
            else:
                if safe:seen[key]=offset
                if end:prefix_text.append(original[:end].decode())
            for i,s in enumerate(c.mappings):
                r=s.mapping.output_slice
                if shared and r.end<=end:new_start,new_end=seen[key]+r.start,seen[key]+r.end
                else:new_start,new_end=offset+r.start-skip,offset+r.end-skip
                translated.append(Translation(v1_spec_id=c.chunk_key,mapping_index=i,output_slice=ByteRange(start=new_start,end=new_end)))
        value=raw.decode();tokens=count_tokens(value);prefix_tokens=sum(count_tokens(s) for s in prefix_text)
        if tokens>(self.p.merge_max if len(group)>1 else self.p.hard_max) or len(translated)>256 or prefix_tokens>80:return None
        members=tuple(c.chunk_key for c in group)
        return Candidate(candidate_id=candidate_key(self.r,members,value,translated),members=members,
            kind=group[0].kind,text=value,token_count=tokens,prefix_tokens=prefix_tokens,
            translations=tuple(translated),deduplicated_prefixes=dedup)

    def run(self):
        reasons={};metadata={}
        for c in self.batch.chunks:
            reason=self.heading_reason(c)
            if reason is None:
                targets=self.heading_targets(c)
                if targets:metadata[c.chunk_key]=targets
                else:reason='orphan_or_unrepresented_heading'
            reasons[c.chunk_key]=reason or 'exact_descendant_heading'
        peers=tuple(self.peer(a,b) for a,b in zip(self.batch.chunks,self.batch.chunks[1:]))
        lookup={(p.left,p.right):p for p in peers};groups=[]
        for c in self.batch.chunks:
            if c.chunk_key in metadata:continue
            p=lookup.get((groups[-1][-1].chunk_key,c.chunk_key)) if groups else None
            if p and p.status=='eligible' and self.pack(tuple(groups[-1])+ (c,)) is not None:groups[-1].append(c)
            else:groups.append([c])
        candidates=[]
        for group in groups:
            candidate=self.pack(tuple(group))
            if candidate is None:raise SelectionError('unchanged v1 candidate violates v2 bounds')
            candidates.append(candidate)
        owners={k:c for c in candidates for k in c.members};ledger=[]
        for c in self.batch.chunks:
            if c.chunk_key in metadata:
                witnesses=[]
                for i,(key,index) in enumerate(metadata[c.chunk_key]):
                    owner=owners[key];translation=next(t for t in owner.translations if (t.v1_spec_id,t.mapping_index)==(key,index))
                    witnesses.append(Witness(mapping_index=i,candidate_id=owner.candidate_id,output_slice=translation.output_slice,
                        retained_spec_id=key,retained_mapping_index=index))
                outcome='metadata_only';owner=None;prefix='inherited_by_descendant';reason='exact_descendant_heading'
            else:
                owner=owners[c.chunk_key];witnesses=[];prefix='shared_exact_heading' if owner.deduplicated_prefixes else 'retained'
                uncertain=any(p.status=='unknown_identity' and c.chunk_key in (p.left,p.right) for p in peers)
                outcome='packed' if len(owner.members)>1 else ('unresolved' if uncertain else 'embedded')
                reason='explicit_adjacent_peers' if outcome=='packed' else ('unknown_identity_keep_embedded' if uncertain else reasons[c.chunk_key])
            ledger.append(Decision(v1_spec_id=c.chunk_key,outcome=outcome,reason=reason,
                candidate_id=owner.candidate_id if owner else None,prefix_disposition=prefix,
                heading_dependencies=tuple(h.node_key for h in c.heading_path),witnesses=tuple(witnesses)))
        primary_keys={s.mapping.node.node_key for c in self.batch.chunks if c.chunk_key not in metadata for s in c.mappings if s.usage=='primary'}
        result=Selection(v1=self.batch,policy=self.p,input_hash=self.batch.canonical_hash(),graph_hash=self.batch.source_graph.canonical_hash(),
            recipe_hash=self.r,candidates=tuple(candidates),ledger=tuple(ledger),peers=peers,
            graph_only_nodes=tuple(n.identity.node_key for n in self.batch.source_graph.nodes if n.identity.node_key not in primary_keys))
        return result.verify()


def select_structural_candidates(batch: SerializationBatch, policy: SelectionPolicy | None=None) -> Selection:
    return _Selection(batch,policy or SelectionPolicy()).run()
