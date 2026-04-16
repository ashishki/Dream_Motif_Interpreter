# Environment and Configuration

Last updated: 2026-04-15

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
GOOGLE_DOC_ID=...
SECRET_KEY=...
ENV=development
```

Optional current tuning:

```env
EMBEDDING_MODEL=text-embedding-3-small
RETRIEVAL_THRESHOLD=0.35
MAX_INDEX_AGE_HOURS=24
BULK_CONFIRM_TOKEN_TTL_SECONDS=600
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_CHAT_ID=0
ASSISTANT_MODEL=claude-haiku-4-5-20251001
VOICE_MEDIA_DIR=/tmp/dream_voice
VOICE_RETENTION_SECONDS=3600
```

`ASSISTANT_MODEL` — Claude model used by the bounded tool-use loop. Defaults to `claude-haiku-4-5-20251001`.

`VOICE_MEDIA_DIR` — writable directory for temporary voice files. Default: `/tmp/dream_voice`.

`VOICE_RETENTION_SECONDS` — retention window for raw voice files (seconds). Default: `3600` (1 hour). Files are deleted immediately after transcription and swept by cleanup for any survivors.

## 2. Phase 6 Telegram Variables

The Telegram bot runtime requires:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_CHAT_ID=...
ANTHROPIC_API_KEY=...
```

Phase 6 contract:

- `TELEGRAM_BOT_TOKEN` is required only for the separate bot process.
- `TELEGRAM_ALLOWED_CHAT_ID` is the single authorized chat ID.
- `ANTHROPIC_API_KEY` is required for the bounded tool-use conversation loop.
- The bot runtime uses long polling: `python3 -m app.telegram`.
- Session history is persisted in the `bot_sessions` table — run migration 007 before starting the bot.

Deferred for later phases:

- `TELEGRAM_ALLOWED_USER_ID`
- voice/media retention variables
- transcription provider variables

## 3. Google Docs Credential Note

### Current code path

The current codebase expects Google Docs access through environment-driven OAuth-style credentials:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REFRESH_TOKEN`
- `GOOGLE_DOC_ID`

### Operational note for planned work

If the operator already has a service-account JSON credential file and the target Google Doc has been shared with that service-account email, keep that credential available for implementation.

Important:

- service-account JSON auth is not yet the documented current code path
- do not describe it as implemented unless the code is changed to support it
- if implementation switches to service-account auth, document that change explicitly and update deployment instructions accordingly

## 4. Secret Handling Rules

- secrets must come from environment or secret-mounted files
- do not commit `.env`
- do not commit credential JSON files
- do not put Telegram tokens, API keys, or Google credentials in docs, fixtures, or logs

## 5. Environment Profiles

Recommended profiles:

- `development`: local API, local bot, local Postgres/Redis
- `production`: private VPS or private host, persistent storage, supervised processes

## 6. Phase 9–10 Feature Flag Variables (Planned)

```env
# Feature flags are read once at process startup because get_settings() is lru-cached; restart required after a change.
MOTIF_INDUCTION_ENABLED=false
RESEARCH_AUGMENTATION_ENABLED=false
RESEARCH_API_KEY=
```

`MOTIF_INDUCTION_ENABLED` — enables the Phase 9 motif induction pipeline. When `false` (default), ingest does not call `MotifService` and the `get_dream_motifs` assistant tool is unavailable. Set to `true` only after migration `009_add_motif_inductions` has been applied.

`RESEARCH_AUGMENTATION_ENABLED` — enables the Phase 10 research augmentation tool. When `false` (default), the `research_motif_parallels` assistant tool is unavailable. Set to `true` only after migration `010_add_research_results` has been applied and `RESEARCH_API_KEY` is configured.

`RESEARCH_API_KEY` — API key for the external search provider used by `ResearchRetriever`. Optional; required only when `RESEARCH_AUGMENTATION_ENABLED=true`. Must not be committed or logged.

See [ADR-010](adr/ADR-010-feature-flag-gating.md) for the rationale behind default-off gating.

## 7. Config Decision Notes

Must be finalized during implementation:

- polling vs webhook mode
- transcription provider config
- media retention settings
- whether Google Docs auth remains OAuth-env based or moves to service-account JSON
- external search provider selection for Phase 10 (`RESEARCH_API_KEY`)
