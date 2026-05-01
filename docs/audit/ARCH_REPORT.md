---
# ARCH_REPORT — Cycle 13
_Date: 2026-05-01 · Scope: Phase 17 WS-17.2–WS-17.6_

Resolution note: ARCH-6 through ARCH-10 were fixed in the follow-up pass on 2026-05-01. The table below preserves the initial review verdicts; resolved status is recorded in `docs/audit/REVIEW_REPORT.md` and `docs/CODEX_PROMPT.md`.

## Component Verdicts

| Component | Verdict | Note |
|-----------|---------|------|
| `app/assistant/facade.py` | DRIFT | Write-status retry lifecycle creates a new status row instead of retiring the failed row selected for retry; DB sub-operations lack explicit child spans |
| `app/assistant/voice_media.py` | DRIFT | Correctly stores transcript for reply-to-voice save, but DB writes/lookups have no explicit spans |
| `app/assistant/session.py` | DRIFT | Pending dream drafts are process-local and capped only by access-time TTL eviction; no max size or durable state |
| `app/telegram/handlers.py` | PASS_WITH_NOTES | Reply-to-voice and pending-confirmation paths are correctly routed; existing feedback commit P3 remains unrelated carry-forward |
| `app/workers/transcribe.py` | PASS | Transcript storage is integrated after transcription and before assistant handling |
| `app/assistant/tools.py` / `chat.py` | PASS_WITH_NOTES | Retry tool replies are honest, but underlying retry lifecycle can retry stale failed rows repeatedly |
| `alembic/versions/015_add_dream_write_statuses.py` | PASS | Adds write-status table with status constraint and indexes |
| `alembic/versions/016_add_voice_transcript_text.py` | PASS | Adds nullable transcript column for operational reply-to-voice behavior |
| `docs/ARCHITECTURE.md` | DRIFT | Storage/component inventory does not include `dream_write_statuses` or the new transcript persistence field |

## Contract Compliance

| Rule | Verdict | Note |
|------|---------|------|
| SQL Safety | PASS | Phase 17 queries use SQLAlchemy ORM/select constructs; no interpolated SQL observed |
| Authorization | PASS | Telegram handlers remain allowlist-bound by the bot context; no new public HTTP route introduced |
| PII / DMI-1 | PASS_WITH_NOTES | No raw dream text found in new log/span/error paths reviewed. Transcript text is stored in DB for explicit user save behavior, not emitted to logs |
| OBS-1 external/DB spans | DRIFT | Several new DB operations lack child spans: status update commit, retry lookup, voice transcript write, transcript lookup |
| OBS-2 counters | PASS_WITH_NOTES | No new HTTP read route was added; Google Doc write remains top-level traced but write-status DB metrics are not granular |
| ADR-006 durable bot state | DRIFT | Pending dream drafts are in process memory and lost on restart; TTL eviction is access-triggered only |
| Runtime tier | PASS | No shell mutation, ad-hoc package install, or runtime privilege expansion introduced |
| LLM output framing | PASS | No new LLM trust escalation; deterministic confirmation/write behavior wraps assistant output |

## Architecture Findings

### ARCH-6 [P2] — Retry Does Not Retire Failed Write Status

Symptom: A successful retry can leave the original failed row in `dream_write_statuses`, making it eligible for subsequent no-argument retry calls.

Evidence: `write_dream_to_google_doc()` always creates a new `DreamWriteStatus(status="pending", attempt_count=1)` at `app/assistant/facade.py:399-411`. `retry_write_to_google_doc()` selects an existing failed row at `app/assistant/facade.py:492-503`, extracts only `dream_id`, then calls `write_dream_to_google_doc()` at `app/assistant/facade.py:508`.

Impact: Duplicate Google Doc appends are possible after a failed write is retried successfully. The user-facing “retry last failed write” command can remain non-idempotent and keep finding the stale failed row instead of returning `nothing_to_retry`.

Fix direction: Retry should update the selected failed row in place, or mark superseded failed rows for that dream/doc as resolved before/after the successful append. Increment `attempt_count` on retry and add a regression test for second retry returning `nothing_to_retry`.

### ARCH-7 [P2] — Phase 17 DB Operations Lack Explicit Observability Spans

Symptom: New Phase 17 persistence paths perform DB work without explicit DB spans.

Evidence: `_mark_dream_write_status()` commits status updates at `app/assistant/facade.py:463-477`; retry lookup executes a select at `app/assistant/facade.py:492-503`; transcript persistence and lookup run DB operations at `app/assistant/voice_media.py:65-99`.

Impact: Failures and latency in the new reliability-critical operational state are harder to distinguish from the top-level assistant/Google Doc operation. This violates the project’s OBS-1 pattern for new external/DB calls.

Fix direction: Add child spans such as `db.write_status.update`, `db.write_status.retry_lookup`, `db.voice_transcript.store`, and `db.voice_transcript.lookup`, with sanitized status attributes only.

### ARCH-8 [P3] — Pending Dream Draft State Is Unbounded And Ephemeral

Symptom: `_pending_dream_drafts` is a module-level dict keyed by chat ID. It evicts expired entries only when a pending-draft function is called and has no max-size cap.

Evidence: `app/assistant/session.py:38`, save/load/pop eviction calls at `app/assistant/session.py:95-127`, and eviction implementation at `app/assistant/session.py:135-144`.

Impact: Restart drops pending confirmations. In a long-running process, many distinct chat IDs can accumulate entries until another draft operation occurs. Single-user allowlist reduces operational risk, so this is P3.

Fix direction: Add a bounded cap and/or persist the pending draft in `bot_sessions` if restart safety is required.

### ARCH-9 [P3] — `APP_TIMEZONE` Is Not In Typed Settings Or Operator Docs

Symptom: Application date resolution uses `APP_TIMEZONE`, defaulting to `Asia/Tbilisi`, but reads the variable directly from `os.environ`.

Evidence: `app/assistant/facade.py:892-901`. `docs/tasks_phase17.md` mentions the setting, but runbook/operator config does not surface it as a formal runtime knob.

Impact: Operators can miss the timezone dependency and get unexpected “сегодня/вчера/позавчера” resolution around midnight or deployment region changes.

Fix direction: Add `APP_TIMEZONE` to typed settings and document it in Telegram bot runbook/config guidance.

### ARCH-10 [P3] — Architecture Storage Inventory Stale For Phase 17

Symptom: `ARCHITECTURE.md` lists current tables without `dream_write_statuses` and does not mention `voice_media_events.transcript_text` or the write-status ORM model.

Evidence: `docs/ARCHITECTURE.md:388-408`.

Impact: Architecture docs no longer describe the implemented operational reliability model for dream write status and reply-to-voice saves.

Fix direction: Update the storage inventory and implemented component table for `dream_write_statuses`, `app/models/write_status.py`, and transcript persistence on `voice_media_events`.

---
