"""Source-preserving adapters around LlamaIndex's Markdown and sentence parsers.

The stored node is always an exact, contiguous slice of the original document.
``model_text`` is a separate view: it omits image URLs and repeated standalone
links, while retaining link destinations needed to associate reviews and items.
No content, policy or product-specific rules are used.

Upstream components (MIT licensed):
https://github.com/run-llama/llama_index/tree/main/llama-index-core/llama_index/core/node_parser
https://github.com/executablebooks/markdown-it-py
"""

from __future__ import annotations

import hashlib
import re
from bisect import bisect_right
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter
from llama_index.core.schema import Document, MetadataMode, NodeRelationship, TextNode
from markdown_it import MarkdownIt

from rag2_engine.evidence_roles import evidence_role

NODE_BUILDER_VERSION = "markdown-source-adapter-v7"
_MARKDOWN = MarkdownIt("commonmark", {"html": False})
_TABLE_MARKDOWN = MarkdownIt("commonmark", {"html": False}).enable("table")


def _canonical_url(value: str, base: str = "", *, include_query: bool = False) -> str | None:
    """Match known HTTP URLs without conflating case-sensitive/reserved paths."""
    try:
        parts = urlsplit(urljoin(base, value))
        scheme = parts.scheme.lower()
        if scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return None
        host = parts.hostname.encode("idna").decode("ascii").lower()
        if ":" in host:
            host = f"[{host}]"
        port = parts.port
        if port is not None and port != {"http": 80, "https": 443}[scheme]:
            host += f":{port}"
        # Decode only RFC3986 unreserved characters. In particular, %2F must
        # remain distinct from a slash and path case must remain significant.
        unreserved = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
        path = re.sub(r"%([0-9a-fA-F]{2})", lambda match: (
            chr(int(match.group(1), 16)) if chr(int(match.group(1), 16)) in unreserved
            else "%" + match.group(1).upper()
        ), parts.path or "/")
        return urlunsplit((scheme, host, path, parts.query if include_query else "", ""))
    except (TypeError, ValueError, UnicodeError):
        return None


def _heading_link(children: list[Any]) -> tuple[str, str] | None:
    """Return a single leading link supplying the heading's visible subject.

    Formatting, surrounding punctuation and a trailing description are allowed.
    Text before the link, multiple links, or an image-only heading are ambiguous
    and therefore do not change subject attribution.
    """
    destinations, inside, label, prefix = [], False, [], []
    for child in children:
        if child.type == "link_open":
            destinations.append(child.attrGet("href") or "")
            inside = True
        elif child.type == "link_close":
            inside = False
        elif child.type in {"text", "code_inline", "html_inline", "image"}:
            if inside and child.type != "image":
                label.append(child.content)
            elif not inside and not destinations:
                prefix.append(child.content)
    if len(destinations) != 1 or re.search(r"\w", "".join(prefix)) or not re.search(r"\w", "".join(label)):
        return None
    return destinations[0], "".join(label).strip()


def _closing_product_link(children: list[Any]) -> str | None:
    """Recognize a standalone explicit card-closing control, never body prose."""
    linked = _heading_link(children)
    if not linked or not re.fullmatch(r"(?:viewproduct)+", re.sub(r"\s+", "", linked[1].casefold())):
        return None
    inside = False
    for child in children:
        if child.type == "link_open":
            inside = True
        elif child.type == "link_close":
            inside = False
        elif not inside and child.type in {"text", "code_inline", "html_inline", "image"} and child.content.strip():
            return None
    return linked[0]


def _subject_sections(document: Document, known_urls: dict[str, Document], corpus_origins: set[str]):
    """Attach explicit linked-heading subjects without changing source slices.

    Only real top-level Markdown heading blocks or the already supported wrapped
    headings can establish a subject. Nested headings inherit that subject until
    a sibling/ancestor closes it; arbitrary body links do not change attribution.
    Structural labels within that section inherit its subject. Parsing the whole
    document also resolves reference-style heading links using markdown-it.
    """
    text = document.text
    line_offsets = [0, *(match.end() for match in re.finditer(r"\r\n|\r|\n", text))]
    if line_offsets[-1] != len(text):
        line_offsets.append(len(text))
    lines = re.split(r"\r\n|\r|\n", text)
    environment: dict[str, Any] = {}
    tokens = _MARKDOWN.parse(text, environment)
    def identity(doc):
        return {"subject_source_id": str(doc.metadata.get("source_id", doc.id_)),
                "subject_title": str(doc.metadata.get("title", "")),
                "subject_url": str(doc.metadata.get("url", ""))}

    primary = identity(document)
    events = {0: (primary, "", [], False)}
    stack: list[tuple[int, dict, str]] = []

    def add(line_number, inline, heading, level):
        while stack and stack[-1][0] >= level:
            stack.pop()
        subject = stack[-1][1] if stack else primary
        linked = _heading_link(inline.children or [])
        base = str(document.metadata.get("url", ""))
        exact = _canonical_url(linked[0], base, include_query=True) if linked else None
        reference_context = any(re.sub(r"[^\w]+", " ", item[2].casefold()).strip()
                                in {"references", "bibliography", "sources", "citations"} for item in stack)
        if reference_context:
            exact = None
        if exact in known_urls:
            subject = identity(known_urls[exact])
        elif exact and urlunsplit((*urlsplit(exact)[:2], "", "", "")) in corpus_origins:
            # An uncrawled card is still a distinct subject. Query parameters are
            # functional identity unless the corpus explicitly says otherwise.
            subject = {"subject_source_id": "linked:" + hashlib.sha256(exact.encode()).hexdigest(),
                       "subject_title": linked[1], "subject_url": exact}
        stack.append((level, subject, heading))
        events[line_offsets[line_number]] = (subject, heading, [item[2] for item in stack], False)

    for index, token in enumerate(tokens):
        if token.level != 0 or token.map is None:
            continue
        if token.type == "heading_open" and index + 1 < len(tokens):
            inline = tokens[index + 1]
            if inline.type == "inline":
                add(token.map[0], inline, inline.content, int(token.tag[1:]))
        elif token.type == "paragraph_open":
            inline = tokens[index + 1] if index + 1 < len(tokens) else None
            destination = _closing_product_link(inline.children or []) if inline and inline.type == "inline" else None
            if destination and stack and stack[-1][1]["subject_source_id"] != primary["subject_source_id"]:
                target = _canonical_url(destination, str(document.metadata.get("url", "")), include_query=True)
                active = _canonical_url(stack[-1][1]["subject_url"], include_query=True)
                if target and target == active:
                    # Explicit card controls close linked-subject scope before
                    # subsequent images, unheaded dialogs or host-page prose.
                    while stack and stack[-1][1]["subject_source_id"] != primary["subject_source_id"]:
                        stack.pop()
                    events[line_offsets[token.map[1]]] = (primary, "", [item[2] for item in stack], True)
            for line_number in range(*token.map):
                wrapped = re.fullmatch(r"\s*(\*\*|__)(#{1,6})[ \t]+(.+?)\1\s*", lines[line_number])
                if wrapped:
                    inline = _MARKDOWN.parseInline(wrapped.group(3), environment)[0]
                    add(line_number, inline, wrapped.group(3), len(wrapped.group(2)))

    positions = sorted(events)
    for start, end, title, method in _sections(document):
        event_index = bisect_right(positions, start) - 1
        subject, _, headings, closed_card = events[positions[event_index]]
        cursor, active_title = start, title
        if closed_card and _heading_link(_MARKDOWN.parseInline(title)[0].children or []):
            active_title = ""
        for position in positions[event_index + 1:]:
            if position >= end:
                break
            next_subject, next_title, next_headings, _ = events[position]
            if text[cursor:position].strip():
                yield cursor, position, active_title, method, subject, headings
            cursor, subject, active_title, headings = position, next_subject, next_title, next_headings
        if text[cursor:end].strip():
            yield cursor, end, active_title, method, subject, headings


def _bounded(text: str, tokenizer: Callable[[str], list[Any]], limit: int) -> str:
    """Bound only descriptive metadata, never the source passage."""
    text = " ".join(text.split())
    if len(tokenizer(text)) <= limit:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if len(tokenizer(text[:middle])) <= limit:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip()


def _canonical_source(text: str) -> tuple[str, list[int]]:
    """Mirror the Markdown parser's newline/heading normalization with offsets.

    MarkdownNodeParser reconstructs headings with one separating space and
    removes leading/trailing section whitespace. Its native offsets can therefore
    be absent for CRLF or tab-separated headings. This map restores original
    character positions without changing the source bytes or searching globally
    for a duplicated passage.
    """
    chars: list[str] = []
    starts: list[int] = []
    index = 0
    while index < len(text):
        starts.append(index)
        if text.startswith("\r\n", index):
            chars.append("\n")
            index += 2
        else:
            chars.append(text[index])
            index += 1
    normalized = "".join(chars)
    in_fence = False
    position = 0
    for line in normalized.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence:
            match = re.match(r"^(#+)\s(.*)", line)
            if match:
                chars[position + len(match.group(1))] = " "
        position += len(line) + 1
    return "".join(chars), [*starts, len(text)]


def _sections(document: Document) -> list[tuple[int, int, str, str]]:
    # The current LlamaIndex Markdown parser recognizes backtick fences only.
    # Avoid treating headings inside a CommonMark tilde fence as real sections.
    if any(token.type == "fence" and token.markup.startswith("~") for token in _MARKDOWN.parse(document.text)):
        return [(0, len(document.text), "", "sentence_fallback")]
    canonical, offsets = _canonical_source(document.text)
    parsed = MarkdownNodeParser.from_defaults().get_nodes_from_node(
        Document(id_=document.id_, text=canonical)
    )
    result: list[tuple[int, int, str, str]] = []
    cursor = 0
    for section in parsed:
        position = canonical.find(section.text, cursor)
        if position < 0:
            # Fail safely to the established sentence parser if a future upstream
            # parser adds another normalization that this adapter cannot map.
            return [(0, len(document.text), "", "sentence_fallback")]
        end = position + len(section.text)
        first_line = section.text.split("\n", 1)[0]
        heading = re.match(r"^#+\s+(.*)", first_line)
        path = section.metadata.get("header_path", "/").strip("/")
        # Leaf headings carry the local topic; do not repeat a long ancestor
        # marketing headline in every model input.
        section_title = heading.group(1) if heading else path.rsplit('/', 1)[-1]
        plain_heading = re.sub(r'[^\w\s]', '', section_title).casefold().strip()
        plain_title = re.sub(r'[^\w\s]', '', str(document.metadata.get('title',''))).casefold().strip()
        if plain_title and plain_heading.startswith(plain_title):
            section_title = ''
        result.append((offsets[position], offsets[end], section_title, "markdown"))
        cursor = end
    return [part for section in result for part in _block_sections(document, *section)]


def _block_sections(
    document: Document, start: int, end: int, title: str, method: str,
) -> list[tuple[int, int, str, str]]:
    """Expose structural labels missed by an ATX-only Markdown section parser.

    markdown-it supplies real block/line boundaries, so lists and fenced code
    cannot masquerade as plain labels. The source is never rewritten. A short
    title-like paragraph is promoted only when followed by substantive prose or
    a list; ordinary short sentences and link/image controls stay untouched.
    Explicit headings accidentally wrapped in emphasis are recognized separately.
    """
    text = document.text[start:end]
    offsets = [0, *(match.end() for match in re.finditer(r"\r\n|\r|\n", text))]
    lines = re.split(r"\r\n|\r|\n", text)
    tokens = _MARKDOWN.parse(text)
    blocks = []
    for index, token in enumerate(tokens):
        if token.level != 0 or token.map is None or token.type == "inline":
            continue
        inline = tokens[index + 1] if index + 1 < len(tokens) and tokens[index + 1].type == "inline" else None
        blocks.append({"token": token, "inline": inline})

    def plain(block):
        inline = block["inline"]
        return _inline_text(inline.children or []).strip() if inline else ""

    def has_rich_inline(block):
        inline = block["inline"]
        return bool(inline and any(child.type in {"link_open", "image", "code_inline"}
                                   for child in inline.children or []))

    def is_body(block):
        token = block["token"]
        if token.type in {"bullet_list_open", "ordered_list_open"}:
            return True
        if token.type != "paragraph_open":
            return False
        # Link-only/image-only blocks are controls or media, not a following
        # explanation. Inline links within a real sentence remain valid prose.
        inline = block["inline"]
        prose = "".join(child.content for child in inline.children or [] if child.type == "text") if inline else ""
        return len(re.findall(r"\w+", prose)) >= 8

    def label(block):
        token = block["token"]
        value = plain(block)
        if token.type != "paragraph_open" or token.map[1] - token.map[0] != 1 or has_rich_inline(block):
            return ""
        words = re.findall(r"[^\W_]+", value, flags=re.UNICODE)
        if not words or len(value) > 120 or not words[0][0].isalpha():
            return ""
        # A standalone question naturally labels its answer, including an
        # emphasized FAQ question that is not marked as a Markdown heading.
        if value.endswith("?") and len(words) <= 20:
            return value
        if len(words) > 8 or re.search(r"[.!?;]$", value) or any(char in value for char in "$%=|"):
            return ""
        connectors = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to", "with"}
        title_case = all(word[0].isupper() or not word[0].islower() or word.casefold() in connectors
                         for word in words)
        if title_case or (" & " in value and words[0][0].isupper()):
            return value
        return ""

    boundaries: dict[int, str] = {0: title}
    for index, block in enumerate(blocks):
        token = block["token"]
        if token.type == "paragraph_open":
            for line_number in range(*token.map):
                original_line = lines[line_number]
                wrapped = re.fullmatch(r"\s*(\*\*|__)(#{1,6})[ \t]+(.+?)\1\s*", original_line)
                if wrapped:
                    inline = _MARKDOWN.parseInline(wrapped.group(3))[0]
                    heading = _inline_text(inline.children or []).strip()
                    boundaries[offsets[line_number]] = heading
            candidate = label(block)
            if candidate and index + 1 < len(blocks) and is_body(blocks[index + 1]):
                boundaries.setdefault(offsets[token.map[0]], candidate)
            # Keep list rows together, but do not let the following prose become
            # a tail of a long table/list of checkout or navigation options.
            if index and blocks[index - 1]["token"].type in {"bullet_list_open", "ordered_list_open"}:
                if is_body(block) and not has_rich_inline(block):
                    boundaries.setdefault(offsets[token.map[0]], "")

    if len(boundaries) == 1:
        return [(start, end, boundaries[0], "markdown_blocks" if boundaries[0] != title else method)]
    positions = sorted(boundaries)
    output = []
    active_title = title
    for index, position in enumerate(positions):
        active_title = boundaries[position] or active_title
        finish = positions[index + 1] if index + 1 < len(positions) else len(text)
        if text[position:finish].strip():
            output.append((start + position, start + finish, active_title, "markdown_blocks"))
    return output


def _inline_text(children: list[Any]) -> str:
    parts: list[str] = []
    destinations: list[str] = []
    for child in children:
        if child.type == "image":
            # Alt text can describe a fact (such as an ingredient), so keep it.
            if child.content.strip():
                parts.append(child.content)
        elif child.type == "link_open":
            destinations.append(child.attrGet("href") or "")
        elif child.type == "link_close":
            destination = destinations.pop() if destinations else ""
            if destination:
                parts.append(f" ({destination})")
        elif child.type in {"softbreak", "hardbreak"}:
            parts.append("\n")
        elif child.type in {"text", "code_inline", "html_inline"}:
            parts.append(child.content)
        elif child.children:
            parts.append(_inline_text(child.children))
    return "".join(parts)


def _table_sections(document: Document, start: int, end: int):
    """Use markdown-it's table/row maps to isolate exact source spans.

    The header is carried as source-derived model metadata on later row chunks.
    No cells or rows are reconstructed, including escaped pipes and Unicode.
    """
    text = document.text[start:end]
    offsets = [0, *(match.end() for match in re.finditer(r"\r\n|\r|\n", text))]
    if offsets[-1] != len(text):
        offsets.append(len(text))
    tokens = _TABLE_MARKDOWN.parse(text)
    cursor = start
    for index, token in enumerate(tokens):
        if token.type != "table_open" or token.level != 0 or token.map is None:
            continue
        table_start, table_end = [start + offsets[line] for line in token.map]
        if document.text[cursor:table_start].strip():
            yield cursor, table_start, {}
        # markdown-it maps the header row separately from the delimiter row.
        header_end = start + offsets[min(token.map[0] + 2, token.map[1])]
        rows = []
        for row in tokens[index + 1:]:
            if row.type == "table_close" and row.level == token.level:
                break
            if row.type == "tr_open" and row.map:
                rows.append(tuple(start + offsets[line] for line in row.map))
        yield table_start, table_end, {
            "table_header": document.text[table_start:header_end],
            "table_header_start_char_idx": table_start,
            "table_header_end_char_idx": header_end,
            "table_start_char_idx": table_start,
            "table_end_char_idx": table_end,
            "table_rows": rows,
        }
        cursor = table_end
    if document.text[cursor:end].strip():
        yield cursor, end, {}


def _readable_markdown(text: str) -> str:
    parts: list[str] = []
    for token in _MARKDOWN.parse(text):
        if token.type == "inline":
            parts.append(_inline_text(token.children or []))
        elif token.type in {"fence", "code_block", "html_block"}:
            parts.append(token.content)
    return "\n".join(part for part in parts if part.strip()).strip()


def model_text(node: TextNode, *, include_metadata: bool = True) -> str:
    """Return explicit model input; citation consumers must keep using node.text.

    Only adjacent identical standalone Markdown links are collapsed.
    Repeated prose, prices, guarantees, warnings and payment terms are retained:
    popularity across pages does not establish that a fact is expendable.
    """
    lines: list[str] = []
    previous_link: str | None = None
    for line in node.text.splitlines():
        stripped = line.strip()
        if re.fullmatch(r"(?:[-*+]\s+)?\[[^\]\n]+\]\([^\s]+\)", stripped):
            if stripped == previous_link:
                continue
            previous_link = stripped
        elif stripped:
            previous_link = None
        lines.append(line)
    body = _readable_markdown("\n".join(lines))
    if not include_metadata:
        return body
    heading = "\n".join(
        f"{key}: {node.metadata[key]}"
        for key in ("document_title", "section", "table_header_model")
        if node.metadata.get(key)
    )
    return "\n\n".join(part for part in (heading, body) if part)


def has_textual_evidence(node: TextNode) -> bool:
    """Index substantive source content, keeping every raw node for citations.

    A product-photo link plus its matching wishlist control is navigation, not
    a statement about the host document. Only complete control labels are
    omitted. Unknown links, ordinary short facts and factual image alt text
    remain eligible; this does not rewrite source or model text.
    """
    tokens = _MARKDOWN.parse(node.text)
    normalize = lambda value: " ".join(value.split()).casefold()
    image_labels = {
        normalize(child.content)
        for token in tokens for child in (token.children or [])
        if child.type == 'image' and child.content.strip()
    }
    image_labels.update(normalize(str(node.metadata[key])) for key in
                        ('title', 'subject_title', 'document_title')
                        if node.metadata.get(key))

    def factual_alt(value):
        # Numeric specifications and explicit key/value labels carry information
        # even when the capture consists solely of an image. A sentence-ending
        # dot alone also occurs in generic image controls and is not evidence.
        return bool(re.search(
            r'\d\s*(?:%|°|(?:mg|kg|g|ml|cl|l|mm|cm|m|oz|lb|lbs|'
            r'v|w|wh|mah|hz|kwh|capsules?|servings?|tablets?)\b)'
            r'|\w\s*:\s*\S', value, re.I))

    def navigation_only(value):
        label = normalize(value).strip(' *-!|.\t')
        if re.fullmatch(r'(?:view product\s*)+', label):
            return True
        if label in {'loading', 'show more', 'read more', 'share', 'link',
                     'previous', 'next', 'enlarge photo'}:
            return True
        action = re.fullmatch(
            r'(?:add to|remove from) (?:wish\s*list|cart|basket)(?:\s+(.+))?', label)
        # A suffix is omitted only when it is a captured product-photo label
        # or document title. Additional delivery/price/prose text stays intact.
        return bool(action and (not action[1] or action[1] in image_labels))

    parts = []
    in_heading = False
    for token in tokens:
        if token.type == 'heading_open':
            in_heading = True
        elif token.type == 'heading_close':
            in_heading = False
        elif token.type == 'inline' and not in_heading:
            children = [c for c in (token.children or [])
                        if c.type not in {'link_open', 'link_close'}
                        and (c.type != 'image' or factual_alt(c.content))]
            value = _inline_text(children).strip()
            if value and not navigation_only(value):
                parts.append(value)
        elif token.type in {'fence','code_block','html_block'} and token.content.strip():
            parts.append(token.content)
    body = ' '.join(parts).strip(' *-!|\n\t')
    if not body:
        return False
    controls = re.sub(r'\b(?:loading|show more|read more|share|link|previous|next)\b', '', body, flags=re.I)
    controls = re.sub(r'yes, this review.*?was helpful\.\s*\d+ people voted yesno, this review.*?people voted no', '', controls, flags=re.I)
    return bool(re.search(r'\w', controls))


def build_nodes(
    documents: Sequence[Document],
    tokenizer: Callable[[str], list[Any]],
    chunk_tokens: int,
    chunk_overlap: int,
) -> list[TextNode]:
    """Build heading-aware original-source nodes with official sentence splitting.

    A short FAQ/review section remains together when it fits the token budget.
    Long sections are split by SentenceSplitter with overlap, and retain their
    heading as bounded metadata. Offsets use Python Unicode character indices,
    matching the retrieval service's existing source-verification contract.

    This function never loads models, changes documents, or calls a provider.
    """
    if chunk_tokens < 32 or not 0 <= chunk_overlap < chunk_tokens:
        raise ValueError("Require chunk_tokens >= 32 and 0 <= overlap < chunk_tokens.")
    if len({document.id_ for document in documents}) != len(documents):
        raise ValueError("Document IDs must be unique.")
    def unique_urls(include_query):
        known: dict[str, Document] = {}
        ambiguous: set[str] = set()
        for document in documents:
            canonical = _canonical_url(str(document.metadata.get("url", "")), include_query=include_query)
            if canonical:
                if canonical in known:
                    ambiguous.add(canonical)
                known[canonical] = document
        for canonical in ambiguous:
            known.pop(canonical, None)
        return known

    # Never discard query parameters: a single known /item?id=1 does not imply
    # that /item?id=2 is that same item merely because it has not been crawled.
    known_urls = unique_urls(True)
    corpus_origins = {
        urlunsplit((*urlsplit(url)[:2], "", "", ""))
        for doc in documents
        if (url := _canonical_url(str(doc.metadata.get("url", "")), include_query=True))
    }
    output: list[TextNode] = []
    for document in documents:
        document_nodes: list[TextNode] = []
        sections = (
            (start, end, title, method, subject, headings, table)
            for section_start, section_end, title, method, subject, headings
            in _subject_sections(document, known_urls, corpus_origins)
            for start, end, table in _table_sections(document, section_start, section_end)
        )
        for section_start, section_end, title, method, subject, headings, table in sections:
            metadata = dict(document.metadata)
            # Metadata receives at most a quarter of the total chunk budget.
            # The original title remains untouched for citations and display.
            budget = max(4, min(24, chunk_tokens // 10))
            subject_title = subject["subject_title"]
            metadata.update({
                **subject,
                **evidence_role(document.metadata, [*headings, title]),
                "document_title": _bounded(subject_title, tokenizer, budget),
                "section": _bounded(title, tokenizer, budget),
                "section_start_char_idx": section_start,
                "section_end_char_idx": section_end,
                "node_parser": method,
                "node_builder_version": NODE_BUILDER_VERSION,
            })
            row_spans = table.get("table_rows", [])
            metadata.update({key: value for key, value in table.items() if key != "table_rows"})
            if table:
                metadata["table_header_model"] = _bounded(table["table_header"], tokenizer, max(4, chunk_tokens // 4))
                # Keep header line structure in the normal case. A very wide
                # header is explicitly flagged; its complete raw span remains.
                if len(tokenizer(table["table_header"])) <= max(4, chunk_tokens // 4):
                    metadata["table_header_model"] = table["table_header"].strip()
                metadata["table_header_truncated"] = (
                    metadata["table_header_model"] != table["table_header"].strip()
                )
            excluded = [key for key in metadata if key not in {"document_title", "section", "table_header_model"}]
            section_document = Document(
                id_=f"{document.id_}:{section_start}:{section_end}",
                text=document.text[section_start:section_end],
                metadata=metadata,
                excluded_embed_metadata_keys=excluded,
                excluded_llm_metadata_keys=excluded,
            )
            splitter = SentenceSplitter(
                chunk_size=chunk_tokens,
                chunk_overlap=0 if table else chunk_overlap,
                tokenizer=tokenizer,
                paragraph_separator="\n" if table else "\n\n",
                include_metadata=True,
                include_prev_next_rel=False,
            )
            table_cursor = 0
            for node in splitter.get_nodes_from_documents([section_document]):
                if table:
                    # Upstream offset reconstruction may find an earlier equal
                    # sentence in an oversized repeated row. Table overlap is
                    # zero, so a monotonic cursor has an unambiguous alignment.
                    position = section_document.text.find(node.text, table_cursor)
                    if position < 0 or section_document.text[table_cursor:position].strip():
                        raise ValueError("A table passage cannot be aligned without losing source text.")
                    node.start_char_idx = position
                    node.end_char_idx = position + len(node.text)
                    table_cursor = node.end_char_idx
                if node.start_char_idx is None or node.end_char_idx is None:
                    raise ValueError("SentenceSplitter returned an unaligned source passage.")
                node.start_char_idx += section_start
                node.end_char_idx += section_start
                if document.text[node.start_char_idx:node.end_char_idx] != node.text:
                    raise ValueError("A parsed passage does not match its original source.")
                if table:
                    # SentenceSplitter keeps short newline-delimited rows as
                    # units. Oversized rows use its standard recursive fallback.
                    node.metadata["table_row_fragmented"] = any(
                        document.text[max(start, node.start_char_idx):min(end, node.end_char_idx)].strip()
                        and ((start < node.start_char_idx and bool(document.text[start:node.start_char_idx].strip()))
                             or (node.end_char_idx < end and bool(document.text[node.end_char_idx:end].strip())))
                        for start, end in row_spans
                        if start < node.end_char_idx and end > node.start_char_idx
                    )
                    for excluded_keys in (node.excluded_embed_metadata_keys, node.excluded_llm_metadata_keys):
                        excluded_keys.append("table_row_fragmented")
                node.id_ = hashlib.sha256(
                    f"{NODE_BUILDER_VERSION}:{document.id_}:{node.start_char_idx}:{node.end_char_idx}".encode()
                ).hexdigest()
                node.relationships = {NodeRelationship.SOURCE: document.as_related_node_info()}
                if len(tokenizer(node.get_content(metadata_mode=MetadataMode.EMBED))) > chunk_tokens:
                    raise ValueError("SentenceSplitter exceeded the configured passage token budget.")
                document_nodes.append(node)
        for index, node in enumerate(document_nodes):
            if index:
                node.relationships[NodeRelationship.PREVIOUS] = document_nodes[index - 1].as_related_node_info()
            if index + 1 < len(document_nodes):
                node.relationships[NodeRelationship.NEXT] = document_nodes[index + 1].as_related_node_info()
        output.extend(document_nodes)
    return output
