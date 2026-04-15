# Voice Pipeline

Last updated: 2026-04-15 (P7-T03 update — implemented)

## 1. Purpose

This document defines the voice-message path for Dream Motif Interpreter (Phase 7 implemented).

## 2. Goal

A user should be able to send a Telegram voice note and receive a grounded assistant response based on a transcript processed through the same assistant path as text.

## 3. Implementation Reference

For the voice ingress lifecycle, use:

- `~/Documents/dev/ai-stack/projects/film-school-assistant`

as the primary implementation reference.

Specifically reuse its proven pattern shape for:

- Telegram file download
- temporary media storage
- async acknowledgement to the user
- transcription handoff
- cleanup-oriented operational thinking

Do not copy its domain persistence model or assume local Whisper is mandatory for Dream Motif Interpreter.

## 4. Recommended Flow

1. Telegram voice update arrives.
2. Bot validates the sender.
3. Bot persists a media-event record.
4. Bot downloads the voice file to temporary storage.
5. Bot acknowledges that processing has started.
6. Bot enqueues a transcription job.
7. Worker transcribes the audio.
8. Transcript is routed through the normal text assistant flow.
9. Bot sends the final reply.
10. Raw media is deleted on a short retention schedule.

## 5. Recommended Initial Provider Strategy

Start with managed transcription.

Why:

- lower operational complexity
- no local Whisper packaging or model-management burden in Phase 7
- faster path to a production-ready voice interface

Local Whisper remains a future option if privacy or cost justifies the operational overhead.

## 6. Storage and Retention Rules

- raw audio is not canonical dream data
- transcript is not canonical dream data by default
- dream archive changes must still pass explicit domain flows

Implemented retention (Phase 7):

- raw audio is deleted **immediately** after successful transcription via `delete_local_voice_file`
- `cleanup_voice_media` (in `app/workers/cleanup.py`) provides a scheduled sweep for any files that
  survived the immediate deletion (e.g., due to transient failure)
- retention window is configurable via `VOICE_RETENTION_SECONDS` (default: 3600 seconds)
- only events in terminal states (`done`, `failed`) with `updated_at < cutoff` are eligible for sweep deletion

Environment variable:

```env
VOICE_RETENTION_SECONDS=3600   # default: 1 hour
```

Run the sweep cleanup periodically (e.g., cron or scheduled arq task):

```python
from app.workers.cleanup import cleanup_voice_media
await cleanup_voice_media(session_factory, retention_seconds=settings.VOICE_RETENTION_SECONDS)
```

## 7. Failure Modes

Must handle:

- download failure
- unsupported media/path failure
- transcription provider failure
- timeout
- duplicate processing
- cleanup failure

## 8. Operational Rules

- media directory must be explicit and writable
- cleanup schedule must be documented
- failures must be traceable to a media job ID
- logs must not include raw dream content or credential data

## 9. Testing Requirements

- voice ingress unit tests
- transcript success-path integration test
- transcription failure-path test
- cleanup job test
- duplicate-job prevention or idempotency test

Execution sequencing for this work is tracked in:

- [docs/tasks_phase6.md](tasks_phase6.md)
