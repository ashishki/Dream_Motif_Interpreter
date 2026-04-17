# Task Graph — Dream Motif Interpreter Phase 11

Version: 1.0
Last updated: 2026-04-17
Status: Planned task graph for Phase 11 — Feedback Loop

## 1. Purpose

This file is the implementation task graph for Phase 11 of Dream Motif Interpreter.

It exists so the repository can preserve:

- Phase 10 execution history in `docs/tasks_phase10.md`
- a clean execution source for Phase 11 feedback loop work
- continuity between the research augmentation layer and the new quality signal capability

## 2. How To Use This File

- use this file as the active implementation authority for Phase 11 feedback loop work
- treat `docs/tasks_phase10.md` as the authoritative history for Phase 10
- read `Context-Refs` before implementation begins
- do not start coding Phase 11 from architecture docs alone when a task here exists

Reference documents:

- `docs/FEEDBACK_LOOP.md`
- `docs/ARCHITECTURE.md §19–20`
- `docs/PHASE_PLAN.md §11`

Execution rules:

- assistant_feedback must never be added to any RAG ingestion pipeline (same rule as research_results)
- digit-reply detection must be deterministic (no LLM calls)
- score column must enforce CHECK constraint: score >= 1 AND score <= 5
- GET /feedback is read-only; no write path through that route
- context JSONB captures message_id, response_summary, tool_calls_made — no raw dream text

## 3. Phase 11 — Feedback Loop

Goal: allow the user to rate assistant responses (1–5) via Telegram digit reply. Capture in assistant_feedback. Expose via read-only API. No automated retraining.

Phase gate:

- 011_add_feedback migration creates assistant_feedback with all required columns
- Telegram handler detects digit-only reply (1–5) and persists an assistant_feedback row
- "Rate this response: reply with 1–5." appended after substantive responses
- "Thanks, noted." sent on digit capture
- GET /feedback returns paginated feedback rows
- assistant_feedback excluded from RAG ingestion pipeline

Dependency graph:

```
WS-11.1 → WS-11.2
WS-11.1 → WS-11.3
WS-11.2 + WS-11.3 → WS-11.4 (optional polish)
```

---

## WS-11.1: DB Migration and ORM Model

Owner:      codex
Phase:      11
Type:       persistence
Depends-On: none

Objective: |
  Add the assistant_feedback table migration and ORM model.

Acceptance-Criteria:
  - id: AC-1
    description: "Migration 011_add_feedback creates the assistant_feedback table: id (UUID PK), chat_id (TEXT NOT NULL), context (JSONB NOT NULL DEFAULT '{}'), score (SMALLINT NOT NULL CHECK score >= 1 AND score <= 5), comment (TEXT NULLABLE), created_at (TIMESTAMPTZ DEFAULT now())."
  - id: AC-2
    description: "ORM model AssistantFeedback is defined in app/models/feedback.py with correct column types."
  - id: AC-3
    description: "Migration does not modify any existing table."
  - id: AC-4
    description: "Model can be imported cleanly: python -c 'from app.models.feedback import AssistantFeedback; print(OK)'"
  - id: AC-5
    description: "app/models/__init__.py exports AssistantFeedback."

Files:
  - alembic/versions/011_add_feedback.py
  - app/models/feedback.py
  - app/models/__init__.py

Context-Refs:
  - docs/FEEDBACK_LOOP.md §3
  - docs/ARCHITECTURE.md §19

Notes: |
  assistant_feedback must NOT be added to any RAG ingestion pipeline.
  No FK to dream_entries or motif_inductions — this table is standalone.

---

## WS-11.2: Telegram Digit-Reply Capture

Owner:      codex
Phase:      11
Type:       assistant
Depends-On: WS-11.1

Objective: |
  Implement digit-reply detection and feedback persistence in the Telegram handler.

Acceptance-Criteria:
  - id: AC-1
    description: "After a substantive assistant response (not error, not transcription ack, not system notice), the assistant appends 'Rate this response: reply with 1–5.'"
  - id: AC-2
    description: "A message containing exactly one digit 1–5 (no spaces, no other chars) sent immediately after a substantive response is interpreted as a rating."
  - id: AC-3
    description: "When a rating is captured, an AssistantFeedback row is persisted with: chat_id, context (message_id + response_summary + tool_calls_made, no raw dream text), score."
  - id: AC-4
    description: "The bot replies 'Thanks, noted.' on digit capture."
  - id: AC-5
    description: "Digit detection is deterministic — no LLM calls. A message containing digits alongside other characters is NOT treated as a rating."
  - id: AC-6
    description: "Behavior is covered by unit tests with a stub DB session."

Files:
  - app/telegram/handler.py (or equivalent Telegram update handler)
  - app/services/feedback_service.py
  - tests/unit/test_feedback_capture.py

Context-Refs:
  - docs/FEEDBACK_LOOP.md §2
  - docs/ARCHITECTURE.md §20

Notes: |
  Read the existing Telegram handler to understand message routing before modifying.
  The "last response was substantive" state can be tracked in bot_sessions or
  as a simple in-memory flag per chat_id in the handler.
  context JSONB must not include raw_text or chunk_text from dream entries.

---

## WS-11.3: GET /feedback API Route

Owner:      codex
Phase:      11
Type:       api
Depends-On: WS-11.1

Objective: |
  Expose assistant_feedback rows via a read-only paginated API endpoint.

Acceptance-Criteria:
  - id: AC-1
    description: "GET /feedback returns assistant_feedback rows ordered by created_at desc."
  - id: AC-2
    description: "Supports pagination: limit (default 20, max 100) and offset query params."
  - id: AC-3
    description: "Route is protected by existing X-API-Key auth middleware."
  - id: AC-4
    description: "Route is covered by unit tests."
  - id: AC-5
    description: "No write path through this route."

Files:
  - app/api/feedback.py
  - app/main.py
  - tests/unit/test_feedback_api.py

Context-Refs:
  - docs/FEEDBACK_LOOP.md §4
  - app/api/research.py (pattern to follow)

---

## WS-11.4: Light Polish (Optional)

Owner:      codex
Phase:      11
Type:       polish
Depends-On: WS-11.2, WS-11.3

Objective: |
  Optional: capture optional comment field if next message follows digit reply within
  a short window. Low priority — only if WS-11.2 and WS-11.3 are complete with time remaining.

Acceptance-Criteria:
  - id: AC-1
    description: "If WS-11.4 is implemented, a text message following a digit-only rating within the same conversation turn is stored in the comment field."

Files:
  - app/telegram/handler.py
  - tests/unit/test_feedback_capture.py

Notes: |
  This workstream is OPTIONAL and may be deferred. Do not block Phase 11 gate on WS-11.4.

---

## 4. Continuity Notes

- `docs/tasks_phase10.md` is the authoritative history for Phase 10 (complete)
- `docs/tasks_phase11.md` is this file — the active task graph for Phase 11
- when files diverge, use this file for Phase 11 implementation work
