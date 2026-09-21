# Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
# Licensed under the Apache License, Version 2.0.
# Modified for Chatbot-SaaS: explicit scoped imports; see port manifest.
import json
import logging
from collections import defaultdict
from ragflow_derived.upstream.prompts.generator import gen_json
from ragflow_derived.upstream.advanced_rag.knowlege_compile._common import knowledge_compile_gen_conf

def raptor_tree_to_graph(tree: dict) -> dict:
    """Project a RAPTOR tree dict (from ``Raptor(is_tree=True)``) onto
    the ``{entities, relations}`` shape the document-structure graph
    endpoint already serves for ``page_index``-kind rows."""
    entities: list[dict] = []
    relations: list[dict] = []

    def _collapse_unary(node: dict) -> dict:
        """Collapse tree nodes that only wrap one child."""
        collapsed = dict(node)
        collapsed["children"] = [_collapse_unary(child) for child in node.get("children") or [] if isinstance(child, dict)]

        while len(collapsed["children"]) == 1:
            child = collapsed["children"][0]
            parent_title = collapsed.get("title") or ""
            child_title = child.get("title") or ""
            parent_description = collapsed.get("description") or parent_title
            child_description = child.get("description") or child_title

            descriptions = [str(parent_description)]
            if child_title and child_title != parent_title and child_title not in child_description:
                descriptions.append(str(child_title))
            if child_description and child_description not in descriptions:
                descriptions.append(str(child_description))

            source_chunk_ids = []
            for source in (collapsed.get("source_chunk_ids") or [], child.get("source_chunk_ids") or []):
                for chunk_id in source:
                    if isinstance(chunk_id, str) and chunk_id and chunk_id not in source_chunk_ids:
                        source_chunk_ids.append(chunk_id)

            collapsed["description"] = "\n\n".join(descriptions)
            if source_chunk_ids:
                collapsed["source_chunk_ids"] = source_chunk_ids
            collapsed["children"] = child.get("children") or []

        return collapsed

    tree = _collapse_unary(tree) if isinstance(tree, dict) else tree

    def _walk(node: dict, parent_id: str | None) -> None:
        if not isinstance(node, dict):
            return
        title = node.get("title") or ""
        node_id = title
        ent: dict = {
            "name": node_id,
            "type": "tree_node",
            "description": node.get("description", title),
            "mention_count": 1,
        }
        src_ids = node.get("source_chunk_ids")
        if isinstance(src_ids, list) and src_ids:
            ent["source_chunk_ids"] = [s for s in src_ids if isinstance(s, str) and s]
        entities.append(ent)
        # A summary and its child can occasionally receive the same LLM-generated
        # title. They are still valid tree nodes, but must not become a self-loop
        # when the tree is projected to graph relations.
        if parent_id is not None and parent_id != node_id:
            relations.append({"from": parent_id, "to": node_id, "type": "child"})
        for child in node.get("children") or []:
            _walk(child, node_id)

    _walk(tree, None)
    return {"entities": entities, "relations": relations}

async def rewrite_duplicate_tree_names(tree: dict, chat_mdl) -> None:
    """Rewrite only duplicate tree titles whose descriptions differ."""
    from ragflow_derived.upstream.advanced_rag.knowlege_compile._common import knowledge_compile_gen_conf
    from ragflow_derived.upstream.prompts.generator import gen_json

    groups: dict[str, list[tuple[dict, str, str]]] = {}

    def _walk(node: dict, path: tuple[int, ...]) -> None:
        if not isinstance(node, dict):
            return
        title = str(node.get("title") or "").strip()
        if title:
            description = str(node.get("description") or title).strip()
            node_key = ".".join(str(index) for index in path)
            groups.setdefault(title, []).append((node, node_key, description))
        for index, child in enumerate(node.get("children") or []):
            _walk(child, (*path, index))

    _walk(tree, (0,))
    for title, candidates in groups.items():
        descriptions = {description for _, _, description in candidates}
        if len(candidates) < 2 or len(descriptions) < 2:
            continue

        items = [{"id": node_key, "description": description} for _, node_key, description in candidates]
        prompt = (
            "The following tree nodes currently have the same title but describe different content. "
            "Give each node a concise, distinct human-readable title. Preserve the original language, "
            "do not add numbering unless necessary, and return only a JSON array of objects with the "
            "same ids and a name field.\n\n"
            f"Current title: {title}\n"
            f"Nodes: {json.dumps(items, ensure_ascii=False)}"
        )
        try:
            result = await gen_json(
                "You rename duplicate tree node titles for display.",
                prompt,
                chat_mdl,
                gen_conf=knowledge_compile_gen_conf(chat_mdl, {"temperature": 0.0}),
            )
        except Exception:
            logging.exception("tree-template: duplicate title rewrite failed for title=%s", title)
            continue

        rewrites = {}
        if isinstance(result, list):
            rewrites = {str(item.get("id")): str(item.get("name")).strip() for item in result if isinstance(item, dict) and item.get("id") and str(item.get("name") or "").strip()}
        for node, node_key, _ in candidates:
            new_title = rewrites.get(node_key)
            if new_title:
                node["title"] = new_title

    # The LLM is asked to produce distinct names, but enforce that contract
    # deterministically before the graph uses titles as relation endpoints.
    used_names: dict[str, int] = {}

    def _ensure_unique(node: dict) -> None:
        if not isinstance(node, dict):
            return
        title = str(node.get("title") or "").strip()
        if title:
            occurrence = used_names.get(title, 0) + 1
            used_names[title] = occurrence
            if occurrence > 1:
                node["title"] = f"{title} ({occurrence})"
        for child in node.get("children") or []:
            _ensure_unique(child)

    _ensure_unique(tree)
