# Model-selected RAGFlow dispatch — single mechanical test

## Freeze and authorization

- Date: 2026-09-22.
- Development project only: `ragflow-derived-dev` / `068a5695-2cf6-4c7f-89fc-3d24a225e4a5`.
- Branch: `ragflow-derived-dev`; starting HEAD: `ec7dd4535eff1dede45d6ddf59f76eb48cb39d42`.
- Retrieval implementation freeze: `395d46be835610c6228252fee543cc3284b7f776`.
- Provider compatibility freeze: `9571d6b9a02eec716eb8d8a099d1409a2e4384c9`.
- Upstream: RAGFlow v0.27.2, `a024bea0cd93f39e6652a42bf84dd20c55bc560b`.
- Model/SDK: Gemini 3.5 Flash-Lite / google-genai 1.55.0, unchanged.
- No provider adapter, retrieval code, upstream prompts, tool schemas, graph, ranking, thresholds, blend or limits changed.

## New fixture and one-shot job

The normal JSONL parser produces seven separate original chunks. Six synthetic
manual index/checklist entries reference appendix record RB742 without giving its
value; the seventh contains that record's arbitrary phrase. New source identity:
`mechanical-dispatch-northbridge-v1`, never a quality-set source.

Frozen question:

> What release phrase does the Northbridge Equipment Manual require for an emergency battery handoff?

Before constructing any Gemini callback, the job ingests the new source normally,
runs the real upstream navigation prefix against real scoped storage for the
question and two shorter document/procedure directions, and refuses leaked or
empty initial evidence. A separate clean `list_chunks` tool operation proves the
original answer is reachable and validates exact source/version/text hashes.
Those preflight tool results never enter the live graph's request-local state.

The full graph retains model-generated planning directions. Therefore the job
also checks the **actual first action messages** before that native request; it
does not assume the preflight directions exhaust every possible model rewrite.
Earlier model inputs are checked for answer injection too. Any leak aborts.

One normal medium graph is permitted, with a shared six-call ceiling including
text planning/review/synthesis. Native selection remains upstream AUTO/default;
there is no tool-selection instruction or forced function configuration.
Provider failure, no first model-selected tool, or budget exhaustion stops the
job without retry. A CREATE-only durable marker prevents duplicate execution.

The isolated job records `_parse_tool_calls`, real `_tool_node` dispatch,
returned evidence, a read-only copy of wire pairing/metadata checks, terminal
parsing, and final citation provenance. Opaque signatures are never recorded.
Wrappers are restored in `finally`; application code is untouched.

## Offline validation

- RAGFlow suite: **535/535 PASS**, socket access blocked, zero provider calls.
- New focused tests: **12/12 PASS**.
- Direct-versus-observed SDK requests/results: identical.
- Actual offline medium graph with/without dispatch observation: identical
  answer, evidence, citations, verdict and mode.
- Fixture parser, preflight provider ban, answer-leak guards, six-call ceiling,
  no-selection/provider-failure stop, metadata pairing, wrapper cleanup: PASS.
- `git diff --check`: PASS.
- Retrieval/provider runtime directories match starting HEAD exactly.

## Live result — strict FAIL, no rerun

- Observation/fixture commit: `b9d962197570c2f953c3e1e54b412a9386bf734a`.
- One-shot deployment: `584e39b5-5dbe-4f5c-831d-3c2183f5619b`.
- Three real prefix probes: PASS **before any Gemini call**; each returned
  authorized index/checklist chunks without the answer.
- Separate actual `list_chunks` preflight: PASS; all seven original chunks
  reachable, source/version/generation and text hashes validated.
- Actual first action context: answer absent. The two live slot navigation
  prefixes also returned only index/checklist references to RB742.
- Exactly one medium graph, **6/6 Gemini calls**, zero provider failures.
- Reported provider token total: **17,829**.
- Stop reason: **SIX_CALL_CEILING**. No seventh call, no retry, no tuning.
- Total job time including ingestion/preflight: **22.554945409297943 seconds**.

### Actual graph sequence

1. Normal question formalization and slot initialization consumed two text calls.
2. The unchanged graph generated two research directions and ran two initial
   action calls concurrently: `release phrase` and
   `Northbridge Equipment Manual emergency battery handoff protocol`.
3. One native response selected `navigate_structure` with
   `{"doc_id":"doc-mechanical-dispatch-northbridge-v1","query":"RB742"}`.
   `_parse_tool_calls` recognized it and the actual `_tool_node` dispatched it.
   Storage correctly reported no compiled catalog structure. The other initial
   response supplied a state patch identifying RB742, not the missing phrase.
4. After the matching FunctionResponse, Gemini selected `retrieve` with
   `{"query":["RB742","appendix entry RB742"]}`. The actual `_tool_node`
   returned the original answer record from real scoped Elasticsearch.
5. Gemini received that real FunctionResponse and continued with a state patch
   whose candidate was **“copper orchard at dusk”**. The native round trips
   preserved provider call IDs, names and complete signed Content metadata.
   The trace records preservation booleans, never signature bytes.
6. The graph needed another model call to finish. The harness stopped before
   exceeding the authorized six-call ceiling. There is **no completed final
   answer or final citation**, and no normal answer terminal to accept.

### Completed coverage versus missing coverage

| Gate | Result |
| --- | --- |
| Initial navigation omits answer | PASS |
| Model-selected FunctionCall and parser recognition | PASS |
| Actual upstream tool dispatch | PASS |
| Real storage retrieves missing original fact | PASS |
| Authorized source/document/version/generation | PASS for observed evidence |
| FunctionResponse pairing and complete provider metadata | PASS |
| Gemini continuation incorporating returned fact | PASS |
| Normal terminal full graph | **FAIL — ceiling stop** |
| Grounded final answer | **FAIL — not produced** |
| Final citation/provenance | **FAIL — final citation not produced** |

Original retrieved answer chunk:
`8c274cc20dc2f87a2bbae5e411c98603b49694f2bc0356e51aefa32ec200ee6d`,
source `mechanical-dispatch-northbridge-v1`, document
`doc-mechanical-dispatch-northbridge-v1`, version `1`, generation `native-v1`,
organization `synthetic-org-a`, bot `synthetic-bot-a`.

Exact original text:

```json
{"entry": "RB742", "value": "copper orchard at dusk"}
```

Saved gzip/base64 trace: `RAGFLOW_MODEL_SELECTED_DISPATCH_LIVE_RESULTS.json`.
Decoded result SHA-256:
`3c02de1ab01a2bebf7faeb60e055f8156822a62d86a0b17a752267cc5638e317`.

The live tool evidence IDs all map to the already validated original seven-row
fixture. Other source authority records remained unchanged. No existing corpus
source was replaced. Only the new fixture was embedded through normal CPU MiniLM
ingestion; no existing corpus was re-embedded and no embedding API was called.

### Trace limitations and interpretation

The recorder stores shared call/sequence counters when requests complete. The
two concurrent initial action requests therefore both show completion counter
`4` and sequence snapshot `2`; these labels are **not** unique call ordinals.
There were two text and four native transport calls, totaling six. This report
does not infer which concurrent initial native request reached Gemini first.
Exact dispatch/FunctionResponse IDs establish the subsequent causal chain.

Because the graph was aborted before `Runtime.advanced` returned, its final
aggregate result/observation/citation pool was not emitted. Preflight original
provenance, real tool dispatch payloads and provider round trips remain saved;
they do not substitute for an accepted terminal answer. No instrumentation or
implementation was changed after observing the result.

The native state patch used the wording “web/corpus retrieval”; no web tool ran.
Only development Elasticsearch retrieval executed. That intermediate wording
is not presented as an evaluated final answer.

## Cleanup and next step

The temporary pre-deploy command was cleared and
`RAGFLOW_DEV_DISPATCH_VALIDATION` set to `DISABLED_AFTER_ONE_SHOT`. The durable
CREATE-only marker remains to prevent replay. Connections closed and the job's
key environment entry was cleared; no key was downloaded, logged or saved.

All 28 pre-existing saved dirty/ignored work files remain unchanged. Main was
neither merged nor pushed; changes/deployment belong only to the development
branch/project. No SAME8, HOLDOUT_B, HOLDOUT_C, old90 or GOLD ran.

**The full mechanical gate is not accepted.** A separately authorized follow-up
would be needed to demonstrate normal full-graph termination and final grounded
citation after the now-proven model-selected tool round trip. Do not resume the
quality datasets under this result.
