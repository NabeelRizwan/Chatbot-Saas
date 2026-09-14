# Phase 3.6 adaptation ledger

Source inspected before implementation, 2026-09-13. Conceptual adaptations only;
no source copied, package installed, framework adopted, or extra model call added.

| Project / license | Pinned source studied | Used here / deliberately not used |
|---|---|---|
| LlamaIndex / MIT | [PrevNextNodePostprocessor, forward/backward node traversal](https://github.com/run-llama/llama_index/blob/7169bcd0dca2e16aecc8e0247f34e50079d9c0d5/llama-index-core/llama_index/core/postprocessor/node.py) | Bound adjacency by source identity and sequence; keep dependent content together. No automatic model-directed expansion or new document-store lookup. |
| Haystack / Apache-2.0 | [SentenceWindowRetriever, run / merge_documents_text](https://github.com/deepset-ai/haystack/blob/9872f764f16913f6919eddd955c25c78554bc00a/haystack/components/retrievers/sentence_window_retriever.py) | Preserve ordered source windows and attribution, avoid duplicate context. Reuse already authorized chunk rows, not a parallel retrieval system. |
| RAGFlow / Apache-2.0 | [Dealer.insert_citations / fetch_chunk_vectors](https://github.com/infiniflow/ragflow/blob/b19a10fb70c64a2a0e29c4a3d20eaa90b969c3b9/rag/nlp/search.py) | Final citation candidates remain restricted to supplied source identities. Do not adopt answer re-embedding, similarity thresholds, its index backend, or additional network calls. |

License files were checked at those same commits. These upstream implementations
do not themselves prove a resource × requested-field obligation is complete.
The local adaptation reserves bounded field bundles ahead of existing selection
caps and carries their source identities through the current pipeline.

Local bounds remain: 8 resolved resources × 12 requested fields; existing
four-chunk ordered section plus one FAQ maximum, three ordinary list chunks;
existing reviewer, document and final-context budgets. Explicit caller limits
are honored. Numeric compatibility is a constraint, not an identity score:
omitted numerals never override specificity, ambiguity or authorization gates.
