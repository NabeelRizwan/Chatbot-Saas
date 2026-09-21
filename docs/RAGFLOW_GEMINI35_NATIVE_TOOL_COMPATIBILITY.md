# Gemini 3.5 Flash-Lite native tool compatibility

Date: 2026-09-22. Status: offline repair validated; live gates pending.

## Identities and limits

- Starting development HEAD: 58c1324b1aca0c1f3c91975033d250fbaa91b836.
- Retrieval implementation freeze: 395d46be835610c6228252fee543cc3284b7f776.
- Upstream: RAGFlow v0.27.2 / a024bea0cd93f39e6652a42bf84dd20c55bc560b.
- SDK before/after: google-genai 1.55.0, unchanged.
- Target: ragflow-derived-dev project 068a5695-2cf6-4c7f-89fc-3d24a225e4a5, backend 92349a32-e92d-4795-b86e-338929b03059.
- No production access, main push/merge, quality datasets, ingestion, corpus re-embedding, or retrieval tuning.
- One-shot CREATE-only execution marker; shared hard maximum 10 attempted provider callbacks, including text helpers; SDK retries=1 attempt. Stop immediately on any smoke failure. No second run.

## Offline request and proven defects

The actual medium executor ran with the installed SDK and an HTTP mock; sockets were denied. It traversed action_session → _llm_once_with_tools → _acompletion → DevGemini.async_completion → Gemini35Provider.native_completion. All request headers were excluded, and only a placeholder credential was used.

The complete unmodified pre-repair JSON request body, system instruction, descriptions and six schemas are in [original wire capture](RAGFLOW_GEMINI35_NATIVE_TOOL_ORIGINAL_WIRE.json). This is a deterministic current-code reconstruction with synthetic model planning and fixture evidence, not a recovered byte-for-byte historical live request. The previous failure retained only sanitized HTTP 400 / INVALID_ARGUMENT, not its raw message or body.

Original shape: model gemini-3.5-flash-lite; roles user/model/user/model/user; upstream-generated navigate_tree and retrieve exchanges precede the first native call. Both functionCall parts lack thoughtSignature and id; functionResponse parts lack id. Unchanged upstream system instruction; six function declarations; empty generationConfig; no toolConfig, sampling or thinking overrides. SDK automatic function execution disabled.

First compatibility violation: upstream _emit_nav_pair deliberately records already-executed navigation as synthetic assistant/tool exchanges. The old provider fallback converted these to unsigned Gemini function calls inside the current user turn. Google's current GenerateContent documentation specifies a 400 for missing current-turn call signatures and explicitly documents a marker for client-executed, non-model history. The repair uses that marker **only** for those synthetic exchanges; Gemini-returned parts/signatures are never replaced. [Google thought-signature contract](https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures)

Independent follow-up defects: the old parser replaced every provider ID with a UUID, omitted response IDs, and preserved only individual function-call parts instead of the entire provider Content. The new transport keeps provider IDs, exact names/arguments, all ordered parts and signatures in request-local state, and sends one matching response per call. Unknown tools, unknown response IDs, duplicates, incomplete responses and modified provider turns fail locally. Internal IDs are generated only when the provider omits one, and remain absent on the corresponding provider wire call/response. [Google Gemini 3.5 matching requirements](https://ai.google.dev/gemini-api/docs/whats-new-gemini-3.5)

Historical causality remains an inference until real gates complete: the initial unsigned-history contract defect is proven offline, but the old safe diagnostic cannot identify the provider's original offending field by itself.

## Complete tool inventory

All below originate in pinned advanced_rag/harness/action_session.py, selected by _active_tool_specs / medium ModeSpec. Local port: backend/ragflow_derived/upstream/advanced_rag/harness/action_session.py. No tool definition changed. Full verbatim description and full parameter schema for **each** tool are stored under body.tools[0].functionDeclarations in the wire capture.

| Tool | Required | Properties | Description characters | Source symbol |
|---|---|---|---:|---|
| retrieve | ["query"] | query | 939 | _RETRIEVE_TOOL_SPEC |
| search_chunks | ["query"] | query | 969 | _SEARCH_CHUNKS_TOOL_SPEC |
| list_chunks | ["doc_id"] | doc_id | 848 | _LIST_CHUNKS_TOOL_SPEC |
| navigate_tree | ["query"] | query | 865 | _NAVIGATE_TREE_TOOL_SPEC |
| navigate_structure | ["doc_id"] | doc_id, query, kind | 853 | _NAVIGATE_STRUCTURE_TOOL_SPEC |
| calculate | ["question","facts"] | question, facts | 816 | _CALCULATE_TOOL_SPEC |

Across all six: root object; string properties; string arrays; retrieve minItems=1/maxItems=3; search_chunks minItems=1/maxItems=2; navigate_structure.kind string enum catalog/mindmap/graph; calculate.facts unbounded string array as upstream. No nested object properties, nullability, schema defaults, additionalProperties, anyOf/oneOf/allOf, $ref, title, format, tuple items or other keywords. “Default catalog” is description text, not a JSON default. graph_explore is ultra-only; web_search is absent without a web provider. Both additional registry schemas are covered offline, but not advertised in this medium run.

## Compatibility matrix

The REST FunctionDeclaration supports JSON-schema object parameters, mutually exclusive with parameters; function names are bounded, parameter names constrained. No arbitrary schema rewriting is justified by these actual definitions. [Google GenerateContent API reference](https://ai.google.dev/api/generate-content#FunctionDeclaration)

| Field / feature | Current serialization | Contract / action |
|---|---|---|
| Root object / properties / required | JSON objects, strings and string arrays | Preserve exactly |
| minItems / maxItems / string enum | Present in listed tools | Preserve exactly; validate locally |
| Names / duplicates | Six unique valid names; valid parameter names | Reject malformed/duplicate locally |
| Description | Full upstream text | No published numeric maximum found; no truncation |
| Empty required / zero properties | Canonical smoke only | Preserve; validate live call 1 |
| $ref, composition, nullable unions, tuples | Absent | No conversion needed; reject unvalidated future features rather than delete constraints |
| additionalProperties / defaults / title / format | Absent | Not claimed universally unsupported; current narrow boundary rejects unvalidated features |
| parameters_json_schema | SDK 1.55.0 emits snake-case JSON field | Kept unchanged; actual live declarations will test acceptance |
| toolConfig / allowed names | Omitted | Default automatic selection; no ANY/NONE override |
| automatic_function_calling | SDK disable=True | No SDK auto-loop/tool execution |
| generationConfig | Empty | Defaults; no temperature/candidate count/thinking budget |
| Synthetic functionCall | Missing signature / IDs before fix | Documented client-history marker; pair IDs |
| Provider functionCall / FunctionResponse | IDs replaced / omitted before fix | Preserve ID, name, response pairing |
| Provider Content | Only call parts saved before fix | Preserve complete ordered content out-of-band |

Function-call mode remains the API default; no forced tool policy was introduced. [Google function-calling modes](https://ai.google.dev/gemini-api/docs/function-calling)

Schema conversion result: identity conversion for every actual RAGFlow declaration. A generic fail-closed validator checks the exercised subset; it does not pretend to implement all JSON Schema, and does not discard unsupported keywords.

## Offline validation

- Full isolated suite: **523/523 PASS**, one pre-existing Starlette deprecation warning. Network denied.
- 50 added tests: canonical schemas, all eight registry declarations, invalid schema rejection, IDs/names, parallel results, missing/foreign/duplicate responses, complete signed-part metadata, client history, installed SDK HTTP serialization, credential non-capture, upstream graph serialization and live-runner stop gates.
- Provenance: 171 mapped files / 175 mappings PASS; official upstream blobs verified.
- 13 critical upstream algorithm AST checks PASS.
- Deployment syntax / secret-pattern preflight PASS; git diff --check PASS.
- All 28 pre-existing dirty/ignored preservation files unchanged.
- No changes under backend/ragflow_derived, dependency pins, prompts, scoring, scope, embeddings, reranker, navigation, fanout or context/candidate limits.

## Frozen live sequence (pending)

1. One get_test_value() request.
2. One lookup_test_topic(topic:string) request.
3. One synthetic function response continuation.
4. One request with all six real medium declarations; no dispatch.
5. One existing “How often does Beacon Laboratory calibrate sensors?” medium mechanical executor on full-mechanical v1 only; remainder of the same ten-call budget.

The runner is shipped only in the development image. Its temporary pre-deploy command/gate will be removed after results are captured. The key stays inside Railway; no value is read, logged or downloaded.

## Files in this workstream

Provider: backend/ragflow_dev/gemini35.py; new backend/ragflow_dev/gemini35_tools.py.
Tests: backend/tests_ragflow/test_gemini35_tool_compatibility.py; test_native_wire_capture.py; test_native_compatibility_job.py.
Validation transport: dev/ragflow/native_tool_compatibility.py; Dockerfile.ragflow-dev; Dockerfile.ragflow-dev.dockerignore.
Evidence: this report and RAGFLOW_GEMINI35_NATIVE_TOOL_ORIGINAL_WIRE.json.

## Live results

Pending. No quality acceptance is claimed.
