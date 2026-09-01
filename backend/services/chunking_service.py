from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional
import tiktoken

CHUNK_SIZE = 650
CHUNK_OVERLAP = 120
ENCODING_NAME = "cl100k_base"


@dataclass(frozen=True)
class TextChunk:
    index: int
    content: str
    token_count: int
    start_token: int
    end_token: int
    heading: str = ""
    section: str = ""
    entity_name: str = ""
    source_url: str = ""
    page_title: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


def count_tokens(text: str) -> int:
    try:
        return len(tiktoken.get_encoding(ENCODING_NAME).encode(text))
    except Exception:
        return max(1, len(text.split()))


def normalize_text(text: str) -> str:
    """
    Normalizes whitespace while carefully preserving structural elements:
    newlines, markdown headers, table rows, bullet lists, and paragraphs.
    """
    if not text:
        return ""
    # Normalize carriage returns
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Normalize spaces/tabs on individual lines
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    # Join and collapse 3+ consecutive newlines to 2
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _split_into_sections(text: str) -> List[Dict[str, Any]]:
    """
    Splits a document into structural sections based on Markdown headings (#, ##, ###),
    horizontal rules, or structured headers.
    """
    lines = text.split("\n")
    sections: List[Dict[str, Any]] = []

    current_heading = "General"
    current_h1 = ""
    current_h2 = ""
    current_lines: List[str] = []

    heading_regex = re.compile(r"^(#{1,6})\s+(.+)$")

    for line in lines:
        match = heading_regex.match(line)
        if match:
            # Save previous section if it has content
            if current_lines:
                sec_text = "\n".join(current_lines).strip()
                if sec_text:
                    sections.append({
                        "heading": current_heading,
                        "h1": current_h1,
                        "h2": current_h2,
                        "text": sec_text,
                    })
                current_lines = []

            hashes, heading_text = match.groups()
            level = len(hashes)
            heading_text = heading_text.strip()
            current_heading = heading_text

            if level == 1:
                current_h1 = heading_text
                current_h2 = ""
            elif level == 2:
                current_h2 = heading_text

            current_lines.append(line)
        elif line.strip().startswith("---") or line.strip().startswith("***"):
            if current_lines:
                sec_text = "\n".join(current_lines).strip()
                if sec_text:
                    sections.append({
                        "heading": current_heading,
                        "h1": current_h1,
                        "h2": current_h2,
                        "text": sec_text,
                    })
                current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sec_text = "\n".join(current_lines).strip()
        if sec_text:
            sections.append({
                "heading": current_heading,
                "h1": current_h1,
                "h2": current_h2,
                "text": sec_text,
            })

    return sections if sections else [{"heading": "General", "h1": "", "h2": "", "text": text}]


def _split_section_by_paragraphs(
    section_text: str,
    encoding: Any,
    max_tokens: int = CHUNK_SIZE,
    overlap_tokens: int = CHUNK_OVERLAP,
) -> List[str]:
    """
    Splits a large section into coherent passages along paragraph, table, or sentence boundaries.
    """
    paragraphs = section_text.split("\n\n")
    passages: List[str] = []
    current_passage_parts: List[str] = []
    current_passage_tokens = 0

    for p in paragraphs:
        p_clean = p.strip()
        if not p_clean:
            continue

        p_tokens = len(encoding.encode(p_clean))

        # If a single paragraph exceeds max_tokens, split it on sentence boundaries
        if p_tokens > max_tokens:
            if current_passage_parts:
                passages.append("\n\n".join(current_passage_parts))
                current_passage_parts = []
                current_passage_tokens = 0

            sentences = re.split(r"(?<=[.!?])\s+", p_clean)
            sub_parts: List[str] = []
            sub_tokens = 0
            for s in sentences:
                s_tokens = len(encoding.encode(s))
                if sub_tokens + s_tokens > max_tokens and sub_parts:
                    passages.append(" ".join(sub_parts))
                    # Overlap with previous sentence if feasible
                    if len(sub_parts) > 1 and sub_tokens > overlap_tokens:
                        sub_parts = [sub_parts[-1], s]
                        sub_tokens = len(encoding.encode(" ".join(sub_parts)))
                    else:
                        sub_parts = [s]
                        sub_tokens = s_tokens
                else:
                    sub_parts.append(s)
                    sub_tokens += s_tokens

            if sub_parts:
                passages.append(" ".join(sub_parts))
            continue

        if current_passage_tokens + p_tokens > max_tokens and current_passage_parts:
            passages.append("\n\n".join(current_passage_parts))
            # Start new passage with overlap if possible
            if len(current_passage_parts) > 1:
                last_part = current_passage_parts[-1]
                current_passage_parts = [last_part, p_clean]
                current_passage_tokens = len(encoding.encode("\n\n".join(current_passage_parts)))
            else:
                current_passage_parts = [p_clean]
                current_passage_tokens = p_tokens
        else:
            current_passage_parts.append(p_clean)
            current_passage_tokens += p_tokens

    if current_passage_parts:
        passages.append("\n\n".join(current_passage_parts))

    return passages


def chunk_text_with_metadata(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
    page_title: Optional[str] = None,
    source_url: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> List[TextChunk]:
    """
    Structure-aware semantic chunking with hierarchy preservation,
    contextual prefixing, and rich metadata.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be zero or greater and smaller than chunk_size")

    cleaned = normalize_text(text)
    if not cleaned:
        return []

    encoding = tiktoken.get_encoding(ENCODING_NAME)
    sections = _split_into_sections(cleaned)
    chunks: List[TextChunk] = []
    current_token_offset = 0

    base_meta = metadata or {}

    for sec in sections:
        sec_text = sec["text"].strip()
        if not sec_text:
            continue

        heading = sec.get("heading", "")
        sec_tokens = len(encoding.encode(sec_text))

        # Determine passages for this section
        if sec_tokens <= chunk_size:
            passages = [sec_text]
        else:
            passages = _split_section_by_paragraphs(
                sec_text,
                encoding=encoding,
                max_tokens=chunk_size,
                overlap_tokens=overlap,
            )

        for passage in passages:
            passage_clean = passage.strip()
            if not passage_clean:
                continue

            # Contextual Prefix Enrichment
            context_prefixes = []
            if page_title and page_title.strip() and not passage_clean.startswith(f"# {page_title}"):
                context_prefixes.append(f"[{page_title.strip()}]")
            if heading and heading != "General" and not passage_clean.startswith(f"#") and heading not in passage_clean[:60]:
                context_prefixes.append(f"[{heading.strip()}]")

            prefix_str = " ".join(context_prefixes)
            if prefix_str and not passage_clean.startswith("["):
                enriched_content = f"{prefix_str}\n{passage_clean}"
            else:
                enriched_content = passage_clean

            token_count = len(encoding.encode(enriched_content))
            start_tok = current_token_offset
            end_tok = current_token_offset + token_count
            current_token_offset = end_tok

            chunk_meta = {
                **base_meta,
                "heading": heading,
                "h1": sec.get("h1", ""),
                "h2": sec.get("h2", ""),
                "page_title": page_title or "",
                "source_url": source_url or "",
            }

            chunks.append(
                TextChunk(
                    index=len(chunks),
                    content=enriched_content,
                    token_count=token_count,
                    start_token=start_tok,
                    end_token=end_tok,
                    heading=heading,
                    section=sec.get("h2", "") or heading,
                    source_url=source_url or "",
                    page_title=page_title or "",
                    metadata=chunk_meta,
                )
            )

    return chunks


def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
    page_title: Optional[str] = None,
    source_url: Optional[str] = None,
) -> List[str]:
    return [
        chunk.content
        for chunk in chunk_text_with_metadata(
            text=text,
            chunk_size=chunk_size,
            overlap=overlap,
            page_title=page_title,
            source_url=source_url,
        )
    ]
