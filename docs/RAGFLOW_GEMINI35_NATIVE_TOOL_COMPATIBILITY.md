# Gemini 3.5 Flash-Lite native tool compatibility

Date: 2026-09-22 (local). Status: **native provider compatibility PASS; strict end-to-end model-selected tool-dispatch gate NOT SATISFIED.** No quality acceptance authorized.

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

The incompatible unsigned-history shape is proven offline and the repaired real medium request now succeeds. All six original declarations also pass Gemini unchanged. The old safe diagnostic did not preserve a provider field path, so the historical error body's exact wording cannot be reconstructed; no intentionally broken live request was sent to obtain it.

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

## Frozen live sequence

Provider-transport/instrumentation freeze: **9571d6b9a02eec716eb8d8a099d1409a2e4384c9**. Retrieval implementation remains **395d46be835610c6228252fee543cc3284b7f776**; git comparison confirms no differences in the complete derived engine, dependency pins or upstream manifest. Initial code deployment: f99c1fe7-7d04-4cee-a9f2-49eb2f19613f. Only report changes may follow this freeze; no post-result tuning.

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
Evidence: this report, RAGFLOW_GEMINI35_NATIVE_TOOL_ORIGINAL_WIRE.json and RAGFLOW_GEMINI35_NATIVE_TOOL_LIVE_RESULTS.json.

## Live results

Initial code deployment f99c1fe7-7d04-4cee-a9f2-49eb2f19613f reached SUCCESS at 2026-09-21T19:40:12Z; HTTP health verified, native models healthy, provider startup calls zero.

One-shot job deployment: **d54f8abe-822b-4f13-a666-a3705f1a4e5e**, report-only commit **36f28cd6502858f0023aed258009733871f83e5f**. Job started 2026-09-21T19:43:06Z; terminal result logged 19:43:22Z. Measured task body: **15.019017726182938 seconds**. **9/10** generateContent attempts, **11,916** reported total tokens; no retries, no additional call after the gate assertion.

| Call | Path | Result | Callback seconds |
|---:|---|---|---:|
| 1 | get_test_value, canonical zero-arg schema | PASS; provider tool call returned | 0.6243730187416077 |
| 2 | lookup_test_topic(topic:string) | PASS; exact requested argument | 0.5840935558080673 |
| 3 | Matching synthetic FunctionResponse | PASS; final text, no extra tool | 0.7274793237447739 |
| 4 | All six original medium declarations | PASS; retrieve returned, intentionally not dispatched | 0.581432405859232 |
| 5 | Mechanical graph text callback | PASS | 0.5818613544106483 |
| 6 | Mechanical graph text callback | PASS | 0.8337067924439907 |
| 7 | Mechanical native turn, including nav_locate/nav_global history | PASS; answer returned, no model-selected calls | 1.0135357454419136 |
| 8 | Mechanical graph text callback | PASS | 1.1621445007622242 |
| 9 | Mechanical graph text callback | PASS | 0.5994196310639381 |

Call 2's provider ID was retained through call 3; one signature-bearing provider part was present and preserved. The returned continuation was: “The result of calling `lookup_test_topic` for the topic \"calibration\" is: `{\"value\":\"synthetic-ok\"}`”. Complete opaque signature bytes were not logged or saved in the report. Parallel and non-call metadata preservation passed offline, not an additional live parallel test.

### Mechanical result and exact remaining gap

Question: “How often does Beacon Laboratory calibrate sensors?”

Answer: **“Beacon Laboratory calibrates sensors every seven days [ID:0].”**

Actual medium graph completed, verdict **SUFFICIENT**, with exact original supporting evidence from **full-mechanical v1 / doc-full-mechanical**. The repaired native turn accepted upstream client-generated navigation history. Three candidate observations and one parent relationship were scoped to synthetic-org-a / synthetic-bot-a / native-v1; READY and source text hashes verified; dropped events zero. Both tenants' source-authority inventories were identical before/after.

However, that navigation prefix already supplied the answer. At **action_session._run_action_node**, `_parse_tool_calls(msg)` returned an empty list and `_parse_terminal` selected the terminal answer path. No model-selected call entered `_tool_node`. The independent declaration smoke's retrieve call was not dispatched, as instructed.

Therefore the strict requirement **Gemini call → actual RAGFlow dispatch → FunctionResponse → continuation in the same mechanical graph** was **not exercised**. The runner correctly marked the mechanical acceptance gate FAIL with its `NO_MODEL_SELECTED_TOOL_CYCLE` assertion after the successful graph result. The artifact's category UNKNOWN / exception OTHER is that local assertion, **not a Gemini transport error**. No remaining provider rejection was observed; there is no evidence here justifying another retrieval or prompt change.

No rerun, forced-tool override, extra question, or use of the remaining one-call allowance. SAME8, HOLDOUT_B, HOLDOUT_C, old90 and GOLD were not run. Quality validation remains gated until a separately authorized mechanical scenario naturally exercises model-selected dispatch.

### Durable evidence and cleanup

[Live evidence envelope](RAGFLOW_GEMINI35_NATIVE_TOOL_LIVE_RESULTS.json) contains the complete non-secret result and observed events, gzip/base64 encoded. Decoded SHA-256: **edb9a18454dd8b4a12361dc3904bdd6a45a47fa6969eada980c34b981405e2ad**, verified against the job output. The full source evidence is synthetic only.

Temporary preDeployCommand cleared to []; RAGFLOW_DEV_NATIVE_TOOL_VALIDATION set to DISABLED_AFTER_ONE_SHOT. The CREATE-only run marker remains intentionally, preventing replay. SDK connections were closed; the process-only key reference was removed from the job environment. The existing authorized key remains solely in development Railway Variables; no secret value, header or credential was downloaded or persisted locally. No corpus/source/vector writes occurred.

### Final requested verdict

- ROOT TOOL-COMPATIBILITY CAUSE: PROVEN contract defects; original raw provider error not retained.
- INCOMPATIBLE FIELDS: unsigned synthetic functionCall history; replaced provider IDs / omitted FunctionResponse.id; incomplete provider Content preservation. No incompatible actual tool schema found.
- SDK: 1.55.0 → 1.55.0.
- MINIMAL ZERO-ARG TOOL: PASS.
- PARAMETERIZED TOOL: PASS.
- FUNCTION RESPONSE ROUND TRIP: PASS.
- GEMINI CALL ID PRESERVATION: PASS.
- THOUGHT SIGNATURE / PROVIDER METADATA: PASS (live simple cycle plus offline complete-part/parallel tests).
- RAGFLOW TOOL SCHEMA CONVERSION: PASS, identity conversion; no semantic rewrite.
- ACTUAL RAGFLOW TOOL DECLARATIONS: PASS.
- AGENTIC MECHANICAL EXECUTOR: FAIL the specified full-cycle acceptance gate; graph execution and grounded answer PASS.
- MODEL CALLS: 9 / 10 maximum.
- OFFLINE TESTS: 523/523.
- RETRIEVAL LOGIC / RAGFLOW PROMPTS / THRESHOLD CHANGED: NO.
- QUALITY DATASETS: NOT RUN.
- PRODUCTION PROJECT TOUCHED: NO.
- NEXT STEP: separately authorize a mechanical test that naturally requires a model-selected tool dispatch. Do not resume quality sets yet; no remaining provider failure was reproduced.
