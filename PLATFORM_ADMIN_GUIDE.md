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
| `/admin/bots` | Search by bot/customer/organization; inspect status, generation configuration and safe credential metadata |
| `/admin/api-credentials` | Add, label, enable, disable, and delete platform-owned profiles |

All lists are paginated (25 rows in the UI; API maximum 100). No impersonation, conversation inspection, knowledge browsing, or customer-secret editing is provided here.

## Add a provider credential

In **API Credentials → Add API credential**, select a provider, enter an operational label, paste its secret into the password-style input, and save.

| Display name | Canonical backend provider | Example label |
| --- | --- | --- |
| Gemini | `gemini` | Gemini Primary |
| OpenAI | `openai` | OpenAI Primary |
| Anthropic / Claude | `claude` | Claude Backup |
| xAI / Grok | `grok` | Grok Primary |

Provider/model options come from the backend's existing model allowlist. This phase does not add models or check key validity with paid provider calls. Save confirms accepted metadata and encrypted persistence, not available provider quota or live model access.

Secrets are Fernet-encrypted with the existing `PLATFORM_KEY_ENCRYPTION_KEY`. Preserve that root key across Backend/Worker deployments and back it up securely. The browser clears the secret after successful save. List/create/update responses return metadata only—not full keys, partial keys, or ciphertext. Do not put secrets into labels, URLs, screenshots, or support messages.

Multiple profiles per provider are supported. **The current pool remains one bot per profile.** Shared profiles are not supported by its existing allocation contract; this phase does not change it or duplicate a secret into bots. No new automatic pooling or rotation is added. The existing customer create/provider-change allocation behavior remains in place.

## Enable, disable, delete, rotate

- **Disable** requires confirmation and releases the assigned bot under existing semantics. The bot may use a configured environment default for the **same provider**; otherwise generation reports a missing credential. No silent switch of provider or assignment to another profile occurs.
- **Enable** makes the profile available again; it does not automatically reassign a previous bot.
- **Delete** is blocked while assigned. The list shows the assigned bot/count. Reassign the bot or disable the profile first, then confirm deletion. This deletes only the encrypted local profile; it does not revoke the upstream provider key.
- **Rotate** by creating a new credential → explicitly reassigning its bot → disabling/deleting the old profile → revoking the old upstream key at the provider when safe. There is no retrieve-old-secret or in-place replacement feature.
- **Rename** changes metadata only; IDs, not labels, identify profiles.

## Configure a bot

1. Find the customer/organization and bot in **Bots**, then choose **Configure**.
2. Select the generation provider and one of the backend-supported models.
3. Select a compatible credential. Only enabled profiles belonging to that provider and free or already assigned to this bot are offered. Search/pagination supports larger pools.
4. Save. The server validates the provider/model/profile, preserves BYOK, and saves atomically. If another administrator changed the configuration, reload the bot list before retrying.

Choosing **Environment default (if configured)** explicitly removes the profile reference. The existing selected-provider defaults are `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and `XAI_API_KEY`. They are never readable through the admin API. Missing defaults make generation unavailable; configuring a profile avoids routine Railway secret edits.

BYOK bots are read-only in this admin editor. Their owner must switch to platform mode in the existing authorized customer settings first. Credential precedence remains customer BYOK → assigned compatible platform profile → selected-provider environment default.

Generation settings are separate from embedding provider/model/dimensions and stored knowledge. This operation does not crawl, ingest, re-embed, change vectors, or change the active embedding profile.

## Security and operational limits

- Every admin endpoint uses the normal bearer access-token user lookup and one canonical admin dependency. Missing/widget credentials receive 401; authenticated customers, including organization owners, receive 403. Cookies alone cannot authorize admin mutations.
- The frontend verifies `/admin/session` before rendering the area. Persisted browser admin flags are discarded. Backend authorization is authoritative for every operation. Existing secure refresh cookies, allowed origins, CORS, and CSRF controls are unchanged.
- Customer APIs keep their organization boundaries and BYOK controls. Platform profile lists, IDs, labels and secrets are admin-private. Customer bot responses retain only the existing platform-use boolean.
- Credential lifecycle operations use a short PostgreSQL transaction-scoped advisory lock across replicas, alongside row locks/constraints. Generation/read operations do not take it. Concurrent admin bot edits also use an expected configuration snapshot and reject stale writes.
- Existing `audit_logs` records actor user ID, action, target non-secret IDs, organization where applicable, and timestamp in the same transaction. CLI promotion records a null application actor (the infrastructure operator is not impersonated); retain Railway/operator access logs for operator attribution. No new audit-view UI or audit logging subsystem is introduced.
- Disabling a credential does not cancel a provider request already in flight. It is not an upstream key revocation. Protect infrastructure access: anyone authorized to run the promotion CLI against production can grant platform-wide administration.
- No deployment, account promotion, live key validation, or real provider-key creation was performed as part of this implementation. Those are deliberate post-deployment operator actions.
