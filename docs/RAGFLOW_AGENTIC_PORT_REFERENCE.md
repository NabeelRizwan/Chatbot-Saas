# Pinned agentic port reference

Source throughout: RAGFlow v0.27.2, `a024bea0cd93f39e6652a42bf84dd20c55bc560b`.

`engine.research` → `advanced.research` → actual `RAGTools` → `run_agentic_rag` → pinned low/agentic LangGraph. The complete action session, state types, reducers, planner, fanout, review, gap-rewrite and synthesis dependencies are mapped under `backend/ragflow_derived/upstream/advanced_rag`. Import adaptation does not replace those algorithms.

| Entry / stage | Exact upstream location | Adaptation |
| --- | --- | --- |
| Capability bundle | `rag/advanced_rag/agentic_rag.py:RAGTools` | Request-local settings, authorized catalogue, explicit neutral model |
| Executor / stopping | `agentic_rag_graph.py:run_agentic_rag/build_agentic_graph` | Imports only; no graph/transition/prompt tuning |
| Fanout | `agentic_rag_graph.py:_expand_fanouts/_fanout_search` | Actual decomposition/prefetch; no per-intent reservation |
| Research | `harness/action_session.py` | Actual native tool loop and State/Variable; Gemini tool transport only |
| Review / gaps | `harness/orchestrator/sufficient_context.py`, `query_rewriter.py` | Actual JSON/prompt/loop behavior |
| Tools | `harness/tools/search.py`, `navigation.py`, `exploration.py` | Scoped DocStore; explicit missing compiled artifacts |
| Evidence narrowing | `harness/memory.py`, `grep_sed_narrow.py`, `tools/text_processing.py` | Operation-local cache; source text separately retained for citations |
| Mode budget | `harness/config.py` | Exact low/medium/high/ultra defaults; unknown public modes refused |

Low performs direct search without a native tool loop. Medium enables research/review; high adds decomposition/fanout; ultra adds relational tools and deeper upstream budgets. These are not four custom algorithms. Advanced BM25/vector-only tools retain upstream tool-specific defaults. In particular, pinned agentic search does **not** pass a cross-encoder callback to Dealer; the normal and explicit RAPTOR paths still use the unchanged real cross-encoder. Do not describe all modes as using an identical reranker.

Native function calls use one `AuthorizedChatModel` interface. `DevGemini` maps upstream OpenAI-shaped tool messages to Gemini native Content/Part objects without prompt or argument rewriting. Request-local Gemini thought signatures are retained only for the same tool-call identity. Automatic SDK tool execution is disabled. Provider, storage and embedding failures are latched so optional upstream catches cannot turn an infrastructure failure into healthy acceptance.

All tools inherit server-issued organization, bot, generation and READY source/version scope. Model document/node IDs may narrow that authority, never create it. Responses are buffered until validation finishes. The upstream `[ID:n]` final pool order is returned separately from expanded original-source support; generated graph/summary text is explicitly labelled.

Limitations: no external web provider, application SQL, product workflow canvas, distributed worker/task DB, durable cross-request action checkpoint, or persisted conversational memory is claimed. Copied optional wiki/NER/community modules are not proof those operational modes are enabled. See the completeness matrix for exact exclusions.
