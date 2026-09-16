"""Offline PDF/DOCX boundary. No Docling, ORM or application imports in this module.

The child process owns Docling and native resources, has a hard deadline and no
network/child-process permission. Model provisioning is a separate deliberate
operation; this adapter can only read the pinned local artifacts.
"""
from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

from services.structural_document import (
    CellAttributes, ListAttributes, NodeAttributes, NodeIdentity, NodeType, PageBox,
    Provenance, RevisionIdentity, SourceLocation, SourceQuality, SourceSpan,
    StructuralDocument, StructuralEdge, StructuralNode, StructureRevisionDescriptor,
    TableAttributes, make_node_key,
)
from services.structural_text_rules import link_attributes

POLICY = 'docling-structure-v1'
PINS = {'docling-slim': '2.127.0', 'docling-core': '2.96.1',
        'docling-parse': '7.20.0', 'docling-ibm-models': '4.0.2',
        'torch': '2.14.0', 'torchvision': '0.29.0', 'transformers': '5.17.0',
        'pypdfium2': '5.13.0', 'opencv-python-headless': '4.13.0.92',
        'pypdf': '6.16.2', 'python-docx': '1.2.0', 'Pillow': '12.3.0'}
# Reviewed immutable local model allowlist. Runtime never downloads these files.
MODEL_FILES = {
    'docling-project--docling-layout-heron/model.safetensors':
        '00333a43451945aaf89db8ca9c0a17e75d1537c17db60fdb91aa95f4c7929e0c',
    'docling-project--docling-layout-heron/config.json':
        'fdea30805ce2f5666b147fca941dcdd27ad468e27d6ed21902207d3da056a97d',
    'docling-project--docling-layout-heron/preprocessor_config.json':
        'cd38cd59999e7a95d68e487fbe5132df3d4e5c32a0836add57e6126ba0c4eaf1',
    'docling-project--docling-models/model_artifacts/tableformer/accurate/tableformer_accurate.safetensors':
        '2a7d6c924b3cd12fb99a09280ca9c33a89c5d60b93253617d2e088c1a40374d9',
    'docling-project--docling-models/model_artifacts/tableformer/accurate/tm_config.json':
        '984e122ceb8ccf84d84c9d2882f6f2302a44b4f1e577babd6289892c36f3cffd',
}


class DoclingAdapterError(ValueError):
    """Safe typed category: never contains source contents, local paths or secrets."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class DoclingLimits:
    source_bytes: int = 20 * 1024 * 1024
    pages: int = 50
    page_points: int = 1440
    nodes: int = 10000
    depth: int = 32
    edges: int = 20000
    table_rows: int = 200
    table_columns: int = 50
    table_cells: int = 5000
    pictures: int = 100
    zip_entries: int = 1000
    expanded_bytes: int = 80 * 1024 * 1024
    timeout_seconds: int = 120
    output_bytes: int = 32 * 1024 * 1024

    def __post_init__(self):
        caps = {'source_bytes': 20*1024*1024, 'pages': 50, 'page_points': 1440,
                'nodes': 10000, 'depth': 32, 'edges': 20000, 'table_rows': 200,
                'table_columns': 50, 'table_cells': 5000, 'pictures': 100,
                'zip_entries': 1000, 'expanded_bytes': 80*1024*1024,
                'timeout_seconds': 120, 'output_bytes': 32*1024*1024}
        if any(type(v) is not int or not 0 < v <= caps[k] for k, v in asdict(self).items()):
            raise DoclingAdapterError('INVALID_LIMIT')


def verify_artifacts(root: Path) -> None:
    try:
        root = root.resolve(strict=True)
    except OSError:
        raise DoclingAdapterError('MODEL_CACHE_INCOMPLETE') from None
    for directory in {Path(name).parts[0] for name in MODEL_FILES}:
        for path in (root / directory).rglob('*'):
            if path.is_symlink(): raise DoclingAdapterError('UNSAFE_MODEL_PATH')
            if path.is_file() and path.relative_to(root).as_posix() not in MODEL_FILES:
                raise DoclingAdapterError('UNREVIEWED_MODEL_ARTIFACT')
    for name, expected in MODEL_FILES.items():
        path = root / name
        try:
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root) or path.is_symlink() or not path.is_file():
                raise DoclingAdapterError('UNSAFE_MODEL_PATH')
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if digest != expected:
                raise DoclingAdapterError('MODEL_CHECKSUM')
        except OSError:
            raise DoclingAdapterError('MODEL_CACHE_INCOMPLETE') from None


def _owned_bytes(artifact: bytes, identity: RevisionIdentity, fmt: str, fidelity: str,
                 limits: DoclingLimits) -> RevisionIdentity:
    identity = RevisionIdentity.model_validate_json(identity.canonical_json())
    if fmt not in ('pdf', 'docx') or fidelity not in ('original', 'layout'):
        raise DoclingAdapterError('INVALID_FORMAT_FIDELITY')
    if type(artifact) is not bytes or not artifact or len(artifact) > limits.source_bytes:
        raise DoclingAdapterError('SOURCE_SIZE')
    if hashlib.sha256(artifact).hexdigest() != identity.source.source_sha256:
        raise DoclingAdapterError('SOURCE_HASH')
    return identity


def extract_artifact(artifact: bytes, *, identity: RevisionIdentity, source_format: str,
                     fidelity: str, model_cache: Path | None = None,
                     limits: DoclingLimits = DoclingLimits(), ocr: bool = False) -> dict:
    """Internal extraction record for differential tests; not an application DTO.

    Only bytes accepted, never URL/file-like strings. Caller reads its owned file.
    A fresh isolated process is intentional here, not a production throughput claim.
    """
    _owned_bytes(artifact, identity, source_format, fidelity, limits)
    if ocr is not False:
        raise DoclingAdapterError('OCR_NOT_PROVISIONED')
    if source_format == 'pdf' and model_cache is None:
        raise DoclingAdapterError('MODEL_CACHE_REQUIRED')
    request = {'artifact': base64.b64encode(artifact).decode('ascii'),
               'format': source_format, 'limits': asdict(limits),
               'model_cache': str(model_cache.resolve()) if model_cache else None}
    worker = Path(__file__).resolve().parents[1] / 'scripts/structural_docling_worker.py'
    # Do not propagate application/database/provider secrets into the parser process.
    env = {k: v for k, v in os.environ.items() if k.upper() in {
        'SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'COMSPEC', 'PATHEXT', 'USERPROFILE'}}
    env.update({'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
                'HF_HUB_DISABLE_TELEMETRY': '1', 'DO_NOT_TRACK': '1',
                'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUTF8': '1',
                'TOKENIZERS_PARALLELISM': 'false', 'OMP_NUM_THREADS': '2'})
    try:
        completed = subprocess.run([sys.executable, '-B', str(worker)],
                                   input=json.dumps(request).encode(), stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, env=env,
                                   timeout=limits.timeout_seconds, check=False,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired:
        raise DoclingAdapterError('CONVERSION_TIMEOUT') from None
    if len(completed.stdout) > limits.output_bytes:
        raise DoclingAdapterError('OUTPUT_SIZE')
    try:
        result = json.loads(completed.stdout)
    except (ValueError, UnicodeError):
        raise DoclingAdapterError('WORKER_FAILED') from None
    if completed.returncode or 'error' in result:
        code = result.get('error', 'WORKER_FAILED')
        raise DoclingAdapterError(code if re.fullmatch(r'[A-Z_]{1,64}', str(code)) else 'WORKER_FAILED')
    return result


def convert_artifact(artifact: bytes, *, identity: RevisionIdentity, source_format: str,
                     fidelity: str, model_cache: Path | None = None,
                     limits: DoclingLimits = DoclingLimits(), ocr: bool = False) -> StructuralDocument:
    result = extract_artifact(artifact, identity=identity, source_format=source_format,
                              fidelity=fidelity, model_cache=model_cache, limits=limits, ocr=ocr)
    return map_extraction(result, artifact=artifact, identity=identity,
                          source_format=source_format, fidelity=fidelity, limits=limits)


def page_box(prov: dict, pages: dict) -> PageBox:
    """Preserve Docling's actual origin and 72-point units, no Y-axis conversion.

    Our bbox uses numeric min/max; Docling uses top/bottom labels. For BOTTOMLEFT,
    b is the smaller Y. Sorting endpoints is representational, not normalization.
    """
    p = prov['page_no']
    if type(p) is not int or p < 1 or str(p) not in pages:
        raise DoclingAdapterError('INVALID_PAGE_PROVENANCE')
    bbox = prov['bbox']
    if bbox['coord_origin'] not in ('TOPLEFT', 'BOTTOMLEFT'):
        raise DoclingAdapterError('INVALID_COORDINATE_ORIGIN')
    l, t, r, b = (bbox[k] for k in ('l', 't', 'r', 'b'))
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in (l, t, r, b)):
        raise DoclingAdapterError('INVALID_BBOX')
    size = pages[str(p)]['size']
    if min(l, r, t, b) < 0 or l > r or r > size['width'] or max(t, b) > size['height']:
        raise DoclingAdapterError('INVALID_BBOX')
    if (bbox['coord_origin'] == 'TOPLEFT' and t > b) or (bbox['coord_origin'] == 'BOTTOMLEFT' and b > t):
        raise DoclingAdapterError('INVALID_BBOX')
    return PageBox(page=p, x0=l, x1=r, y0=min(t, b), y1=max(t, b), unit='points',
                   origin='top_left' if bbox['coord_origin'] == 'TOPLEFT' else 'bottom_left')


def map_extraction(record: dict, *, artifact: bytes, identity: RevisionIdentity,
                   source_format: str, fidelity: str,
                   limits: DoclingLimits = DoclingLimits()) -> StructuralDocument:
    """Map a trusted worker's extraction, never customer-supplied parser metadata.

    No DB writes/identity inference. Local refs are validated; orphan/cyclic text
    fails visibly. Parser-item locations are NOT claims of byte/page provenance.
    """
    identity = _owned_bytes(artifact, identity, source_format, fidelity, limits)
    if record.get('source_sha256') != identity.source.source_sha256 or record.get('ocr_used') is not False:
        raise DoclingAdapterError('EXTRACTION_IDENTITY')
    doc = record['document']
    pages = doc.get('pages', {})
    if len(pages) > limits.pages or len(doc.get('pictures', [])) > limits.pictures:
        raise DoclingAdapterError('EXTRACTION_LIMIT')
    index = {}
    for field in ('groups', 'texts', 'tables', 'pictures', 'key_value_items', 'form_items', 'field_regions', 'field_items'):
        for item in doc.get(field, []):
            ref = item['self_ref']
            if ref in index or not re.fullmatch(r'#/[a-z_]+/\d+', ref):
                raise DoclingAdapterError('INVALID_ITEM_REFERENCE')
            index[ref] = item
            if len(index) > limits.nodes:
                raise DoclingAdapterError('NODE_LIMIT')
    for field in ('body', 'furniture'):
        if doc.get(field): index[doc[field]['self_ref']] = doc[field]
    nodes, edges, visited, depths = [], [], set(), {}
    leaf = 0

    def provenance(path, item=None, cell_bbox=None):
        spans = [SourceSpan(source=identity.source,
                            location=SourceLocation(system='parser_item', parser_item=path))]
        # DOCX page positions are not available from this pinned backend.
        if source_format == 'pdf':
            locations = (item or {}).get('prov', [])
            if cell_bbox is not None:
                # A cell bbox without a unique table page is not a located PDF cell.
                locations = ([dict(locations[0], bbox=cell_bbox)] if len(locations) == 1 else [])
            for p in locations:
                spans.append(SourceSpan(source=identity.source,
                                        location=SourceLocation(system='page_bbox', page_bbox=page_box(p, pages))))
        return Provenance(method='parser', method_version=POLICY,
                          basis='Docling pinned extraction; original item reference; OCR disabled', spans=tuple(spans))

    def add(kind, path, parent, text='', attrs=None, item=None, role='unknown', cell_bbox=None):
        if len(nodes) >= limits.nodes: raise DoclingAdapterError('NODE_LIMIT')
        depth = depths[parent.node_key] + 1 if parent else 0
        if depth > limits.depth: raise DoclingAdapterError('DEPTH_LIMIT')
        key = make_node_key(identity.source, path, 0, text)
        ident = NodeIdentity(revision=identity, node_key=key)
        depths[key] = depth
        node = StructuralNode(identity=ident, parent=parent, parser_path=path, occurrence=0,
                              preorder=len(nodes), node_type=kind, text=text, semantic_role=role,
                              attributes=attrs or NodeAttributes(), provenance=provenance(path, item, cell_bbox))
        nodes.append(node)
        return ident

    root = add('document', '#', None)

    def children(item):
        refs = [r['$ref'] for r in item.get('children', [])]
        # Captions/footnotes may be referenced outside children. Preserve them once.
        for name in ('captions', 'footnotes'):
            for r in item.get(name, []):
                if r['$ref'] not in refs: refs.append(r['$ref'])
        return refs

    def table(item, parent):
        ref, data = item['self_ref'], item['data']
        rows, cols = data['num_rows'], data['num_cols']
        cells = data['table_cells']
        if not 0 <= rows <= limits.table_rows or not 0 <= cols <= limits.table_columns or len(cells) > limits.table_cells:
            raise DoclingAdapterError('TABLE_LIMIT')
        t = add('table', ref, parent, attrs=NodeAttributes(table=TableAttributes(row_count=rows, column_count=cols)), item=item)
        ordered = sorted(enumerate(cells), key=lambda x: (x[1]['start_row_offset_idx'], x[1]['start_col_offset_idx']))
        occupied, header_keys = set(), {}
        explicit = record.get('docx_header_rows', {}).get(ref, [])
        for i, c in ordered:
            r, col, rs, cs = c['start_row_offset_idx'], c['start_col_offset_idx'], c['row_span'], c['col_span']
            if rs < 1 or cs < 1 or r < 0 or col < 0 or r+rs > rows or col+cs > cols:
                raise DoclingAdapterError('INVALID_TABLE_CELL')
            if r+rs != c['end_row_offset_idx'] or col+cs != c['end_col_offset_idx']:
                raise DoclingAdapterError('INVALID_TABLE_CELL')
            slots = {(a, b) for a in range(r, r+rs) for b in range(col, col+cs)}
            if occupied & slots: raise DoclingAdapterError('OVERLAPPING_TABLE_CELLS')
            occupied |= slots
            header = (r in explicit) if source_format == 'docx' else bool(c.get('column_header') or c.get('row_header'))
            if header:
                header_keys[i] = make_node_key(identity.source, f'{ref}/data/table_cells/{i}', 0, c['text'])
        for r in range(rows):
            row = add('table_row', f'{ref}/rows/{r}', t)
            for i, c in ordered:
                if c['start_row_offset_idx'] != r: continue
                h = []
                for j, other in ordered:
                    if j == i or j not in header_keys: continue
                    col_overlap = max(c['start_col_offset_idx'], other['start_col_offset_idx']) < min(c['end_col_offset_idx'], other['end_col_offset_idx'])
                    if col_overlap and other['end_row_offset_idx'] <= r: h.append(header_keys[j])
                    if source_format == 'pdf' and other.get('row_header') and other['start_row_offset_idx'] <= r < other['end_row_offset_idx'] and other['end_col_offset_idx'] <= c['start_col_offset_idx']:
                        h.append(header_keys[j])
                attr = CellAttributes(row=r, column=c['start_col_offset_idx'], row_span=c['row_span'],
                                      column_span=c['col_span'], is_header=i in header_keys, header_keys=tuple(dict.fromkeys(h)))
                cell = add('table_cell', f'{ref}/data/table_cells/{i}', row, c['text'],
                           NodeAttributes(cell=attr), item=item if c.get('bbox') else None, cell_bbox=c.get('bbox'))
                if c.get('ref'): walk(c['ref']['$ref'], cell)
        for sub in children(item):
            if sub not in visited: walk(sub, t)
        return t

    def walk(ref, parent):
        if ref in visited or ref not in index: raise DoclingAdapterError('INVALID_ITEM_GRAPH')
        visited.add(ref)
        item = index[ref]
        label = item.get('label')
        text = item.get('orig', item.get('text', ''))
        if not isinstance(text, str): raise DoclingAdapterError('INVALID_ITEM_TEXT')
        subs = children(item)
        if label == 'table': return table(item, parent)
        if label in ('title', 'section_header'):
            container = add('section', ref+'/section', parent, item=item)
            heading = add('heading', ref, container, text, item=item, role='title' if label == 'title' else 'unknown')
            for sub in subs:
                target = walk(sub, container)
                if len(edges) >= limits.edges: raise DoclingAdapterError('EDGE_LIMIT')
                edges.append(StructuralEdge(from_node=heading, to_node=target, relation='HEADING_FOR',
                                             provenance=provenance(ref, item), validation_state='validated'))
            return container
        attrs = NodeAttributes()
        if label in ('list', 'ordered_list'):
            items = [index.get(x, {}) for x in subs if index.get(x, {}).get('label') == 'list_item']
            modes = {i.get('enumerated', False) for i in items}
            if len(modes) > 1:
                # Docling can group adjacent numbered and bulleted runs together.
                # Keep the original group/ref and every item, but do not invent a
                # single ordered flag for incompatible runs.
                current = add('group', ref, parent, item=item)
                at, run = 0, 0
                while at < len(subs):
                    first = index.get(subs[at], {})
                    if first.get('label') != 'list_item':
                        walk(subs[at], current); at += 1; continue
                    ordered = first.get('enumerated', False)
                    end = at + 1
                    while end < len(subs) and index.get(subs[end], {}).get('label') == 'list_item' and index[subs[end]].get('enumerated', False) == ordered:
                        end += 1
                    attrs = NodeAttributes(list=ListAttributes(ordered=ordered, item_count=end-at, source_block_complete=True))
                    group = add('list', ref+f'/runs/{run}', current, attrs=attrs, item=item)
                    for sub in subs[at:end]: walk(sub, group)
                    at, run = end, run + 1
                return current
            attrs = NodeAttributes(list=ListAttributes(ordered=modes == {True}, item_count=len(items), source_block_complete=True))
            kind = 'list'
        elif label == 'list_item': kind = 'list_item'
        elif label in ('picture', 'chart'): kind = 'media'
        elif 'text' in item: kind = 'paragraph'
        else: kind = 'group'
        role = 'furniture' if item.get('content_layer') == 'furniture' else 'unknown'
        current = add(kind, ref, parent, text, attrs, item=item, role=role)
        if item.get('hyperlink'):
            add('link', ref+'/hyperlink', current, text,
                NodeAttributes(link=link_attributes(str(item['hyperlink']), text)), item=item)
        for sub in subs: walk(sub, current)
        return current

    for field in ('body', 'furniture'):
        if doc.get(field): walk(doc[field]['self_ref'], root)
    # This also catches source-backed items silently omitted by an upstream tree.
    if set(index) != visited: raise DoclingAdapterError('ORPHAN_EXTRACTION_ITEMS')
    parents = {n.parent.node_key for n in nodes if n.parent}
    for i, n in enumerate(nodes):
        if n.identity.node_key not in parents:
            nodes[i] = n.model_copy(update={'leaf_order': leaf}); leaf += 1
    quality = SourceQuality(classification='unknown', disposition='manual_review',
                            detector_version=POLICY, reason_codes=('quality_not_evaluated',),
                            evidence=nodes[0].provenance.spans)
    recipe = {'policy': POLICY, 'pins': PINS, 'limits': asdict(limits),
              'ocr': False, 'model_checksums': MODEL_FILES if source_format == 'pdf' else {},
              'cpu_threads': 2, 'table_mode': 'accurate', 'heading_hierarchy': True}
    revision = StructureRevisionDescriptor(identity=identity, parser_version=POLICY,
        normalizer_version='docling-provenance-v1', source_format=source_format, fidelity=fidelity,
        state='staging', quality=quality,
        configuration_sha256=hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest())
    return StructuralDocument(revision=revision, nodes=tuple(nodes), edges=tuple(edges))
