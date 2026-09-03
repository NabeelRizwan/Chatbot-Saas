# Phase F authentication and secret migration

## Required production configuration

- `APP_ENV=production`
- `JWT_SECRET`: at least 32 unpredictable bytes; never use the development fallback.
- `PLATFORM_KEY_ENCRYPTION_KEY`: a stable Fernet key shared by every API/worker instance. Back it up in the deployment secret manager; losing it makes encrypted platform and BYOK credentials unreadable.
- `ACCESS_TOKEN_EXPIRE_MINUTES`: `1` through `30` (`15` recommended).
- `REFRESH_COOKIE_SECURE=true`
- `REFRESH_COOKIE_SAMESITE=lax` when frontend and API are same-site. Use `none` only for a genuinely cross-site deployment, with HTTPS and an explicit `AUTH_ALLOWED_ORIGINS` list.
- Platform admin bootstrap now uses the explicit one-off `scripts/set_platform_admin.py` command. The former `BOOTSTRAP_ADMIN_EMAIL` registration promotion is removed; see [PLATFORM_ADMIN_GUIDE.md](../PLATFORM_ADMIN_GUIDE.md).

The browser refresh credential is an HttpOnly cookie scoped to `/auth`. Browser auth calls must use credentials and `X-Requested-With: XMLHttpRequest`; cross-origin auth calls must also match `AUTH_ALLOWED_ORIGINS` (or `FRONTEND_URL`). Access JWTs remain in frontend memory and expire after the configured short TTL.

## Legacy plaintext BYOK migration

No database column change is needed: `bots.provider_api_key` remains `TEXT`, containing a versioned `fernet:v1:` envelope after migration.

1. Back up the database and configure the final `PLATFORM_KEY_ENCRYPTION_KEY` on a controlled application host.
2. Temporarily keep `ALLOW_LEGACY_PLAINTEXT_BYOK=true` while old rows are readable.
3. From `backend`, run `python scripts/migrate_byok_keys.py` once. The command reports counts only and never prints key material.
4. Run it again to verify idempotence: `migrated=0` is expected.
5. Deploy all API/worker instances with the same Fernet key, then set `ALLOW_LEGACY_PLAINTEXT_BYOK=false`.

New and updated credentials are encrypted on write. Updating a legacy bot also encrypts its old key before the update commits. Omitted key fields preserve the ciphertext, a valid new key replaces it, and explicit clear stores `NULL`.

## Session behavior

Refresh rotation uses a conditional `revoked_at IS NULL` update, so one token can create exactly one successor. Reuse of an already rotated/revoked token is rejected. Password changes revoke every existing refresh session, then issue one brand-new current-browser cookie; other devices are signed out while the current browser stays signed in. Stateless access JWTs are not blacklisted and can remain valid only until their short expiry.
