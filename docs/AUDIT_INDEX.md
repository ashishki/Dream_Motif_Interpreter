# Audit Index

Index of all phase deep reviews.

---

## Phase 13 — 2026-04-24

Report: [docs/REVIEW_REPORT.md](REVIEW_REPORT.md)
Verdict: PASS — all defects closed (D2 fixed pre-release; D1/D3/D4/D5 fixed in follow-up commit)
Tests: 294 unit tests passing

## Phase 14 — 2026-04-24

Report: implemented without separate deep review (straightforward CRUD addition)
Verdict: PASS — 300 unit tests passing; light review passed
Tests: 300 unit tests passing

## Phase 14 post-release fixes — 2026-04-24

Defects found in Тест 3 (24.04.26) and fixed in same session:
- D1: write succeeded in test but failed silently in bot — root cause: stale conversation history
  preserved failure state; model hallucinated "OAuth 2.0" explanation. Fix: cleared history.
- D2: no retry path — if write failed, user had no tool to retry without creating a duplicate.
  Fix: added retry_write_to_google_doc tool (facade + tools.py).
- D3: title written as NORMAL_TEXT — existing doc uses HEADING_1 for dream titles.
  Fix: replaced append_text with append_dream_entry (batchUpdate insertText + updateParagraphStyle).
- D4: system prompt did not constrain failure explanation — model improvised technical text.
  Fix: SYSTEM_PROMPT now specifies exact failure message and forbids technical improvisation.
- D5: history TTL absent — stale failure messages survived indefinitely.
  Fix: 7-day TTL in load_history; feedback table unaffected.
