# Runbook — Voice Pipeline

Last updated: 2026-04-15 (P8-T01 update — reflects Phase 7 implemented behavior)

## 1. Purpose

Operate and troubleshoot the voice-message path for Dream Motif Interpreter (Phase 7 implemented).

## 2. Provider

Transcription is provided by **OpenAI Whisper API** (`whisper-1` model, managed).

No local Whisper installation or model management is required. All transcription is done via `asyncio.to_thread` wrapping the synchronous OpenAI client call.

## 3. Startup Checklist

- `OPENAI_API_KEY` is set and valid (required for transcription)
- `VOICE_MEDIA_DIR` is a writable directory (default: `/tmp/dream_voice`)
- `VOICE_RETENTION_SECONDS` is set (default: `3600` — 1 hour)
- Database migration `008_add_voice_media_events` has been applied
- `telegram-bot` service is running (transcription task runs inside the bot process)

No separate worker process is required. Transcription runs as an `asyncio.create_task` within the bot event loop.

## 4. VoiceMediaEvent Status Lifecycle

Each voice message creates a `VoiceMediaEvent` row with a UUID identifier.

```
received → transcribed → done
         ↘
           failed
```

| Status       | Meaning                                           |
|--------------|---------------------------------------------------|
| `received`   | Event row created; download not yet complete      |
| `transcribed`| Whisper API returned transcript; chat pending     |
| `done`       | Assistant reply sent; file deleted immediately    |
| `failed`     | Any step failed; user was notified                |

Terminal states: `done`, `failed`.

## 5. Raw Audio Retention

Two-tier cleanup is in place:

**Immediate:** `delete_local_voice_file(local_path)` is called by `transcribe_and_reply` after successful reply. Raw audio is deleted as soon as the reply is sent.

**Sweep:** `cleanup_voice_media(session_factory, retention_seconds=...)` deletes files for events in terminal states with `updated_at < now - VOICE_RETENTION_SECONDS`. Run periodically (e.g., cron or scheduled task) to catch any files that survived a transient failure.

```python
from app.workers.cleanup import cleanup_voice_media
await cleanup_voice_media(session_factory, retention_seconds=settings.VOICE_RETENTION_SECONDS)
```

## 6. Common Failure Modes

### Voice download fails

Symptoms: user receives "Could not download your voice message" reply; bot log shows `Voice download failed for message_id=... event_id=...`.

Check:
- Telegram Bot API connectivity
- `VOICE_MEDIA_DIR` exists and is writable (`ls -la $VOICE_MEDIA_DIR`)
- disk space on the host

Recovery: the VoiceMediaEvent row is created but remains at `received` status. Rerun `cleanup_voice_media` to sweep any partial files.

### Transcription fails (OPENAI_API_KEY missing)

Symptoms: user receives "I could not transcribe your voice note"; bot log shows `RuntimeError: OPENAI_API_KEY is not set`.

Check:
- `OPENAI_API_KEY` env var is set in the running process
- restart the `telegram-bot` service after setting the key

### Transcription fails (API error)

Symptoms: user receives "I could not transcribe your voice note"; bot log shows `Transcription failed for event_id=...`.

Check:
- OpenAI API status
- quota limits on the account
- audio file format (must be `.ogg` — Telegram default)

The VoiceMediaEvent status is updated to `failed`. The raw file remains on disk until the cleanup sweep removes it.

### handle_chat fails after transcription

Symptoms: user receives "I could not transcribe your voice note"; bot log shows `handle_chat failed after transcription for event_id=...`.

Check:
- `ANTHROPIC_API_KEY` is valid
- Anthropic API status
- assistant model availability (`ASSISTANT_MODEL`)

### Bot reply fails to send

Symptoms: transcription succeeds but user receives nothing; log shows `Failed to send Telegram reply for chat_id=...`.

Note: the `transcribe_and_reply` worker creates a standalone `Bot(token=...)` to send the final reply. This is separate from the polling Application instance.

Check:
- bot token remains valid
- Telegram API connectivity from host

### Raw media files accumulate

Symptoms: disk usage grows under `VOICE_MEDIA_DIR`.

Check:
- whether the cleanup sweep is scheduled and running
- log for `Deleted voice media event_id=` or `Failed to delete voice media` entries
- VoiceMediaEvent rows stuck in non-terminal state (query: `SELECT id, status, updated_at FROM voice_media_events WHERE status NOT IN ('done', 'failed')`)

If files persist beyond retention, delete manually and record the incident:
```bash
ls -la $VOICE_MEDIA_DIR
rm -i $VOICE_MEDIA_DIR/*.ogg   # confirm each before deletion
```

## 7. Diagnostics

### Find an event by Telegram message ID

```sql
SELECT id, chat_id, status, local_path, created_at, updated_at
FROM voice_media_events
WHERE telegram_message_id = <message_id>;
```

### List recent failures

```sql
SELECT id, chat_id, status, updated_at
FROM voice_media_events
WHERE status = 'failed'
ORDER BY updated_at DESC
LIMIT 20;
```

### Check active transcription tasks (runtime)

The bot keeps active tasks in `bot_data["_transcription_tasks"]`. No external visibility; use logs.

Key log patterns:
- `Transcription task enqueued event_id=... duration=...s`
- `Transcription succeeded event_id=... chars=...`
- `Transcription failed for event_id=...`
- `handle_chat failed after transcription for event_id=...`
- `Deleted local voice file after transcription path=...`

## 8. Recovery Rules

- failed jobs are traceable by `event_id` (UUID) across logs and DB
- manual retries are not supported — user must resend the voice note
- if raw media remains after repeated failure, clean manually and update the event status:
  ```sql
  UPDATE voice_media_events SET status = 'failed', local_path = ''
  WHERE id = '<event_id>';
  ```
- retries at the API level are the provider's responsibility (OpenAI SDK handles transient errors)

## 9. Logging Rules

- log identifiers: `event_id`, `chat_id`, `message_id`, `path` (filename only, not full path with content)
- log status transitions and char counts; never log transcript text or raw dream content
- `chars=` in success log refers to transcript length (not the text itself)
