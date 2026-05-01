---
# META_ANALYSIS — Cycle 13
_Date: 2026-05-01 · Type: full · Scope: Phase 17 WS-17.2–WS-17.6_

## Project State

Phase 17 was implemented locally after `git pull --ff-only`: text-confirmation dream intake, deterministic relative date/title resolution, Google Doc write status tracking, reply-to-voice save, and user-facing docs/prompt updates are present.

Baseline verified before this review:

- `pytest tests/unit/test_assistant_chat.py tests/unit/test_assistant_facade.py tests/unit/test_feedback_context.py tests/unit/test_gdocs_client.py tests/unit/test_assistant_session.py tests/unit/test_telegram_bot.py tests/unit/test_telegram_voice.py tests/unit/test_transcription_worker.py tests/integration/test_migrations.py -q --tb=short` -> 167 passed, 2 warnings
- `ruff check app/ tests/ alembic/versions/015_add_dream_write_statuses.py alembic/versions/016_add_voice_transcript_text.py` -> clean
- `ruff format --check app/ tests/ alembic/versions/015_add_dream_write_statuses.py alembic/versions/016_add_voice_transcript_text.py` -> clean

Cycle type: full. The reviewed surface includes assistant facade/tool execution, Telegram text/voice handlers, pending dream session state, voice transcript persistence, migrations `015`/`016`, docs, and the Phase 17 task graph.

## Findings Summary

| Sev | Count | IDs |
|-----|-------|-----|
| P0 | 0 | — |
| P1 | 0 | — |
| P2 | 2 | CODE-11, CODE-12 |
| P3 | 3 | CODE-13, CODE-14, CODE-15 |

Stop-Ship: No. There are no P0/P1 issues. The initial P2/P3 findings were fixed in the follow-up pass; see `docs/audit/REVIEW_REPORT.md` and `docs/CODEX_PROMPT.md`.

## New Open Findings

| ID | Sev | Description | Files | Status |
|----|-----|-------------|-------|--------|
| CODE-11 | P2 | Successful retry does not retire the original failed write-status row. `retry_write_to_google_doc()` selects the latest `failed` row, but `write_dream_to_google_doc()` always inserts a fresh `pending` row and marks that new row `succeeded`/`failed`. The originally selected `failed` row remains failed, so the next retry without `dream_id` can retry the same already-successfully-written dream again instead of returning `nothing_to_retry`. | `app/assistant/facade.py:402-424`, `app/assistant/facade.py:502-542` | Resolved — FIX-13 applied 2026-05-01 |
| CODE-12 | P2 | New DB persistence paths added in Phase 17 are not consistently wrapped in explicit child spans. The top-level Google Doc write span exists, but `_mark_dream_write_status()` performs DB commit work without its own DB span, `retry_write_to_google_doc()` performs the failed-status lookup without a DB span, and voice transcript persistence/lookups also perform DB calls without spans. This weakens OBS-1 coverage for new external/DB calls. | `app/assistant/facade.py:403-424`, `app/assistant/facade.py:488-542`, `app/assistant/voice_media.py:43-104` | Resolved — FIX-14 applied 2026-05-01 |
| CODE-13 | P3 | Pending dream drafts use a process-local dict with TTL eviction only on access and no max-size cap. A long-running bot receiving many distinct chat IDs can accumulate stale entries until another draft operation happens; restart also drops pending state. | `app/assistant/session.py:26`, `app/assistant/session.py:149-158` | Resolved — FIX-15 applied 2026-05-01 |
| CODE-14 | P3 | `APP_TIMEZONE` is read directly from `os.environ` inside facade code, not via typed settings or documented operator config. Runtime behavior exists, but the configuration contract is discoverable only from task notes. | `app/shared/config.py:53`, `app/assistant/facade.py:935-944`, `docs/RUNBOOK_TELEGRAM_BOT.md:47-52` | Resolved — FIX-16 applied 2026-05-01 |
| CODE-15 | P3 | `ARCHITECTURE.md` storage/component inventory is stale for Phase 17. It lists `voice_media_events` but not the new `transcript_text` operational field and omits the implemented `dream_write_statuses` table/model. | `docs/ARCHITECTURE.md:388-414` | Resolved — FIX-17 applied 2026-05-01 |

## Carry-Forward Findings

The Cycle 12 P2 items are resolved in current code/docs: `FIX-10`, `FIX-11`, and `FIX-12` are marked closed in `docs/CODEX_PROMPT.md`. Cycle 12 P3 carry-forward items remain present unless explicitly addressed elsewhere:

- CODE-4 [P3] feedback commit still lacks explicit error handling in `app/telegram/handlers.py`.
- CODE-5 [P3] `RESEARCH_API_KEY` empty-string startup validation remains deferred.
- CODE-6 [P3] feedback pending state remains an unbounded in-memory dict.
- CODE-7 [P3] DECISION_LOG D-014 is still absent.
- CODE-9 [P3] older Phase 11 architecture wording may still need full cleanup.
- CODE-10 [P3] Phase 11 journal coverage should remain checked before closing governance debt.

## Prompt Scope For ARCH Review

Architecture review should focus on write-status lifecycle, DB observability coverage, pending dream draft state durability/boundedness, typed config/documentation for `APP_TIMEZONE`, and Phase 17 storage model reflection in `ARCHITECTURE.md`.

## Prompt Scope For CODE Review

1. `app/assistant/facade.py` — write status lifecycle, retry query, relative date config
2. `app/assistant/voice_media.py` — transcript persistence and lookup
3. `app/assistant/session.py` — pending dream draft lifecycle
4. `app/telegram/handlers.py` — text confirmation and reply-to-voice save path
5. `app/workers/transcribe.py` — transcript storage integration
6. `app/assistant/tools.py` and `app/assistant/chat.py` — retry tool behavior and user-facing truthfulness
7. `alembic/versions/015_add_dream_write_statuses.py` and `016_add_voice_transcript_text.py`
8. `tests/unit/test_assistant_facade.py`, `test_assistant_session.py`, `test_telegram_voice.py`, `test_transcription_worker.py`

## Notes For Consolidation

- No `.py` fix should be applied during this review pass.
- CODEX_PROMPT should carry forward new P2/P3 findings and assign a P2 fix queue before Phase 18 operational work relies on retry semantics.
- Add a targeted regression test for “failed row is retired after successful retry; next retry returns `nothing_to_retry`”.
---
