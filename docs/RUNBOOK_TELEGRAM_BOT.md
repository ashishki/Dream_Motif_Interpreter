# Runbook — Telegram Bot

Last updated: 2026-05-09 (Phase 22 Test 7/8 smoke checks)

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
  - `015_add_dream_write_statuses` — Google Doc write attempt tracking
  - `016_add_voice_transcript_text` — stored voice transcript for reply-to-voice saves
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
APP_TIMEZONE=Asia/Tbilisi                  # default; resolves "сегодня/вчера/позавчера"
```

## 4. Recording Smoke Test

Run this after deployment or after changing Telegram, voice, assistant, or Google Docs write code.

1. Send a natural dream opening, for example: `Сегодня мне приснилось, что я шёл по мосту над морем`.
2. Verify the bot does not ask whether to record it and replies with either `Сон сохранён и добавлен в документ` after a successful Google Doc write or the archive-only retry message after a failed write.
3. Verify the Google Doc gets one heading in the form `дд.мм.гг - <title>` and the title does not duplicate the date.
4. Send a duplicate of the same dream text; verify it does not create a duplicate Google Doc entry.
5. Temporarily break Google Docs write credentials or use a test failure stub; verify the bot says the dream was saved only in the archive and does not claim it was added to Google Doc.
6. Restore write access and send `повтори запись в Google Doc`; verify it retries the failed write, not the latest unrelated dream.
7. Send a voice message, wait for transcription, then reply to that voice message with `запиши сон`; verify the stored transcript is saved.
8. Repeat the reply-to-voice save while transcription is still processing or after a failed transcription; verify the bot does not claim success.

## 5. Test 6 Regression Smoke Checklist

Run this checklist after any deployment that touches recording, search, or assistant tool routing.

1. Text short dream: send `Сегодня мне приснилось рыба`; verify the bot saves immediately, does not ask for more details, and does not create a pending confirmation draft.
2. Voice short dream: send a voice message whose transcript starts with `сегодня мне приснилось`; verify the transcript is saved directly without the assistant asking whether to record it.
3. Successful Google Doc write: verify the visible success text is exactly `Сон сохранён и добавлен в документ` with no document name, URL, or fallback document ID.
4. Failed Google Doc write: force a write failure and verify the bot says the dream was saved only in the archive and gives the retry phrase `повтори запись в Google Doc`.
5. Fish/image search: ask `найди сон с рыбой`; verify the response contains an archive-backed evidence fragment with `рыба` or a same-stem fish word from the dream text.
6. Full dream by title/date: ask for the full text of `04.04.26, Кирилл, мужик, настольки`; verify the assistant resolves the title/date, calls `get_dream`, and does not ask the user for a UUID.

Automated regression slice:

```bash
.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_assistant_facade.py tests/unit/test_rag_query.py tests/unit/test_retrieval_eval.py tests/unit/test_telegram_bot.py tests/unit/test_telegram_voice.py tests/unit/test_transcription_worker.py -q --tb=short
```

## 6. Common Failure Modes

## 6. Test 7/8 Sync, Notes, Titles, Interpretation Checklist

Run this checklist after deployments that touch Google Docs sync, note writing, title intake, or
interpretation.

1. Check service state:

```bash
systemctl is-active dream-motif-api.service dream-motif-auto-sync.service dream-motif-telegram.service
```

2. Inspect auto-sync state for the primary doc and confirm `last_sync_status` is `synced` or an
honest recent failure, not a stale `running` state.
3. Trigger one sync and verify the bot tells the user it will notify when sync completes or fails.
4. Verify the current Google Doc can contain duplicate parsed candidates without aborting the
whole sync.
5. Verify `dream_entries` contains `5.11.24 запретная рыба`.
6. Ask `найди сон с рыбой`; verify the first result is `5.11.24 запретная рыба` with exact fish
evidence.
7. Add a note to the latest dream; inspect Google Doc and verify the note is at the end of that
dream section, before the next dream heading.
8. Save a dream with `Название — Пирог с фруктовой начинкой`; verify the stored title is exactly
that title and `raw_text` does not include the recording command.
9. Ask for an interpretation; verify the bot shows the pending prompt and does not interpret until
the user replies `да`. Reply `нет` in a separate run and verify it cancels.

Auto-sync Redis inspection helper:

```bash
.venv/bin/python - <<'PY'
import asyncio
from redis import asyncio as aioredis
from app.services.auto_sync import read_auto_sync_state
from app.shared.config import get_effective_google_doc_id, get_settings

async def main():
    redis = aioredis.from_url(get_settings().REDIS_URL)
    try:
        print(await read_auto_sync_state(redis, get_effective_google_doc_id()))
    finally:
        await redis.aclose()

asyncio.run(main())
PY
```

Automated Phase 22 regression slice:

```bash
.venv/bin/python -m pytest tests/unit/test_auto_sync.py tests/unit/test_ingest_notify.py tests/unit/test_rag_ingestion.py tests/unit/test_segmentation.py tests/unit/test_gdocs_client.py tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py tests/unit/test_assistant_session.py tests/unit/test_telegram_bot.py tests/unit/test_rag_query.py tests/unit/test_retrieval_eval.py -q --tb=short
```

## 7. Common Failure Modes

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

## 8. Voice Failure Diagnostics

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

## 9. Session State Diagnostics

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

## 10. Safety Rule

If chat-driven mutation tools are not in the approved phase scope, disable or omit them entirely.

## 11. Logging Rules

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
