"""Private offline child entrypoint. Never import from the web/ingestion runtime."""
from __future__ import annotations

import base64
from contextlib import redirect_stdout
import hashlib
import importlib.metadata
from io import BytesIO
import json
import logging
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.structural_docling_adapter import DoclingAdapterError, DoclingLimits, PINS, verify_artifacts


def deny_io(*args, **kwargs):
    raise DoclingAdapterError('NETWORK_OR_EXECUTION_DENIED')


def isolate():
    # Process-local only: never monkeypatch network functions in an application worker.
    socket.socket.connect = deny_io
    socket.socket.connect_ex = deny_io
    socket.create_connection = deny_io
    socket.getaddrinfo = deny_io
    socket.gethostbyname = deny_io
    socket.socket.sendto = deny_io
    # Keep Popen's class identity intact (asyncio subclasses it on Windows).
    def audit(event, args):
        if event in ('subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn',
                     'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.sendto'):
            deny_io()
    sys.addaudithook(audit)
    os.system = deny_io
    os.environ.update({'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
                       'HF_HUB_DISABLE_TELEMETRY': '1', 'DO_NOT_TRACK': '1'})


def preflight(artifact, fmt, limits):
    if len(artifact) > limits.source_bytes: raise DoclingAdapterError('SOURCE_SIZE')
    if fmt == 'pdf':
        from pypdf import PdfReader
        import pypdf.filters
        old_cap = pypdf.filters.ZLIB_MAX_OUTPUT_LENGTH
        pypdf.filters.ZLIB_MAX_OUTPUT_LENGTH = min(old_cap, limits.expanded_bytes)
        try:
            reader = PdfReader(BytesIO(artifact), strict=True)
            if reader.is_encrypted: raise DoclingAdapterError('ENCRYPTED_PDF')
            if not reader.pages: raise DoclingAdapterError('EMPTY_PDF')
            if len(reader.pages) > limits.pages: raise DoclingAdapterError('PAGE_LIMIT')
            text_pages = []
            for page in reader.pages:
                # The pinned text-layer pipeline reverses reading order on the
                # frozen 90-degree fixture. Do not silently accept that layout.
                if page.rotation % 360:
                    raise DoclingAdapterError('ROTATED_PDF_UNSUPPORTED')
                scale = float(page.get('/UserUnit', 1))
                dimensions = (float(page.mediabox.width), float(page.mediabox.height))
                if not 0 < scale <= 1 or any(not math.isfinite(v) or not 0 < v <= limits.page_points for v in dimensions):
                    raise DoclingAdapterError('PAGE_SIZE_LIMIT')
                text_pages.append(bool(page.extract_text().strip()))
            if not any(text_pages): raise DoclingAdapterError('OCR_REQUIRED_OR_EMPTY_PDF')
            # No OCR is provisioned. A mixed scanned/text PDF must not be reported
            # complete after silently ignoring a textless page (even a blank one).
            if not all(text_pages): raise DoclingAdapterError('TEXTLESS_PAGE_UNSUPPORTED')
            return {}
        except DoclingAdapterError:
            raise
        except Exception:
            raise DoclingAdapterError('MALFORMED_PDF') from None
        finally:
            pypdf.filters.ZLIB_MAX_OUTPUT_LENGTH = old_cap
    if fmt != 'docx': raise DoclingAdapterError('UNSUPPORTED_FORMAT')
    from defusedxml import ElementTree as ET
    try:
        with zipfile.ZipFile(BytesIO(artifact)) as archive:
            entries = archive.infolist()
            if len(entries) > limits.zip_entries or sum(e.file_size for e in entries) > limits.expanded_bytes:
                raise DoclingAdapterError('ZIP_LIMIT')
            if len(set(e.filename for e in entries)) != len(entries): raise DoclingAdapterError('DUPLICATE_ZIP_MEMBER')
            media_count, pixels = 0, 0
            for entry in entries:
                name = entry.filename
                if '\\' in name or name.startswith('/') or '..' in Path(name).parts or entry.flag_bits & 1:
                    raise DoclingAdapterError('UNSAFE_DOCX')
                if '/embeddings/' in name or name.lower().endswith(('.emf', '.wmf', '.svg', '.bin')):
                    raise DoclingAdapterError('UNSUPPORTED_EMBEDDED_MEDIA')
                if name.startswith('word/charts/'):
                    raise DoclingAdapterError('DOCX_CHART_UNSUPPORTED')
                if name.endswith(('.xml', '.rels')):
                    tree = ET.fromstring(archive.read(entry))
                    stack = [(tree, 0)]
                    count = 0
                    while stack:
                        el, depth = stack.pop(); count += 1
                        if depth > 80 or count > 100000: raise DoclingAdapterError('XML_LIMIT')
                        stack.extend((child, depth+1) for child in el)
                        if el.tag.endswith('}Relationship') and el.get('TargetMode') == 'External' and not el.get('Type', '').endswith('/hyperlink'):
                            raise DoclingAdapterError('EXTERNAL_RESOURCE')
                        if el.tag.endswith('}ilvl') and int(el.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '0')) >= limits.depth:
                            raise DoclingAdapterError('DEPTH_LIMIT')
                if name.startswith('word/media/'):
                    from PIL import Image
                    media_count += 1
                    if media_count > limits.pictures: raise DoclingAdapterError('PICTURE_LIMIT')
                    with Image.open(BytesIO(archive.read(entry))) as picture:
                        pixels += picture.width * picture.height
                        if picture.width * picture.height > 20_000_000 or pixels > 40_000_000:
                            raise DoclingAdapterError('IMAGE_SIZE_LIMIT')
            return docx_table_headers(archive.read('word/document.xml'))
    except DoclingAdapterError:
        raise
    except Exception:
        raise DoclingAdapterError('MALFORMED_DOCX') from None


def docx_table_headers(xml, exported=None):
    """Accept explicit header rows only with a verified source-table association.

    The pinned backend flattens 1x1 layout tables. Do not let those tables shift
    another table's header flags; reject any remaining shape/content mismatch.
    This is validation of source labels, not a second table extraction engine.
    """
    from defusedxml import ElementTree as ET
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    descriptors = []
    for table in ET.fromstring(xml).findall('.//w:tbl', ns):
        rows = table.findall('w:tr', ns)
        cols = len(table.findall('w:tblGrid/w:gridCol', ns))
        if len(rows) == cols == 1:
            continue
        header_rows = [r for r, row in enumerate(rows)
                       if row.find('w:trPr/w:tblHeader', ns) is not None and
                       row.find('w:trPr/w:tblHeader', ns).get('{'+ns['w']+'}val', '1') not in ('0', 'false', 'off')]
        first = []
        if rows:
            first = [' '.join('\n'.join(''.join(t.text or '' for t in p.findall('.//w:t', ns))
                                      for p in c.findall('w:p', ns)).split())
                     for c in rows[0].findall('w:tc', ns)]
        descriptors.append((len(rows), cols, first, header_rows))
    if exported is not None:
        tables = exported.get('tables', [])
        if len(tables) != len(descriptors): raise DoclingAdapterError('DOCX_TABLE_ASSOCIATION')
        for table, (rows, cols, first, _) in zip(tables, descriptors):
            data = table['data']
            actual = [' '.join(c['text'].split()) for c in data['table_cells'] if c['start_row_offset_idx'] == 0]
            if (data['num_rows'], data['num_cols'], actual) != (rows, cols, first):
                raise DoclingAdapterError('DOCX_TABLE_ASSOCIATION')
    return {f'#/tables/{i}': d[3] for i, d in enumerate(descriptors)}


def run(request):
    start = time.perf_counter()
    limits = DoclingLimits(**request['limits'])
    artifact = base64.b64decode(request['artifact'], validate=True)
    fmt = request['format']
    headers = preflight(artifact, fmt, limits)
    for package, version in PINS.items():
        if importlib.metadata.version(package) != version:
            raise DoclingAdapterError('DEPENDENCY_VERSION')
    model_path = Path(request['model_cache']) if request.get('model_cache') else None
    if fmt == 'pdf':
        if model_path is None: raise DoclingAdapterError('MODEL_CACHE_REQUIRED')
        verify_artifacts(model_path)
    # Imports intentionally occur after isolation and admission. No ML application calls.
    from docling.document_converter import DocumentConverter, PdfFormatOption, WordFormatOption
    from docling.datamodel.base_models import InputFormat, DocumentStream, ConversionStatus
    from docling.datamodel.pipeline_options import PdfPipelineOptions, ConvertPipelineOptions
    from docling.datamodel.backend_options import MsWordBackendOptions
    from docling.datamodel.accelerator_options import AcceleratorOptions, AcceleratorDevice
    import torch
    torch.set_num_threads(2)
    torch.manual_seed(0)
    torch.use_deterministic_algorithms(True)
    if fmt == 'pdf':
        options = PdfPipelineOptions(artifacts_path=model_path, do_ocr=False,
            enable_remote_services=False, allow_external_plugins=False,
            do_picture_description=False, do_picture_classification=False,
            do_chart_extraction=False, do_code_enrichment=False, do_formula_enrichment=False,
            generate_page_images=False, generate_picture_images=False,
            document_timeout=float(limits.timeout_seconds - 1),
            accelerator_options=AcceleratorOptions(device=AcceleratorDevice.CPU, num_threads=2))
        options.heading_hierarchy_options.enabled = True
        option = PdfFormatOption(pipeline_options=options)
        kind = InputFormat.PDF
    else:
        option = WordFormatOption(pipeline_options=ConvertPipelineOptions(
            enable_remote_services=False, allow_external_plugins=False,
            do_picture_description=False, do_picture_classification=False),
            backend_options=MsWordBackendOptions(enable_remote_fetch=False,
                enable_local_fetch=False, render_chart_images=False))
        kind = InputFormat.DOCX
    converter = DocumentConverter(allowed_formats=[kind], format_options={kind: option})
    converter.initialize_pipeline(kind)
    initialized = time.perf_counter()
    result = converter.convert(DocumentStream(name='owned-artifact.'+fmt, stream=BytesIO(artifact)),
                               max_num_pages=limits.pages, max_file_size=limits.source_bytes,
                               raises_on_error=True)
    if result.status != ConversionStatus.SUCCESS or result.errors:
        raise DoclingAdapterError('INCOMPLETE_CONVERSION')
    doc = result.document
    if len(doc.pictures) > limits.pictures: raise DoclingAdapterError('PICTURE_LIMIT')
    if sum(len(getattr(doc, x, [])) for x in ('texts','groups','pictures','tables')) > limits.nodes:
        raise DoclingAdapterError('NODE_LIMIT')
    # No image payloads/paths emitted. Media refs/captions/provenance remain.
    exported = doc.model_dump(mode='json', by_alias=True, exclude_computed_fields=True)
    if fmt == 'docx':
        with zipfile.ZipFile(BytesIO(artifact)) as archive:
            headers = docx_table_headers(archive.read('word/document.xml'), exported)
    for p in exported.get('pictures', []): p['image'] = None
    for p in exported.get('pages', {}).values(): p['image'] = None
    elapsed = time.perf_counter() - start
    import psutil
    memory = psutil.Process().memory_info()
    return {'document': exported, 'source_sha256': hashlib.sha256(artifact).hexdigest(),
            'ocr_used': False, 'ocr_engine': None, 'ocr_pages': [], 'ocr_confidence': None,
            'docx_header_rows': headers, 'elapsed_seconds': elapsed,
            'import_setup_seconds': initialized-start, 'conversion_seconds': time.perf_counter()-initialized,
            'process_peak_rss_bytes': getattr(memory, 'peak_wset', None),
            'process_rss_bytes': memory.rss,
            'versions': PINS}


def main():
    isolate()
    logging.disable(logging.CRITICAL)
    try:
        raw = sys.stdin.buffer.read(29*1024*1024)
        if len(raw) >= 29*1024*1024: raise DoclingAdapterError('SOURCE_SIZE')
        request = json.loads(raw)
        with redirect_stdout(sys.stderr): result = run(request)
        output = json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(output) > request['limits']['output_bytes']: raise DoclingAdapterError('OUTPUT_SIZE')
        sys.stdout.buffer.write(output)
    except DoclingAdapterError as exc:
        sys.stdout.write(json.dumps({'error': exc.code})); return 1
    except Exception:
        # Never leak input contents, local paths, environment or upstream tracebacks.
        sys.stdout.write(json.dumps({'error': 'CONVERSION_FAILED'})); return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
