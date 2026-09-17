"""Source-exact Phase M import and atomic-fts-v1, independent of serving RAG."""
from collections import defaultdict
import hashlib

from services import structural_retrieval_entries_v2 as m
from services.structural_retrieval_entries import _size
from services.structural_chunking import digest
from services.canary_contracts import CanaryError, SourcePin


def _uncovered(start, end, intervals):
    pieces = [(start, end)]
    for a, b in intervals:
        pieces = [(x, y) for left, right in pieces
                  for x, y in ((left, min(a, right)), (max(b, left), right)) if x < y]
    return pieces


def atomic_projection(batch, atom):
    """Dedup only repeated scoped node intervals; preserve exact original parts too."""
    if atom.scope != batch.scope or atom not in batch.atoms:
        raise CanaryError('FOREIGN_ATOM')
    parts = {p.chunk_key: p for p in batch.evidence.chunks}
    nodes = {n.identity: n for n in batch.evidence.source_graph.nodes}
    own_nodes = set(atom.nodes)
    seen = defaultdict(list)
    segments, maps = [], []
    offset = 0
    original = [parts[k] for k in atom.source_parts]
    if [p.part_index for p in original] != list(range(len(original))) or any(p.part_count != len(original) for p in original):
        raise CanaryError('INCOMPLETE_CONTINUATION')
    for part in original:
        for span in part.mappings:
            v = span.mapping
            if span.usage == 'inherited' and v.role == 'heading' and v.node not in own_nodes:
                continue
            node = nodes[v.node]
            raw = node.text.encode('utf-8')
            a, b = v.node_slice.start, v.node_slice.end
            if raw[a:b] != part.text.encode()[v.output_slice.start:v.output_slice.end]:
                raise CanaryError('ATOM_SOURCE_BYTES_MISMATCH')
            for left, right in _uncovered(a, b, seen[v.node]):
                text = raw[left:right].decode('utf-8')
                if segments:
                    offset += 1  # versioned LF separator, not source evidence
                segments.append(text)
                maps.append(dict(node=v.node.model_dump(mode='json'), node_slice=[left, right],
                    projection_slice=[offset, offset + right-left], role=v.role,
                    origin=span.usage, source_part=part.chunk_key))
                offset += right-left
            seen[v.node].append((a, b))
    payload = dict(policy='atomic-fts-v1', atom=atom.model_dump(mode='json'),
        canonical_text='\n'.join(segments), projection_maps=maps,
        source_parts=[p.model_dump(mode='json') for p in original],
        nodes=[nodes[n].model_dump(mode='json') for n in atom.nodes])
    return payload


def primary_routes(batch):
    """Frozen ownership-based routing, never query similarity or string equality."""
    witnesses = {a.atom_key: a.witness_entry for a in batch.heading_allocations if a.witness_entry}
    parts = {c.chunk_key: c for c in batch.evidence.chunks}
    result = {}
    for atom in batch.atoms:
        bodies, contexts = [], []
        for entry in batch.make_index().entries_for_atom(atom.atom_key, scope=batch.scope):
            body = [v for v in entry.memberships if v.atom_key == atom.atom_key and v.usage == 'body']
            if body:
                bodies.append((min(v.part_index for v in body), entry.ordinal, entry.entry_key))
            else:
                actual = defaultdict(list)
                for v in entry.mappings:
                    actual[(v.node, v.usage)].append((v.node_slice.start, v.node_slice.end))
                required = [s.mapping for key in atom.source_parts for s in parts[key].mappings]
                if all(_size(actual[(s.node, s.role)] + [(s.node_slice.start, s.node_slice.end)]) ==
                       _size(actual[(s.node, s.role)]) for s in required):
                    contexts.append((entry.ordinal, entry.entry_key))
        if bodies:
            result[atom.atom_key] = ('ENTRY', min(bodies)[2])
        elif atom.atom_key in witnesses:
            result[atom.atom_key] = ('ENTRY', witnesses[atom.atom_key])
        elif contexts:
            result[atom.atom_key] = ('ENTRY', min(contexts)[1])
        else:
            result[atom.atom_key] = ('ATOM_ONLY', atom.atom_key)
    return result


def prepare_batch(batch):
    # JSON round-trip rejects unsafe model_copy/update ingress; exact M verifier.
    batch = m.RetrievalEntryBatch.model_validate_json(batch.canonical_json()).verify(scope=batch.scope)
    projections = tuple(atomic_projection(batch, a) for a in batch.atoms)
    routes = primary_routes(batch)
    mappings = dict(memberships=[v.model_dump(mode='json') | {'entry': e.entry_key}
                               for e in batch.entries for v in e.memberships],
                    spans=[v.model_dump(mode='json') | {'entry': e.entry_key}
                           for e in batch.entries for v in e.mappings])
    if len(mappings['spans']) > 25000:
        raise CanaryError('SPAN_CAPACITY')
    return batch, projections, routes, mappings


def source_pin(batch, *, source_id, website_id=None):
    batch, atoms, routes, mappings = prepare_batch(batch)
    return SourcePin(scope=batch.scope, source_id=source_id, website_id=website_id,
        batch_hash=batch.canonical_hash(), entries=tuple(e.entry_key for e in batch.entries),
        atoms=tuple(a.atom_key for a in batch.atoms), mapping_hash=digest(mappings),
        projection_hash=digest({'atoms': atoms, 'routes': routes}),
        quality_hash=digest(batch.coverage.model_dump(mode='json')))


def exact_input_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def evidence_view(payload):
    """Lossless source fields with repeated identity/policy moved to outer scope.

    Original immutable payload digest remains attached. No source strings,
    roles, attributes, ranges, continuation or qualification mappings are cut.
    """
    parts=[]
    for p in payload['source_parts']:
        parts.append({k:p[k] for k in ('chunk_key','bundle_key','kind','text','part_index','part_count',
            'complete_unit','source_block_complete','list_item_indices','byte_count')} | {
            'heading_path':[n['node_key'] for n in p['heading_path']],
            'table_cells':[n['node_key'] for n in p['table_cells']],
            'mappings':[dict(node=v['mapping']['node']['node_key'],node_slice=v['mapping']['node_slice'],
                output_slice=v['mapping']['output_slice'],role=v['mapping']['role'],origin=v['usage']) for v in p['mappings']]})
    nodes=[]
    for n in payload['nodes']:
        # Node payload is retained; remove only repeated revision/source scopes.
        row=dict(n)
        row['identity']=n['identity']['node_key']
        row['parent']=n['parent']['node_key'] if n['parent'] else None
        provenance=dict(n['provenance'])
        provenance['spans']=[{'location':v['location']} for v in provenance['spans']]
        row['provenance']=provenance
        nodes.append(row)
    return dict(atom=payload['atom'],policy=payload['policy'],original_payload_hash=digest(payload),
                source_parts=parts,nodes=nodes)
