# Deployment Guide

Last updated: 2026-08-30

## 1. Runtime boundary

Dream Motif Interpreter is a private, single-operator deployment. The implemented Compose
topology is:

- `postgres`: PostgreSQL 16 with pgvector; canonical archive, sessions, durable jobs and receipts
- `redis`: sync coordination plus short-lived Telegram workflow state
- `migrate`: one-shot `alembic upgrade head`
- `api`: FastAPI on port 8000
- `telegram-bot`: long-polling Telegram adapter plus durable job supervisors
- `auto-sync`: optional Google Docs metadata polling, enabled through the `autosync` profile

There is no required arq process. Dream post-processing and voice delivery are claimed from
PostgreSQL by the Telegram runtime, with leases and restart recovery.

## 2. Compose deployment

Create the untracked environment file and replace every placeholder:

```bash
cp .env.example .env
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Put the generated value in `SECRET_KEY`, set a separate random `POSTGRES_PASSWORD`, configure
Telegram/provider credentials, then:

```bash
export BUILD_SHA="$(git rev-parse HEAD)"
export DEPLOY_BACKUP_DIR=/var/backups/dream-motif
./scripts/deploy_compose.sh --backup-dir "$DEPLOY_BACKUP_DIR"
docker compose ps
curl --fail http://127.0.0.1:8000/health
```

`scripts/deploy_compose.sh` is the required rollout entry point, including for the first launch.
It quiesces every application writer (`api`, `telegram-bot`, `auto-sync`), waits for PostgreSQL and
Redis, writes a custom-format PostgreSQL dump plus manifest into an absolute backup directory,
validates the dump with `pg_restore --list`, builds the requested revision, runs Alembic to
completion, and starts the application only after migration succeeds. After migration, it starts
the API first and restarts Telegram/auto-sync only after the API reports `/ready` for the intended
`BUILD_SHA`, so background writers do not accept new work during a failed readiness gate. If
backup, build, migration, or readiness fails after writers were stopped, writers remain stopped. A
plain `docker compose up` is not a safe upgrade procedure because a previous application revision
can continue writing while the schema changes.

The script refuses a dirty Git worktree and requires `BUILD_SHA` to equal the checked-out `HEAD`.
Commit the intended release before rollout; do not use an arbitrary SHA to label a locally modified
build.

The API is explicitly bound to `0.0.0.0` inside its container. `BUILD_SHA` is baked into the
image, recorded as the image's OCI revision label, and returned by `/health`; rebuild whenever it
changes. Compose tags all application services as
`${APP_IMAGE_REPOSITORY:-dream-motif-interpreter}:${BUILD_SHA:-unknown}`. Keep previous release
tags until the rollback drill for that release has passed. Start optional auto-sync only when
`AUTO_SYNC_ENABLED=true`:

```bash
./scripts/deploy_compose.sh --backup-dir "$DEPLOY_BACKUP_DIR" --with-auto-sync
```

Compose persists:

- PostgreSQL in `postgres_data`
- downloaded/retryable voice media in `voice_media`
- active Google Docs source configuration in `runtime_state`

There is no database-password fallback: Compose refuses to render until `POSTGRES_PASSWORD` is
set. The required-env guard is centralized on the Postgres service; dependent app DSNs reference
the same value without duplicating the guard text. PostgreSQL, Redis and the API publish to
`127.0.0.1` by default. Treat changing any bind address as a separate exposure decision requiring a
firewall/reverse proxy and the backend auth controls. Use the host's secret manager or a protected
environment file; never reuse `SECRET_KEY` as the database password.

## 3. Migrations and durable work

Deploy only at Alembic head. The current hardening chain includes:

- `021_voice_delivery_durability`: idempotent Telegram voice ingress, leases and durable delivery
- `022_capture_idempotency`: stable source identity, note/write receipts and uniqueness
- `023_dream_processing_jobs`: independent leased stages for index, analysis, motif and Google Docs
- `024_restore_graph_controls`: append-only restore for hidden graph items
- `025_note_processing_jobs`: independently leased indexing and Google Docs delivery for notes

Text capture commits the dream and its stage jobs in one transaction. A provider outage therefore
cannot erase the archive entry. Each stage retries independently; Google Docs uses both a database
receipt and a document-side idempotency marker. A note acknowledgement has the same narrow meaning:
the canonical note and its durable jobs were committed; indexing and Google Docs run in the
background. Never repair either queue by deleting rows.

Schema migrations require a quiesced application even when a specific revision appears additive:

1. stop `api`, `telegram-bot` and `auto-sync`
2. start/wait for PostgreSQL and Redis
3. create a custom-format `pg_dump`, verify it with `pg_restore --list`, and record its manifest
4. run `alembic upgrade head` and require exit code 0
5. start the new API revision
6. require `/ready` to report `status=ok` and the intended `BUILD_SHA`
7. start the Telegram bot, then optional auto-sync

The provided script enforces this order. Do not start application dependencies implicitly through
Compose while an upgrade is in progress.

## 4. Voice lifecycle and retention

`VOICE_MEDIA_DIR` must be writable and persistent for the bot container. The default Compose path
is `/var/lib/dream-voice`. The database record is created before download acknowledgement, and the
downloaded path is persisted before background processing begins.

- transient transcription failures retain raw audio for a bounded retry window
- a reply is persisted before raw media is removed
- Telegram delivery resumes from the stored chunk cursor
- periodic maintenance retries due work, removes expired raw files and purges operational
  transcripts after `VOICE_TRANSCRIPT_RETENTION_SECONDS`

An operational transcript is not an archive dream. It becomes one only after the user explicitly
saves it.

## 5. Redis requirement

PostgreSQL remains the durable system of record. Redis holds expiring interaction context such as
displayed dream references, pending notes, pending dream confirmation and interpretation consent.
The bot checks Redis at startup. A production/staging rollout must fail rather than silently lose
restart safety; development/test may report an explicit degraded state.

Check connectivity without printing values that can contain private text:

```bash
docker compose exec redis redis-cli ping
```

## 6. Google Docs credentials

Two implemented paths are supported:

1. `GOOGLE_SERVICE_ACCOUNT_FILE` pointing to a mounted JSON file shared with the target document.
2. OAuth refresh-token variables: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and
   `GOOGLE_REFRESH_TOKEN`.

Service account configuration takes precedence. The base Compose file deliberately has no
credential bind mount, so missing service-account credentials do not prevent OAuth-only or
Google-disabled boot. For a service account, set an absolute host path and opt in to the overlay:

```bash
export GOOGLE_SERVICE_ACCOUNT_HOST_FILE=/absolute/path/google-service-account.json
docker compose -f docker-compose.yml \
  -f docker-compose.google-service-account.yml config --quiet
./scripts/deploy_compose.sh --google-service-account
```

The overlay requires the source path to be set, mounts it read-only as
`/run/secrets/google-service-account.json`, and sets the container-visible
`GOOGLE_SERVICE_ACCOUNT_FILE`. It is intentionally not included by a plain `docker compose up`.
Ensure the non-root container user can read the host file; do not bake or copy it into the image.
The active document configuration is stored separately in `RUNTIME_STATE_FILE`. API, bot and
auto-sync share the same volume; updates use a sibling advisory lock file plus atomic
write/fsync/replace, so readers in another process never observe partial JSON. Keep the state file
and its `.lock` file on a local filesystem that supports POSIX `flock`; network filesystems with
unreliable advisory locking are unsupported.

## 7. Rollout verification

Before treating a rollout as healthy:

1. The deploy script's migration command exited 0; `docker compose ps` shows Postgres/Redis
   healthy, the pre-migration backup manifest exists, and the API passed readiness before
   bot/auto-sync were restarted.
2. `/health.status` is `ok` (or an understood indexing backlog) and `health.build_sha` equals the
   intended Git commit; `unknown` is not acceptable in production.
3. Redis returns `PONG`.
4. A synthetic/private smoke dream creates one archive row and four stage jobs, reaches terminal
   stage success, appears once in Google Docs and is searchable.
5. Replaying the same Telegram update/message ID creates neither a duplicate dream nor a duplicate
   document append. Sending the same words as a new Telegram message creates a separate legitimate
   archive entry.
6. A note acknowledgement first reports queued background work; its `index` and `gdocs` jobs then
   reach success independently, without a duplicate insertion on replay.
7. A voice smoke reaches `delivered`, and a forced Telegram send failure remains recoverable from
   its durable chunk cursor.
8. `voice_media` and `runtime_state` are writable by the non-root container user.

`GET /health` checks database/index health and exposes deployment identity. It does not prove
Redis, Telegram, Google Docs, provider quota, the whole outbox or user-perceived quality; keep the
runbook smoke tests as separate release gates.

## 8. Direct-process deployment

For systemd/VPS operation, use the same quiesced order:

1. stop API, Telegram and auto-sync services and wait for them to exit
2. confirm PostgreSQL and Redis are healthy
3. run `alembic upgrade head` and stop on any non-zero exit
4. start `uvicorn app.main:app --host 0.0.0.0 --port 8000`
5. start `python -m app.telegram`
6. optionally start `python -m app.auto_sync`

See [SYSTEMD_SETUP.md](SYSTEMD_SETUP.md), [RUNBOOK_TELEGRAM_BOT.md](RUNBOOK_TELEGRAM_BOT.md),
[RUNBOOK_VOICE_PIPELINE.md](RUNBOOK_VOICE_PIPELINE.md), [AUTH_SECURITY.md](AUTH_SECURITY.md) and
[ENVIRONMENT.md](ENVIRONMENT.md).
