"""Offline v2 heading allocation over frozen L packing and exact evidence.

Only search-container allocation changes. v1 is imported, never patched; typed
body packing, source graph, atoms, lexical coverage and budgets remain v1's.
One complete admitted descendant witnesses a heading, never a union of entries.
"""
from collections import defaultdict
from functools import lru_cache
import hashlib
from pathlib import Path
from typing import Literal

from services import structural_retrieval_entries as v1
from services.structural_document import Value, Digest
from services.structural_chunking import SerializationBatch, digest


class RetrievalEntryPolicy(v1.RetrievalEntryPolicy):
    version: Literal['structural-retrieval-entry-v2'] = 'structural-retrieval-entry-v2'
    heading_rule: Literal['single-complete-admitted-context-witness-v2'] = 'single-complete-admitted-context-witness-v2'


class StructuralRetrievalEntry(v1.StructuralRetrievalEntry):
    policy: RetrievalEntryPolicy


class HeadingAllocation(Value):
    scope: v1.RetrievalEntryScope
    atom_key: Digest
    disposition: Literal['CONTEXTUAL_ONLY', 'STANDALONE']
    witness_entry: Digest | None = None


def _old_policy(policy):
    return v1.RetrievalEntryPolicy(**policy.model_dump(exclude={'version', 'heading_rule'}))


@lru_cache(maxsize=1)
def _implementation_hash():
    return hashlib.sha256(Path(__file__).read_text(encoding='utf-8').replace('\r\n', '\n').encode()).hexdigest()


def recipe(policy, source_recipe):
    return digest({'policy': policy.model_dump(), 'implementation': _implementation_hash(),
                   'frozen_v1_recipe': v1.recipe(_old_policy(policy), source_recipe)})


def _batch_key(scope, ih, rh, entries, allocations):
    return digest({'scope': scope.model_dump(), 'input': ih, 'recipe': rh,
                   'entries': [e.entry_key for e in entries],
                   'heading_allocations': [a.model_dump() for a in allocations]})


def _part_gates(evidence):
    """Same quality/resource/uncertain-owner/barrier semantics as frozen v1.

    Section equality is deliberately not required: explicit heading_path can
    carry ancestor headings into nested sections. No text matching is used.
    """
    bounds = v1._boundaries(evidence)
    doc = evidence.source_graph
    uncertain_nodes = {e.from_node.node_key for e in doc.edges
                       if e.relation.value == 'DESCRIBES' and e.validation_state.value != 'validated'}
    quality, uncertain, barrier = {}, {}, {}
    serial = 0
    for n in doc.nodes:
        k = n.identity.node_key
        parent = n.parent.node_key if n.parent else None
        quality[k] = n.quality or (quality[parent] if parent else doc.revision.quality)
        uncertain[k] = k if k in uncertain_nodes else (uncertain[parent] if parent else '')
        if n.semantic_role.value in ('navigation', 'furniture') or quality[k].disposition.value == 'quarantine':
            serial += 1
        barrier[k] = serial
    gates = {}
    for c in evidence.chunks:
        primary = [s.mapping.node.node_key for s in c.mappings if s.usage == 'primary']
        owners = tuple(dict.fromkeys(uncertain[n.node_key] for n in c.members if uncertain[n.node_key]))
        if c.kind in ('review', 'product_card') and not bounds[c.chunk_key][3]:
            owners = owners or (c.bundle_key,)
        gates[c.chunk_key] = (bounds[c.chunk_key][2], bounds[c.chunk_key][3], owners, barrier[primary[0]])
    return gates


def _covers(ranges, interval):
    return v1._size(ranges + [interval]) == v1._size(ranges)


def complete_heading_witnesses(batch, *, scope):
    """Internal validated-batch analysis; public callers should use batch.verify.

    Representation reachability, NOT semantic dense recall. Full node identity,
    lexical atom, original inherited part and boundary are all required. Work is
    indexed by context memberships, not every heading times every entry.
    """
    if batch.scope != scope or batch.evidence.source_graph.revision.identity != scope.revision:
        raise v1.EntryError('foreign heading witness scope')
    parts = {c.chunk_key: c for c in batch.evidence.chunks}
    headings = {a.atom_key: a for a in batch.atoms if a.kind == 'heading'}
    lexical = {a.atom_key for a in batch.coverage.atoms}
    nodes = {n.identity: n for n in batch.evidence.source_graph.nodes}
    gates = _part_gates(batch.evidence)
    witnesses = {}
    for entry in batch.entries:
        if entry.scope != scope:
            raise v1.EntryError('foreign heading witness entry')
        bodies = [parts[m.source_part] for m in entry.memberships
                  if m.usage == 'body' and parts[m.source_part].kind != 'heading']
        if not bodies:
            continue
        candidates = {m.atom_key for m in entry.memberships if m.usage == 'context'} & headings.keys()
        inherited = defaultdict(list)
        for m in entry.mappings:
            if m.origin_usage == 'inherited':
                inherited[(m.atom_key, m.node, m.usage)].append((m.node_slice.start, m.node_slice.end))
        for key in sorted(candidates - witnesses.keys()):
            atom = headings[key]
            if key not in lexical or atom.scope != scope:
                continue
            source_parts = [parts[k] for k in atom.source_parts]
            required = [s.mapping for c in source_parts for s in c.mappings]
            primary = [s.mapping for c in source_parts for s in c.mappings if s.usage == 'primary']
            if not primary:
                continue
            # Inline link annotations can share primary heading bytes, but are
            # not hierarchy nodes. Their exact mappings remain required below.
            heading_nodes = {m.node for m in primary if nodes[m.node].node_type.value == 'heading'}
            if not heading_nodes:
                continue
            primary_ranges = defaultdict(list)
            for m in primary:
                primary_ranges[m.node].append((m.node_slice.start, m.node_slice.end))
            if any(v1._union(ranges) != [(0, len(nodes[node].text.encode()))]
                   for node, ranges in primary_ranges.items()):
                continue
            # A real selected body source part must authorize these inherited
            # headings. An unrelated equal string or forged extra mapping cannot.
            eligible = [c for c in bodies if heading_nodes.issubset(c.heading_path)
                        and all(gates[c.chunk_key] == gates[h.chunk_key] for h in source_parts)]
            if not eligible:
                continue
            actual = defaultdict(list)
            for c in eligible:
                for s in c.mappings:
                    if s.usage == 'inherited':
                        m = s.mapping
                        actual[(m.node, m.role)].append((m.node_slice.start, m.node_slice.end))
            # Complete required primary and companion mappings must survive in
            # THIS entry; no partial-byte or multi-entry union is a witness.
            if not all(_covers(actual[(m.node, m.role)], (m.node_slice.start, m.node_slice.end))
                       for m in required):
                continue
            if not all(_covers(inherited[(key, m.node, m.role)], (m.node_slice.start, m.node_slice.end))
                       for m in primary):
                continue
            companions = defaultdict(list)
            for m in entry.mappings:
                companions[(m.node, m.usage)].append((m.node_slice.start, m.node_slice.end))
            if all(_covers(companions[(m.node, m.role)], (m.node_slice.start, m.node_slice.end)) for m in required):
                witnesses[key] = entry.entry_key
    return witnesses


def _standalone_part(base, c, by_part, owners, boundary):
    """Exact one-part fallback for a heading v1 suppressed without a v2 witness.

    This is v1's single-part representation (no regrouping/splitting). Required
    companions and original continuations stay intact. No source text is edited.
    """
    members = [v1.RetrievalEntryMembership(scope=base.scope, atom_key=by_part[c.chunk_key],
        source_part=c.chunk_key, part_index=c.part_index, part_count=c.part_count, usage='body')]
    maps = []
    for span in c.mappings:
        m = span.mapping
        atom = by_part[c.chunk_key]
        if span.usage == 'inherited' and m.role == 'heading' and m.node.node_key in owners:
            atom, owner = owners[m.node.node_key]
            member = v1.RetrievalEntryMembership(scope=base.scope, atom_key=atom,
                source_part=owner.chunk_key, part_index=owner.part_index, part_count=owner.part_count, usage='context')
            if member not in members:
                members.append(member)
        maps.append(v1.RetrievalEntryMappedSpan(atom_key=atom, node=m.node, node_slice=m.node_slice,
            entry_slice=m.output_slice, usage=m.role, origin_usage=span.usage))
    key, section, quality, resources = boundary
    payload = dict(scope=base.scope, ordinal=0, kind='heading', text=c.text, section=section,
        evidence_atoms=tuple(dict.fromkeys(m.atom_key for m in members)),
        context_nodes=tuple(dict.fromkeys(m.node for m in maps if m.origin_usage == 'inherited')),
        memberships=tuple(members), mappings=tuple(maps), token_count=c.token_count, byte_count=c.byte_count,
        context_token_count=v1._context_tokens(c.text, maps), logical_child_count=len({m.atom_key for m in members}),
        mapping_count=len(maps), quality_key=quality, resources=resources, boundary_key=key,
        policy=base.policy, input_hash=base.input_hash, recipe_hash=base.recipe_hash,
        coverage_state='exact_routing_not_final_evidence')
    entry = v1.StructuralRetrievalEntry.model_validate(dict(payload, entry_key='0' * 64))
    return entry.model_copy(update={'entry_key': v1._entry_key(entry.model_dump(mode='json'))})


def _allocations(batch, *, scope):
    witnesses = complete_heading_witnesses(batch, scope=scope)
    body_parts = {m.source_part for e in batch.entries for m in e.memberships if m.usage == 'body'}
    rows = []
    for atom in batch.atoms:
        if atom.kind != 'heading':
            continue
        if atom.atom_key in witnesses:
            if body_parts.intersection(atom.source_parts):
                raise v1.EntryError('redundant standalone heading retained')
            rows.append(HeadingAllocation(scope=scope, atom_key=atom.atom_key,
                disposition='CONTEXTUAL_ONLY', witness_entry=witnesses[atom.atom_key]))
        else:
            if not set(atom.source_parts).issubset(body_parts):
                raise v1.EntryError('heading lacks full context witness or standalone fallback')
            rows.append(HeadingAllocation(scope=scope, atom_key=atom.atom_key, disposition='STANDALONE'))
    return tuple(rows)


class RetrievalEntryBatch(v1.RetrievalEntryBatch):
    policy: RetrievalEntryPolicy
    entries: tuple[StructuralRetrievalEntry, ...]
    heading_allocations: tuple[HeadingAllocation, ...]

    def verify(self, *, scope):
        policy = RetrievalEntryPolicy.model_validate_json(self.policy.canonical_json())
        if self.recipe_hash != recipe(policy, self.evidence.recipe_hash):
            raise v1.EntryError('v2 recipe mismatch')
        old_policy = _old_policy(policy)
        old_recipe = v1.recipe(old_policy, self.evidence.recipe_hash)
        converted = []
        for ordinal, entry in enumerate(self.entries):
            StructuralRetrievalEntry.model_validate_json(entry.canonical_json())
            if (entry.policy != policy or entry.recipe_hash != self.recipe_hash or entry.ordinal != ordinal
                    or entry.input_hash != self.input_hash or entry.entry_key != v1._entry_key(entry.model_dump(mode='json'))):
                raise v1.EntryError('v2 entry identity mismatch')
            data = entry.model_dump(mode='json')
            data.update(policy=old_policy.model_dump(mode='json'), recipe_hash=old_recipe)
            data['entry_key'] = v1._entry_key(data)
            converted.append(v1.StructuralRetrievalEntry.model_validate(data))
        # Reuse all frozen v1 byte/ownership/continuation/budget validators on a
        # lossless identity-rekeyed view. Never monkeypatch v1 or its fingerprints.
        legacy = v1.RetrievalEntryBatch(scope=self.scope, evidence=self.evidence, atoms=self.atoms,
            entries=tuple(converted), policy=old_policy, input_hash=self.input_hash, recipe_hash=old_recipe,
            coverage=v1._coverage(self.evidence, self.atoms, converted),
            batch_key=digest({'scope': self.scope.model_dump(), 'input': self.input_hash,
                             'recipe': old_recipe, 'entries': [e.entry_key for e in converted]}))
        legacy.verify(scope=scope)
        if self.coverage != v1._coverage(self.evidence, self.atoms, self.entries):
            raise v1.EntryError('v2 coverage mismatch')
        if self.heading_allocations != _allocations(self, scope=scope):
            raise v1.EntryError('v2 heading witness mismatch')
        if self.batch_key != _batch_key(scope, self.input_hash, self.recipe_hash, self.entries, self.heading_allocations):
            raise v1.EntryError('v2 batch key mismatch')
        if len(self.canonical_json().encode()) > policy.max_batch_bytes:
            raise v1.EntryError('v2 output batch byte bound exceeded')
        return self


def revise_heading_allocation(base: v1.RetrievalEntryBatch, *, scope: v1.RetrievalEntryScope,
                              policy: RetrievalEntryPolicy | None = None) -> RetrievalEntryBatch:
    """Revise an already selected offline v1 batch; lexical-only bodies stay so."""
    p = RetrievalEntryPolicy.model_validate_json((policy or RetrievalEntryPolicy()).canonical_json())
    if len(base.canonical_json().encode()) > p.max_batch_bytes:
        raise v1.EntryError('input batch byte bound exceeded')
    base = v1.RetrievalEntryBatch.model_validate_json(base.canonical_json()).verify(scope=scope)
    if base.policy != _old_policy(p):
        raise v1.EntryError('heading revision cannot change other packing rules')
    witnesses = complete_heading_witnesses(base, scope=scope)
    parts = {c.chunk_key: c for c in base.evidence.chunks}
    entries = []
    for entry in base.entries:
        bodies = [m for m in entry.memberships if m.usage == 'body']
        if any(m.atom_key in witnesses for m in bodies):
            # Frozen L never mixes heading bodies with other bodies. Refuse an
            # alternate input shape instead of dropping its unrelated evidence.
            if not all(m.atom_key in witnesses for m in bodies):
                raise v1.EntryError('mixed heading/body allocation cannot be pruned')
        else:
            entries.append(entry)
    represented = {m.source_part for e in entries for m in e.memberships if m.usage == 'body'}
    _, by_part, owners = v1._atoms(base.evidence, scope)
    bounds = v1._boundaries(base.evidence)
    for atom in base.atoms:
        if atom.kind == 'heading' and atom.atom_key not in witnesses:
            for key in atom.source_parts:
                if key not in represented:
                    entries.append(_standalone_part(base, parts[key], by_part, owners, bounds[key]))
    entries.sort(key=lambda e: min(parts[m.source_part].ordinal for m in e.memberships if m.usage == 'body'))
    rh = recipe(p, base.evidence.recipe_hash)
    revised = []
    for ordinal, entry in enumerate(entries):
        data = entry.model_dump(mode='json')
        data.update(ordinal=ordinal, policy=p.model_dump(mode='json'), recipe_hash=rh)
        data['entry_key'] = v1._entry_key(data)
        revised.append(StructuralRetrievalEntry.model_validate(data))
    data = dict(scope=scope, evidence=base.evidence, atoms=base.atoms, entries=tuple(revised), policy=p,
        input_hash=base.input_hash, recipe_hash=rh, coverage=v1._coverage(base.evidence, base.atoms, revised))
    provisional = RetrievalEntryBatch(**data, heading_allocations=(), batch_key='0' * 64)
    allocations = _allocations(provisional, scope=scope)
    result = RetrievalEntryBatch(**data, heading_allocations=allocations,
        batch_key=_batch_key(scope, base.input_hash, rh, revised, allocations))
    return result.verify(scope=scope)


def build_retrieval_entries(evidence: SerializationBatch, *, scope: v1.RetrievalEntryScope,
                            policy: RetrievalEntryPolicy | None = None) -> RetrievalEntryBatch:
    p = policy or RetrievalEntryPolicy()
    base = v1.build_retrieval_entries(evidence, scope=scope, policy=_old_policy(p))
    return revise_heading_allocation(base, scope=scope, policy=p)
