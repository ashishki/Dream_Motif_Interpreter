# Runbook — Telegram Bot

Last updated: 2026-04-15 (P8-T01 update — added voice, session, and transcription diagnostics)

## 1. Purpose

Operate the Telegram bot runtime for Dream Motif Interpreter (Phase 6+ implemented).

## 2. Primary Responsibilities

- accept authorized updates
- reject unauthorized updates
- route user text and voice requests
- call assistant tools safely
- report failures clearly

## 3. Startup Checklist

- `TELEGRAM_BOT_TOKEN` set in environment
- `TELEGRAM_ALLOWED_CHAT_ID` set to the single authorized chat ID (integer)
- `ANTHROPIC_API_KEY` set (required for the bounded tool-use loop)
- `OPENAI_API_KEY` set (required for voice transcription via Whisper)
- `DATABASE_URL` reachable and migrations applied:
  - `007_add_bot_sessions` — chat session persistence
  - `008_add_voice_media_events` — voice media tracking
- `REDIS_URL` reachable
- `VOICE_MEDIA_DIR` is a writable directory (default: `/tmp/dream_voice`)

Startup command (direct):

```bash
python3 -m app.telegram
```

Startup via Compose:

```bash
docker compose up telegram-bot
```

The bot process runs long polling. No public webhook endpoint is required.

Optional tuning:

```env
ASSISTANT_MODEL=claude-haiku-4-5-20251001   # default; override for a different model tier
VOICE_MEDIA_DIR=/tmp/dream_voice            # default
VOICE_RETENTION_SECONDS=3600               # default: 1 hour
```

## 4. Common Failure Modes

### Bot starts but receives nothing

Check:
- bot token validity
- polling/webhook mode mismatch
- deployment firewall or connectivity

### Bot receives messages from unauthorized source

Symptoms: log shows `Dropped update from unauthorized chat_id=...`; no reply is sent to the sender.

Check:
- `TELEGRAM_ALLOWED_CHAT_ID` is set to the correct integer value
- the bot was not added to an unexpected group chat

### Bot replies with backend failure

Symptoms: user receives "Something went wrong. Please try again."

Check:
- DB connectivity (`DATABASE_URL`)
- Redis connectivity (`REDIS_URL`)
- `ANTHROPIC_API_KEY` is valid
- retrieval service health (embedding index, pgvector)
- logs for the unhandled error via `error_handler`

### Assistant returns no usable text

Symptoms: user receives a blank reply or fallback.

Check:
- `ANTHROPIC_API_KEY` is valid and has quota
- `ASSISTANT_MODEL` is a valid model ID
- bounded tool-use loop hit MAX_TOOL_ROUNDS=5 without an end_turn response (log will show this)

## 5. Voice Failure Diagnostics

Voice messages go through a two-stage pipeline: the handler persists + downloads, then a background task transcribes and replies.

### Transcription task not enqueued

Symptoms: user receives "Processing your voice note..." but never gets a reply.

Check logs for:
- `Voice ingress complete — transcription skipped (missing config) event_id=...`

This means one of the required bot_data keys is missing: `session_factory`, `bot_token`, or `facade`.

Check:
- startup completed without errors
- all required env vars are set (see Startup Checklist)

### Transcription task fails silently

Symptoms: no reply after ack; event stuck at `received` or `failed` in DB.

Check logs for:
- `Transcription failed for event_id=...` — Whisper API error
- `handle_chat failed after transcription for event_id=...` — assistant pipeline error
- `Failed to send Telegram reply for chat_id=...` — reply delivery failure

Diagnose event:
```sql
SELECT id, status, updated_at, local_path
FROM voice_media_events
WHERE id = '<event_id>';
```

### Voice download fails

Log pattern: `Voice download failed for message_id=... event_id=...`

Check disk space and `VOICE_MEDIA_DIR` permissions. User will have already received "Could not download your voice message."

## 6. Session State Diagnostics

Chat history is persisted in the `bot_sessions` table (one row per `chat_id`).

### Session history not loading

Symptoms: assistant does not recall context from previous messages.

Check:
- migration `007_add_bot_sessions` was applied
- `session_factory` is configured in bot_data (set in `build_application`)
- `load_history` failure is logged at WARNING level with the exception

### Session history growing unexpectedly large

The history is trimmed to the last `MAX_HISTORY_MESSAGES=20` messages on each save. If this appears to be growing beyond that, check the `history_json` column directly:

```sql
SELECT chat_id, length(history_json), updated_at FROM bot_sessions;
```

### Resetting a session

To clear a chat's history (e.g., after a support incident):

```sql
UPDATE bot_sessions SET history_json = '[]', updated_at = now()
WHERE chat_id = <chat_id>;
```

## 7. Safety Rule

If chat-driven mutation tools are not in the approved phase scope, disable or omit them entirely.

## 8. Logging Rules

Use identifiers and statuses.
Do not log raw dream text, transcript text, or secrets.

Key log patterns:
- `Dropped update from unauthorized chat_id=...` — auth guard
- `Voice download failed for message_id=... event_id=...` — ingress failure
- `Voice file downloaded event_id=... path=...` — download success
- `Transcription task enqueued event_id=... duration=...s` — task created
- `Transcription succeeded event_id=... chars=...` — Whisper returned
- `Transcription failed for event_id=...` — Whisper error
- `handle_chat failed after transcription for event_id=...` — assistant error
- `Deleted local voice file after transcription path=...` — immediate cleanup
