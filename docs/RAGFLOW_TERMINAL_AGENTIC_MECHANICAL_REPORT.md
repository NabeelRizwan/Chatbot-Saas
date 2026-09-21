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

## Live result

Pending the single authorized eight-call run. No acceptance claimed yet.
SAME8 / HOLDOUT_B / HOLDOUT_C / old90 / GOLD: NOT RUN.
