# Deployment Guide

Last updated: 2026-04-21

## 1. Deployment Philosophy

Dream Motif Interpreter remains a private, single-user deployment.
The recommended topology for Phase 6+ is multi-process but still operationally small.

Recommended canonical deployment documentation:

- Compose-first
- systemd optional for operators who prefer VPS-native service management

## 2. Current Backend Topology

Current backend services:

- API process
- worker process (arq)
- PostgreSQL (pgvector)
- Redis

`docker-compose.yml` in the repository root defines `postgres` and `redis` infrastructure services.

## 3. Phase 6 Telegram-Enabled Topology

Phase 6 service set:

```text
postgres       — primary persistent store (dreams, themes, bot sessions)
redis          — ephemeral job-state, arq worker coordination
api            — FastAPI HTTP layer (python3 -m uvicorn app.main:app)
telegram-bot   — long-polling Telegram bot (python3 -m app.telegram)
auto-sync      — lightweight Google Docs metadata polling + conditional sync (python3 -m app.auto_sync)
```

Today the minimal always-on runtime is:

- Postgres
- Redis
- API
- Telegram bot
- auto-sync

Pre-start prerequisite: run `alembic upgrade head` to apply migrations including `007_add_bot_sessions`.

Optional future services:

```text
media-cleanup
```

## 4. Recommended Initial Telegram Deployment Mode

Start with polling.

Why:

- simplest private deployment path
- no public webhook endpoint required
- easier debugging during Phase 6

Webhook can be reconsidered later if operations require it.

## 5. Voice Deployment Notes

Phase 7 adds:

- temporary voice-media directory
- transcription jobs
- cleanup schedule

Deployment must define:

- writable media path
- retention period
- cleanup mechanism
- transcription provider credentials or binaries

## 6. Google Docs Credential Deployment Note

Current code expects env-driven OAuth-style credentials.
If implementation later adopts service-account JSON, deployment instructions must add:

- secure placement of the JSON file
- file path mounting
- permission hardening
- rotation/update procedure

Until then, keep current docs explicit: service-account JSON may exist operationally, but it is not yet the documented runtime contract.

## 7. Minimum Production Checklist

- Postgres reachable
- Redis reachable
- API starts cleanly
- bot starts and rejects unauthorized chats
- auto-sync loop starts cleanly
- Google Docs credentials are valid
- tracing/logging configured
- media directory exists if voice is enabled
- cleanup policy is enabled if voice is enabled

## 8. Local Background Run

For a small private deployment, it is acceptable to run the app as a few background processes:

```text
postgres
redis
api
telegram-bot
auto-sync
```

Recommended local start order:

1. infrastructure (`docker compose up -d postgres redis`)
2. migrations (`alembic upgrade head`)
3. API (`python3 -m app.main`)
4. Telegram bot (`python3 -m app.telegram`)
5. auto-sync (`python3 -m app.auto_sync`)

For persistent boot-time startup, prefer `systemd` units instead of manual background processes.
See [SYSTEMD_SETUP.md](SYSTEMD_SETUP.md).

## 9. Operational Documentation

Before production rollout of Phase 6+:

- [RUNBOOK_TELEGRAM_BOT.md](RUNBOOK_TELEGRAM_BOT.md)
- [RUNBOOK_VOICE_PIPELINE.md](RUNBOOK_VOICE_PIPELINE.md)
- [AUTH_SECURITY.md](AUTH_SECURITY.md)
- [ENVIRONMENT.md](ENVIRONMENT.md)
- [tasks_phase6.md](tasks_phase6.md)
