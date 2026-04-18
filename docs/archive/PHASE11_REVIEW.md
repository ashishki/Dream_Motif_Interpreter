---
# REVIEW_REPORT — Cycle 12
_Date: 2026-04-18 · Scope: WS-11.1–WS-11.3 (Phase 11 Feedback Loop, partial)_

## Executive Summary

- Stop-Ship: No
- Phase 11 is partially implemented: WS-11.1 (DB migration + ORM model), WS-11.2 (Telegram digit-reply capture), and WS-11.3 (GET /feedback API) are complete; WS-11.4 (optional comment capture) is not yet implemented and is deferred.
- Baseline is 225 unit tests passing (as of 2026-04-17); CODEX_PROMPT.md §Current State still read 216 — stale carry-forward corrected in this cycle.
- No P0 or P1 findings. The system is safe to proceed; Phase 11 gate criteria (WS-11.1–11.3 required) are met.
- Three P2 findings this cycle: GET /feedback emits no OTel meter counter (OBS-2 gap); AssistantFeedback ORM model missing score CheckConstraint (schema/ORM divergence); retrieval_eval.md missing mandatory Cycle 11 advisory row (RET-7).
- Seven P3 findings this cycle: unguarded DB commit in handlers.py suppresses FEEDBACK_ACK reply on error; RESEARCH_API_KEY empty-string not validated at startup (third cycle carry-forward); unbounded _feedback_pending_by_chat dict with no TTL or size cap; DECISION_LOG.md missing WS-11.4 deferral entry; CODEX_PROMPT.md baseline stale at 216 vs actual 225; ARCHITECTURE.md §19 header still reads "(Planned — Phase 11)"; IMPLEMENTATION_JOURNAL.md has no Phase 11 entry.
- All three Cycle 10 Fix Queue items (FIX-7/FIX-8/FIX-9) are confirmed closed.
- ADR compliance: all Phase 11 components pass except ADR-006 drift (in-memory feedback pending state not durable). Authorization, PII, SQL safety, and OTel span contracts all pass.

---

## P0 Issues

_None._

---

## P1 Issues

_None._

---

## P2 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-1 | `GET /feedback` emits an OTel span (`db.query.feedback.list`) but no meter counter. OBS-2 requires a labeled counter per external/DB call on every read route. All other read routes emit labeled counters; this route is the only exception. Fix: add `get_meter(__name__).create_counter("feedback.list_total")` with a `{"status": "success"\|"error"}` attribute, consistent with the OBS-2 pattern in `app/api/research.py`. | `app/api/feedback.py` | Open — new Cycle 12; see FIX-10 |
| CODE-2 | `AssistantFeedback` ORM model defines `score` as `SmallInteger()` with no `CheckConstraint`. The Alembic migration `011_add_feedback.py` correctly creates `ck_assistant_feedback_score_range` in the DDL, but the ORM model omits the mirror constraint in `__table_args__`. `FeedbackService.record()` provides a Python-level guard, but direct ORM usage (fixtures, admin scripts, future data migrations) bypasses it with no model-level protection. Fix: add `sa.CheckConstraint("score >= 1 AND score <= 5", name="ck_assistant_feedback_score_range")` to `AssistantFeedback.__table_args__`. | `app/models/feedback.py` | Open — new Cycle 12; see FIX-11 |
| CODE-3 | `docs/retrieval_eval.md §Evaluation History` ends at the Cycle 10 advisory row (2026-04-17). RET-7 mandates an advisory row each cycle regardless of whether the RAG layer changed. Phase 11 did not modify chunking, embedding, ranking, or evidence assembly; the T12 baseline metrics carry forward unchanged. Fix: add Cycle 11 advisory row confirming the RAG layer is unchanged in Phase 11. | `docs/retrieval_eval.md` | Open — new Cycle 12; see FIX-12 |

---

## P3 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-4 | `handlers.py` calls `session.commit()` immediately after `FeedbackService.record()` with no `try/except`. A transient DB failure during commit propagates as an unhandled exception and silently suppresses the `FEEDBACK_ACK` ("Thanks, noted.") reply to the user. Fix: wrap the commit in `try/except`, log the DB error, and still deliver the ack reply. | `app/telegram/handlers.py:54–58` | Open — new Cycle 12 |
| CODE-5 | When `RESEARCH_AUGMENTATION_ENABLED=True`, `RESEARCH_API_KEY` defaults to `""` with no `model_validator` at startup. ADR-010 acknowledges the deferral; no FIX entry has been assigned. A fail-fast validator would catch misconfiguration early. | `app/shared/config.py:31` | Open — Cycle 10 carry-forward (third cycle); no change |
| CODE-6 | `_feedback_pending_by_chat` dict in `context.bot_data` is unbounded. Long-running bots with many distinct `chat_id` values, or chats where the user never sends a digit reply, will accumulate stale entries indefinitely. No TTL eviction or max-size cap. Also causes ADR-006 drift (non-durable bot state). Fix: add a max-size cap or TTL eviction, or formally defer with a DECISION_LOG entry. | `app/telegram/handlers.py:44, 74–79, 203–204` | Open — new Cycle 12 |
| CODE-7 | `docs/DECISION_LOG.md` has no WS-11.4 deferral entry. The WS-9.7 deferral precedent (D-012) establishes that deferred optional scope must be logged as a decision (D-014). DECISION_LOG currently ends at D-013. Fix: add D-014 recording WS-11.4 (optional comment capture) as explicitly deferred. | `docs/DECISION_LOG.md` | Open — new Cycle 12; GOV-5 violation |
| CODE-8 | `docs/CODEX_PROMPT.md §Current State` baseline field reads 216. Actual unit test count is 225 after Phase 11 WS-11.1–11.3 additions (measured 2026-04-17). Fix: update baseline to 225 (applied in this cycle's CODEX_PROMPT.md patch). | `docs/CODEX_PROMPT.md` | Resolved in this cycle (Cycle 12 CODEX_PROMPT patch) |
| CODE-9 | `docs/ARCHITECTURE.md §19` header reads `## 19. Feedback Model (Planned — Phase 11)`. WS-11.1, WS-11.2, and WS-11.3 are implemented. Fix: update §19 header to `(Implemented — Phase 11 WS-11.1–11.3)`; move `assistant_feedback` row from §20 Planned table to §20 Current tables; annotate `FeedbackService` in §9 component table. | `docs/ARCHITECTURE.md:381` | Open — new Cycle 12; GOV-5 violation |
| CODE-10 | `docs/IMPLEMENTATION_JOURNAL.md` has no Phase 11 entry. WS-11.1–11.3 scope, test baseline 225, and WS-11.4 deferral decision are not recorded. Fix: append Phase 11 journal entry covering WS-11.1–11.3 scope, D-014 deferral, and baseline 225. | `docs/IMPLEMENTATION_JOURNAL.md` | Open — new Cycle 12; GOV-5 violation |

---

## Carry-Forward Status

| ID | Sev | Description | Status | Change |
|----|-----|-------------|--------|--------|
| CODE-1 (C10) | P2 | ResearchRetriever.retrieve() missing OTel span and counter | **Closed** — FIX-7 applied 2026-04-17 | Closed Cycle 11 |
| CODE-2 (C10) | P2 | ResearchSynthesizer.synthesize() missing OTel span and counter | **Closed** — FIX-8 applied 2026-04-17 | Closed Cycle 11 |
| CODE-3 (C10) | P2 | retrieval_eval.md missing Cycle 10 advisory row | **Closed** — FIX-9 applied 2026-04-17 | Closed Cycle 11 |
| CODE-4 (C10) | P3 | IMPLEMENTATION_JOURNAL.md no Phase 10 entry | **Closed** — FIX-9 applied 2026-04-17 | Closed Cycle 11 |
| CODE-5 (C10) | P3 | RESEARCH_API_KEY empty-string not validated at startup | **Open** — no FIX assigned; entering third cycle | No change |
| ARCH-1 (C10) | P3 | app/research/ absent from ARCHITECTURE.md §9 | **Closed** — FIX-9 applied 2026-04-17 | Closed Cycle 11 |
| ARCH-2 (C10) | P3 | Duplicate §18 section number in ARCHITECTURE.md | **Closed** — FIX-9 applied 2026-04-17 | Closed Cycle 11 |
| ARCH-4 (C10) | P3 | ARCHITECTURE.md §18 header read "(Planned — Phase 10)" | **Closed** — FIX-9 applied 2026-04-17 | Closed Cycle 11 |
| DOC-1 (C11) | P3 | CODEX_PROMPT.md baseline stale (216 vs 225) | **Resolved** — patched in Cycle 12 CODEX_PROMPT update | Resolved |

---

## Stop-Ship Decision

**No** — Zero P0 and zero P1 findings. Phase 11 gate criteria (WS-11.1–11.3 required, WS-11.4 optional/deferred) are met. Three P2 findings (FIX-10/FIX-11/FIX-12) must be resolved before Phase 12 begins. Seven P3 findings are logged for the next fix queue pass.

---
