"""Ingestion adapter: platform supplies bytes; never fetches URLs or external images."""
from io import BytesIO
import re
from .contracts import EngineError
from .upstream.markdown_parser import MarkdownElementExtractor
from .upstream.html_parser import RAGFlowHtmlParser
from .upstream.chunking import merge_paragraphs
from .upstream.runtime import decode_text, num_tokens_from_string


def parse(content, kind, *, tokenizer, chunk_tokens=512, max_bytes=8_388_608, count_tokens=num_tokens_from_string):
    raw = content.encode() if isinstance(content, str) else content
    if not isinstance(raw, bytes) or len(raw) > max_bytes:
        raise EngineError("PARSER_FAILED", "input bounds")
    try:
        if kind in ("txt", "md", "markdown", "crawl", "html"):
            text = decode_text(raw)[0]
        elif kind == "pdf":
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(raw))
            if len(reader.pages) > 1000:
                raise EngineError("PARSER_FAILED", "page bounds")
            text = "\n\n".join(p.extract_text() or "" for p in reader.pages)
        elif kind == "docx":
            from docx import Document
            from docx.text.paragraph import Paragraph
            from docx.table import Table
            import zipfile
            with zipfile.ZipFile(BytesIO(raw)) as package:
                if sum(x.file_size for x in package.infolist()) > max_bytes * 20:
                    raise EngineError("PARSER_FAILED", "expanded bounds")
            document = Document(BytesIO(raw))
            parts = []
            for item in document.iter_inner_content():
                if isinstance(item, Paragraph):
                    prefix = "# " if item.style and item.style.name.startswith("Heading") else ""
                    parts.append(prefix + item.text)
                elif isinstance(item, Table):
                    parts.append("\n".join("| " + " | ".join(c.text for c in row.cells) + " |" for row in item.rows))
            text = "\n\n".join(parts)
        else:
            raise EngineError("PARSER_FAILED", "unsupported format")
        if kind == "html":
            parser_type = type("ScopedHtmlParser", (RAGFlowHtmlParser,), {"tokenizer": tokenizer})
            chunks = parser_type.parser_txt(text, chunk_tokens)
        else:
            sections = MarkdownElementExtractor(text).extract_elements(delimiter="\n", include_meta=True)
            chunks = []
            # Keep protected blocks (tables/fences/lists) whole; upstream paragraph grouping for adjacent prose.
            pending = []
            def flush():
                for group in merge_paragraphs(pending, chunk_tokens, size=count_tokens):
                    chunks.append("\n".join(group))
                pending.clear()
            for section in sections:
                value = section["content"]
                if re.match(r"^(?:\||[\x60~]{3}|[-*+]\s|\d+\.\s)", value.lstrip()) or "<table" in value:
                    flush()
                    chunks.append(value)
                else:
                    pending.append(value)
            flush()
        result = []
        for order, value in enumerate(chunks):
            if not value.strip():
                continue
            headings = re.findall(r"^#{1,6}\s+(.+)$", value, re.MULTILINE)
            result.append({"text": value, "order": order, "headings": headings,
                           "kind": "table" if "<table" in value or value.lstrip().startswith("|") else "text"})
        if not result:
            raise EngineError("PARSER_FAILED", "empty/no extractable text")
        return result
    except EngineError:
        raise
    except Exception:
        raise EngineError("PARSER_FAILED", "parser") from None
