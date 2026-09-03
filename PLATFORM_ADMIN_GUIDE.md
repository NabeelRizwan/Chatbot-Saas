# Platform admin guide

## Access and first administrator

A platform administrator is an existing user with server-stored `User.is_admin=true`. Organization owners/admins remain ordinary customers unless explicitly promoted. No separate admin password, JWT, authentication service, or public promotion endpoint exists.

1. Deploy infrastructure, run the Backend migration release step, and start Backend/Worker/Frontend as described in [RAILWAY_PRODUCTION_SETUP.md](RAILWAY_PRODUCTION_SETUP.md).
2. Register the intended owner account at `https://APP_DOMAIN/signup` using normal authentication. Verify you created the intended account before promotion.
3. From the Backend application directory, in an authorized infrastructure shell with the production `DATABASE_URL`, run:

   ```text
   python scripts/set_platform_admin.py --email "EXISTING_ACCOUNT_EMAIL"
   ```

   It resolves only that existing account, shows its user ID, and requires typing `PROMOTE`. It never requests or prints a password. Unknown/disabled accounts fail. Repeating the command is idempotent.

4. For a noninteractive Railway one-off command in the Backend service environment, use either:

   ```text
   python scripts/set_platform_admin.py --email "EXISTING_ACCOUNT_EMAIL" --yes
   python scripts/set_platform_admin.py --user-id EXISTING_USER_ID --yes
   ```

   Replace the placeholder with one exact account, run only one command, and verify the reported ID. Run inside infrastructure with access to the private database; do not assume a local shell can reach Railway private networking. Do not put promotion in the start command, pre-deploy migration hook, or a recurring job. `--yes` is deliberate promotion authority, not an application setting.

5. Log in again at `https://APP_DOMAIN/login` to refresh the browser's user metadata. Open `https://APP_DOMAIN/admin` or the **Admin** navigation item.

Use the same command to deliberately promote another existing operator later. The former `BOOTSTRAP_ADMIN_EMAIL` registration promotion is removed and ignored; remove any stale deployment variable. Existing administrators retain their stored role. No real account is promoted by deploying this code.

## Console

| Route | Purpose |
| --- | --- |
| `/admin` | Organization, bot, enabled-profile counts |
| `/admin/organizations` | Searchable organization IDs/names, bot counts, creation dates; link to filtered bots |
| `/admin/bots` | Search bot/customer/organization; filter by provider, profile or unassigned; inspect generation settings and credential capacity |
| `/admin/api-credentials` | Add, label, edit capacity, enable/disable, inspect assigned bots, and delete empty profiles |

All lists are paginated (25 rows in the UI; API maximum 100). No impersonation, conversation inspection, knowledge browsing, or customer-secret editing is provided here.

## Add a provider credential

In **API Credentials → Add API credential**, select a provider, enter an operational label, set **Maximum bot assignments** (default **2**, minimum **1**), paste its secret into the password-style input, and save.

| Display name | Canonical backend provider | Example label |
| --- | --- | --- |
| Gemini | `gemini` | Gemini Primary |
| OpenAI | `openai` | OpenAI Primary |
| Anthropic / Claude | `claude` | Claude Backup |
| xAI / Grok | `grok` | Grok Primary |

Provider/model options come from the backend's existing model allowlist. This phase does not add models or check key validity with paid provider calls. Save confirms accepted metadata and encrypted persistence, not available provider quota or live model access.

Secrets are Fernet-encrypted with the existing `PLATFORM_KEY_ENCRYPTION_KEY`. Preserve that root key across Backend/Worker deployments and back it up securely. The browser clears the secret after successful save. List/create/update responses return metadata only—not full keys, partial keys, or ciphertext. Do not put secrets into labels, URLs, screenshots, or support messages.

## Bot-based allocation and capacity

**Capacity is per bot, not per customer.** One bot references at most one profile; one profile can serve multiple bots up to its configurable maximum. A customer with three bots consumes three slots. Different organizations/customers may share a profile without sharing knowledge, conversations, quotas or tenant usage records.

| Profile | Maximum bots | Automatically assigned bots |
| --- | --- | --- |
| Gemini Primary | 2 | Bot A, Bot B |
| Gemini Secondary | 2 | Bot C, Bot D |

Creation, cloning, switching generation provider, and switching from BYOK to platform mode choose the **oldest enabled, same-provider profile with capacity**, ordered by creation timestamp then ID. Customer/organization identity is not an allocation input. A full profile is skipped, not overloaded. No secret is copied into a bot.

If no matching slot exists, creation may succeed **unassigned**. Admin Bots shows **Unassigned — generation unavailable**. Generation fails with a generic customer-safe unavailable message; it does not use an environment key, another provider, or another bot's credential. Adding capacity does not redistribute existing bots or automatically attach previously unassigned bots: explicitly assign those bots in the admin editor.

The credentials list shows status, exact assigned count / maximum, remaining slots, and the first 10 assigned bots (organization/customer, name, ID, provider/model). **View all assigned bots** opens the paginated profile-filtered bot list. Disabled profiles can have free slots numerically, but none are usable while disabled.

**Edit capacity** changes only that profile. Increasing permits more future allocations; decreasing below the current assignment count is rejected. Reassign/unassign enough bots first. If another admin edited the maximum, reload before retrying. Capacity is an assignment limit, not a claim about upstream token/rate quotas.

## Enable, disable, delete, rotate

- **Disable** warns how many bots are affected and requires confirmation. Every bot reference stays intact for visibility; new generation and new assignments are blocked. No provider switch, environment fallback, rotation, or automatic redistribution occurs.
- **Enable** resumes eligibility for the existing bot references and permits future allocations if slots remain.
- **Delete** is blocked while ANY bot still references the profile, including a disabled profile. Reassign or unassign every bot first, then confirm deletion. This deletes only the encrypted profile; it does not revoke the upstream provider key.
- **Rotate** by creating a new credential → explicitly reassigning each assigned bot → disabling/deleting the old profile → revoking the old upstream key at the provider when safe. There is no retrieve-old-secret or in-place replacement feature.
- **Rename** changes metadata only; IDs, not labels, identify profiles.

## Configure a bot

1. Find the customer/organization and bot in **Bots**, then choose **Configure**.
2. Select the generation provider and one of the backend-supported models.
3. Select a compatible credential. Only enabled profiles belonging to that provider and below capacity or already assigned to this bot are offered. Search/pagination supports larger pools.
4. Save. The server validates the provider/model/profile, preserves BYOK, and saves atomically. If another administrator changed the configuration, reload the bot list before retrying.

Choosing **Unassigned — generation unavailable** removes this bot’s reference only. When changing provider, the empty option instead requests **Auto-allocate for new provider (if capacity exists)**: assign a compatible slot or remain unassigned. The old incompatible reference is removed in the same transaction. A failed explicit move to a full, disabled or mismatched profile preserves the previous configuration. Other bots on either profile are untouched.

BYOK bots are read-only in this admin editor. Their owner must switch to platform mode in the existing authorized customer settings first. Credential precedence is customer BYOK → assigned enabled compatible platform profile. BYOK bots consume no pool slot; switching to BYOK releases only their slot. Omitted BYOK values still leave the key unchanged, and explicit clear still removes it. Infrastructure/embedding environment credentials remain unchanged, but are not managed-bot generation fallbacks.

Generation settings are separate from embedding provider/model/dimensions and stored knowledge. This operation does not crawl, ingest, re-embed, change vectors, or change the active embedding profile.

## Security and operational limits

- Every admin endpoint uses the normal bearer access-token user lookup and one canonical admin dependency. Missing/widget credentials receive 401; authenticated customers, including organization owners, receive 403. Cookies alone cannot authorize admin mutations.
- The frontend verifies `/admin/session` before rendering the area. Persisted browser admin flags are discarded. Backend authorization is authoritative for every operation. Existing secure refresh cookies, allowed origins, CORS, and CSRF controls are unchanged.
- Customer APIs keep their organization boundaries and BYOK controls. Platform profile lists, IDs, labels and secrets are admin-private. Customer responses expose neither allocation IDs/labels/counts/capacity nor the former assignment boolean; the customer’s existing platform/BYOK usage-mode choice remains.
- Credential lifecycle operations use a short PostgreSQL transaction-scoped advisory lock across replicas, alongside row locks/constraints. Generation/read operations do not take it. Assignment counts are read after that lock at READ COMMITTED isolation. Create/clone/provider changes, moves/removals, capacity edits and enable/disable/delete share it. Concurrent admin bot edits use an expected configuration snapshot; capacity edits use the expected previous maximum. Stale writes are rejected.
- Existing `audit_logs` records actor user ID, action, target non-secret IDs, organization where applicable, and timestamp in the same transaction. CLI promotion records a null application actor (the infrastructure operator is not impersonated); retain Railway/operator access logs for operator attribution. No new audit-view UI or audit logging subsystem is introduced.
- Disabling a credential does not cancel a provider request already in flight. It is not an upstream key revocation. Protect infrastructure access: anyone authorized to run the promotion CLI against production can grant platform-wide administration.
- No deployment, account promotion, live key validation, or real provider-key creation was performed as part of this implementation. Those are deliberate post-deployment operator actions.

## Existing-installation rollout

This release adds Alembic revision `20260903_01`; no existing migrations are edited. It adds `max_bot_assignments` (default 2, check >= 1), keeps encrypted bytes untouched, backfills valid legacy reverse links only when the bot has no canonical reference, and preserves all existing valid bot-side assignments. Existing capacities are retained or raised to the current count if needed. Disabled references remain disabled. Invalid canonical provider/BYOK combinations stop the migration transaction for administrator review; nothing is silently removed.

`Bot.platform_credential_id` is authoritative. The old `PlatformApiKey.allocated_to_bot_id` column remains historical and is NOT used by the new runtime. **Do not mix old one-to-one writers with new shared-profile writers.** Schedule a controlled rollout: back up, drain/stop old Backend and Worker replicas, run `python scripts/run_migrations.py` once from `backend`, then start only the new Backend/Worker/Frontend version. Do not roll back to one-to-one code after sharing profiles.

Before customer traffic, use `/admin/api-credentials` to add suitable real credentials/capacity, then `/admin/bots` to assign existing unassigned platform bots and check disabled profiles. Bots formerly relying on environment generation defaults now require a pool profile or explicit customer BYOK. Routine provider keys belong in the admin console; infrastructure and embedding secrets remain infrastructure-managed. Do not change the encryption root key.

No migration was applied to the customer database during development of this phase. Migration acceptance tests use disposable schemas only. Follow the normal one-off release gate; application replicas do not run production migrations.
