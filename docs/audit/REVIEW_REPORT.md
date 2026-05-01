---
# REVIEW_REPORT — Cycle 13
_Date: 2026-05-01 · Scope: Phase 17 WS-17.2–WS-17.6_

## Executive Summary

- Stop-Ship: No.
- No P0/P1 findings.
- Initial review found two P2 issues and three P3 issues.
- Resolution pass completed in this turn: FIX-13 through FIX-17 are applied and marked resolved in `docs/CODEX_PROMPT.md`.
- Verification after fixes: targeted assistant facade/session/voice slice passed (68 passed); combined Phase 17 slice passed (169 passed); ruff check and ruff format check are clean.

## P0 Issues

_None._

## P1 Issues

_None._

## P2 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-11 | Successful retry does not retire the original failed write-status row. The retry path selects a failed row, but then calls `write_dream_to_google_doc()`, which inserts and updates a new status row. The old failed row remains eligible for future retry lookup, so a second retry can append the same dream again instead of returning `nothing_to_retry`. | `app/assistant/facade.py:402-424`, `app/assistant/facade.py:502-542` | Resolved — FIX-13 applied 2026-05-01 |
| CODE-12 | New Phase 17 DB operations are not consistently wrapped in explicit child spans. Status update commit, failed-status retry lookup, voice transcript persistence, and transcript lookup all perform DB work without their own spans, weakening OBS-1 coverage for the reliability-critical path. | `app/assistant/facade.py:403-424`, `app/assistant/facade.py:488-542`, `app/assistant/voice_media.py:43-104` | Resolved — FIX-14 applied 2026-05-01 |

## P3 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-13 | Pending dream drafts are stored in `_pending_dream_drafts`, a module-level dict with access-triggered TTL eviction and no max-size cap. Restart loses state; many distinct chat IDs can grow memory until another draft operation occurs. | `app/assistant/session.py:26`, `app/assistant/session.py:149-158` | Resolved — FIX-15 applied 2026-05-01 |
| CODE-14 | `APP_TIMEZONE` controls deterministic relative date resolution but is read directly from `os.environ` instead of typed settings and is not documented in the Telegram operator runbook. | `app/shared/config.py:53`, `app/assistant/facade.py:935-944`, `docs/RUNBOOK_TELEGRAM_BOT.md:47-52` | Resolved — FIX-16 applied 2026-05-01 |
| CODE-15 | `ARCHITECTURE.md` storage/component inventory is stale for Phase 17 and omits `dream_write_statuses`, `app/models/write_status.py`, and the new `voice_media_events.transcript_text` operational persistence. | `docs/ARCHITECTURE.md:388-414` | Resolved — FIX-17 applied 2026-05-01 |

## Carry-Forward Notes

Cycle 12 P2 fix queue items (`FIX-10`, `FIX-11`, `FIX-12`) are already marked resolved in current `CODEX_PROMPT.md`. Cycle 12 P3 findings remain governance/operability debt unless closed by a later explicit patch. They are not reclassified in this Cycle 13 review.

## Stop-Ship Decision

**No**. The implementation passes the targeted test/lint baseline and has no P0/P1 failures. The initial P2 retry/observability issues were fixed in this pass.

## Recommended Fix Queue

| Fix | Sev | Scope |
|-----|-----|-------|
| FIX-13 | P2 | Resolved — retry updates the selected failed row in place and increments `attempt_count`; regression test added |
| FIX-14 | P2 | Resolved — explicit sanitized DB spans added around write-status and voice transcript persistence paths |
| FIX-15 | P3 | Resolved — pending dream drafts now have oldest-first max-size eviction |
| FIX-16 | P3 | Resolved — `APP_TIMEZONE` moved into typed settings and documented in Telegram runbook |
| FIX-17 | P3 | Resolved — `ARCHITECTURE.md` refreshed for Phase 17 storage/components |

---
