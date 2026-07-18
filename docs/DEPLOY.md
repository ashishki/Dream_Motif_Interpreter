# Deployment Guide

Last updated: 2026-07-18

## 1. Deployment boundary

Dream Motif Interpreter is a private, single-operator deployment. It is not a public multi-user service and does not provide a security or availability SLA.

The product-managed PostgreSQL archive is the source of truth for the private beta. Google Docs is an optional import/mirror adapter. A Google or provider failure may degrade sync, search, transcription, or interpretation, but must not delete a committed dream.

See [ADR-011](adr/ADR-011-private-beta-source-of-truth.md).

## 2. Canonical topology

```text
postgres       — durable dreams, notes, themes, chunks, sessions and controls
redis          — ephemeral locks, job state and notifications
migrate        — one-shot Alembic upgrade before application processes
api            — FastAPI and protected Mini App data routes
telegram-bot   — long-polling private bot

auto-sync      — Google Drive metadata polling and conditional ingestion
```

The Compose file also creates:

- `postgres_data` — durable database volume;
- `runtime_config` — temporary shared source configuration used by the current file-backed Google source settings;
- `voice_media` — temporary voice files that survive a bot process restart long enough for cleanup.

`runtime_config` is a transition mechanism, not the target source model. Source ownership must move to PostgreSQL before multi-user work.

## 3. Prerequisites

- Docker Engine with Compose v2;
- a private HTTPS host for Telegram Mini App usage;
- a Telegram bot token and allowed private chat ID;
- PostgreSQL/Redis ports available if exposed locally;
- provider credentials for features that are enabled;
- Google credentials only when Google Docs import/mirror is used.

## 4. Environment

Create a local environment file:

```bash
cp .env.example .env
```

Replace all placeholder values. Never commit `.env`, provider keys, Telegram tokens, Google tokens, private document IDs, real dream text, or exported archive content.

The current Settings model still requires `GOOGLE_DOC_ID`. Use a non-secret placeholder only when Google is intentionally disconnected; capture remains managed by PostgreSQL, while Google operations will report partial failure.

## 5. Start

```bash
docker compose config
docker compose build
docker compose up -d
```

Compose runs the `migrate` job before API, bot and auto-sync.

Inspect status:

```bash
docker compose ps
docker compose logs --tail=100 api telegram-bot auto-sync
```

Health:

```bash
curl http://127.0.0.1:8000/health
```

Expected behavior:

- HTTP 200 when storage is reachable and the index is not stale;
- HTTP 503 when storage is unavailable or the index is older than `MAX_INDEX_AGE_HOURS`;
- an empty but reachable archive may return HTTP 200 with `index_last_updated=null`.

## 6. Mini App

The HTML shell is served at:

```text
/dream-memory/mini-app
```

The shell contains no dream data and is intentionally public. All state/export/privacy routes remain protected by either:

- `X-API-Key`, or
- validated Telegram WebApp `initData` sent as `X-Telegram-Init-Data`.

`TELEGRAM_MINI_APP_URL` must point to the HTTPS URL exposed to Telegram. The current graph shell is a prototype and is not the full archive/coding private-beta UI.

## 7. Google Docs

Current implementation supports:

- OAuth refresh credentials or service-account credentials;
- reading configured Docs;
- metadata polling;
- importing recognized entries and notes;
- targeted writes and retry status.

Current limitations:

- manual/env source configuration is still required;
- metadata polling is not the final Drive change-feed contract;
- external body edits and deletion do not have complete reconciliation semantics;
- full symmetric bidirectional sync must not be claimed.

The target onboarding is OAuth consent plus Google Picker, followed by durable Drive change tokens, optional watch notifications and polling fallback.

## 8. Data protection

Minimum private-beta posture:

1. Restrict the host and database network to the operator.
2. Terminate HTTPS at a maintained reverse proxy.
3. Store `.env` outside source control with least-readable permissions.
4. Back up `postgres_data` using encrypted storage.
5. Test restore into an isolated environment.
6. Rotate provider and Telegram credentials after any suspected exposure.
7. Do not send real dream text to external research tools.
8. Keep raw voice media short-lived and verify cleanup.
9. Treat Google document names/IDs and Telegram identifiers as private metadata.

## 9. Backup and restore

A private beta is not ready until both backup and restore are rehearsed.

Example logical backup:

```bash
docker compose exec -T postgres \
  pg_dump -U "${POSTGRES_USER:-postgres}" "${POSTGRES_DB:-dream_motif}" \
  > private-backup.sql
```

Store the result encrypted and outside the repository.

Restore must be tested in a disposable database before relying on it for recovery. Do not overwrite the live archive as a test.

## 10. Update and rollback

Before update:

1. create an encrypted database backup;
2. record the deployed commit SHA;
3. inspect migration upgrade and downgrade behavior;
4. run CI-equivalent checks;
5. deploy to a private staging copy when a migration or sync change is involved.

Update:

```bash
docker compose build
docker compose up -d
```

Rollback application code by redeploying the previous commit/image. Roll back a database migration only when its downgrade is explicitly tested and no newer data would be lost. Otherwise restore from backup into a separate instance and reconcile.

## 11. Operational checks

- API health is not falsely green when PostgreSQL is unavailable.
- Telegram rejects unauthorized chats.
- capture succeeds when embeddings or Google are unavailable.
- failed Google writes are visible as partial failure and retryable.
- auto-sync state exposes failed/stale/running/synced distinctly.
- source settings are consistent across API, bot and auto-sync.
- no raw dream text, title, note, prompt, token, local media path or private document ID appears in normal logs.
- the current graph-only delete action is not presented as full archive deletion.

## 12. Known private-beta blockers

The runtime is still single-user. Before admitting a second user, implement workspace ownership and isolation across every table, query, vector, source, job, credential and audit event.

The current Mini App is graph-first and does not yet provide the archive/detail/code/sync user journeys required by the private-beta gate. Track the rollout in [the private-beta audit](reviews/PRIVATE_BETA_AUDIT_2026-07-18.md).
