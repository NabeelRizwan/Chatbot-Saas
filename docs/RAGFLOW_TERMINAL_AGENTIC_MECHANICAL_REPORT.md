# Terminal-completion mechanical follow-up

## Frozen scope

- Date: 2026-09-22 (local timezone).
- Starting HEAD: `9c5fcc3089c75393a1661930600ada267023b305`.
- Branch/project: `ragflow-derived-dev` only.
- Railway project: `068a5695-2cf6-4c7f-89fc-3d24a225e4a5`.
- Retrieval freeze: `395d46be835610c6228252fee543cc3284b7f776`.
- Provider compatibility freeze: `9571d6b9a02eec716eb8d8a099d1409a2e4384c9`.
- Upstream: RAGFlow v0.27.2 / `a024bea0cd93f39e6652a42bf84dd20c55bc560b`.
- Gemini: `gemini-3.5-flash-lite`; google-genai `1.55.0`.

The sole execution-policy change is the test callback ceiling: **6 → 8**.
The original six-call runner, fixture, question, source, provider adapter,
RAGFlow code/prompts, retrieval parameters and stopping conditions are unchanged.
The new entry point reads the existing fixture rather than ingesting anything.
It uses a new CREATE-only marker:
`model-selected-dispatch-terminal-2026-09-22-v2`; the old marker is retained.

## Pre-model integrity gates

- Compare 192 frozen files against their bytes in the prior executed commit
  `b9d962197570c2f953c3e1e54b412a9386bf734a`.
- Verify exact question bytes and fixture file hash against the saved old result.
- Re-fetch all seven original records through the real authorized upstream
  `list_chunks` tool; compare complete records with the prior saved provenance.
- Repeat the three navigation probes without any model callback; refuse answer
  leakage before enabling Gemini. Retain the actual first-action leak guard.
- Compare existing source/vector inventory digests before/after the run and all
  source authority records; no ingestion, embedding or fixture mutation.
- Preserve old result SHA-256:
  `3c02de1ab01a2bebf7faeb60e055f8156822a62d86a0b17a752267cc5638e317`.

Question, unchanged:

> What release phrase does the Northbridge Equipment Manual require for an emergency battery handoff?

## Observation and terminal definition

The previous forwarding/dispatch recorder is reused. Additional observation
records stable per-request ordinals, completed text/native responses, safe graph
fields, and the next upstream function stack if the eight-call gate stops the
run. It never modifies inputs, outputs, scores, candidates or graph state.

Normal **outer** completion is assessed from return of the actual full graph,
original supporting evidence, final answer and resolved final citation. An inner
action session's `<state>` patch is not itself failure: the frozen outer graph
can normally proceed through draft, sufficient-context review and final synthesis
after such a patch. No upstream stopping condition is changed or bypassed.

## Offline validation

- **84/84 focused tests PASS**: new terminal harness, previous mechanical runner,
  Gemini tool wire compatibility and actual medium/agentic graph tests.
- Socket access denied; no live provider calls during implementation/tests.
- New harness tests: 15 PASS, including the preserved artifact, 192 Git-blob
  hashes, exact-record refusal checks, eight-call stop, inherited fail-stop/leak
  guards and identical direct-versus-observed native requests/results.
- `git diff --check`: PASS.
- No diff in retrieval/provider/upstream source or the existing fixture/runner.

## Live result — FAIL: authorized ceiling reached

- Executed harness commit: `991096b123e3e8d803aa3d90fdeaabd6a9ece38c`.
- One-shot deployment: `7e2ada1b-c482-48fd-b759-5bbb3c38bacd`.
- Preflight: **PASS before any Gemini call**. All 192 frozen files and all seven
  original evidence records matched. Fixture/question/answer bytes were unchanged.
- Initial navigation/action answer leak: **NO**. The live automatic navigation
  payloads also contained only references, not the answer phrase.
- Exactly one medium graph, **8/8 Gemini calls**, **0 provider failures**.
- Reported provider tokens: **26,756**.
- Total job time including preflight: **13.206574256997555 seconds**.
- Stop: **EIGHT_CALL_CEILING**, before a ninth provider request.
- No final answer, final citation, completed SCA review, or full graph return.

### Actual model-call sequence

The ordinals below are recorded at callback entry and stay distinct for
concurrent requests; they are not the older completion-counter snapshots.

| Call | Actual operation / response |
| --- | --- |
| 1 | Question formalization; same entity and requested release phrase |
| 2 | Initialization produced two slots: `dataset` and `web` |
| 3 | First slot selected `navigate_structure` for appendix RB742 |
| 4 | Second parallel slot selected `navigate_structure` for the same appendix |
| 5 | Selected `retrieve`, queries `RB742` and `emergency battery handoff release phrase` |
| 6 | Other slot selected `retrieve`, queries `appendix entry RB742` and `RB742` |
| 7 | Continued after FunctionResponse; state patch supplied the exact phrase at strength 1.0 |
| 8 | Other slot continued after FunctionResponse; state patch supplied the exact phrase at strength 0.99 |

Both `navigate_structure` calls executed normally and reported `no_structure`.
Both retrieve calls dispatched through the actual `_tool_node` into real scoped
Elasticsearch. One returned status `ok`; the other reported `redundant` because
its evidence was already in the shared pool. Both returned the original RB742
answer record. This redundant work is recorded, not hidden as extra recall.

Native FunctionCalls were recognized by `_parse_tool_calls`. Matching
FunctionResponses were sent back and accepted by Gemini; IDs, names and complete
provider Content/signature metadata were preserved. No opaque signature bytes
are included in either report or saved trace. No tool-selection mode was forced.

### Exact graph state and first blocked decision

At the eight-call boundary:

- Slot 0 and slot 1 both held **copper orchard at dusk**; the merged strengths
  were 1.00, with original answer-chunk evidence IDs attached.
- `unresolved_slots = []`.
- `search_rounds = 0`.
- `current_queries = []`.
- `collected_answer = null`: these were action-session **state patches**, not
  an already-composed final answer.
- The outer graph had rendered the slot draft with the exact phrase and sources.
- No sufficient-context verdict had been produced yet.

The **next upstream node was `sca`**, at `agentic_rag_graph.py:1088`, calling
`sufficient_context_agent` at `sufficient_context.py:282`. The existing function
was requesting its normal `gen_json` review callback. The test-only gate refused
this ninth call before model access.

Another call was therefore expected by the **normal upstream workflow**. Final
synthesis (`formalize_answer`) would still follow the review/routing decision;
its output and total eventual call count cannot be claimed without execution.

There is **no evidence of a repeated SCA/rewrite loop** in this attempt:
`search_rounds` remained zero, both slots resolved, and the graph progressed to
its first SCA review. The duplicated navigation/retrieval came from two parallel
planned slots, not an unbounded loop. The model's `web` slot label did not grant
web access: no web tool or external web retrieval executed.

### Gate results

| Gate | Result |
| --- | --- |
| Existing fixture, question, original answer and frozen code identical | PASS |
| Initial answer absent | PASS |
| Model-selected tools, actual parser and tool dispatch | PASS |
| Real Elasticsearch retrieval of missing record | PASS |
| FunctionResponse and Gemini continuation | PASS |
| Provider IDs/signatures/metadata preservation | PASS |
| Tenant/source/version/generation scope | PASS |
| Normal terminal outer graph | **FAIL — callback ceiling** |
| Grounded final answer | **FAIL — not produced** |
| Final citation | **FAIL — not produced** |

## Original provenance and preservation

- Organization: `synthetic-org-a`.
- Bot: `synthetic-bot-a`.
- Source: `mechanical-dispatch-northbridge-v1`.
- Document: `doc-mechanical-dispatch-northbridge-v1`.
- Version: `1`; generation: `native-v1`.
- Answer chunk: `8c274cc20dc2f87a2bbae5e411c98603b49694f2bc0356e51aefa32ec200ee6d`.
- Exact original text: `{"entry": "RB742", "value": "copper orchard at dusk"}`.
- Original text SHA-256: `50aa3b6998b3ada9c545722f0e15d20ccbcdf0cdb8f01d086eed4feab262a3d6`.
- Saved live observation: **111 authorized-candidate events**, zero dropped
  events; every event matched the permitted original fixture's scope and hash.
- No foreign, stale or unauthorized candidate was observed.
- Complete stored-row/vector digest before and after:
  `cb38543945cd3199d1550a7c8adcbecf397bf250c2b04048bce7bbee9420e53d`.
- All source authority records unchanged; prior six-call marker unchanged.
- No ingestion, source/chunk/metadata/structure write, or embedding operation.

Saved result: `RAGFLOW_TERMINAL_AGENTIC_LIVE_RESULTS.json` (gzip/base64 envelope).
Decoded SHA-256:
`0a6ab04cbfc621bb4f13cd74dacc949a7b15ed9db03767dafc19e95100a66fb9`.
The old six-call result/report remain intact alongside this follow-up result.

## Cleanup and final decision

The temporary pre-deploy command was removed and the new trigger set to
`DISABLED_AFTER_ONE_SHOT`. The new durable marker remains; the old marker was
neither deleted nor bypassed. Connections closed and the process key environment
entry was cleared. No secret was downloaded or persisted.

No automatic ceiling increase, second attempt, post-result tuning, or further
Gemini call. No retrieval/provider/RAGFlow/prompt change. No main merge/push or
production project access. SAME8 / HOLDOUT_B / HOLDOUT_C / old90 / GOLD: NOT RUN.

**TERMINAL AGENTIC MECHANICAL ACCEPTANCE: FAIL.** The remaining gap is normal SCA
review followed by final answer synthesis and original-source citation. Those
stages were not completed within the authorized eight calls. Quality evaluation
remains unstarted; no tuning is proposed or performed.
