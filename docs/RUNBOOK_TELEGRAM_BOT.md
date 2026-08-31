# Runbook — Telegram Bot

Last updated: 2026-08-31

## 1. Purpose

Operate the private Telegram adapter, verify a release with one high-value canary, and recover
durable capture/voice work without exposing archive text.

## 2. Startup gate

Required:

- Alembic is at head (`025_note_processing_jobs` or later)
- PostgreSQL with pgvector is reachable
- Redis returns `PONG`
- Telegram token and the single allowed chat ID are configured
- Anthropic/OpenAI and one Google Docs credential path are configured
- `VOICE_MEDIA_DIR` and `RUNTIME_STATE_FILE` are persistent and writable
- `SECRET_KEY` is strong and `BUILD_SHA` is the intended commit

Compose start:

```bash
export BUILD_SHA="$(git rev-parse HEAD)"
export DEPLOY_BACKUP_DIR=/var/backups/dream-motif
./scripts/deploy_compose.sh --backup-dir "$DEPLOY_BACKUP_DIR"
docker compose ps
curl --fail http://127.0.0.1:8000/health
docker compose exec redis redis-cli ping
```

Expected: `migrate` exits 0; Postgres/Redis are healthy; API and bot stay running;
the pre-migration backup manifest exists; `health.build_sha` equals `$BUILD_SHA`. `unknown` or a
mismatch blocks production rollout.

Direct start:

Use this only after stopping every existing API, bot and auto-sync process; the migration must not
run alongside an older writer.

```bash
alembic upgrade head
python -m app.telegram
```

Long polling is intentional. No Telegram webhook is required.

## 3. Automated release gate

Run deterministic checks before the private live canary:

```bash
.venv/bin/ruff check app/ scripts/ tests/
.venv/bin/ruff format --check app/ scripts/ tests/
.venv/bin/pytest tests/ -q --tb=short
.venv/bin/python scripts/eval_public_fixture.py \
  --check reports/evidence/portfolio-audit-2026-07-13/dream_motif_public_retrieval_v1.json
```

The full pytest suite needs disposable PostgreSQL/pgvector. It does not need real Telegram,
Google Docs or model credentials; those remain one bounded canary below.

## 4. One end-to-end private canary

Use a distinctive disposable phrase and remove only the test data through the normal operator
workflow afterward.

1. Send `/start`; verify the response teaches the primary `Мне приснилось…` flow and `/help` is
   available.
2. Send `Не сохраняй, но мне приснилось, что ...`; verify no archive row is created.
3. Send `Мне приснилась серебряная рыба у синей двери. Что это значит?`.
4. Verify the save card immediately shows `✅ Сон сохранён`, date/title/preview and separate
   `Архив`, `Обработка`, `Google Docs` states. Only the dream sentence—not the question—belongs in
   `raw_text`.
5. Verify one `dream_entries` row and four stage rows (`gdocs`, `index`, `analysis`, `motif`) were
   committed. Wait for due stages to settle; the document contains one entry and exact search for
   `серебряная рыба` returns a real archive sentence.
6. Replay the same Telegram update/message ID in a controlled adapter test. Verify no duplicate
   archive row, processing stage or Google Docs append appears. Then send the same words as a new
   message and verify a separate dream is created: content equality is not event identity.
7. Reply to the save card with `Добавь заметку к этому сну: canary`. Verify the immediate response
   says the note was saved and queued, then verify its independent `index` and `gdocs` jobs reach
   success. Replay the same note action once; note and document insertion stay idempotent.
8. Restart the bot between a pending confirmation and `да`; verify Redis restores the intended
   context. Then try a bare `да` with no pending context; it must not mutate anything.
9. Send a short voice version. Verify one voice event reaches `delivered`; a duplicate update does
   not schedule a second transcription or reply.
10. Open `/map`; verify draft motifs show source evidence, research is blocked until confirmation,
    hide removes an item from normal output, and restore brings back only a hidden item.

This canary covers capture, negative intent, compound text splitting, durable jobs, exact
retrieval, reply routing, restart state, voice and motif review in one pass.

## 5. Dream processing diagnostics

Aggregate state without selecting dream text:

```sql
SELECT status, stage, count(*) AS jobs,
       min(available_at) AS next_due,
       max(updated_at) AS last_update
FROM dream_processing_jobs
GROUP BY status, stage
ORDER BY status, stage;
```

Find actionable rows:

```sql
SELECT id, dream_id, status, stage, attempt_count,
       available_at, locked_at, updated_at, left(last_error, 200) AS error
FROM dream_processing_jobs
WHERE status IN ('retryable', 'failed')
   OR (status = 'running' AND locked_at < now() - interval '10 minutes')
ORDER BY updated_at;
```

Interpretation:

- `pending`: newly committed and not claimed yet
- `running`: leased; short-lived during provider/document work
- `retryable`: temporary failure with a future `available_at`
- `succeeded`: that independent stage is complete
- `failed`: bounded attempts exhausted; operator action is required

The live supervisor continuously drains due work and recovers stale leases. Restarting the bot is
safe but should not be necessary for ordinary retries. Never delete jobs or set them to succeeded
manually. Use the explicit stage-retry path to reset an exhausted attempt budget; sending the same
text as a new Telegram message intentionally creates a new dream. A failed Google Docs receipt can
also be retried with `повтори запись в Google Doc`; a prior successful receipt stays a no-op by
design.

Note jobs have the same status vocabulary and are diagnosed separately:

```sql
SELECT status, stage, count(*) AS jobs,
       min(available_at) AS next_due,
       max(updated_at) AS last_update
FROM note_processing_jobs
GROUP BY status, stage
ORDER BY status, stage;
```

The acknowledgement is complete once the note plus jobs commit. It is normal to see `pending`
briefly afterward; it is not correct to report Google Docs as updated until the `gdocs` job and its
receipt succeed.

## 6. Redis degraded state

Redis stores expiring context that can contain pending dream/note text. Check connectivity only:

```bash
docker compose exec redis redis-cli ping
docker compose logs --since=10m telegram-bot | grep -E 'Redis|operational state'
```

Do not print keys/values into tickets or public logs.

In production/staging, startup must fail if Redis is unavailable. In development/test, an explicit
degraded log/flag is permitted, but restart-safe `да`, `к этому`, displayed result numbers and
pending notes are not guaranteed. Restore Redis, restart the bot, and ask the user to repeat the
full request—not a short confirmation—if its TTL/context was lost.

## 7. Common incidents

### Bot starts but receives nothing

- verify token and allowed chat ID
- check that no second poller is using the same token
- inspect `docker compose logs telegram-bot`
- verify the process did not fail its Redis or configuration gate

### Save card remains pending

- run the aggregate/actionable SQL above
- check provider quota only for the failed stage; independent stages should continue
- for `gdocs`, inspect the DB receipt status and service-account/OAuth permission
- for `index`, verify embeddings and pgvector
- for `analysis`/`motif`, verify the bounded model provider and feature flag

Do not copy `last_error` to a public issue without checking it contains no private/provider detail.

### Duplicate Google Docs entry

- confirm the dream has exactly one `(dream_id, target_doc_id)` write receipt
- inspect document named ranges for the dream idempotency marker
- verify all character offsets use UTF-16 when the entry includes emoji
- do not delete the canonical dream to repair the mirror

### Wrong dream receives a note

- stop mutation testing for that chat
- verify the user replied to the concrete save/result message
- check Redis availability and message-reference TTL
- reproduce with synthetic IDs; never dump private Redis payloads

### Unauthorized user reaches a handler

- stop the bot immediately
- rotate the Telegram token if exposure is plausible
- verify `TypeHandler(Update, chat_guard)` remains group `-1000`
- run the unauthorized replay test before restart

## 8. Shutdown and rollback

```bash
docker compose stop telegram-bot api
```

Supervisors stop accepting work and release/cancel their tasks; database leases expire and are safe
to reclaim on the next start. For code rollback, deploy a previous compatible image while leaving
the database at the newer migration head. Do not run destructive Alembic downgrades on the private
archive. Before relying on a deployment backup, run:

```bash
./scripts/verify_compose_rollback.sh \
  --manifest /var/backups/dream-motif/dream_motif_YYYYMMDDTHHMMSSZ_<build-sha>.dump.manifest \
  --restore-drill-db dream_motif_restore_drill
```

The verifier restores only into the disposable `_restore_drill` database and drops it afterward; it
refuses the canonical `dream_motif` database.

After rollback, verify `/health.build_sha`, Redis, one read-only search and the outbox aggregates
before resuming new capture.
