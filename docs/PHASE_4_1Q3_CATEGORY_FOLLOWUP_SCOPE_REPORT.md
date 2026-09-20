# Phase 4.1Q3 — Category / Follow-up Scope Repair

## Status

**Q3 STATUS: ACCEPT — semantic scope repair only.** All offline and targeted gates pass. Scope misses are **4 → 0**; no old Q1-supported obligation or required document is lost. This does **not** mean four new materialized hits: the same four obligations now fail later, at unchanged byte allocation (two) or channel recall (two).

Validation date: 2026-09-21 Asia/Calcutta (2026-09-20 UTC). Retrieval has stopped; connections closed and process-only credential removed. A single local-only Q3 checkpoint is authorized; no push or deployment.

Accepted Q1 checkpoint: `fd2178602dc74352dd93219c50012d320685a6e5` (main).
Q1 materialized support remains the accepted **89/109**, required-document recall **91/109**.
Q2A and Q2B remain rejected, untracked experiments. Neither allocator is imported or adopted.
No packing, channel, query, vector, GOLD, byte-cap, unit-cap, tenant predicate or production change.

## Proven defect and narrow correction

`resource_probe_builder.build_resource_probes` did not recognize the existential category grammar in case 53. Its relative-clause “that” could take the conversation-reference path even with empty history. `resource_scope_adapter.apply_resource_discovery` then treated its unique category identity as a specific entity (`category_intent=False`). `choose_scope_strategy` applied `resolved_single → confident_single_resource → EXACT_SCOPED [13]`. Case 54 inherited the same identity without retaining the preceding set-discovery intent. Documents 25 and 29 were excluded semantically, despite membership in the server-authorized set.

The additive `preserve_discovery_scope` handoff runs in `rag_planning.prepare_query` **after** resolution and **before** field-obligation binding. It only revisits an already proven exact scope. It recognizes bounded, anchored plural discovery grammar where the requested set noun matches the resolved canonical name/alias. That identity remains an unmodified routing hint, not exclusive evidence scope. Complete short deictic/comparative follow-ups can inherit discovery from the most recent relevant **user** turn within eight history messages, with the same nonempty topic-to-identity binding; assistant text cannot establish it. An intervening explicit request stops inheritance. A field set such as discounts **for** a named item is not treated as a resource set in either the original turn or its follow-up.

It reruns the existing scope policy/security checks before using its existing `broad_request` path. The identical `HardKnowledgeScope` object remains authoritative: `None` semantic IDs mean all of this hard scope, never all database documents. Resolved identities, candidate proofs, query text, vectors and requested fields are unchanged. The new decision/reason already participates in the execution/cache identity.

English grammar is deliberately conservative: at most 2,000 characters per discovery turn, a 160-character noun phrase, plural set grammar, and full short-follow-up matching. A collection title alone does not imply discovery. Field questions such as “any reviews of X” and “any discounts for X” do not broaden X. No benchmark IDs, product names, GOLD, expected documents or ontology-specific nouns occur in policy code.

## Pre-fix reproduction / focused validation

Two actual `prepare_query → resource catalog → scope adapter` tests with a synthetic course collection failed on the untouched baseline: both the discovery question and “Which one?” returned `EXACT_SCOPED` instead of broad-authorized. Both pass after the change. SQLite FTS/trigram approximations in the existing fixture are explicitly offline surrogates; the identity SQL, catalog, proof, adapter and final handoff execute actual runtime code.

- Focused suite: **283/283 PASS** (20 initial Q3 tests plus scoped-RAG, resource discovery/safety, probe/history, canary-security and compact-packing regressions).
- Intermediate Q3 and Q1 wrapper tests: **31/31 PASS**.
- Final complete focused selection on final code: **296/296 PASS**, 80.476 s, including **25 Q3 tests**. Earlier overlapping runs are not additional unique tests.
- Syntax/import checks and whitespace review: PASS.
- The canonical offline runner now registers the Q3 test module; no full benchmark was run.

Final command (backend's existing `.venv/Scripts/python.exe -B -W ignore::DeprecationWarning -m unittest`, with `-q`): `test_discovery_scope test_scoped_rag_architecture test_resource_discovery test_resource_discovery_safety test_resource_probe_understanding test_resource_probe_history test_canary_stage_a test_compact_evidence_pack test_compact_evidence_canary`.

Exact product lookup and its follow-up stay narrowed; similar collection/product titles, explicit subject switching, empty/assistant-only/malformed history, ambiguous/unknown proofs, restricted/empty authorization and stale identity are covered. An explicitly resolved collection lookup also stays exact. The synthetic “collection page says” phrase was already unresolved by the old probe builder; its before/after decision is identical, not a new Q3 regression or a claimed parser repair.

## All-90 file-only scope replay

Initial scope replay: `.codex_phase4q/scope-q3-48744b1d5dc44b838ee0d2613357e889`.
Final scope replay and closure proofs: `.codex_phase4q/scope-q3-c0fc06146973474aa456e3c76c2c99ff`.
All 90 saved questions, histories, resolutions and hard scopes were replayed through the **same runtime scope safeguard**, without planner/provider/DB calls. The accepted Q1 snapshot and actual scope were checked for each case. All 182 directly read frozen files were hash-checked unchanged. GOLD was used only afterward to score eligibility.

**CHANGED_SCOPE_CASES: [53, 54]**. No other scope decision changed.

| Case | Q1 effective scope | Candidate effective scope | Reason | Hard containment | Old supported obligation/document inaccessible |
| --- | --- | --- | --- | --- | --- |
| 53 | `[13]` | all 23 already-authorized documents | `explicit_category_discovery` | PASS | 0 / 0 |
| 54 | `[13]` | all 23 already-authorized documents | `discovery_set_followup` | PASS | 0 / 0 |

Exact authorized set: `[3,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32]`.
Scope-caused mapped misses: **4 → 0**, confirmed by the targeted manifest/SQL eligibility traces below. No earlier Q1-required document becomes inaccessible. This is an eligibility result, not a new materialized-support score.

## Security

Focused tests pass for foreign organizations/bots, unauthorized document IDs, a foreign collection, identical names in other bots, stale catalog links, captured source versions, inactive crawl/profile scope, empty hard scope, malformed/unknown/ambiguous resolution and hard-scope containment.
Existing canary tests explicitly exercise stale generation/source, invalid manifest digest, foreign-node/source scope, permission failures before fusion and scope-before-limit. The targeted wrapper inherits Q1's read-only repository, expiry refusal, exact row/provenance guards and immutable output rules. It cannot renew a lease or write the retained corpus.

## Targeted retrieval validation

Only changed cases **53 and 54**, structural lane, ran once each. No unchanged case or legacy lane was rerun. Full retained identity/source/vector preflight read existing records and validated all 180 saved P lanes without executing 90 queries. The unchanged retained manifests, query vectors, Dense/FTS/RRF functions, Q1 whole-exact packer and **131072-byte / 48-unit** limits were used. Output is a new Q3-only directory; Q1/P artifacts remained read-only.

Live artifacts: `.codex_phase4q/scope-q3-48744b1d5dc44b838ee0d2613357e889/live-81e3d6fff4ec496784d4eb7dd4d2b046`.

Terminal: **COMPLETE**, cases `[53,54]`, no failure/cleanup error, provider calls **0**, database writes **0**, lease renewals **0**. Total including full preflight: **1756.190638 seconds**. This is a guarded disposable-database measurement, not production response latency. SQLAlchemy emitted the unchanged channel's Cartesian-product warning; both channel calls succeeded, with no degradation or second repair.

| Case | Scope before → after | Mapped Dense/RRF @48 | Materialized support | Required-document coverage | Pack bytes before → after | Units | Byte / unit exclusions | Source-noise proxy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 53 | `[13]` → authorized 23 | 1/3 → 2/3 | **1/3 → 1/3** | **1/3 → 1/3** | 131045 → 131045 | 38 | 74 / 0 | 0/38 |
| 54 | `[13]` → authorized 23 | 0/2 → 1/2 | **0/2 → 0/2** | **0/2 → 0/2** | 130820 → 130898 | 42 | 84 / 0 | 42/42 |

FTS returned no candidates for either frozen query; this was a successful empty result, not a channel exception. Both packs report `INCOMPLETE_BUDGET`. Source noise is the existing required-document proxy, not a complete relevance or factual-quality judgment.

| Case / document | Dense ranks containing mapped support | FTS ranks | RRF ranks containing mapped support | Materialized | First remaining loss |
| --- | --- | --- | --- | --- | --- |
| 53 / 25 | 31, 37 | none | 31, 37 | NO | BYTE_CAP |
| 53 / 29 | none | none | none | NO | NO_MAPPED_CHANNEL_SUPPORT |
| 53 / 13 | 1–15, 17–24, 28 | none | 1–15, 17–24, 28 | YES | None |
| 54 / 25 | 45 | none | 45 | NO | BYTE_CAP |
| 54 / 29 | none | none | none | NO | NO_MAPPED_CHANNEL_SUPPORT |

Case 53 additionally has a document-13 route at rank 16 without the mapped support. The table intentionally distinguishes exact mapped-support routes from merely finding a document.

Times: case 53 total **430033.981300 ms**, Dense **2266.599800 ms**, FTS **1650.681000 ms**; case 54 total **463150.659700 ms**, Dense **2331.771000 ms**, FTS **1763.385200 ms**. These totals include the existing guarded remote materialization/revalidation path.

After live completion, a file-only replay of these two **saved new** channel arrays reproduced each actual pack's full model-byte SHA256 exactly. It confirmed the mapped document-25 atoms were requested and excluded specifically by **BYTES**, rather than inferring that cause from aggregate counts. No SQL/channel/ranker/provider was rerun. Per-obligation comparison: old support lost **0**; old required documents lost **0**. Case 53 retains all old atom identities; case 54 replaces **two nonmapped old atoms** with two different atoms. This displacement is disclosed; no claim is made that all nonmapped semantic detail was preserved.

### Final policy / live-input parity

Review found that the initial history rule could mistake “any discounts for a named item” for resource discovery. A deterministic negative test reproduced it; the final rule binds the prior nonempty topic to an existing resolved name/alias too. Empty aliases cannot supply that proof. The running live code was not changed; this conservative guard was completed afterward.

The final **90/90** replay has identical decisions/scopes to the admitted candidate. For both live cases, the final policy reproduces the exact hard-scope identity, effective IDs, query bytes/hash, snapshot identity and saved vector receipt used in the measured run. `final-live-input-parity.json` records both policy hashes and that input equivalence. The downstream implementation is unchanged. Thus the live retrieval evidence is reusable without running either query twice; it is not falsely described as a second run under the final source hash.

## Scope / limitations / next causes

This is retrieval-only: no generated answers, chat/widget calls or provider quota. The safeguard does not repair the earlier probe classification itself, expand the parser to arbitrary language, change generation prompts, or guarantee that newly eligible content ranks into the pack. Q1 support outside the two changed scopes is reused, not claimed as newly rerun.

Original known causes **byte=12, channel=4** are not repaired; **scope=4 → 0**. The four formerly scope-blocked obligations remain unmaterialized: **two newly exposed byte misses and two newly exposed channel misses**. Combined earliest-loss accounting is therefore **byte=14, channel=6, scope=0**, using unchanged saved evidence for the other 88 cases. This is mixed saved/targeted accounting, **not** a new full-90 live benchmark or claim of improved aggregate materialized support. Accepted Q1's score remains the reported baseline **89/109**.

## Final review and checkpoint scope

Final diff review: the only existing runtime change is the two-line post-resolution call. The new pure helper has no DB/provider access, corpus scan, metadata-derived instructions, hard-scope mutation or benchmark-specific rules. The canonical test runner adds one module. No Dense/FTS/RRF, ranker, compact packer, source snapshot, vector, GOLD, model, prompt, ingestion, credential configuration or production file is changed.

Files for the single accepted local checkpoint:

- `backend/services/discovery_scope.py`
- `backend/services/rag_planning.py`
- `backend/test_discovery_scope.py`
- `backend/scripts/replay_discovery_scope.py`
- `backend/scripts/validate_discovery_scope.py`
- `backend/scripts/test_scoped_rag_regressions.py`
- `docs/PHASE_4_1Q3_CATEGORY_FOLLOWUP_SCOPE_REPORT.md`

The nine pre-existing untracked Q2 diagnosis/rejected-experiment files are preserved and excluded from this checkpoint. Generated canary artifacts and credentials are not committed. The disposable credential was read from the explicitly supplied prior user message only into this run's process, fingerprint-checked against the retained target, never printed or newly persisted, and cleared on exit.

**Accept Q3's scope correction only.** No provider/model call, new embedding, chat/widget test, production access, lease extension, crawl/re-ingestion, channel/packing change, push or deployment. Stop here; further work on remaining channel/byte losses requires separate authorization.
