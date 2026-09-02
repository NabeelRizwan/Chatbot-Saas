# Production Operations

## Deploy or update

1. Review the diff, migration head, dependency lockfiles, and configuration changes.
2. Back up PostgreSQL before any migration and confirm the latest bucket objects are retained.
3. Deploy the same immutable commit to Worker and Backend; deploy Frontend when browser-facing variables or code changed.
4. Confirm Worker heartbeat, `/health/live`, `/health/ready`, login/refresh, one chat, and one queued ingestion job.
5. Watch error classification, provider latency/429s, crawl page usage, queue depth, failed jobs, DB pool pressure, and response latency during rollout.

## Rollback

Roll back application services to the last known-good immutable commit/image. The production-hardening migration is additive and intentionally has no destructive downgrade. If an older application cannot tolerate the additive schema, restore the pre-deploy database backup in a controlled maintenance window. Never drop columns or rewrite migration history as an emergency shortcut. Preserve the credential-encryption key and object bucket.

## Backups

- Enable automated PostgreSQL backups and practice a restore before the pilot.
- Enable bucket retention/versioning if the selected provider supports it.
- Back up configuration inventories, not secret values in source control.
- Record the deployed commit, migration revision, and restore point for each release.

## Troubleshooting

| Symptom | Check | Safe response |
| --- | --- | --- |
| Worker unavailable | Redis reachability, worker logs, heartbeat key, queue name, same commit/config | Restore dependency/config, restart one worker, then retry failed jobs through the existing lifecycle |
| Redis unavailable | `REDIS_URL`, TLS/network policy, connection timeouts, service metrics | Restore Redis; production readiness must remain false and ARQ must not silently become local background work |
| Provider 429/quota | Normalized error kind, bot provider/model, credential-profile status, provider retry hint and quota console | Wait for reset or assign an authorized same-provider credential; do not switch provider/model implicitly |
| Provider auth/model error | Bot config, BYOK/profile/default resolution, profile provider/status | Correct only the affected bot/profile; never log or return the secret |
| Firecrawl quota/failure | provider audit, pages requested/crawled/indexed, skipped/failed URLs, quota | Reduce the configured bounded scope or restore quota, then use the existing retry/recrawl path |
| Failed ingestion | job customer-safe error, source lifecycle, worker logs, source-object existence | Keep the active corpus, correct the cause, retry/reindex from the durable source |
| Object storage unavailable | bucket endpoint/region, credentials, private policy, head-bucket result | Restore storage; readiness remains false. Do not enable local production fallback |
| DB or migration unhealthy | DB reachability, pool metrics, current/head revision | Stop rollout, restore DB access, and run only the committed additive migration path |

## Source-object reconciliation

Database deletion is authoritative and object deletion is best-effort after the final DB reference is removed. Monitor deletion warnings and periodically compare private object keys with `Document.storage_provider/storage_key`; delete confirmed unreferenced objects with an audited maintenance procedure. Before removing legacy API/worker disks, migrate any pre-object-storage `file_path` originals to private object storage and verify their hashes. Do not re-crawl or re-embed merely to move the original file.

## Basic monitoring

Alert on `/health/live` failure, sustained `/health/ready` failure, missing worker heartbeat, Redis/DB/storage errors, queue age/depth, repeated job failures, provider 429/auth/5xx classifications, Firecrawl quota, ingestion coverage drops, chat p95 latency, and tenant quota rejection rate. Never include API keys, refresh tokens, authorization headers, decrypted BYOK values, prompts containing sensitive customer data, or raw bucket credentials in alerts.
