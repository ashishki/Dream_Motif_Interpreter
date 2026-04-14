# Deployment Guide

Last updated: 2026-04-14

## 1. Deployment Philosophy

Dream Motif Interpreter remains a private, single-user deployment.
The recommended topology for Phase 6+ is multi-process but still operationally small.

Recommended canonical deployment documentation:

- Compose-first
- systemd optional for operators who prefer VPS-native service management

## 2. Current Backend Topology

Current backend services:

- API process
- worker process
- PostgreSQL
- Redis

The repository already includes [docker-compose.yml](/home/ashishki/Documents/dev/ai-stack/projects/Dream_Motif_Interpreter/docker-compose.yml) for PostgreSQL and Redis.

## 3. Planned Telegram-Enabled Topology

Recommended target service set:

```text
postgres
redis
api
worker
telegram-bot
optional: media-cleanup
optional: scheduled-sync
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
- workers start cleanly
- bot starts and rejects unauthorized chats
- tracing/logging configured
- media directory exists if voice is enabled
- cleanup policy is enabled if voice is enabled

## 8. Operational Documentation

Before production rollout of Phase 6+:

- [RUNBOOK_TELEGRAM_BOT.md](RUNBOOK_TELEGRAM_BOT.md)
- [RUNBOOK_VOICE_PIPELINE.md](RUNBOOK_VOICE_PIPELINE.md)
- [AUTH_SECURITY.md](AUTH_SECURITY.md)
- [ENVIRONMENT.md](ENVIRONMENT.md)
- [tasks_phase6.md](tasks_phase6.md)
