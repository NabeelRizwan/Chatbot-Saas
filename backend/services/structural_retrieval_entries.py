"""Offline search representations over immutable v1 evidence; never final evidence.

No DB, provider, query, retrieval or ingestion imports. The trusted caller supplies
scope separately. Existing v1 bundles supply typed atomic units/continuations;
their graph and mappings are retained, not repacked or rewritten. See the L ledger.
"""
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
import hashlib
from pathlib import Path
import re
from types import MappingProxyType
from typing import Literal

from pydantic import Field, model_validator
from services.structural_document import (
    Value, Digest, Positive, NonNegative, ByteRange, NodeIdentity, RevisionIdentity,
)
from services.structural_chunking import SerializationBatch, count_tokens, digest, local_tokenizer


class EntryError(ValueError):
    """Fail closed; no partial batch escapes a failed construction."""


class RetrievalEntryPolicy(Value):
    version: Literal['structural-retrieval-entry-v1'] = 'structural-retrieval-entry-v1'
    target: Positive = Field(default=500, le=800)
    soft_min: Positive = Field(default=250, le=800)
    soft_max: Positive = Field(default=700, le=800)
    hard_max: Positive = Field(default=800, le=800)
    context_max: NonNegative = Field(default=80, le=80)
    max_children: Positive = Field(default=32, le=32)
    max_mappings: Positive = Field(default=256, le=256)
    max_parts: Positive = Field(default=256, le=256)
    max_entries: Positive = Field(default=10000, le=20000)
    max_output_bytes: Positive = Field(default=33554432, le=33554432)
    max_batch_bytes: Positive = Field(default=134217728, le=134217728)
    heading_rule: Literal['exact-descendant-context-or-standalone-v1'] = 'exact-descendant-context-or-standalone-v1'
    boundary_rule: Literal['section-quality-resource-unresolved-v1'] = 'section-quality-resource-unresolved-v1'

    @model_validator(mode='after')
    def ordered(self):
        if not self.soft_min <= self.target <= self.soft_max <= self.hard_max or self.context_max >= self.hard_max:
            raise ValueError('inconsistent entry budgets')
        return self


class RetrievalEntryScope(Value):
    revision: RevisionIdentity
    crawl_id: Positive | None = None
    crawl_version: Positive | None = None

    @model_validator(mode='after')
    def paired(self):
        if (self.crawl_id is None) != (self.crawl_version is None):
            raise ValueError('crawl identity requires ID and version')
        return self


class EvidenceAtom(Value):
    scope: RetrievalEntryScope
    atom_key: Digest
    bundle_key: Digest
    kind: Literal['prose','heading','list','table','faq','review','product_card',
                  'price_block','directions','ingredients','timeline_stage','warning']
    nodes: tuple[NodeIdentity, ...]
    source_parts: tuple[Digest, ...]


class RetrievalEntryMappedSpan(Value):
    atom_key: Digest
    node: NodeIdentity
    node_slice: ByteRange
    entry_slice: ByteRange
    usage: Literal['body','heading','header','qualifier','context']
    origin_usage: Literal['primary','inherited','overlap']


class RetrievalEntryMembership(Value):
    scope: RetrievalEntryScope
    atom_key: Digest
    source_part: Digest
    part_index: NonNegative
    part_count: Positive
    usage: Literal['body','context']

    @model_validator(mode='after')
    def part(self):
        if self.part_index >= self.part_count:
            raise ValueError('invalid continuation')
        return self


class StructuralRetrievalEntry(Value):
    scope: RetrievalEntryScope
    entry_key: Digest
    ordinal: NonNegative
    kind: Literal['contextual','heading','continuation']
    text: str
    section: NodeIdentity
    evidence_atoms: tuple[Digest, ...]
    context_nodes: tuple[NodeIdentity, ...]
    memberships: tuple[RetrievalEntryMembership, ...]
    mappings: tuple[RetrievalEntryMappedSpan, ...]
    token_count: NonNegative
    byte_count: NonNegative
    context_token_count: NonNegative
    logical_child_count: NonNegative
    mapping_count: NonNegative
    quality_key: Digest
    resources: tuple[NodeIdentity, ...]
    boundary_key: Digest
    policy: RetrievalEntryPolicy
    input_hash: Digest
    recipe_hash: Digest
    coverage_state: Literal['exact_routing_not_final_evidence'] = 'exact_routing_not_final_evidence'

    @model_validator(mode='after')
    def bounded(self):
        p = self.policy
        if (self.token_count > p.hard_max or self.context_token_count > p.context_max
                or self.logical_child_count > p.max_children or self.mapping_count > p.max_mappings):
            raise ValueError('entry bound exceeded')
        if self.logical_child_count != len(self.evidence_atoms) or self.mapping_count != len(self.mappings):
            raise ValueError('entry count mismatch')
        if any(m.scope != self.scope for m in self.memberships):
            raise ValueError('foreign membership')
        if any(n.revision != self.scope.revision for n in (self.section, *self.context_nodes)):
            raise ValueError('foreign context/section')
        if any(m.node.revision != self.scope.revision for m in self.mappings):
            raise ValueError('foreign mapping')
        return self


class CoverageRow(Value):
    node: NodeIdentity
    disposition: Literal['DENSE_AND_LEXICAL','LEXICAL_ONLY','GRAPH_ONLY','EXCLUDED_WITH_REASON']
    source_bytes: NonNegative
    mapped_bytes: NonNegative
    excluded_bytes: NonNegative
    reasons: tuple[str, ...]


class AtomDisposition(Value):
    atom_key: Digest
    disposition: Literal['DENSE_AND_LEXICAL','LEXICAL_ONLY']
    entry_keys: tuple[Digest, ...]


class RetrievalEntryCoverageLedger(Value):
    nodes: tuple[CoverageRow, ...]
    atoms: tuple[AtomDisposition, ...]
    unaccounted_bytes: Literal[0] = 0


@dataclass(frozen=True)
class RetrievalEntryIndex:
    scope: RetrievalEntryScope
    entries: object
    atoms: object
    reverse: object

    def entries_for_atom(self, atom_key, *, scope):
        if scope != self.scope or atom_key not in self.atoms:
            raise EntryError('foreign or unknown atom')
        return tuple(self.entries[k] for k in self.reverse[atom_key])

    def atoms_for_entry(self, entry_key, *, scope):
        if scope != self.scope or entry_key not in self.entries:
            raise EntryError('foreign or unknown entry')
        return tuple(self.atoms[k] for k in self.entries[entry_key].evidence_atoms)


class RetrievalEntryBatch(Value):
    scope: RetrievalEntryScope
    batch_key: Digest
    evidence: SerializationBatch
    atoms: tuple[EvidenceAtom, ...]
    entries: tuple[StructuralRetrievalEntry, ...]
    coverage: RetrievalEntryCoverageLedger
    policy: RetrievalEntryPolicy
    input_hash: Digest
    recipe_hash: Digest

    def make_index(self):
        return RetrievalEntryIndex(self.scope,
            MappingProxyType({e.entry_key:e for e in self.entries}),
            MappingProxyType({a.atom_key:a for a in self.atoms}),
            MappingProxyType({r.atom_key:r.entry_keys for r in self.coverage.atoms}))

    def verify(self, *, scope):
        if scope != self.scope or self.evidence.source_graph.revision.identity != scope.revision:
            raise EntryError('trusted source scope mismatch')
        self.evidence.verify()
        if self.input_hash != self.evidence.canonical_hash():
            raise EntryError('input hash mismatch')
        if self.recipe_hash != recipe(self.policy, self.evidence.recipe_hash):
            raise EntryError('recipe mismatch')
        atoms, by_part, heading_owners = _atoms(self.evidence, scope)
        if atoms != self.atoms:
            raise EntryError('atomic identity mismatch')
        nodes = {n.identity.node_key:n for n in self.evidence.source_graph.nodes}
        atom_map = {a.atom_key:a for a in atoms}
        atom_nodes = {a.atom_key:frozenset(a.nodes) for a in atoms}
        parts = {c.chunk_key:c for c in self.evidence.chunks}
        metadata = _boundaries(self.evidence)
        for ordinal,e in enumerate(self.entries):
            StructuralRetrievalEntry.model_validate_json(e.canonical_json())
            if (e.ordinal != ordinal or e.scope != scope or e.policy != self.policy
                    or e.input_hash != self.input_hash or e.recipe_hash != self.recipe_hash
                    or e.entry_key != _entry_key(e.model_dump(mode='json'))):
                raise EntryError('entry identity mismatch')
            raw = e.text.encode()
            if len(raw)!=e.byte_count or count_tokens(e.text)!=e.token_count:
                raise EntryError('entry text count mismatch')
            seen = bytearray(len(raw))
            for m in e.mappings:
                if m.atom_key not in atom_map or m.node not in atom_nodes[m.atom_key]:
                    raise EntryError('mapping not owned by atom')
                n = nodes.get(m.node.node_key)
                a,b = m.node_slice,m.entry_slice
                if not n or n.identity!=m.node or b.end>len(raw) or a.end>len(n.text.encode()) or a.start==a.end:
                    raise EntryError('mapping range mismatch')
                original=n.text.encode()[a.start:a.end]; actual=raw[b.start:b.end]
                original.decode();actual.decode()
                if original!=actual:
                    raise EntryError('mapping byte mismatch')
                seen[b.start:b.end]=b'\1'*(b.end-b.start)
            if any(not covered and raw[i]!=10 for i,covered in enumerate(seen)):
                raise EntryError('unmapped nonseparator bytes')
            if e.context_token_count != _context_tokens(e.text,e.mappings):
                raise EntryError('context token mismatch')
            if e.evidence_atoms != tuple(dict.fromkeys(m.atom_key for m in e.memberships)):
                raise EntryError('membership ordering mismatch')
            if set(m.atom_key for m in e.mappings)!=set(e.evidence_atoms):
                raise EntryError('unrepresented or unregistered atom membership')
            for m in e.memberships:
                c=parts.get(m.source_part)
                if not c or by_part[c.chunk_key]!=m.atom_key or (m.part_index,m.part_count)!=(c.part_index,c.part_count):
                    raise EntryError('invalid source continuation reference')
                if m.usage=='body' and metadata[c.chunk_key][0]!=e.boundary_key:
                    raise EntryError('entry crossed hard boundary')
                if m.usage=='body':
                    _,sec,q,rs=metadata[c.chunk_key]
                    if (sec,q,rs)!=(e.section,e.quality_key,e.resources):
                        raise EntryError('entry boundary metadata mismatch')
                    # Every original part span (including mandatory context) must
                    # survive. Shared heading mappings may belong to their own atom.
                    actual=defaultdict(list)
                    for span in e.mappings:
                        actual[(span.node,span.usage)].append((span.node_slice.start,span.node_slice.end))
                    for span in c.mappings:
                        source=span.mapping; key=(source.node,source.role)
                        interval=(source.node_slice.start,source.node_slice.end)
                        if _size(actual[key]+[interval])!=_size(actual[key]):
                            raise EntryError('required source part span lost')
        if self.coverage != _coverage(self.evidence,self.atoms,self.entries):
            raise EntryError('coverage mismatch')
        if self.batch_key != digest({'scope':scope.model_dump(),'input':self.input_hash,
                                     'recipe':self.recipe_hash,'entries':[e.entry_key for e in self.entries]}):
            raise EntryError('batch key mismatch')
        if len(self.entries)>self.policy.max_entries or sum(e.byte_count for e in self.entries)>self.policy.max_output_bytes:
            raise EntryError('batch output bound exceeded')
        return self


@lru_cache(maxsize=1)
def _implementation_hash():
    return hashlib.sha256(Path(__file__).read_text(encoding='utf-8').replace('\r\n','\n').encode()).hexdigest()


def recipe(policy, source_recipe):
    return digest({'policy':policy.model_dump(),'implementation':_implementation_hash(),
                   'tokenizer':local_tokenizer()[1],'source_serializer_recipe':source_recipe})


def _entry_key(data):
    return digest({k:v for k,v in data.items() if k!='entry_key'})


def _union(intervals):
    result=[]
    for a,b in sorted(intervals):
        if result and a<=result[-1][1]: result[-1]=(result[-1][0],max(b,result[-1][1]))
        else: result.append((a,b))
    return result


def _size(intervals): return sum(b-a for a,b in _union(intervals))


def _context_tokens(text,maps):
    ranges=_union((m.entry_slice.start,m.entry_slice.end) for m in maps if m.origin_usage=='inherited')
    raw=text.encode()
    return count_tokens('\n'.join(raw[a:b].decode() for a,b in ranges)+'\n') if ranges else 0


def _atoms(batch,scope):
    groups={}; by_part={}; heading_owners={}
    for c in batch.chunks:
        groups.setdefault(c.bundle_key,[]).append(c)
    atoms=[]
    for bundle,parts in groups.items():
        key=digest({'scope':scope.model_dump(),'bundle':bundle})
        nodes=tuple(dict.fromkeys(n for c in parts for n in (*c.members,*c.source_nodes)))
        atoms.append(EvidenceAtom(scope=scope,atom_key=key,bundle_key=bundle,kind=parts[0].kind,
                                  nodes=nodes,source_parts=tuple(c.chunk_key for c in parts)))
        for c in parts:
            by_part[c.chunk_key]=key
            if c.kind=='heading':
                for m in c.mappings:
                    if m.usage=='primary': heading_owners[m.mapping.node.node_key]=(key,c)
    return tuple(atoms),by_part,heading_owners


def _boundaries(batch):
    doc=batch.source_graph; nodes={n.identity.node_key:n for n in doc.nodes}
    quality={}; section={}; resources={}; own=defaultdict(list)
    uncertain_nodes=set(); uncertain={}
    for e in doc.edges:
        if e.relation.value=='DESCRIBES':
            if e.validation_state.value=='validated': own[e.from_node.node_key].append(e.to_node)
            else: uncertain_nodes.add(e.from_node.node_key)
    barrier={}; serial=0
    for n in doc.nodes:
        k=n.identity.node_key;p=n.parent.node_key if n.parent else None
        uncertain[k]=k if k in uncertain_nodes else (uncertain[p] if p else '')
        quality[k]=n.quality or (quality[p] if p else doc.revision.quality)
        section[k]=n.identity if n.node_type.value in ('section','document') else section[p]
        resources[k]=tuple(own[k]) if own[k] else (resources[p] if p else ())
        if n.semantic_role.value in ('navigation','furniture') or quality[k].disposition.value=='quarantine': serial+=1
        barrier[k]=serial
    result={}
    for c in batch.chunks:
        primary=[m.mapping.node.node_key for m in c.mappings if m.usage=='primary']
        if not primary: raise EntryError('evidence part lacks primary mapping')
        k=primary[0]; q=quality[k].canonical_hash(); sec=section[k]
        rs=tuple(dict.fromkeys(r for node in c.members for r in resources[node.node_key]))
        # Source-backed DESCRIBES is relevance only. Conflicting ownership refuses
        # the atom rather than letting a routing entry hide the conflict.
        if len(rs)>1: raise EntryError('atomic unit crosses known resource boundary')
        unknown_owners=tuple(dict.fromkeys(uncertain[node.node_key] for node in c.members if uncertain[node.node_key]))
        if len(unknown_owners)>1: raise EntryError('atomic unit crosses unresolved ownership boundary')
        unresolved=unknown_owners or ((c.bundle_key,) if c.kind in ('review','product_card') and not rs else ())
        boundary=digest({'section':sec.model_dump(),'quality':q,'resources':[r.model_dump() for r in rs],
                         'unresolved':unresolved,'barrier':barrier[k],
                         'headings':[n.model_dump() for n in c.heading_path]})
        result[c.chunk_key]=(boundary,sec,q,rs)
    return result


def _coverage(batch,atoms,entries):
    mapped=defaultdict(list); expected=defaultdict(list); excluded=defaultdict(list); reasons=defaultdict(set)
    for c in batch.chunks:
        for s in c.mappings:
            m=s.mapping; expected[m.node.node_key].append((m.node_slice.start,m.node_slice.end))
    reverse=defaultdict(list)
    for e in entries:
        for a in e.evidence_atoms: reverse[a].append(e.entry_key)
        for m in e.mappings: mapped[m.node.node_key].append((m.node_slice.start,m.node_slice.end))
    for x in batch.excluded:
        k=x.node.node_key; excluded[k].append((x.node_slice.start,x.node_slice.end));reasons[k].add(x.reason)
    # Inline link metadata can be excluded by its exact containing parent span.
    # Follow parent provenance only (bounded depth), never text-find/global scan.
    node_map={n.identity.node_key:n for n in batch.source_graph.nodes}
    for n in batch.source_graph.nodes:
        k=n.identity.node_key
        if expected[k] or not n.attributes.link: continue
        ns=next((s.location.byte_range for s in n.provenance.spans if s.location.system.value=='utf8_bytes'),None)
        parent=n.parent
        while ns and parent:
            pn=node_map[parent.node_key]
            ps=next((s.location.byte_range for s in pn.provenance.spans if s.location.system.value=='utf8_bytes'),None)
            if ps and any(ps.start+a<=ns.start and ps.start+z>=ns.end for a,z in excluded[parent.node_key]):
                excluded[k]=[(0,len(n.text.encode()))];reasons[k].add('link_metadata_only');break
            parent=pn.parent
    rows=[]
    for n in batch.source_graph.nodes:
        k=n.identity.node_key; total=len(n.text.encode()); exp=_size(expected[k]); got=_size(mapped[k]); ex=_size(excluded[k])
        # Lexical coverage uses original exact atom mappings, never dense text.
        if _size(expected[k]+excluded[k])!=total:
            raise EntryError('unaccounted source evidence bytes')
        if _size(expected[k]+mapped[k])!=exp:
            raise EntryError('entry introduced ineligible source bytes')
        disposition=('DENSE_AND_LEXICAL' if got else 'LEXICAL_ONLY') if exp else (
            'EXCLUDED_WITH_REASON' if ex else 'GRAPH_ONLY')
        rows.append(CoverageRow(node=n.identity,disposition=disposition,source_bytes=total,
            mapped_bytes=got,excluded_bytes=ex,reasons=tuple(sorted(reasons[k])) or (('empty_structure',) if not total else ())))
    return RetrievalEntryCoverageLedger(nodes=tuple(rows),atoms=tuple(AtomDisposition(atom_key=a.atom_key,
        disposition='DENSE_AND_LEXICAL' if reverse[a.atom_key] else 'LEXICAL_ONLY',
        entry_keys=tuple(dict.fromkeys(reverse[a.atom_key]))) for a in atoms))


def _leading_headings(c):
    spans=[s.mapping for s in c.mappings if s.usage=='inherited' and s.mapping.role=='heading']
    end=0; chosen=[]; raw=c.text.encode()
    for m in sorted(spans,key=lambda m:m.output_slice.start):
        a,b=m.output_slice.start,m.output_slice.end
        if a!=end: break
        chosen.append((m.node.node_key,m.node_slice.start,m.node_slice.end))
        end=b+(1 if raw[b:b+1]==b'\n' else 0)
    if any(s.mapping.output_slice.start<end and (s.usage!='inherited' or s.mapping.role!='heading') for s in c.mappings):
        return (),0
    return tuple(chosen),end


def build_retrieval_entries(evidence: SerializationBatch, *, scope: RetrievalEntryScope,
                            policy: RetrievalEntryPolicy | None=None) -> RetrievalEntryBatch:
    """One source at a time; v1 provides exact atom bundles and safe continuations.

    Ingress revalidates all frozen DTOs even after unchecked model_copy. The caller
    must supply independently trusted scope; no text/URL metadata is consulted.
    """
    p=RetrievalEntryPolicy.model_validate_json((policy or RetrievalEntryPolicy()).canonical_json())
    scope=RetrievalEntryScope.model_validate_json(scope.canonical_json())
    raw=evidence.canonical_json()
    if len(raw.encode())>p.max_batch_bytes: raise EntryError('input batch byte bound exceeded')
    b=SerializationBatch.model_validate_json(raw).verify()
    if b.source_graph.revision.identity!=scope.revision: raise EntryError('trusted source scope mismatch')
    atoms,by_part,heading_owners=_atoms(b,scope); boundaries=_boundaries(b)
    atom_kinds={a.atom_key:a.kind for a in atoms}
    ih=b.canonical_hash();rh=recipe(p,b.recipe_hash)
    nodes={n.identity.node_key:n for n in b.source_graph.nodes}
    inherited=defaultdict(list)
    for c in b.chunks:
        if c.kind!='heading':
            for s in c.mappings:
                if s.usage=='inherited' and s.mapping.role=='heading':
                    m=s.mapping;inherited[m.node.node_key].append((m.node_slice.start,m.node_slice.end))
    skip=set()
    for c in b.chunks:
        if c.kind!='heading': continue
        primary=[s.mapping for s in c.mappings if s.usage=='primary']
        useful=any(re.search(r'[\d?!]|\b(?:warning|must|never|shall)\b',nodes[m.node.node_key].text,re.I) for m in primary)
        if not useful and all(_size(inherited[m.node.node_key]+[(m.node_slice.start,m.node_slice.end)])==_size(inherited[m.node.node_key]) for m in primary):
            skip.add(c.chunk_key)
    entries=[]; current=None; prefix_signature=(); prefix_end=0

    def flush():
        nonlocal current,prefix_signature,prefix_end
        if current is None: return
        current['ordinal']=len(entries)
        current['entry_key']=_entry_key(current)
        entries.append(StructuralRetrievalEntry.model_validate(current))
        if len(entries)>p.max_entries: raise EntryError('entry count bound exceeded')
        current=None;prefix_signature=();prefix_end=0

    def candidate(c,base):
        boundary,sec,q,rs=boundaries[c.chunk_key]
        data=dict(base) if base else dict(scope=scope.model_dump(mode='json'),ordinal=0,kind='contextual',
            section=sec.model_dump(mode='json'),quality_key=q,resources=[r.model_dump(mode='json') for r in rs],
            boundary_key=boundary,policy=p.model_dump(mode='json'),input_hash=ih,recipe_hash=rh,
            coverage_state='exact_routing_not_final_evidence')
        sig,lead=_leading_headings(c)
        cut=lead if base and sig and sig==prefix_signature else 0
        prefix=(base['text']+'\n') if base else ''
        rawpart=c.text.encode()[cut:];text=prefix+rawpart.decode(); offset=len(prefix.encode())
        maps=list(base['mappings']) if base else [];members=list(base['memberships']) if base else []
        def member(atom,part,usage):
            m=RetrievalEntryMembership(scope=scope,atom_key=atom,source_part=part.chunk_key,
                part_index=part.part_index,part_count=part.part_count,usage=usage).model_dump(mode='json')
            if m not in members: members.append(m)
        member(by_part[c.chunk_key],c,'body')
        for s in c.mappings:
            m=s.mapping; atom=by_part[c.chunk_key]
            if s.usage=='inherited' and m.role=='heading' and m.node.node_key in heading_owners:
                atom,owner=heading_owners[m.node.node_key];member(atom,owner,'context')
            a,z=m.output_slice.start,m.output_slice.end
            if cut and z<=cut: ea,ez=a,z
            elif a>=cut: ea,ez=offset+a-cut,offset+z-cut
            else: raise EntryError('prefix cut crosses source mapping')
            mapped=RetrievalEntryMappedSpan(atom_key=atom,node=m.node,node_slice=m.node_slice,
                entry_slice=ByteRange(start=ea,end=ez),usage=m.role,origin_usage=s.usage).model_dump(mode='json')
            if mapped not in maps: maps.append(mapped)
        ms=tuple(RetrievalEntryMappedSpan.model_validate(m) for m in maps)
        ids=list(dict.fromkeys(m['atom_key'] for m in members))
        kinds={atom_kinds[k] for k in ids} if c.kind=='heading' else set()
        data.update(text=text,mappings=maps,memberships=members,evidence_atoms=ids,
            context_nodes=[n.model_dump(mode='json') for n in dict.fromkeys(m.node for m in ms if m.origin_usage=='inherited')],
            token_count=count_tokens(text),byte_count=len(text.encode()),context_token_count=_context_tokens(text,ms),
            logical_child_count=len(ids),mapping_count=len(maps),
            kind='heading' if kinds=={'heading'} else ('continuation' if any(m['part_count']>1 for m in members if m['usage']=='body') else 'contextual'))
        return data

    total_bytes=0
    for c in b.chunks:
        if c.part_count>p.max_parts: raise EntryError('continuation bound exceeded')
        if c.chunk_key in skip: continue
        if current and (boundaries[c.chunk_key][0]!=current['boundary_key'] or c.kind=='heading' or current['kind']=='heading'):
            flush()
        trial=candidate(c,current)
        fits=(trial['token_count']<=p.soft_max and trial['context_token_count']<=p.context_max
              and trial['logical_child_count']<=p.max_children and trial['mapping_count']<=p.max_mappings)
        # Past target only accept a genuinely small tail, not an arbitrary peer.
        if current and (not fits or (current['token_count']>=p.target and c.token_count>=p.soft_min)):
            flush();trial=candidate(c,None)
        if current is None: prefix_signature,prefix_end=_leading_headings(c)
        StructuralRetrievalEntry.model_validate(dict(trial,entry_key='0'*64))
        current=trial
        total_bytes+=c.byte_count
        if total_bytes>p.max_output_bytes: raise EntryError('serialized byte bound exceeded')
    flush()
    ledger=_coverage(b,atoms,entries)
    result=RetrievalEntryBatch(scope=scope,batch_key=digest({'scope':scope.model_dump(),'input':ih,'recipe':rh,
        'entries':[e.entry_key for e in entries]}),evidence=b,atoms=atoms,entries=tuple(entries),coverage=ledger,
        policy=p,input_hash=ih,recipe_hash=rh)
    if len(result.canonical_json().encode())>p.max_batch_bytes: raise EntryError('output batch byte bound exceeded')
    return result.verify(scope=scope)
