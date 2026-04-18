---
# META_ANALYSIS — Cycle 11
_Date: 2026-04-17 · Type: full_

## Project State

Phase 10 (WS-10.1–WS-10.5) complete. Phase 11 (Feedback Loop) in progress: WS-11.1 (DB migration + ORM model), WS-11.2 (Telegram digit-reply capture), and WS-11.3 (GET /feedback API route) are implemented. WS-11.4 (optional comment capture) is not yet implemented.
Next: WS-11.4 — Light Polish (optional), then Phase 11 gate verification and CODEX_PROMPT.md baseline update.

Baseline: 225 unit tests passing (measured 2026-04-17; up from 216 at Cycle 10 close). CODEX_PROMPT.md §Current State still reads 216 — stale; requires update to 225.

Change vs Cycle 10: all Cycle 10 Fix Queue items (FIX-7/FIX-8/FIX-9) confirmed applied and closed. Three new Phase 11 source files added (`app/telegram/handlers.py`, `app/services/feedback_service.py`, `app/api/feedback.py`), three new model/migration files (`app/models/feedback.py`, `alembic/versions/011_add_feedback.py`, `app/models/__init__.py` updated), and two new test files (`tests/unit/test_feedback_capture.py`, `tests/unit/test_feedback_api.py`).

---

## Open Findings

| ID | Sev | Description | Files | Status |
|----|-----|-------------|-------|--------|
| CODE-5 | P3 | `RESEARCH_API_KEY` defaults to `""` with no `model_validator` at startup when `RESEARCH_AUGMENTATION_ENABLED=True`. ADR-010 acknowledges deferral, but a fail-fast validator would catch misconfiguration early. No FIX assignment exists; risk remains accepted without explicit closure. | `app/shared/config.py:31` | Open — Cycle 10 carry-forward; no FIX entry assigned |
| DOC-1 | P3 | `docs/CODEX_PROMPT.md §Current State` baseline field reads 216; actual unit test count is 225 after Phase 11 WS-11.1–11.3 additions. | `docs/CODEX_PROMPT.md` | Open — new Cycle 11 |
| WS11-1 | P2 | `AssistantFeedback` ORM model has no SQLAlchemy-level `CheckConstraint` on the `score` column. The CHECK constraint exists in the migration DDL (`ck_assistant_feedback_score_range`), but the ORM model definition omits it. `FeedbackService.record()` provides a Python-level guard (score < 1 or score > 5 raises ValueError), but direct ORM usage bypassing the service has no model-level protection. | `app/models/feedback.py:22`, `app/services/feedback_service.py:16–17` | Open — new Cycle 11 |
| WS11-2 | P3 | `GET /feedback` route opens a `db.query.feedback.list` OTel child span but emits no meter counter. All other API read routes emit a labeled counter per OBS-2. | `app/api/feedback.py:26–45` | Open — new Cycle 11 |
| WS11-3 | P3 | In-memory `_feedback_pending_by_chat` dict in `handlers.py` (stored in `context.bot_data`) is unbounded. Long-running bots with many distinct `chat_id` values, or chats where the user never sends a digit reply, will accumulate stale entries indefinitely. No TTL eviction or max-size cap. | `app/telegram/handlers.py:44, 74–79` | Open — new Cycle 11 |
| WS11-4 | P3 | `handlers.py` calls `session.commit()` immediately after `FeedbackService.record()` with no try/except. A transient DB failure during commit propagates as an unhandled exception and suppresses the `FEEDBACK_ACK` reply to the user. | `app/telegram/handlers.py:55–58` | Open — new Cycle 11 |

### Closed findings confirmed at Cycle 11 (FIX-7/FIX-8/FIX-9 applied 2026-04-17)

| ID | Sev | Description | Status |
|----|-----|-------------|--------|
| CODE-1 (C10) | P2 | `ResearchRetriever.retrieve()` external HTTP call had no OTel span or counter | **Closed** — FIX-7 applied; span at `retriever.py:36`, counter at `retriever.py:30` |
| CODE-2 (C10) | P2 | `ResearchSynthesizer.synthesize()` LLM call had no OTel span or counter | **Closed** — FIX-8 applied; span at `synthesizer.py:40`, counter at `synthesizer.py:32` |
| CODE-3 (C10) | P2 | `docs/retrieval_eval.md` missing Cycle 10 advisory row | **Closed** — FIX-9 applied; Cycle 10 advisory row present |
| CODE-4 (C10) | P3 | `docs/IMPLEMENTATION_JOURNAL.md` had no Phase 10 entry | **Closed** — FIX-9 applied; Phase 10 entry present |
| ARCH-1 (C10) | P3 | `app/research/` and `ResearchService` absent from `ARCHITECTURE.md §9` | **Closed** — `app/research/` row present at `ARCHITECTURE.md:188` |
| ARCH-2 (C10) | P3 | Duplicate `## 18` section number in `ARCHITECTURE.md` | **Closed** — formerly conflicting section now correctly numbered `## 22` |
| ARCH-4 (C10) | P3 | `ARCHITECTURE.md §18` header read `(Planned — Phase 10)` | **Closed** — header now reads `## 18. Research Augmentation Layer` without status qualifier |

---

## PROMPT_1 Scope (architecture)

- feedback table isolation: verify `assistant_feedback` has no FK to `dream_entries`, `dream_themes`, or `dream_chunks`; confirm the table is excluded from all RAG ingestion pipeline code paths
- Telegram handler state model: in-memory `_feedback_pending_by_chat` per-chat dict lives in `context.bot_data`; assess whether this is consistent with bot session restart semantics and multi-instance deployment; compare with `bot_sessions` table for persistent state precedent
- GET /feedback auth coverage: route is covered by the global `require_authentication` middleware (not in `PUBLIC_PATHS`); confirm no accidental bypass path exists for this route
- context JSONB privacy: WS-11.2 AC-3 requires no raw dream text in the `context` field; confirm `response_summary` and `tool_calls_made` fields in the handler do not capture raw dream text
- WS-11.4 deferral decision: if WS-11.4 (optional comment capture) is deferred, assess whether this should be recorded in `docs/DECISION_LOG.md` following the WS-9.7 deferral pattern (D-012)

---

## PROMPT_2 Scope (code, priority order)

1. `app/telegram/handlers.py` (new — Phase 11 digit-reply detection, substantive-response classification, feedback state management)
2. `app/services/feedback_service.py` (new — feedback persistence service; session ownership and validation logic)
3. `app/api/feedback.py` (new — GET /feedback paginated read endpoint; auth and OTel coverage)
4. `app/models/feedback.py` (new — AssistantFeedback ORM model; CHECK constraint presence)
5. `alembic/versions/011_add_feedback.py` (new — migration with score CHECK constraint and all required columns per WS-11.1 AC-1)
6. `app/models/__init__.py` (changed — exports AssistantFeedback per WS-11.1 AC-5)
7. `app/main.py` (changed — feedback router registered; auth middleware applies)
8. `tests/unit/test_feedback_capture.py` (new — digit-reply and substantive-response unit tests; WS-11.2 AC-6)
9. `tests/unit/test_feedback_api.py` (new — GET /feedback unit tests; WS-11.3 AC-4)
10. `app/shared/config.py` (regression check — CODE-5 carry-forward: `RESEARCH_API_KEY` still has no startup validator)

---

## Cycle Type

Full — Phase 11 implementation is in progress with three of four workstreams (WS-11.1–WS-11.3) implemented and the optional WS-11.4 not yet started. All Cycle 10 Fix Queue items are confirmed closed. This cycle reviews the complete new feedback loop surface for the first time. No P0 or P1 findings; the system is safe to complete Phase 11 and close the gate.

---

## Notes for PROMPT_3

- Primary consolidation focus: update `docs/CODEX_PROMPT.md` baseline from 216 to 225 and move WS-11.1, WS-11.2, WS-11.3 to Completed Tasks; confirm Phase 11 gate criteria (WS-11.1–WS-11.3 required, WS-11.4 optional).
- CODE-5 (`RESEARCH_API_KEY` startup validation) has been carried forward since Cycle 10 with no FIX assignment. Either assign FIX-10 or formally document acceptance in ADR-010 §Consequences and close the finding with a decision reference.
- WS11-1 (ORM-level score CHECK constraint absence) should be assigned a FIX entry if the project intends to use `AssistantFeedback` directly in any context outside `FeedbackService.record()`. Low risk today; medium risk as the codebase grows.
- If WS-11.4 is deferred, record the decision in `docs/DECISION_LOG.md` consistent with the WS-9.7 deferral pattern (D-012). Do not silently omit it.
- Cycle 11 advisory row must be added to `docs/retrieval_eval.md` Evaluation History confirming the RAG layer is unchanged in Phase 11 (per RET-7 mandatory-each-cycle rule).
---
