"""Offline synthetic fixtures only; never regenerates GOLD or calls a provider."""
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.structural_document import SourceIdentity, RevisionIdentity
from services.structural_docling_adapter import extract_artifact, map_extraction
from hashlib import sha256

FIXTURES = Path(__file__).resolve().parents[1] / 'tests/fixtures/structural_gold_docling_v1'


def identity(data):
    return RevisionIdentity(source=SourceIdentity(organization_id=81001, bot_id=81002,
        document_id=81003, document_version_id='owned-fixture-v1', source_version=1,
        source_sha256=sha256(data).hexdigest()), structure_revision_id='fixture-structure-v1')


def matched(expected, actual):
    a, b = Counter(expected), Counter(actual)
    hit = sum((a & b).values())
    return {'matched': hit, 'expected': sum(a.values()), 'emitted': sum(b.values()),
            'recall': hit/sum(a.values()) if a else None,
            'precision': hit/sum(b.values()) if b else None}


def metrics(dto, record, gold):
    nodes = list(dto.nodes)
    doc = record['document']
    items = {x['self_ref']: x for x in doc.get('texts', [])}
    def payload(node):
        # GOLD labels omit markers. Remove only the exact marker declared by
        # Docling, never arbitrary leading digits/punctuation from source text.
        marker = items.get(node.parser_path, {}).get('marker', '')
        if node.node_type.value == 'list_item' and marker and node.text.startswith(marker):
            return node.text[len(marker):].lstrip()
        return node.text
    lists = []
    for n in nodes:
        if n.attributes.list:
            lists.append([payload(x) for x in nodes
                          if x.parent == n.identity and x.node_type.value == 'list_item'])
    body_text = [payload(n) for n in nodes if n.text and n.node_type.value != 'link']
    raw_texts = [x.get('orig', x.get('text', '')) for x in doc.get('texts', [])]
    raw_cells = [c['text'] for t in doc.get('tables', []) for c in t['data']['table_cells']]
    refs = {n.parser_path for n in nodes}
    return {
        'heading': matched(gold['headings'], [n.text for n in nodes if n.node_type.value == 'heading']),
        'list_membership_order': matched([tuple(x) for x in gold['lists']], [tuple(x) for x in lists]),
        'table_cells': matched(gold['table_cells'], [n.text for n in nodes if n.attributes.cell]),
        'headers': matched(gold['headers'], [n.text for n in nodes if n.attributes.cell and n.attributes.cell.is_header]),
        'text': matched(gold['text'], body_text),
        'ordered_text_payload_equal': ' '.join(gold['text']) == ' '.join(body_text),
        'links': matched(gold['links'], [n.attributes.link.original_href for n in nodes if n.attributes.link]),
        'media': {'expected':gold['pictures'], 'actual':sum(n.node_type.value == 'media' for n in nodes)},
        'parser_item_provenance': sum(any(s.location.system.value == 'parser_item' for s in n.provenance.spans) for n in nodes),
        'page_bbox_nodes': sum(any(s.location.system.value == 'page_bbox' for s in n.provenance.spans) for n in nodes),
        'node_count': len(nodes),
        'docling_to_dto_text': matched(raw_texts, [n.text for n in nodes if n.parser_path in {x['self_ref'] for x in doc.get('texts', [])}]),
        'docling_to_dto_cells': matched(raw_cells, [n.text for n in nodes if n.attributes.cell]),
        'docling_missing_item_refs': sorted(x['self_ref'] for field in ('texts','groups','pictures','tables') for x in doc.get(field, []) if x['self_ref'] not in refs),
        'ocr_used': record['ocr_used'], 'ocr_engine': record['ocr_engine'],
        'worker_elapsed_seconds': record['elapsed_seconds'],
        'import_setup_seconds': record['import_setup_seconds'], 'conversion_seconds': record['conversion_seconds'],
        'process_peak_rss_bytes': record.get('process_peak_rss_bytes'),
        'canonical_hash': dto.canonical_hash(),
    }


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--models', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    expected = json.loads((FIXTURES/'expected.json').read_text(encoding='utf-8'))
    results = {}
    for name in ('workshop.pdf', 'workshop.docx', 'merged.pdf'):
        data = (FIXTURES/name).read_bytes()
        fmt = name.rsplit('.',1)[1]
        config = dict(identity=identity(data), source_format=fmt, fidelity='original')
        record = extract_artifact(data, model_cache=args.models, **config)
        dto = map_extraction(record, artifact=data, **config)
        result = metrics(dto, record, expected[name])
        again = extract_artifact(data, model_cache=args.models, **config)
        result['repeated_extraction_identical'] = dto.canonical_json() == map_extraction(again, artifact=data, **config).canonical_json()
        results[name] = result
        print(name, json.dumps(result), flush=True)
    args.output.parent.mkdir(exist_ok=True, parents=True)
    args.output.write_text(json.dumps(results, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
