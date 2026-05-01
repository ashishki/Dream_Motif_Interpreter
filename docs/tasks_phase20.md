# Task Graph — Dream Motif Interpreter Phase 20

Version: 1.0
Last updated: 2026-05-01
Status: Planned — polish backlog from Тест 5

## 1. Purpose

Phase 20 collects lower-priority UX polish that should follow the critical recording and
search fixes.

## 2. Workstreams

---

## WS-20.1: Place Notes Under the Target Dream in Google Doc

Owner:      codex
Phase:      20
Type:       Google Docs write behavior
Priority:   P2
Depends-On: Phase 17 write status stabilization

Objective:
  `add_dream_note` currently appends note text to the document, but not necessarily under the
  target dream heading. Make note placement target-aware where possible.

Acceptance-Criteria:
  - AC-1: Note is saved in `dream_notes` as today.
  - AC-2: Google Doc insertion attempts to place the note under the matching dream heading.
  - AC-3: If exact placement cannot be found, append fallback is explicit in logs and user message.
  - AC-4: Tests cover successful placement and fallback append.

Files:
  - `app/services/gdocs_client.py`
  - `app/assistant/facade.py`
  - `tests/unit/test_gdocs_client.py`
  - `tests/unit/test_assistant_facade.py`

---

## WS-20.2: Emoji Reaction Semantics

Owner:      codex
Phase:      20
Type:       feedback
Priority:   P2
Depends-On: user provides emoji mapping

Objective:
  Interpret stored Telegram reactions as qualitative feedback once the user provides the emoji
  list and meanings.

Acceptance-Criteria:
  - AC-1: Mapping is configurable and documented.
  - AC-2: Reaction feedback can be converted into assistant feedback context.
  - AC-3: Unknown emoji remain stored as raw reactions without interpretation.
  - AC-4: Tests cover mapped, unmapped, added, and removed reactions.

Files:
  - `app/models/reaction.py`
  - `app/services/feedback_service.py` or new reaction feedback service
  - `app/telegram/bot.py`
  - `docs/FEEDBACK_LOOP.md`
  - `tests/unit/test_reaction_model.py`
  - `tests/unit/test_feedback_context.py`

Blocker:
  User must provide emoji list and meanings.

---

## WS-20.3: Feedback Prompt UX Decision

Owner:      codex
Phase:      20
Type:       UX docs + Telegram behavior
Priority:   P3
Depends-On: WS-20.2

Objective:
  Decide whether the numeric "Оцените ответ от 1 до 5" prompt remains, is shortened, or is
  replaced by emoji reactions.

Acceptance-Criteria:
  - AC-1: `docs/FEEDBACK_LOOP.md` records the chosen UX.
  - AC-2: Telegram handler behavior matches the doc.
  - AC-3: User guide is updated.

Files:
  - `app/telegram/handlers.py`
  - `docs/FEEDBACK_LOOP.md`
  - `docs/USER_GUIDE_RU.md`

## 3. Phase Gate

- [ ] Notes placement behavior is target-aware or explicitly falls back.
- [ ] Emoji semantics implemented after mapping is provided.
- [ ] Feedback prompt UX decision documented.
