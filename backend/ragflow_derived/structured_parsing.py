"""Bounded byte-only adapter for the real pinned CPU document parsers.

No remote image fetching, OCR substitution or filesystem filename reads. Parser
representations are identified as such, not original binary document text.
"""
from io import BytesIO
import zipfile
from .contracts import EngineError


CPU_FORMATS = frozenset({"docx", "xlsx", "csv", "json", "jsonl", "epub", "pptx", "pdf"})


def _package_bounds(raw, max_bytes):
    if not zipfile.is_zipfile(BytesIO(raw)):
        return
    with zipfile.ZipFile(BytesIO(raw)) as package:
        entries = package.infolist()
        if len(entries) > 10000 or sum(e.file_size for e in entries) > max_bytes * 20:
            raise EngineError("PARSER_FAILED", "expanded bounds")
        # No ZIP extraction occurs; these bounds also cover embedded media.
        if any(e.flag_bits & 1 for e in entries):
            raise EngineError("PARSER_FAILED", "encrypted package")


def parse_cpu(raw, kind, *, filename, chunk_tokens, max_bytes):
    _package_bounds(raw, max_bytes)
    pieces = []

    def add(text, representation, **metadata):
        if text and text.strip():
            pieces.append({"text": text, "order": len(pieces), "headings": [],
                           "kind": representation, "parser_metadata": metadata})

    if kind == "docx":
        from .upstream.naive_docx import Docx
        from .upstream.merge import naive_merge_docx
        rows = Docx()(filename=filename, binary=raw, from_page=0, to_page=1000)
        try:
            merged, _ = naive_merge_docx(rows, chunk_tokens)
            for row in merged:
                add(row["text"], row["ck_type"], parser="ragflow.naive.Docx/naive_merge_docx")
        finally:
            for _, image, _ in rows:
                if image is not None:
                    image.close()
        # Embedded image bytes are recognized by upstream, but no description
        # is fabricated when no authorized vision provider is configured.
    elif kind in {"xlsx", "csv"}:
        from .upstream.excel_parser import RAGFlowExcelParser
        for text, position in RAGFlowExcelParser().html(raw):
            add(text, "table", parser="ragflow.ExcelParser.html", sheet_position=list(position))
    elif kind in {"json", "jsonl"}:
        from .upstream.json_parser import RAGFlowJsonParser
        for text in RAGFlowJsonParser(chunk_tokens)(raw):
            add(text, "structured", parser="ragflow.JsonParser")
    elif kind == "pptx":
        from .upstream.ppt_parser import RAGFlowPptParser
        for page, text in enumerate(RAGFlowPptParser()(raw, 0, 1000), 1):
            add(text, "text", parser="ragflow.PptParser", page=page)
    elif kind == "epub":
        from .upstream.epub_parser import RAGFlowEpubParser
        for text in RAGFlowEpubParser()(filename, raw, chunk_tokens):
            add(text, "text", parser="ragflow.EpubParser", reading_order=len(pieces))
    elif kind == "pdf":
        from pypdf import PdfReader
        from .upstream.plain_pdf_parser import PlainParser
        if len(PdfReader(BytesIO(raw)).pages) > 1000:
            raise EngineError("PARSER_FAILED", "page bounds")
        parser = PlainParser()
        sections, _ = parser(raw, from_page=0, to_page=1000)
        for text, _ in sections:
            add(text, "text", parser="ragflow.PlainParser", outline=parser.outlines)
        # PlainParser does not expose per-line bboxes/pages. Do not invent them.
    else:
        raise EngineError("PARSER_FAILED", "unsupported CPU format")
    if not pieces:
        raise EngineError("PARSER_FAILED", "empty/no extractable text")
    if sum(len(p["text"].encode()) for p in pieces) > max_bytes * 20:
        raise EngineError("PARSER_FAILED", "parsed output bounds")
    return pieces
