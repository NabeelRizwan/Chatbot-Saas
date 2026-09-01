import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse


@dataclass
class DocumentNode:
    url: str
    title: str
    entity_type: str  # 'hub', 'category', 'subcategory', 'detail', 'policy', 'faq', 'support', 'contact'
    depth: int
    parent_url: Optional[str] = None
    category_path: List[str] = field(default_factory=list)
    sibling_urls: List[str] = field(default_factory=list)
    child_urls: List[str] = field(default_factory=list)
    chunk_count: int = 0
    character_count: int = 0
    word_count: int = 0
    cta_count: int = 0


POLICY_TERMS_PATTERN = re.compile(
    r"\b(policy|policies|terms|privacy|refund|return|shipping|delivery|warranty|guarantee|disclaimer|tos|legal)\b",
    re.IGNORECASE,
)
FAQ_TERMS_PATTERN = re.compile(
    r"\b(faq|frequently-asked-questions|q-and-a|help-center|knowledge-base)\b",
    re.IGNORECASE,
)
SUPPORT_TERMS_PATTERN = re.compile(
    r"\b(support|contact|customer-service|reach-us|about-us|about|locations|stores)\b",
    re.IGNORECASE,
)


def infer_entity_type(url: str, title: str, depth: int) -> str:
    """Infers the structural entity type of a web page using URL path and title clues."""
    path = urlparse(url).path.lower().strip("/")
    title_lower = title.lower()

    if not path or path in ("", "index.html", "home"):
        return "hub"

    if POLICY_TERMS_PATTERN.search(path) or POLICY_TERMS_PATTERN.search(title_lower):
        return "policy"

    if FAQ_TERMS_PATTERN.search(path) or FAQ_TERMS_PATTERN.search(title_lower):
        return "faq"

    if SUPPORT_TERMS_PATTERN.search(path) or SUPPORT_TERMS_PATTERN.search(title_lower):
        return "support"

    segments = [s for s in path.split("/") if s]
    if len(segments) == 1:
        return "category"
    elif len(segments) == 2:
        return "subcategory"
    else:
        return "detail"


def extract_category_path(url: str, title: str, parent_title: Optional[str] = None) -> List[str]:
    """Extracts a human-readable hierarchical category path from URL path segments and titles."""
    path = urlparse(url).path.strip("/")
    if not path:
        return [title or "Home"]

    segments = [s.replace("-", " ").replace("_", " ").title() for s in path.split("/") if s]
    if parent_title and parent_title not in segments:
        return [parent_title] + segments
    return segments if segments else [title]


def infer_document_relationships(
    documents: List[Dict[str, Any]],
    root_url: Optional[str] = None,
) -> List[DocumentNode]:
    """
    Analyzes a collection of ingested document records or page dicts,
    infers hierarchical tree relationships (parent, children, siblings, category paths),
    and assigns structural metadata.
    """
    if not documents:
        return []

    # Map URLs to doc items
    doc_map: Dict[str, Dict[str, Any]] = {}
    for d in documents:
        u = d.get("source_url") or d.get("url") or ""
        if u:
            doc_map[u] = d

    # Find root url if not provided
    if not root_url:
        for u in doc_map:
            parsed = urlparse(u)
            if not parsed.path.strip("/"):
                root_url = u
                break
        if not root_url and documents:
            root_url = documents[0].get("source_url") or documents[0].get("url") or ""

    nodes: List[DocumentNode] = []
    url_to_node: Dict[str, DocumentNode] = {}

    for u, d in doc_map.items():
        title = d.get("title") or d.get("page_title") or u
        raw_text = d.get("raw_text") or d.get("markdown") or ""
        chunk_count = d.get("chunk_count", 0)
        metadata = d.get("metadata_json") or d.get("metadata") or {}
        ctas = metadata.get("cta_links", []) if isinstance(metadata, dict) else []

        parsed = urlparse(u)
        path_segments = [s for s in parsed.path.strip("/").split("/") if s]
        depth = len(path_segments)

        entity_type = infer_entity_type(u, title, depth)
        cat_path = extract_category_path(u, title)

        node = DocumentNode(
            url=u,
            title=title,
            entity_type=entity_type,
            depth=depth,
            category_path=cat_path,
            chunk_count=chunk_count,
            character_count=len(raw_text),
            word_count=len(raw_text.split()),
            cta_count=len(ctas),
        )
        url_to_node[u] = node
        nodes.append(node)

    # Establish parent-child links based on URL path hierarchy
    for node in nodes:
        if node.url == root_url or node.depth == 0:
            node.parent_url = None
            continue

        parsed = urlparse(node.url)
        segments = [s for s in parsed.path.strip("/").split("/") if s]
        parent_candidate = None

        # Look for direct prefix ancestor
        for i in range(len(segments) - 1, 0, -1):
            ancestor_path = "/" + "/".join(segments[:i])
            for u in url_to_node:
                if urlparse(u).path.rstrip("/") == ancestor_path:
                    parent_candidate = u
                    break
            if parent_candidate:
                break

        if not parent_candidate and root_url in url_to_node and node.url != root_url:
            parent_candidate = root_url

        node.parent_url = parent_candidate
        if parent_candidate and parent_candidate in url_to_node:
            if node.url not in url_to_node[parent_candidate].child_urls:
                url_to_node[parent_candidate].child_urls.append(node.url)

    # Establish sibling links (nodes with same parent)
    for node in nodes:
        if node.parent_url and node.parent_url in url_to_node:
            siblings = [
                u for u in url_to_node[node.parent_url].child_urls
                if u != node.url
            ]
            node.sibling_urls = siblings

    return nodes


def build_website_coverage_manifest(
    documents: List[Dict[str, Any]],
    root_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Builds a complete Website Knowledge Coverage Manifest containing
    structured statistics, categorized breakdown, and hierarchical tree view.
    """
    nodes = infer_document_relationships(documents, root_url=root_url)

    type_counts: Dict[str, int] = {}
    for n in nodes:
        type_counts[n.entity_type] = type_counts.get(n.entity_type, 0) + 1

    total_chars = sum(n.character_count for n in nodes)
    total_words = sum(n.word_count for n in nodes)
    total_chunks = sum(n.chunk_count for n in nodes)
    total_ctas = sum(n.cta_count for n in nodes)
    max_depth = max((n.depth for n in nodes), default=0)

    # Build hierarchical tree dictionary
    node_map = {n.url: n for n in nodes}
    root_nodes = [n for n in nodes if not n.parent_url]

    def _build_subtree(node: DocumentNode) -> Dict[str, Any]:
        return {
            "title": node.title,
            "url": node.url,
            "entity_type": node.entity_type,
            "depth": node.depth,
            "chunks": node.chunk_count,
            "chars": node.character_count,
            "ctas": node.cta_count,
            "children": [_build_subtree(node_map[child_u]) for child_u in node.child_urls if child_u in node_map],
        }

    tree_roots = [_build_subtree(rn) for rn in root_nodes]
    ascii_tree = render_ascii_coverage_tree(tree_roots)

    return {
        "root_url": root_url,
        "total_documents": len(nodes),
        "total_characters": total_chars,
        "total_words": total_words,
        "total_chunks": total_chunks,
        "total_ctas": total_ctas,
        "max_depth": max_depth,
        "type_breakdown": type_counts,
        "nodes": [asdict(n) for n in nodes],
        "tree": tree_roots,
        "ascii_tree": ascii_tree,
    }


def render_ascii_coverage_tree(tree_roots: List[Dict[str, Any]], indent_prefix: str = "") -> str:
    """Renders a human-readable ASCII representation of the website knowledge tree."""
    lines = []
    for idx, root in enumerate(tree_roots):
        lines.append(f"Website Hub: {root['title']} ({root['url']})")
        lines.extend(_render_children_ascii(root.get("children", []), ""))
    return "\n".join(lines)


def _render_children_ascii(children: List[Dict[str, Any]], prefix: str) -> List[str]:
    lines = []
    count = len(children)
    for idx, child in enumerate(children):
        is_last = (idx == count - 1)
        connector = "└── " if is_last else "├── "
        type_tag = f"[{child['entity_type'].upper()}]"
        chunk_tag = f"({child['chunks']} chunks, {child['chars']} chars)"
        lines.append(f"{prefix}{connector}{type_tag} {child['title']} {chunk_tag}")
        
        sub_prefix = prefix + ("    " if is_last else "│   ")
        if child.get("children"):
            lines.extend(_render_children_ascii(child["children"], sub_prefix))
    return lines
