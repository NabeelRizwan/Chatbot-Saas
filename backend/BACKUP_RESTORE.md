# PostgreSQL backup and restore runbook

Use PostgreSQL client tools matching the server major version. Test restoration in an isolated database; never rehearse against production.

## Backup

Set `DATABASE_URL` in the shell without printing it, then run:

```sh
pg_dump --dbname="$DATABASE_URL" --format=custom --no-owner --no-privileges --file=chatbot-saas.dump
pg_restore --list chatbot-saas.dump > chatbot-saas.dump.list
```

Back up/version the private object-storage bucket at the same recovery point. Store the database dump, bucket recovery point, application revision, Alembic revision, and `PLATFORM_KEY_ENCRYPTION_KEY` in protected systems with separate access controls. During the additive rollout, separately retain any original uploads still referenced only by legacy `file_path` rows. Never commit them.

## Restore drill

Create an empty isolated database and set `RESTORE_DATABASE_URL` to it:

```sh
createdb chatbot_saas_restore_test
pg_restore --dbname="$RESTORE_DATABASE_URL" --clean --if-exists --no-owner --no-privileges chatbot-saas.dump
```

Restore the bucket snapshot/version to an isolated private bucket and point both API and Worker at it. Restore legacy file originals only when the database manifest still contains `file_path`-only rows. Start the API and worker with the restored database/Redis and no public traffic. Confirm:

1. `GET /health/ready` is 200 and Alembic is at head.
2. A known organization and user can authenticate.
3. A known bot retains provider/model/status/widget/origin configuration without exposing secrets.
4. Knowledge documents, websites, active versions, chunks, and pgvector dimensions/counts match the backup manifest.
5. A grounded bot query returns expected evidence and a source link.
6. Quota usage/reservations and conversation analytics remain internally consistent.
7. A restored source object can be downloaded to a worker temp file, integrity-checked, reprocessed, and removed locally while the durable object remains.

Record the dump checksum, start/end time, restored row-count manifest, application revision, and the operator. Destroy the isolated restore database and files only after evidence is retained according to policy.

## Recovery notes

- Redis is not the source of truth for ingestion jobs. After database recovery, start Redis and the worker; periodic reconciliation repairs durable jobs whose dispatch was interrupted.
- Redis persistence is still recommended to reduce recovery time and preserve rate-limit/cache state.
- If a forward migration fails, do not run ad-hoc schema edits. Restore the verified pre-deploy dump or repair through a reviewed migration.
- Do not restore production secrets into an environment accessible to untrusted users.
