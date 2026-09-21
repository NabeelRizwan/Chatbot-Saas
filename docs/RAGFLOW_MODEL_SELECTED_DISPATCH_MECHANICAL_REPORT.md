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

## Live result

Pending one-shot development execution. No acceptance claimed yet.
No SAME8, HOLDOUT_B, HOLDOUT_C, old90 or GOLD executed in this task.
