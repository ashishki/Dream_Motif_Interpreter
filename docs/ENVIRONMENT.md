# Environment and Configuration

Last updated: 2026-08-31

## 1. Current Backend Variables

The current backend expects:

```env
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/dmi
REDIS_URL=redis://localhost:6379/0
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REFRESH_TOKEN=...
GOOGLE_SERVICE_ACCOUNT_FILE=
GOOGLE_SERVICE_ACCOUNT_HOST_FILE=
GOOGLE_API_TIMEOUT_SECONDS=60
GOOGLE_DOC_ID=...
SECRET_KEY=<random value of at least 32 bytes>
ENV=development
BUILD_SHA=<deployed git commit SHA>
APP_IMAGE_REPOSITORY=dream-motif-interpreter
RUNTIME_STATE_FILE=/var/lib/dream-motif/runtime_extra_docs.json
```

Optional current tuning:

```env
EMBEDDING_MODEL=text-embedding-3-small
RETRIEVAL_THRESHOLD=0.20
BULK_CONFIRM_TOKEN_TTL_SECONDS=600
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_CHAT_ID=0
TELEGRAM_MINI_APP_URL=
TELEGRAM_WEBAPP_AUTH_MAX_AGE_SECONDS=86400
TELEGRAM_NUMERIC_FEEDBACK_ENABLED=false
ASSISTANT_MODEL=claude-haiku-4-5-20251001
VOICE_MEDIA_DIR=/tmp/dream_voice
VOICE_RETENTION_SECONDS=3600
VOICE_TRANSCRIPT_RETENTION_SECONDS=604800
AUTO_SYNC_ENABLED=false
AUTO_SYNC_INTERVAL_SECONDS=300
```

`SECRET_KEY` protects backend REST routes. Outside `ENV=test`/`testing` it must be nonblank,
at least 32 bytes long, and have sufficient character diversity. Generate one with
`python -c 'import secrets; print(secrets.token_urlsafe(32))'`; do not reuse a provider token.

`BUILD_SHA` is the deployed Git commit identifier returned by public `GET /health`. Set it in
the deployment pipeline so operator smoke tests can verify the running revision. It defaults to
`unknown` for local development.

`APP_IMAGE_REPOSITORY` is the Compose image repository used for application services. Compose tags
the shared app image as `APP_IMAGE_REPOSITORY:BUILD_SHA` so an operator can select a previous
release image during a rollback drill.

`ASSISTANT_MODEL` — Claude model used by the bounded tool-use loop. Defaults to `claude-haiku-4-5-20251001`.

`VOICE_MEDIA_DIR` — writable directory for temporary voice files. Default: `/tmp/dream_voice`.

`VOICE_RETENTION_SECONDS` — retention window for raw voice files (seconds). Default: `3600` (1 hour). A file is removed after its reply has first been durably staged; failed/retryable transcription keeps it only until the configured sweep boundary.

`VOICE_TRANSCRIPT_RETENTION_SECONDS` — retention window for operational voice transcripts used by reply-to-voice actions. Default: `604800` (7 days). The bot maintenance supervisor purges expired transcripts separately from raw audio.

`AUTO_SYNC_ENABLED` — enables lightweight Google Docs metadata checks followed by sync only when the document has changed. Default: `false`.

`AUTO_SYNC_INTERVAL_SECONDS` — interval between metadata checks. Default: `300` seconds.

`GOOGLE_API_TIMEOUT_SECONDS` — hard timeout for each Google Docs/Drive HTTP request. Default:
`60` seconds. Keep it below the durable worker stage timeout so a cancelled stage cannot leave an
unbounded background thread and a competing retry.

`TELEGRAM_NUMERIC_FEEDBACK_ENABLED` — enables the legacy Telegram 1–5 rating prompt and digit
capture. Default: `false`; keep disabled unless the UX is explicitly re-approved.

`TELEGRAM_MINI_APP_URL` — optional HTTPS URL opened by the bot's `/map`
command as a Telegram Web App button. The URL should point at the deployed
Dream Memory Map mini app surface; data reads still go through protected backend
routes such as `GET /dream-memory/state`.

`TELEGRAM_WEBAPP_AUTH_MAX_AGE_SECONDS` — maximum accepted age for Telegram
WebApp `initData` authentication on protected backend routes. Default: `86400`.

`RUNTIME_STATE_FILE` — path to runtime state for the active primary Google Doc, extra connected
docs, and cached document names. Compose points all relevant services at one persistent named
volume. The local default is `runtime_extra_docs.json`; it is ignored by git and must never be
committed because it contains operator-specific document identifiers. Every reader/writer also
uses a sibling `${RUNTIME_STATE_FILE}.lock` advisory file lock, and writes use fsync plus atomic
replace. API, bot and auto-sync must therefore see the same state directory, not separate mounts.
Use a local POSIX filesystem with reliable `flock`; unsupported network filesystems can defeat the
cross-process serialization guarantee.

## 2. Phase 6 Telegram Variables

The Telegram bot runtime requires:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_CHAT_ID=...
TELEGRAM_MINI_APP_URL=
TELEGRAM_WEBAPP_AUTH_MAX_AGE_SECONDS=86400
TELEGRAM_NUMERIC_FEEDBACK_ENABLED=false
ANTHROPIC_API_KEY=...
```

Phase 6 contract:

- `TELEGRAM_BOT_TOKEN` is required only for the separate bot process.
- `TELEGRAM_ALLOWED_CHAT_ID` is the single authorized chat ID.
- `TELEGRAM_MINI_APP_URL` enables the `/map` command to open the Dream Memory
  Map mini app as a Telegram Web App button.
- `TELEGRAM_WEBAPP_AUTH_MAX_AGE_SECONDS` bounds replay age for Telegram WebApp
  `initData` accepted by protected backend routes.
- `TELEGRAM_NUMERIC_FEEDBACK_ENABLED=false` keeps digit-only user replies available for numbered choices.
- `ANTHROPIC_API_KEY` is required for the bounded tool-use conversation loop.
- The bot runtime uses long polling: `python3 -m app.telegram`.
- Automatic Google Docs sync is a separate process: `python3 -m app.auto_sync`.
- Session history is persisted in the `bot_sessions` table — run migration 007 before starting the bot.
- Redis is required for restart-safe pending confirmations, reply targets and displayed result
  references. Outside test/development, an unavailable Redis is a deployment failure rather than
  a safe long-term degraded mode.
- Voice uses OpenAI Whisper and the two retention variables above; delivery progress is durable in
  PostgreSQL.

## 2.1 Google Docs Auto-Sync

When auto-sync is enabled, the system does not fetch the full Google Doc every cycle.

Instead it:

1. requests lightweight Google metadata
2. checks whether the document marker changed
3. runs the normal ingest sync only when there is a real change

Recommended starting values:

```env
AUTO_SYNC_ENABLED=true
AUTO_SYNC_INTERVAL_SECONDS=300
```

## 3. Google Docs Credential Note

### Current code path

The current codebase supports two Google Docs credential paths:

1. OAuth-style env credentials:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REFRESH_TOKEN`
- `GOOGLE_DOC_ID`

2. Service-account JSON file:

- `GOOGLE_SERVICE_ACCOUNT_FILE`
- `GOOGLE_DOC_ID`

Resolution order in code:

- if `GOOGLE_SERVICE_ACCOUNT_FILE` is set, `GDocsClient` loads service-account credentials from that file
- otherwise it falls back to the OAuth refresh-token flow

### Operational note

For local private setup, service-account auth is the simpler path if the Google Doc has already been shared with the service-account email.

For a direct process, `GOOGLE_SERVICE_ACCOUNT_FILE` is the path visible to that process. The base
Compose stack leaves it blank and does not mount a credential file, so OAuth-only and
Google-disabled boot do not depend on a host JSON path. To opt in to service-account auth in
Compose, set `GOOGLE_SERVICE_ACCOUNT_HOST_FILE` to an existing protected host file and include
`docker-compose.google-service-account.yml`; the overlay mounts it read-only and supplies the
container-visible path. The host-path variable has no effect without that overlay.

## 4. Secret Handling Rules

- secrets must come from environment or secret-mounted files
- do not commit `.env`
- do not commit credential JSON files
- do not put Telegram tokens, API keys, or Google credentials in docs, fixtures, or logs

## 5. Environment Profiles

Recommended profiles:

- `development`: local API, local bot, local Postgres/Redis
- `production`: private VPS or private host, persistent storage, supervised processes

## 6. Phase 9–10 Feature Flag Variables

```env
# Feature flags are read once at process startup because get_settings() is lru-cached; restart required after a change.
MOTIF_INDUCTION_ENABLED=true
RESEARCH_AUGMENTATION_ENABLED=false
RESEARCH_API_KEY=
```

`MOTIF_INDUCTION_ENABLED` — enables the implemented motif induction pipeline. Default: `true`.
Set it to `false` to skip new motif induction while keeping existing motifs readable. Migration
`009_add_motif_inductions` (or a later Alembic head) is required.

`RESEARCH_AUGMENTATION_ENABLED` — enables the Phase 10 research augmentation tool. When `false` (default), the `research_motif_parallels` assistant tool is unavailable. Set to `true` only after migration `010_add_research_results` has been applied and `RESEARCH_API_KEY` is configured.

`RESEARCH_API_KEY` — API key for the external search provider used by `ResearchRetriever`. Optional; required only when `RESEARCH_AUGMENTATION_ENABLED=true`. Must not be committed or logged.

See [ADR-010](adr/ADR-010-feature-flag-gating.md) for the rationale behind default-off gating.

## 7. Fixed Runtime Decisions

- Telegram ingress uses long polling.
- Voice transcription uses OpenAI Whisper.
- Raw audio and operational transcript retention are configured independently.
- External research stays provider-gated by `RESEARCH_AUGMENTATION_ENABLED` and
  `RESEARCH_API_KEY`.
