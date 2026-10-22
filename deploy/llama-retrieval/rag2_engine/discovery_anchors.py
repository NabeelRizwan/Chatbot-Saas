"""Resolve extractive routing witnesses back to indexed original source nodes."""
import hashlib
from llama_index.core.schema import NodeWithScore


def source_anchor_nodes(summary, source_nodes, model_nodes, documents, limit=3):
    """Return source passages behind prose excerpts, never the routing summary.

    A search over a whole page can otherwise lose the exact description that
    made its summary relevant. All anchors still enter the shared reranker;
    none bypass relevance selection or acquire a fabricated relevance score.
    """
    if limit < 0:
        raise ValueError('Anchor limit must be nonnegative.')
    source_id=summary.metadata.get('source_id')
    if source_id not in documents or not summary.metadata.get('discovery_only'):
        return []
    source=documents[source_id]['text']
    if summary.metadata.get('source_sha256') != hashlib.sha256(source.encode()).hexdigest():
        raise ValueError('Discovery source fingerprint does not match the dataset.')
    result,seen=[],set()
    for witness in summary.metadata.get('discovery_witnesses',[]):
        if witness['kind']!='prose':
            continue
        start,end=witness['start_char'],witness['end_char']
        if not 0<=start<end<=len(source) or source[start:end]!=witness['text']:
            raise ValueError('Discovery witness does not match its original source.')
        eligible=[node for node in source_nodes.values() if node.node_id in model_nodes
            and node.metadata.get('source_id')==source_id
            and node.metadata.get('subject_source_id',source_id)==source_id
            and node.metadata.get('evidence_role')!='REVIEW'
            and node.start_char_idx<end and start<node.end_char_idx]
        eligible.sort(key=lambda n:(-min(end,n.end_char_idx)+max(start,n.start_char_idx),n.start_char_idx))
        for raw in eligible[:1]:
            if raw.node_id not in seen and len(result)<limit:
                result.append(NodeWithScore(node=model_nodes[raw.node_id]))
                seen.add(raw.node_id)
    return result


def retain_overview_descriptions(ranked, selected, anchor_groups, max_count):
    """For a routed catalogue overview, retain its exact description passages.

    Document-level retrieval selects these pages. Relevance scoring of a broad
    company question alone can favor repeated brand endorsements over the page's
    description. Round-robin descriptions preserve the requested document view;
    any remaining capacity uses normal selected evidence. Only already-scored
    native nodes are eligible, within the same total core count.
    """
    by_id={item.node.node_id:item for item in ranked}
    groups=[list(ids)[:3] for ids in anchor_groups.values()]
    result,seen=[],set()
    for position in range(3):
        for group in groups:
            if position>=len(group): continue
            node_id=group[position]
            if node_id in by_id and node_id not in seen and len(result)<max_count:
                result.append(by_id[node_id]); seen.add(node_id)
    for item in selected:
        if item.node.node_id not in seen and len(result)<max_count:
            result.append(item); seen.add(item.node.node_id)
    return result
