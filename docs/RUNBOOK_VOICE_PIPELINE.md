# Runbook — Voice Pipeline

Last updated: 2026-08-31

## Purpose

This runbook covers Telegram voice-message ingestion, transcription, reply delivery,
crash recovery, and retention. A voice event is operational state, not an archived
dream. The archive changes only when the user explicitly asks to save a dream or note.

## Runtime contract

- PostgreSQL migrations must be at Alembic head. Migrations `008`, `016`, and `021`
  create the voice event table and its durable recovery/delivery fields.
- `VOICE_MEDIA_DIR` must be an absolute, writable, persistent path shared across bot
  restarts. Compose mounts the `voice_media` volume there.
- `VOICE_RETENTION_SECONDS` controls raw `.ogg` retention (default: one hour).
- `VOICE_TRANSCRIPT_RETENTION_SECONDS` controls operational transcript retention
  (default: seven days).
- `OPENAI_API_KEY` is required for the managed Whisper `whisper-1` transcription call.
- `TELEGRAM_BOT_TOKEN`, PostgreSQL, and Redis must be available to the bot process.

The bot runs both transcription and the maintenance supervisor in its event loop. The
supervisor polls durable events, renews five-minute leases while they are being handled,
retries due work, and performs retention cleanup every five minutes. No separate voice
worker or cron job is required.

## Durable lifecycle

```text
received -> downloaded -> processing -> transcribed -> processing
                                                      |
                                                      v
                                              reply_pending -> delivered

processing -> transcription_retryable -> processing
processing -> transcription_failed -> reply_pending -> delivered
```

`done` and `failed` remain readable for legacy rows. New work uses the states above.

| State | Meaning | Recovery behavior |
|---|---|---|
| `received` | Metadata is committed; media may still need downloading | Claim after a crash and download by Telegram file id |
| `downloaded` | `local_path` is committed | Resume transcription |
| `processing` | A leased worker is active | Reclaim only after lease expiry |
| `transcribed` | Transcript is committed | Resume assistant processing without retranscribing |
| `transcription_retryable` | Provider attempt failed, below the limit | Retry when `next_attempt_at` is due |
| `transcription_failed` | Three transcription attempts failed | Persist and deliver a clear failure reply |
| `reply_pending` | Reply text and chunk cursor are committed | Resume from the first undelivered chunk |
| `delivered` | Every reply chunk was acknowledged by Telegram | Terminal |

The unique `(chat_id, telegram_message_id)` constraint makes repeated Telegram updates
idempotent. `lease_owner` and `lease_expires_at` prevent two bot instances from handling
the same event at once. Delivery progress is stored after each chunk, so a retry does not
start the whole reply over.

## Retention and privacy

Raw audio is deleted immediately after the reply is durably staged. If the process dies
earlier, tracked raw media and untracked stale `.ogg`/`.ogg.part` files are deleted after
`VOICE_RETENTION_SECONDS`. Cleanup accepts only regular files under the configured media
root and refuses symlinks or outside paths.

Operational transcript text is kept only to recover assistant processing and is cleared
after `VOICE_TRANSCRIPT_RETENTION_SECONDS`. Logs may contain identifiers, state, attempt
counts, and character counts; they must never contain transcript or dream text.

## Deploy and startup checks

```bash
export BUILD_SHA="$(git rev-parse HEAD)"
./scripts/deploy_compose.sh
docker compose ps
docker compose logs --tail=100 telegram-bot
```

The shared deploy script stops API, bot and auto-sync before Alembic runs. Do not migrate a live
voice/capture writer or replace this sequence with a direct Compose start during an upgrade.

Confirm that startup logs show voice recovery and no repeating maintenance failure.
Verify the mounted path from inside the service:

```bash
docker compose exec telegram-bot sh -lc 'test -d /var/lib/dream-voice && test -w /var/lib/dream-voice'
```

Do not print directory contents in shared incident channels: filenames are operational
identifiers.

## Diagnostics

Recent non-terminal events:

```sql
SELECT id, chat_id, telegram_message_id, status,
       transcription_attempt_count, delivery_attempt_count,
       reply_chunks_delivered, next_attempt_at,
       lease_owner, lease_expires_at, updated_at
FROM voice_media_events
WHERE status NOT IN ('delivered', 'done', 'failed')
ORDER BY updated_at ASC
LIMIT 100;
```

Due or abandoned work:

```sql
SELECT id, status, next_attempt_at, lease_expires_at, updated_at
FROM voice_media_events
WHERE (next_attempt_at IS NULL OR next_attempt_at <= now())
  AND (lease_expires_at IS NULL OR lease_expires_at < now())
  AND status IN (
    'received', 'downloaded', 'processing', 'transcribed',
    'transcription_retryable', 'transcription_failed', 'reply_pending'
  )
ORDER BY updated_at;
```

Aggregate backlog:

```sql
SELECT status, count(*) AS events, min(updated_at) AS oldest
FROM voice_media_events
GROUP BY status
ORDER BY status;
```

Useful log fields are `event_id`, `chat_id`, `message_id`, `status`, attempt counts,
and filename only. Relevant messages include claimed recovery batches, lease loss,
retry scheduling, durable reply staging, chunk delivery, and retention counts.

## Incident recovery

### Download failed or process crashed before path commit

Check Telegram connectivity, free disk space, and write access to `VOICE_MEDIA_DIR`.
The event remains recoverable in `received`; the live supervisor retries the download.
An identical Telegram update also safely resumes a `received` row that has no path.

### Transcription provider failed

Check `OPENAI_API_KEY`, provider status, and quota. Do not rewrite the event manually.
The supervisor retries with backoff up to three attempts. After the final attempt it
delivers an explicit failure message and retains no raw audio beyond the normal policy.

### Assistant failed after transcription

The committed transcript is reused; Whisper is not called again. Fix the model/provider
dependency and restart the bot if necessary. The startup sweep will reclaim the row.

### Telegram reply failed midway

The row remains `reply_pending`, with `reply_chunks_delivered` pointing at the next chunk.
Restore Bot API connectivity. The live supervisor retries with backoff; restarting the bot
is also safe.

### Bot was restarted

No SQL intervention is required. Startup claims due and expired events, while a periodic
sweep handles later retries. Confirm that `lease_expires_at` advances for active rows and
that the backlog decreases.

### Media volume is growing

Check retention-cycle errors and confirm the configured directory matches the mounted
volume. Never use a recursive delete or a wildcard cleanup. The supported cleanup path is:

```python
from app.workers.cleanup import cleanup_orphan_voice_files, cleanup_voice_media

await cleanup_voice_media(
    session_factory,
    retention_seconds=settings.VOICE_RETENTION_SECONDS,
    media_dir=settings.VOICE_MEDIA_DIR,
)
await cleanup_orphan_voice_files(
    session_factory,
    retention_seconds=settings.VOICE_RETENTION_SECONDS,
    media_dir=settings.VOICE_MEDIA_DIR,
)
```

If cleanup refuses a path, investigate the configuration or symlink; do not bypass the
media-root check.

## Acceptance smoke test

1. Send a short voice note and observe the immediate processing acknowledgement.
2. Confirm one database row exists for the Telegram message id.
3. Wait for the assistant reply and confirm the row reaches `delivered`.
4. Resend the same update in a controlled test and confirm no second row or second reply.
5. In staging, interrupt the bot after transcript persistence; restart it and confirm the
   same row resumes without another transcription.
6. In staging, interrupt a multi-chunk reply; restart it and confirm delivery resumes from
   `reply_chunks_delivered`.
7. Confirm raw audio disappears after reply staging and transcript text is purged after the
   configured retention window.
