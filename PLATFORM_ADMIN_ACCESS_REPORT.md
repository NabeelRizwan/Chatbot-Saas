# Platform admin access report

Verdict: **PLATFORM ADMIN CONSOLE READY — FIRST ADMIN BOOTSTRAP REQUIRED AFTER DEPLOYMENT**

## Repository and scope

- Starting commit: `46bf78c8d6a14413bf56d5d4d9483217be6a147a`.
- Started on clean `main`, after fetch, with local HEAD equal to `origin/main`.
- Final commit: the commit containing this report, titled `Add secure platform admin credential console`. Resolve its exact SHA with `git log -1 --format=%H -- PLATFORM_ADMIN_ACCESS_REPORT.md`; the SHA and push result are also provided in the completion message. This avoids embedding a self-referential commit hash.
- No Railway deployment, real key creation, real account promotion, customer impersonation, migration, or customer-corpus mutation was performed.

## Existing flow and changes

| Area | Before | Delivered |
| --- | --- | --- |
| Authentication | Normal login/short-lived access JWT plus rotating HttpOnly refresh cookie; DB-backed user lookup | Reused unchanged. No second authentication system. |
| Platform authorization | Existing separate `User.is_admin`; admin dependency; registration could promote an environment-matched email | Same DB flag/dependency reused on every admin endpoint. Registration always creates normal users. No organization-role overload. |
| Bootstrap | `BOOTSTRAP_ADMIN_EMAIL` at registration | Explicit existing-account CLI, confirmation or `--yes`, idempotent, disabled/unknown users rejected, no password input/output. |
| Credentials | Encrypted Fernet pool; safe provider matching; masked-key responses; settings-page management | Dedicated guarded console, metadata-only response models, no display-time decryption, bounded lists, safe validation/error responses, same transactional lifecycle. |
| Bot configuration | Customer provider/model configuration and standalone admin assignment endpoint | Atomic admin provider/model/profile editor using existing bot fields, validator and assignment services; stale snapshots rejected. |
| Customer privacy | Customer bot responses included profile IDs/labels | Those platform-private fields removed; BYOK and tenant controls preserved. |

### Authorization and frontend

Routes: `/admin`, `/admin/organizations`, `/admin/bots`, `/admin/api-credentials`. Overview counts are lightweight; lists have search and bounded pagination. Organization links filter the bot list.

Normal authentication resolves the active user from the database on each admin request. No credentials/widget tokens → 401; ordinary customers and organization owners → 403; platform admin → permitted. Client-side role flags are not authority: persisted admin flags are discarded, navigation uses authenticated state, and `/admin/session` gates rendering. Secure cookies, auth origins, CORS, and CSRF architecture were not weakened. Admin mutations require the ordinary bearer access token, not cookies alone.

### Credential operations and bot settings

- Canonical supported providers remain `gemini`, `openai`, `claude`, `grok`; the UI obtains existing supported model lists from the backend. No model/provider adapters changed or speculative models added.
- Add, list, rename, enable, disable, delete, and explicitly assign compatible profiles. Multiple profiles per provider work.
- Reuse `PLATFORM_KEY_ENCRYPTION_KEY` and Fernet storage. Secret input is password-style, never persisted in browser storage, and cleared after successful save. Read/write responses contain no raw key, partial key, or ciphertext. Invalid input/database/encryption failures do not echo submitted secrets.
- Existing **one profile per bot** allocation remains. Shared profile assignment was not added because the current architecture explicitly enforces 1:1 allocation. The UI states this and prevents choosing another bot's profile; the backend independently rejects it.
- Disabled keys cannot be assigned. Disabling releases the current bot as before; a same-provider environment default may still be used. Otherwise credential resolution fails clearly. No automatic provider switch or new automatic key redistribution is introduced.
- Assigned deletion is blocked with assigned-bot metadata visible; reassign or disable first. Disable/delete confirmation is required. Revocation at the upstream provider remains a separate operator action.
- No in-place secret replacement was invented. Rotation is create new → reassign → disable/delete old.
- Existing resolution order remains BYOK → assigned compatible profile → selected-provider environment default. BYOK bots cannot be overridden through this editor; their owner must deliberately switch modes first.
- Only generation provider/model/profile references change. Tests verify no document/chunk/embedding writes; RAG, Firecrawl, embeddings, storage, and ingestion code are untouched.
- Database transaction-scoped advisory locking coordinates lifecycle operations across replicas, with row locks/constraints and expected-config checks. Four live PostgreSQL race tests cover assignment vs disable/delete, two bots claiming one key, and two admins updating one bot.
- Existing `audit_logs` stores action, actor, target IDs and timestamp transactionally. CLI promotion has a null application actor; infrastructure access logs identify the operator. No secret is audited.

## Validation

| Check | Exact result |
| --- | --- |
| `python -m unittest -q backend.test_platform_admin_console backend.test_platform_admin_concurrency` | **19 passed**, 9.312s: 15 isolated SQLite API/service tests + 4 real PostgreSQL races |
| Phase F, A, A2, B, final-production architecture, Railway readiness (`unittest`) | **79 passed**, 2.476s; expected unavailable-Redis warning in a fallback path, no failures |
| `python backend/scripts/test_admin_regressions.py` — Phase 11 security | **8 passed**, 19.400s |
| Same isolated runner — production platform | **5 passed**, 21.331s; includes 50 synthetic concurrent requests and no-recrawl checks |
| Same isolated runner — existing credential pool script | **39/39 checks passed** |
| `E2E_BASE_URL=http://127.0.0.1:3101` with `npm run test:admin -- --reporter=list` | **6 passed**, 3.1s, actual production-built Next/React UI with intercepted synthetic APIs |
| `npm run typecheck` | Passed |
| `npm run lint` | Passed: 0 errors, 2 pre-existing `no-img-element` warnings |
| `npm run build` | Passed; all four admin routes included |
| Python compile/import | 12 changed Python files compiled; admin/auth/bot/key/CLI runtime imports passed |
| Diff/secret review | No real credentials, customer emails, customer-specific runtime logic, or forbidden component changes |

Commands above are run from the repository root unless prefixed by npm (frontend directory); Python module commands use `PYTHONPATH=backend`. The browser suite requires a local frontend server, but intercepts API calls and never authenticates a real account. The DB regression runner creates and verifies its own random schema, uses synthetic embeddings and mocked generation/Redis, blocks external HTTP, and removes its schema afterward. These are not live provider or deployed Railway benchmarks.

Initial checks found one unused frontend import and two browser-selector issues; corrected, with final lint/browser runs passing. The fresh-schema Phase 11 run initially failed because old fixtures omitted the already-required bot customer ID; only those synthetic fixtures/cleanup were corrected, not runtime schema or security assertions.

## Corpus and migration safety

No migration/model changes were needed. Existing Alembic files and the explicit production release/startup flow remain unchanged.

Read-only full-row checksums before/after match:

| Controlled local data | Rows | Unchanged fingerprint |
| --- | ---: | --- |
| Documents | 10 | `2572ab3a0879a9226b3bbaaebb4fa3fc` |
| Chunks (including vectors) | 573 | `ee3c5f4033c1fd22a0ce6a02e322ddd2` |

No synthetic PostgreSQL schemas remained after completed tests. Temporary synthetic rows were deleted with their isolated schemas; no customer rows were deleted. No recrawl/reingestion/re-embedding of customer data occurred.

## Files and operator handoff

- Backend: admin/auth routes; auth/bot/platform-key services; customer bot response schema; new `scripts/set_platform_admin.py`; `.env.example` and auth guide.
- Frontend: four admin pages/layout, admin shell/console, admin API client/helper, sidebar, cached role handling, and removal of the duplicate credential UI from customer settings.
- Tests: new admin API and concurrency suites, isolated regression runner, browser suite/npm command; updated bootstrap regression and Phase 11 fixtures.
- Documentation: [PLATFORM_ADMIN_GUIDE.md](PLATFORM_ADMIN_GUIDE.md), this report, and the post-deploy step in [RAILWAY_PRODUCTION_SETUP.md](RAILWAY_PRODUCTION_SETUP.md).

After a separately authorized deployment: infrastructure → one-off migrations → services → normal owner registration → `python scripts/set_platform_admin.py --email "EXISTING_ACCOUNT_EMAIL" --yes` in the Backend environment → normal login → `/admin` → add and assign credentials. No permanent admin secret is required in Railway.

Remaining manual actions: deploy when authorized; verify the intended owner account; run the explicit promotion command; log in again; add real provider profiles; confirm live provider/model access and quotas. Preserve/back up the encryption root. Shared profiles, impersonation, upstream key revocation, live key validation, in-place secret replacement, and an audit-log UI are not implemented in this phase.
