# Bot credential pool report

## Pre-change audit

Starting commit: `4428723df9371dfe70dd27b70f31da5b71e2cd45`. Clean `main`; local and fetched `origin/main` match.

- `Bot.platform_credential_id` is already a nullable, non-unique foreign key. It can represent many bots referencing one encrypted profile without a new assignment table.
- The legacy `PlatformApiKey.allocated_to_bot_id` unique reverse link, one-to-one ORM relationships, service checks, and frontend filtering currently enforce one bot per profile. The service allocates only `available`/unallocated rows and writes both directions.
- Disable currently clears the bot reference; list/read metadata and credential usage still derive from the reverse link. Those assumptions must be removed for shared profiles.
- Customer creation/provider changes swallow pool-allocation errors, and generation falls back to environment keys. That fallback would bypass capacity and must stop for managed bot generation. BYOK and infrastructure/embedding configuration remain separate.
- Admin provider updates already have expected-snapshot protection; credential lifecycle operations already share a PostgreSQL transaction-scoped advisory lock. Reuse both.
- Existing `audit_logs`, encrypted storage, admin authentication, provider/model validation, and tenant/usage boundaries are reused.

## Delivered implementation

Final implementation commit: `5731ec023387e59905d676edad9f7291c6fbc3e1` — **Add capacity-based platform credential allocation**.

This report is packaged in a following documentation-only commit. The final synchronized branch-head SHA is reported in the task completion message; `git log -1 --format=%H -- BOT_CREDENTIAL_POOL_REPORT.md` resolves the report commit. No runtime or test changes follow the implementation commit.

| Contract | Before | After |
| --- | --- | --- |
| Assignment | Reverse-link one-to-one | One bot → zero/one profile; profile → many bots |
| Source of truth | Two overlapping references | `Bot.platform_credential_id` only |
| Capacity | Implicit one bot | `max_bot_assignments`, default 2, integer >= 1 |
| Full pool | Create unassigned, then environment fallback | Create unassigned; managed generation fails closed |
| Disable | Release the bot | Preserve all references; block new generation/allocation |
| Delete | Disable could release the blocker | Reject while any bot reference remains, even disabled |

### Allocation, concurrency and lifecycle

- Allocation is BOT-based, never customer-based. New/clone platform bots, provider changes and switching from BYOK choose the oldest enabled matching-provider profile with a free slot, ordered by `created_at`, then ID. Two bots belonging to one customer use two slots; two organizations may legitimately share one profile.
- Counts use the indexed bot-side foreign key across all tenants. No secret is copied into bots, and no assignment table or new allocation service is introduced. The legacy reverse column/index/constraint remain historical, with no active service fallback to them.
- The existing PostgreSQL transaction-scoped advisory lock `(73421, 1)` serializes lifecycle writers across replicas. Counts are checked after locking under READ COMMITTED; row locks and the capacity check remain in the same transaction until commit/rollback. Tests use the application's `autoflush=False` behavior. No process-local locking is used for correctness.
- Manual moves require an enabled, same-provider destination with free capacity. They release only the selected bot's old reference; rejected moves roll back without changing either assignment. Keeping the current slot is allowed at full capacity. Existing bot configuration snapshots reject stale admin saves.
- Capacity edits include the expected previous maximum. Increases permit future allocation; decreases below the current count and stale edits return safe 409 errors. Invalid/zero/fractional/boolean values return 422. A database check also rejects capacity below 1.
- Disable warns about the affected count, retains all references and stops new use. Enable restores eligibility of those references. Neither action redistributes bots or changes provider. Already in-flight provider calls are not canceled; disabling is not upstream key revocation.
- Delete requires zero references, including for disabled profiles. Bot deletion/BYOK switch/removal releases only that bot's slot. Key rotation is explicit: add replacement profile, move each bot, then retire the empty old profile.
- Changing provider atomically assigns a compatible new profile or leaves the bot unassigned; an incompatible old reference is never retained. A stale request holding an older provider snapshot fails closed instead of sending a new provider's secret to the old adapter.
- Existing `audit_logs` record create/auto-assign/manual assign/remove/capacity/enable/disable/delete, non-secret IDs, timestamp, and user actor where applicable. No credential values are logged.

### Admin visibility, BYOK and isolation

- Credentials show Enabled/Disabled, assigned count / maximum, remaining slots, and a bounded preview of 10 assigned bots including organization/customer/name/ID/provider/model. A link opens all assigned bots with pagination.
- Bots show credential label and capacity, or **Unassigned — generation unavailable** / **Disabled — admin action required**. Provider/profile/unassigned filters are available. Search and lists retain API limits of at most 100 rows.
- Generation precedence is BYOK → assigned enabled compatible pool profile. There is **no environment generation fallback** for managed bots. No free capacity means generic customer-safe service-unavailable failure, not overload, random redistribution, fabricated credentials or provider switching.
- BYOK encryption and omitted/replace/explicit-clear behavior remain unchanged. BYOK bots do not allocate a platform slot; changing to BYOK releases their slot. Admin generation editing remains blocked until the customer deliberately leaves BYOK mode.
- Customer responses contain no profile IDs/labels/capacity/assignment lists, including removal of the unused assignment boolean. The existing customer-visible platform/BYOK choice is retained. Admin auth, tenant checks, refresh/session architecture and customer secrets are unchanged.
- Organization/bot/request usage boundaries remain intact. Existing profile usage counters are an additional best-effort aggregate, now updated atomically from bot references; they are not the billing ledger. Tests demonstrate two organizations retain separate usage totals while sharing a profile.
- No generation adapters, supported model catalogs, embedding configuration, vectors, RAG, storage, Firecrawl, ingestion, Redis architecture, billing implementation or analytics calculations changed. Synthetic knowledge row snapshots and SQL-write checks confirm admin generation changes do not write documents/chunks.

## Migration and deployment precautions

New additive revision: `20260903_01`, following `20260902_02`. Existing migration files are unchanged.

The migration adds capacity/default/check, preserves encrypted bytes, backfills compatible non-BYOK legacy reverse references only where the canonical reference is absent, and preserves existing valid canonical assignments. Existing capacities remain or rise to the assignment count when necessary. Disabled state is preserved. An incompatible canonical provider/BYOK reference aborts the transaction for administrator review instead of deleting data. No destructive downgrade, table/column drop, truncate, corpus reset, decryption or re-encryption is added.

**Do not mix old one-to-one writers and new pool writers.** For a future rollout: back up → drain/stop old Backend/Worker → run `python scripts/run_migrations.py` once from `backend` → start new Backend/Worker/Frontend → provision/check assignments before customer traffic. Production replicas still only check migration head. Do not roll back to the old allocator after sharing profiles.

No migration was applied to the customer database; its revision remains `20260902_02`. Real migration tests used guarded randomly named disposable schemas, removed afterward. The older migration test fixture was also guarded against accidentally resolving public/customer tables through `search_path`.

## Exact validation results

All final runs passed. No live paid provider calls or customer chatbot questions were used.

| Validation | Final result |
| --- | --- |
| Admin console, pool contracts, PostgreSQL races, auth/F1 sessions, Phase A/A2, bot contract, provider/architecture, Railway readiness | **115 tests passed**, 22.448 s |
| New PostgreSQL/Alembic capacity migration suite | **5 tests passed**, 19.903 s |
| Existing Phase I migration acceptance script | **3 tests passed** |
| Isolated Phase 11 security | **8 tests passed**, 16.972 s |
| Isolated production platform suite, including concurrent chat and tenant isolation | **5 tests passed**, 19.839 s |
| Isolated Phase G atomic quota/usage/analytics regression | **8 tests passed**, 16.322 s |
| Legacy pool verification inside the isolated runner | **39/39 assertions passed** |
| Real rendered production Next/React admin browser tests, intercepted synthetic API | **9 tests passed**, 4.5 s |
| Frontend bot normalization/create/update contract, compiled to ES2022 | **28 assertions passed** |
| `npm run typecheck` | **PASS** |
| `npm run lint` | **PASS: 0 errors**, 2 pre-existing `no-img-element` warnings |
| `npm run build` | **PASS**, 21 pages generated |
| Python syntax validation | **PASS**, all 17 changed Python files; runtime imports also exercised by tests |
| Diff/secret review | **PASS**, no configured secret values or controlled-customer markers in added code/report |

Backend grouped command, run from the repository root with `PYTHONPATH=backend` and deprecation warnings suppressed:

```text
python -m unittest backend.test_platform_admin_console backend.test_platform_admin_concurrency backend.test_bot_credential_pool backend.test_phase_f_auth_secrets backend.test_phase_a_tenant_chat_security backend.test_phase_a2_stop_ship_security backend.test_phase_b_bot_contract backend.test_final_production_architecture backend.test_railway_deployment_readiness -q
python -m unittest backend.test_bot_credential_pool_migrations -q
```

Additional entry points, run from `backend`: `python test_phase_i_migrations.py`, `python scripts/test_admin_regressions.py`. Browser command from `frontend`: `npm run test:admin -- --reporter=list`, using `E2E_BASE_URL=http://127.0.0.1:3101` against a production Next server. That test server was stopped afterward. The normal stack was not started or deployed.

New/expanded coverage includes four simultaneous new bots with capacity 2, four assignments spread across two profiles, cross-organization sharing, concurrent atomic usage increments, assignment-versus-disable/delete/capacity-reduction, stale admin bot/capacity edits, clone, BYOK clear/replacement, failed manual move rollback, customer privacy, bounded metadata, and stale-provider key safety. Migration coverage includes fresh/existing/multiple providers/legacy references/ciphertext preservation/idempotency/atomic failure.

An initial regression exposed an outdated in-memory test fixture that lacked the new lifecycle-lock mock; the fixture was corrected and the grouped suite rerun successfully. One existing Redis-unavailable warning occurred in the grouped regressions; it was not optimized or hidden and did not fail tests. DB-backed production/quota tests used isolated schemas, synthetic embeddings and fake Redis, with external HTTP blocked. Browser tests validate real UI behavior against mocked API responses; they do not claim a live production deployment.

## Corpus and secret safety

Read-only checks before and after all tests: **10 READY documents / 573 READY chunks**, unchanged. Full-row fingerprints, including stored vectors/metadata:

| Rows | Before and after fingerprint |
| --- | --- |
| Documents | `2572ab3a0879a9226b3bbaaebb4fa3fc` |
| Chunks | `ee3c5f4033c1fd22a0ce6a02e322ddd2` |

No customer corpus content, account credentials or specific bot IDs are hardcoded into the implementation. No real profile keys were added, returned, decrypted for display or logged. Only synthetic test credentials were created in isolated stores.

## Remaining operator actions

Read-only **local** inventory: **0 platform profiles; 11 platform bots unassigned**. This is not a production inventory. Provision sufficient capacity through `/admin/api-credentials`, then explicitly assign existing unassigned bots in `/admin/bots`. New bots thereafter allocate automatically when slots exist. Saving a key confirms encrypted persistence, not upstream quota/model access; perform live validation only in a separately authorized deployment.

The customer DB migration, real-key provisioning, production inventory and Railway deployment were deliberately NOT performed. Preserve the encryption root key and embedding/infrastructure secrets. Three non-secret compiler-generated JavaScript test files remain in an OS temporary directory because shell cleanup was blocked; they are outside the repository and no test server remains running.

## Verdict

BOT CREDENTIAL POOL READY — ADMIN MUST ADD CAPACITY BEFORE NEW BOTS
