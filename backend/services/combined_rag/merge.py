# Adapted from LangChain MergerRetriever.merge_documents (MIT).
# Pinned commit d7508191bcf2af823ad8a168a15772710de5592b.
# Full upstream source/license and hashes are retained in vendor/.
"""Upstream round-robin loop applied to already retrieved, ranked source IDs."""


def interleave(lanes):
    merged_documents = []
    max_docs = max(map(len, lanes), default=0)
    for i in range(max_docs):
        for doc in lanes:
            if i < len(doc):
                merged_documents.append(doc[i])
    return list(dict.fromkeys(merged_documents))
