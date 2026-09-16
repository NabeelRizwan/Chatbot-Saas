"""Offline, read-only sources; optional JSON output goes to an explicit path.

No DB/provider application imports. This does not create or update GOLD.
"""
from collections import Counter
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.structural_chunking import count_tokens, serialize_structural_document
from scripts.evaluate_structural_text_adapter import parse_source


def union_length(intervals):
    end, total = 0, 0
    for lo, hi in sorted(intervals):
        total += max(0, hi-max(lo, end))
        end = max(end, hi)
    return total


def distribution(values):
    values = sorted(values)
    if not values:
        return dict(min=0, p50=0, p95=0, max=0)
    return dict(min=values[0], p50=values[(len(values)-1)//2],
                p95=values[min(len(values)-1, int(len(values)*.95))], max=values[-1])


def metrics(batch):
    doc, chunks = batch.source_graph, batch.chunks
    maps, exclusions = {}, {}
    raw_ranges = []
    by_key = {n.identity.node_key: n for n in doc.nodes}
    for c in chunks:
        for s in c.mappings:
            m = s.mapping
            maps.setdefault(m.node.node_key, []).append((m.node_slice.start, m.node_slice.end))
            n = by_key[m.node.node_key]
            for span in n.provenance.spans:
                if span.location.system.value == 'utf8_bytes':
                    loc = span.location.byte_range
                    if loc.end-loc.start == len(n.text.encode()):
                        raw_ranges.append((loc.start+m.node_slice.start, loc.start+m.node_slice.end))
                    break
    for x in batch.excluded:
        exclusions.setdefault(x.node.node_key, []).append((x.node_slice.start, x.node_slice.end))
    # Metadata-only parent spans also account for their inline annotation nodes.
    for n in doc.nodes:
        if n.identity.node_key in maps or not n.attributes.link:
            continue
        if any(x.reason == 'link_metadata_only' and x.node == n.identity for x in batch.excluded):
            continue
        ns = next((s.location.byte_range for s in n.provenance.spans if s.location.system.value == 'utf8_bytes'), None)
        if ns:
            for x in batch.excluded:
                p = by_key[x.node.node_key]
                ps = next((s.location.byte_range for s in p.provenance.spans if s.location.system.value == 'utf8_bytes'), None)
                if ps and ps.start+x.node_slice.start <= ns.start and ps.start+x.node_slice.end >= ns.end:
                    exclusions[n.identity.node_key] = [(0, len(n.text.encode()))]
    represented = sum(union_length(v) for v in maps.values())
    accounted = sum(union_length(maps.get(k, []) + exclusions.get(k, [])) for k in by_key)
    total = sum(len(n.text.encode()) for n in doc.nodes)
    memberships = {i.node_key for c in chunks for i in c.members}
    metadata_only = {i.node_key for i in batch.metadata_only_nodes}
    excluded_nodes = {k for k, v in exclusions.items() if union_length(v) == len(by_key[k].text.encode())}
    def retention(predicate):
        expected = [n for n in doc.nodes if predicate(n) and n.identity.node_key not in excluded_nodes]
        return {'expected': len(expected), 'retained': sum(n.identity.node_key in memberships or n.identity.node_key in maps or n.identity.node_key in metadata_only for n in expected)}
    timeline_bundles = {}
    for c in chunks:
        if c.kind == 'timeline_stage':
            stages = [i.node_key for i in c.members if by_key[i.node_key].attributes.timeline]
            timeline_bundles[c.bundle_key] = stages
    links = [n for n in doc.nodes if n.attributes.link]
    raw_root = next((s.location.byte_range for s in doc.nodes[0].provenance.spans
                     if s.location.system.value == 'utf8_bytes'), None)
    return {
        'nodes': len(doc.nodes), 'chunks': len(chunks),
        'tokens': sum(c.token_count for c in chunks),
        'token_distribution': distribution([c.token_count for c in chunks]),
        'source_structural_tokens': sum(count_tokens(n.text) for n in doc.nodes),
        'source_text_bytes': total, 'represented_node_bytes': represented,
        'excluded_bytes': accounted-represented, 'unaccounted_bytes': total-accounted,
        'raw_source_evidence_bytes': union_length(raw_ranges),
        'raw_source_bytes': raw_root.end-raw_root.start if raw_root else None,
        'chunk_kinds': dict(Counter(c.kind for c in chunks)),
        'token_counts': [c.token_count for c in chunks],
        'excluded_roles': dict(Counter(by_key[x.node.node_key].semantic_role.value for x in batch.excluded)),
        'excluded_reasons': dict(Counter(x.reason for x in batch.excluded)),
        'unknown_nodes': sum(n.semantic_role.value == 'unknown' and bool(n.text) for n in doc.nodes),
        'headings': retention(lambda n: n.node_type.value == 'heading'),
        'lists': retention(lambda n: n.attributes.list is not None),
        'list_items': retention(lambda n: n.node_type.value == 'list_item'),
        'cells': retention(lambda n: n.attributes.cell is not None),
        'headers': retention(lambda n: n.attributes.cell is not None and n.attributes.cell.is_header),
        'reviews': retention(lambda n: n.semantic_role.value == 'review'),
        'faq_questions': retention(lambda n: n.semantic_role.value == 'faq_question'),
        'timeline_stages': retention(lambda n: n.attributes.timeline is not None),
        'commercial': retention(lambda n: n.attributes.commercial is not None),
        'quantities': retention(lambda n: bool(n.attributes.quantities)),
        'warnings': retention(lambda n: n.semantic_role.value == 'warning'),
        'links': {'expected': len(links), 'text_retained': sum(n.identity.node_key in maps for n in links),
                  'metadata_retained': len(links)},
        'review_reference_edges': sum(e.relation.value == 'REFERS_TO' and
                                      by_key[e.from_node.node_key].semantic_role.value == 'review' for e in doc.edges),
        'timeline_stage_separation': all(len(stages) <= 1 for stages in timeline_bundles.values()),
        'max_parts': max((c.part_count for c in chunks), default=0),
        'max_mappings': max((len(c.mappings) for c in chunks), default=0),
        'metadata_only_empty_lists': sum(k in metadata_only and n.attributes.list is not None for k,n in by_key.items()),
        'max_prefix_tokens': max((c.prefix_tokens for c in chunks), default=0),
        'mapping_exact': bool(batch.verify()),
        'hard_cap': all(c.token_count <= 800 for c in chunks),
        'chunk_expansion_per_node': len(chunks)/len(doc.nodes),
        'byte_expansion': sum(c.byte_count for c in chunks)/max(1,total),
        'canonical_hash': batch.canonical_hash(),
    }


def shadow(path):
    payload = json.loads(path.read_text(encoding='utf-8'))
    results = []
    start = time.perf_counter()
    for record in payload['documents']:
        text = record.get('raw_text') or ''
        doc = parse_source(text, document_id=record['id'])
        batch = serialize_structural_document(doc)
        m = metrics(batch)
        m['document_id'] = record['id']
        m['repeat_identical'] = batch.canonical_hash() == serialize_structural_document(doc).canonical_hash()
        results.append(m)
        print(json.dumps(m), flush=True)
    return {'documents': results, 'elapsed_seconds': time.perf_counter()-start,
            'total_chunks': sum(x['chunks'] for x in results),
            'total_tokens': sum(x['tokens'] for x in results),
            'total_nodes': sum(x['nodes'] for x in results),
            'chunks_per_document': distribution([x['chunks'] for x in results]),
            'error_count': 0}


def gold():
    from scripts.structural_chunk_gold_v1 import specs, build
    from scripts.structural_gold_v1 import load_gold
    fixtures = {s['name']:build(s) for s in specs()}
    fixtures.update({'witness_'+name:doc for name,doc in load_gold().items()})
    result = {}
    for name, doc in fixtures.items():
        batch = serialize_structural_document(doc)
        result[name] = metrics(batch)
        result[name]['repeat_identical'] = batch.canonical_hash() == serialize_structural_document(doc).canonical_hash()
    return result


def docling(models):
    from scripts.evaluate_structural_docling_adapter import FIXTURES, identity
    from services.structural_docling_adapter import extract_artifact, map_extraction
    result = {}
    for name in ('workshop.pdf','merged.pdf','workshop.docx'):
        data = (FIXTURES/name).read_bytes()
        config = dict(identity=identity(data),source_format=name.rsplit('.',1)[1],fidelity='original')
        record = extract_artifact(data,model_cache=models,**config)
        doc = map_extraction(record,artifact=data,**config)
        batch = serialize_structural_document(doc)
        result[name] = metrics(batch)
        result[name]['repeat_identical'] = batch.canonical_hash() == serialize_structural_document(doc).canonical_hash()
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--snapshot', type=Path)
    mode.add_argument('--gold', action='store_true')
    mode.add_argument('--docling-models', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = shadow(args.snapshot) if args.snapshot else (gold() if args.gold else docling(args.docling_models))
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k != 'documents'}) if args.snapshot else 'Offline fixture metrics complete')
