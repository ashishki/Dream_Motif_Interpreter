# Environment and Configuration

Last updated: 2026-04-14

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
```

## 2. Planned Phase 6+ Variables

The Telegram-enabled system is expected to add variables such as:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_CHAT_ID=...
TELEGRAM_ALLOWED_USER_ID=...
TELEGRAM_MODE=polling
BOT_SESSION_RETENTION_DAYS=30
VOICE_MEDIA_DIR=data/voice
VOICE_MEDIA_RETENTION_HOURS=48
TRANSCRIPTION_PROVIDER=managed
TRANSCRIPTION_MODEL=...
```

These names are planning placeholders until implementation finalizes the exact contract.

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

## 6. Config Decision Notes

Must be finalized during implementation:

- polling vs webhook mode
- transcription provider config
- media retention settings
- whether Google Docs auth remains OAuth-env based or moves to service-account JSON
