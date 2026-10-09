"""Optional, extractive document routing with official LlamaIndex IndexNodes.

This module does not rank, embed, rerank, generate answers or change serving.
Routing summaries are NOT source evidence: each extract keeps its own original
source offsets; callers must retrieve detail nodes before answering.

Upstream (MIT):
https://developers.llamaindex.ai/python/framework/integrations/retrievers/recursive_retriever_nodes/
https://github.com/run-llama/llama_index/blob/main/llama-index-core/llama_index/core/retrievers/recursive_retriever.py
https://github.com/executablebooks/markdown-it-py
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from typing import Any

from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import Document, IndexNode, NodeRelationship, NodeWithScore, TextNode
from llama_index.core.vector_stores import FilterCondition, FilterOperator, MetadataFilter, MetadataFilters
from markdown_it import MarkdownIt

DISCOVERY_VERSION = "extractive-document-discovery-v1"
_MARKDOWN = MarkdownIt("commonmark", {"html": False})


def _clip(text: str, tokenizer: Callable, limit: int) -> tuple[str, int]:
    """Use the official sentence splitter for a bounded exact first excerpt."""
    if limit <= 0 or not text.strip():
        return "", 0
    splitter = SentenceSplitter(chunk_size=limit, chunk_overlap=0, tokenizer=tokenizer)
    excerpt = splitter.split_text(text)[0]
    start = text.find(excerpt)
    if start < 0 or len(tokenizer(excerpt)) > limit:
        raise ValueError("Discovery excerpt is not an exact bounded source slice.")
    return excerpt, start


def _blocks(document: Document, raw_nodes: Sequence[TextNode]):
    """Extract mapped Markdown blocks, accepting only their original source text."""
    text = document.text
    offsets = [0, *(match.end() for match in re.finditer(r"\r\n|\r|\n", text))]
    if offsets[-1] != len(text):
        offsets.append(len(text))
    source_id = str(document.metadata.get("source_id", document.id_))
    output = []
    for index, token in enumerate(tokens := _MARKDOWN.parse(text)):
        if token.level != 0 or token.map is None or token.type not in {"heading_open", "paragraph_open"}:
            continue
        inline = tokens[index + 1] if index + 1 < len(tokens) else None
        if inline is None or inline.type != "inline":
            continue
        children = inline.children or []
        # Linked headings are often cross-sell/navigation cards. Details remain
        # in the ordinary index; summaries only describe the host document.
        if token.type == "heading_open" and any(c.type in {"link_open", "image"} for c in children):
            continue
        words = " ".join(c.content for c in children if c.type in {"text", "code_inline"})
        if not words.strip():
            continue
        start, end = [offsets[line] for line in token.map]
        related = [node for node in raw_nodes if node.start_char_idx < end and start < node.end_char_idx]
        if not related:
            continue
        # An overlap with foreign-card or review evidence is conservatively
        # excluded. UNKNOWN is retained as unknown, never promoted to PRIMARY.
        if any(str(n.metadata.get("subject_source_id", source_id)) != source_id
               or n.metadata.get("evidence_role") == "REVIEW" for n in related):
            continue
        role = "PRIMARY" if any(n.metadata.get("evidence_role") == "PRIMARY" for n in related) else "UNKNOWN"
        kind = "heading" if token.type == "heading_open" else "prose"
        if kind == "prose":
            # Character substance avoids requiring whitespace-delimited words
            # in scripts such as Chinese and Japanese.
            if len(re.findall(r"\w", words)) < 24 or words.isupper():
                continue
            # Images and standalone link labels are not descriptive prose.
            outside, linked = [], False
            for child in children:
                if child.type == "link_open":
                    linked = True
                elif child.type == "link_close":
                    linked = False
                elif child.type == "text" and not linked:
                    outside.append(child.content)
            if len(re.findall(r"\w", " ".join(outside))) < 24:
                continue
        output.append({"start": start, "end": end, "kind": kind, "role": role,
                       "level": int(token.tag[1:]) if kind == "heading" else None})
    return output


def build_discovery_nodes(
    documents: Sequence[Document],
    source_nodes: Mapping[str, TextNode] | Sequence[TextNode],
    tokenizer: Callable[[str], list[Any]],
    *,
    max_tokens: int = 256,
    max_headings: int = 10,
    max_description_tokens: int = 128,
) -> list[IndexNode]:
    """Build one deterministic source-summary routing node per nonempty document.

    Reserve descriptive prose before fitting shallow headings. PRIMARY paragraphs
    are preferred; otherwise only the first three eligible lead paragraphs are
    considered as an explicitly UNKNOWN fallback. Known reviews and cross-sell
    subjects are omitted. Empty documents produce no routing node.

    ``IndexNode.index_id`` is the original source ID, ready for an official
    RecursiveRetriever's retriever_dict. The caller owns root ranking and total
    detail/reranker budgets; this helper cannot spend or extend those budgets.
    """
    if max_tokens < 64 or max_headings < 0 or not 0 <= max_description_tokens <= max_tokens:
        raise ValueError("Require at least64 summary tokens and valid heading/description limits.")
    docs = {str(doc.metadata.get("source_id", doc.id_)): doc for doc in documents}
    if len(docs) != len(documents) or len({doc.id_ for doc in documents}) != len(documents):
        raise ValueError("Discovery source IDs and document IDs must be unique.")
    grouped: dict[str, list[TextNode]] = {source_id: [] for source_id in docs}
    nodes = source_nodes.values() if isinstance(source_nodes, Mapping) else source_nodes
    for node in nodes:
        source_id = str(node.metadata.get("source_id", ""))
        if source_id not in docs:
            raise ValueError("Discovery raw node refers to an unavailable document.")
        doc = docs[source_id]
        start, end = node.start_char_idx, node.end_char_idx
        if (not isinstance(start, int) or not isinstance(end, int)
                or not 0 <= start < end <= len(doc.text) or doc.text[start:end] != node.text
                or node.metadata.get("url") != doc.metadata.get("url")
                or node.source_node is None or node.source_node.node_id != doc.id_):
            raise ValueError("Discovery raw node provenance is invalid.")
        grouped[source_id].append(node)
    result = []
    for source_id, document in docs.items():
        if not document.text.strip():
            continue
        raw = sorted(grouped[source_id], key=lambda node: (node.start_char_idx, node.end_char_idx))
        blocks = _blocks(document, raw)
        title = str(document.metadata.get("title", ""))
        title_excerpt, title_start = _clip(title, tokenizer, min(32, max_tokens // 4))
        parts = [f"Title: {title_excerpt}"] if title_excerpt else []
        witnesses = []
        used_prose_tokens = 0

        def add(block, allowance):
            nonlocal used_prose_tokens
            allowance = min(allowance, max_tokens - len(tokenizer("\n\n".join(parts))))
            if allowance < 1:
                return False
            # Labels/separators also consume tokens. Retry with a smaller exact
            # excerpt if tokenizer boundaries make the assembled view longer.
            label = "Heading" if block["kind"] == "heading" else "Excerpt"
            for limit in range(allowance, 0, -1):
                quote, relative = _clip(document.text[block["start"]:block["end"]], tokenizer, limit)
                candidate = f"{label}: {quote}"
                if len(tokenizer("\n\n".join([*parts, candidate]))) <= max_tokens:
                    start = block["start"] + relative
                    key = (start, start + len(quote))
                    if any((w["start_char"], w["end_char"]) == key for w in witnesses):
                        return False
                    parts.append(candidate)
                    witnesses.append({"source_id": source_id, "start_char": start,
                                      "end_char": start + len(quote), "text": quote,
                                      "kind": block["kind"], "role": block["role"],
                                      "heading_level": block["level"]})
                    if block["kind"] == "prose":
                        used_prose_tokens += len(tokenizer(quote))
                    return True
            return False

        primary = [b for b in blocks if b["kind"] == "prose" and b["role"] == "PRIMARY"]
        lead = [b for b in blocks if b["kind"] == "prose"][:3]
        descriptions = primary[:3] or lead
        for block in descriptions:
            add(block, min(64, max_description_tokens - used_prose_tokens))
        # Shallow headings describe source structure; source order breaks ties.
        headings = sorted((b for b in blocks if b["kind"] == "heading"), key=lambda b: (b["level"], b["start"]))
        count = 0
        seen_headings = set()
        for block in headings:
            heading = document.text[block["start"]:block["end"]].strip()
            if heading in seen_headings:
                continue
            seen_headings.add(heading)
            if count >= max_headings:
                break
            if add(block, min(24, max_tokens)):
                count += 1
        summary = "\n\n".join(parts)
        if not summary:
            continue
        source_hash = hashlib.sha256(document.text.encode()).hexdigest()
        metadata = {
            "source_id": source_id, "title": title, "url": document.metadata.get("url", ""),
            "discovery_version": DISCOVERY_VERSION, "discovery_only": True,
            "answer_evidence": False, "source_sha256": source_hash,
            "discovery_witnesses": witnesses,
            "title_provenance": {"kind": "document_metadata", "field": "title", "text": title_excerpt,
                                 "start_char": title_start, "end_char": title_start + len(title_excerpt)},
            "description_basis": "PRIMARY" if primary else "UNKNOWN_LEAD" if lead else "NONE",
            "summary_tokens": len(tokenizer(summary)), "max_summary_tokens": max_tokens,
            "omitted_eligible_blocks": max(0, len(blocks) - len(witnesses)),
        }
        node_id = "discovery-" + hashlib.sha256(
            f"{DISCOVERY_VERSION}:{source_id}:{source_hash}:{summary}".encode()
        ).hexdigest()
        result.append(IndexNode(id_=node_id, index_id=source_id, text=summary, metadata=metadata,
                                excluded_embed_metadata_keys=list(metadata), excluded_llm_metadata_keys=list(metadata),
                                relationships={NodeRelationship.SOURCE: document.as_related_node_info()}))
    return result


def ranked_source_ids(
    ranked: Sequence[NodeWithScore], available_source_ids: Collection[str], *, max_sources: int,
) -> list[str]:
    """Keep retriever order and deduplicate valid IndexNode routes, without scores."""
    if max_sources < 0:
        raise ValueError("Source limit cannot be negative.")
    allowed = set(available_source_ids)
    result = []
    for item in ranked:
        node = item.node
        if (not isinstance(node, IndexNode) or not node.metadata.get("discovery_only")
                or node.index_id != node.metadata.get("source_id")):
            raise ValueError("Only provenance-bearing discovery IndexNodes may route sources.")
        if len(result) >= max_sources:
            break
        if node.index_id in allowed and node.index_id not in result:
            result.append(node.index_id)
    return result


def source_scope_filters(source_id: str) -> MetadataFilters:
    """Official filters restrict detail search to a source's own subject text."""
    return MetadataFilters(condition=FilterCondition.AND, filters=[
        MetadataFilter(key="source_id", value=source_id, operator=FilterOperator.EQ),
        MetadataFilter(key="subject_source_id", value=source_id, operator=FilterOperator.EQ),
    ])
