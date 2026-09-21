"""Ingestion adapter: platform supplies bytes; never fetches URLs or external images."""
import re
from .contracts import EngineError
from .upstream.html_parser import RAGFlowHtmlParser
from .upstream.naive_markdown import Markdown, merge_markdown_sections
from .upstream.merge import naive_merge
from .upstream.txt_parser import RAGFlowTxtParser
from .upstream.codecs import decode_text
from .upstream.delim import DEFAULT_DELIMITER
from .upstream.runtime import num_tokens_from_string


def parse(content, kind, *, tokenizer, chunk_tokens=512, max_bytes=8_388_608, count_tokens=num_tokens_from_string,
          filename="document"):
    raw = content.encode() if isinstance(content, str) else content
    if not isinstance(raw, bytes) or len(raw) > max_bytes:
        raise EngineError("PARSER_FAILED", "input bounds")
    try:
        from .structured_parsing import CPU_FORMATS, parse_cpu
        if kind in CPU_FORMATS:
            return parse_cpu(raw, kind, filename=filename, chunk_tokens=chunk_tokens, max_bytes=max_bytes)
        if kind in ("txt", "md", "markdown", "crawl", "html"):
            text = decode_text(raw)[0]
        else:
            raise EngineError("PARSER_FAILED", "unsupported format")
        if kind == "html":
            parser_type = type("ScopedHtmlParser", (RAGFlowHtmlParser,), {"tokenizer": tokenizer})
            chunks = naive_merge(parser_type.parser_txt(text, chunk_tokens), chunk_tokens)
        elif kind == "txt":
            chunks = naive_merge(RAGFlowTxtParser.parser_txt(text, chunk_tokens), chunk_tokens)
        else:
            sections, _, images = Markdown(chunk_tokens)(filename, raw, separate_tables=False,
                                                          delimiter=DEFAULT_DELIMITER,
                                                          return_section_images=True)
            chunks, _ = merge_markdown_sections(sections, images, chunk_tokens)
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
