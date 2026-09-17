"""Frozen M fixture construction and exact reachability assertions; offline only."""
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path

from scripts.evaluate_structural_text_adapter import parse_source
from services.structural_document import (
    StructuralDocument, SemanticRole, SourceQuality, StructuralEdge, Relation,
    ValidationState, SourceLocation, CoordinateSystem, PageBox, make_node_key,
)
from services.structural_chunking import serialize_structural_document, digest, count_tokens
from services import structural_retrieval_entries as v1

ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / 'backend/fixtures/structural_retrieval_heading_gold_v1'


def cases():
    raw = (GOLD / 'cases.json').read_bytes().replace(b'\r\n', b'\n')
    manifest = json.loads((GOLD / 'manifest.json').read_text())
    assert sha256(raw).hexdigest() == manifest['cases_sha256']
    result = json.loads(raw)['cases']
    assert len(result) == manifest['case_count']
    return result


def evidence(spec):
    heading, body, variant = spec['heading'], spec['body'], spec.get('variant')
    text = '# ' + (heading or 'Empty DTO heading') + ('\n\n' + body if body else '')
    if variant == 'duplicate':
        text += '\n\n# ' + heading + '\n\nA different source occurrence.'
    if variant == 'multiple':
        text += '\n\n## First child\n\nA child passage.\n\n## Second child\n\nAnother passage.'
    if variant == 'nested':
        text += '\n\n## Inner 2\n\nAnother passage.'
    if variant == 'barrier':
        text = '# ' + heading + '\n\nNavigation marker\n\n' + body
    doc = parse_source(text)
    if not heading:
        # Explicit empty-heading DTO; Markdown grammar need not emit empty nodes.
        n = next(n for n in doc.nodes if n.node_type.value == 'heading')
        old_key = n.identity.node_key
        new_key = make_node_key(n.identity.revision.source, n.parser_path, n.occurrence, '')
        payload = doc.model_dump(mode='json')
        for item in payload['nodes']:
            if item['identity']['node_key'] == old_key:
                item['text'] = ''
                for span in item['provenance']['spans']:
                    br = span['location'].get('byte_range')
                    if br:
                        br['end'] = br['start']
        doc = StructuralDocument.model_validate_json(json.dumps(payload).replace(old_key, new_key))
    if variant != 'typed_faq':
        # Control input DTO semantics, not parser/runtime behavior. These cases
        # isolate heading allocation even when the text resembles an FAQ/warning.
        doc = doc.model_copy(update={
            'nodes': tuple(n.model_copy(update={'semantic_role': SemanticRole.UNKNOWN}) for n in doc.nodes),
            'edges': tuple(e for e in doc.edges if e.relation != Relation.QA_PAIR)})
    nodes, edges = [], list(doc.edges)
    for n in doc.nodes:
        if n.node_type.value == 'paragraph':
            if variant == 'excluded' or (variant == 'barrier' and n.text == 'Navigation marker'):
                n = n.model_copy(update={'semantic_role': SemanticRole.NAVIGATION})
            if variant in ('quarantine', 'quality'):
                q = doc.revision.quality.model_dump()
                q.update(classification='blocked' if variant == 'quarantine' else 'mixed',
                         disposition='quarantine' if variant == 'quarantine' else 'accept', reason_codes=('fixture',))
                n = n.model_copy(update={'quality': SourceQuality.model_validate(q)})
            if variant == 'resource':
                edges.append(StructuralEdge(from_node=n.identity, to_node=n.identity, relation=Relation.DESCRIBES,
                    provenance=n.provenance, validation_state=ValidationState.VALIDATED))
        if variant in ('pdf', 'docx'):
            spans = tuple(s.model_copy(update={'location': SourceLocation(system=CoordinateSystem.PAGE_BBOX,
                page_bbox=PageBox(page=1, x0=0, y0=n.preorder, x1=100, y1=n.preorder+1,
                                 unit='points', origin='top_left'))}) for s in n.provenance.spans)
            n = n.model_copy(update={'provenance': n.provenance.model_copy(update={'spans': spans})})
        nodes.append(n)
    revision = doc.revision
    if variant in ('pdf', 'docx', 'txt'):
        revision = revision.model_copy(update={'source_format': 'text' if variant == 'txt' else variant,
                                               'fidelity': 'extracted_text' if variant == 'txt' else 'layout'})
    doc = StructuralDocument.model_validate_json(doc.model_copy(update={
        'nodes': tuple(nodes), 'edges': tuple(edges), 'revision': revision}).canonical_json())
    batch = serialize_structural_document(doc)
    if variant == 'partial':
        # Valid exact source DTO with a deliberately partial inherited heading.
        # Primary heading bytes remain complete in their independent source part.
        parts = []
        for c in batch.chunks:
            spans = []
            for s in c.mappings:
                if c.kind != 'heading' and s.usage == 'inherited' and s.mapping.role == 'heading':
                    m = s.mapping
                    half = m.node_slice.start + 1
                    m = m.model_copy(update={'node_slice': m.node_slice.model_copy(update={'end': half}),
                        'output_slice': m.output_slice.model_copy(update={'end': m.output_slice.start+1})})
                    s = s.model_copy(update={'mapping': m})
                spans.append(s)
            # Drop unmapped prefix remainder from TEXT too, leaving exact bytes.
            if c.kind != 'heading':
                raw = c.text.encode(); old = c.mappings[0].mapping
                if c.mappings[0].usage == 'inherited':
                    cut = old.output_slice.end - old.output_slice.start - 1
                    raw = raw[:old.output_slice.start+1] + raw[old.output_slice.end:]
                    spans = [s if i == 0 else s.model_copy(update={'mapping': s.mapping.model_copy(update={
                        'output_slice': s.mapping.output_slice.model_copy(update={
                            'start': s.mapping.output_slice.start-cut, 'end': s.mapping.output_slice.end-cut})})})
                        for i, s in enumerate(spans)]
                    c = c.model_copy(update={'text': raw.decode(), 'byte_count': len(raw),
                                             'token_count': count_tokens(raw.decode())})
            parts.append(c.model_copy(update={'mappings': tuple(spans)}))
        batch = batch.model_copy(update={'chunks': tuple(parts)}).verify()
    return batch


def base(spec):
    b = evidence(spec)
    r = v1.build_retrieval_entries(b, scope=v1.RetrievalEntryScope(revision=b.source_graph.revision.identity))
    if spec.get('variant') == 'lexical':
        entries = tuple(e for e in r.entries if e.kind == 'heading')
        entries = tuple(e.model_copy(update={'ordinal': i}) for i, e in enumerate(entries))
        entries = tuple(e.model_copy(update={'entry_key': v1._entry_key(e.model_dump(mode='json'))}) for e in entries)
        r = r.model_copy(update={'entries': entries, 'coverage': v1._coverage(r.evidence, r.atoms, entries),
            'batch_key': digest({'scope': r.scope.model_dump(), 'input': r.input_hash,
                                'recipe': r.recipe_hash, 'entries': [e.entry_key for e in entries]})}).verify(scope=r.scope)
    return r


def assert_reachability(result):
    """Independent exact-byte witness. Proves representation reachability,
    NOT semantic dense recall. Does not call the v2 decision helper.
    """
    index = result.make_index()
    parts = {c.chunk_key: c for c in result.evidence.chunks}
    atoms = {a.atom_key: a for a in result.atoms}
    lexical = {a.atom_key: a for a in result.coverage.atoms}
    nodes = {n.identity: n for n in result.evidence.source_graph.nodes}
    checked = 0
    for row in result.heading_allocations:
        atom = atoms[row.atom_key]
        assert atom.scope == row.scope == result.scope
        assert row.atom_key in lexical
        if row.disposition != 'CONTEXTUAL_ONLY':
            continue
        entry = index.entries[row.witness_entry]
        assert entry.scope == result.scope
        assert atom in index.atoms_for_entry(entry.entry_key, scope=result.scope)
        assert entry in index.entries_for_atom(atom.atom_key, scope=result.scope)
        assert not any(m.usage == 'body' and m.atom_key == atom.atom_key for e in result.entries for m in e.memberships)
        covered = defaultdict(set)
        for m in entry.mappings:
            if m.atom_key == atom.atom_key and m.origin_usage == 'inherited':
                a, b = m.node_slice, m.entry_slice
                assert nodes[m.node].text.encode()[a.start:a.end] == entry.text.encode()[b.start:b.end]
                covered[m.node].update(range(a.start, a.end))
        for key in atom.source_parts:
            for s in parts[key].mappings:
                if s.usage == 'primary':
                    m = s.mapping
                    assert set(range(m.node_slice.start, m.node_slice.end)).issubset(covered[m.node])
        checked += 1
    return checked
