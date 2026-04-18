# Feedback Loop — Dream Motif Interpreter

This document defines the feedback capture capability planned for Phase 11: its purpose, capture mechanism, data model, admin access, and explicit scope boundaries.

---

## 1. Purpose

The feedback loop provides a quality signal for human review of assistant responses. It allows the user to rate individual responses on a 1–5 scale with an optional comment.

Ratings are stored for manual inspection only. They do not feed into automated retraining, do not alter model behavior in any session, and are not used for any unsupervised training pipeline. The sole purpose is to accumulate a quality signal that a human reviewer can inspect.

This phase is independent of Phase 9 (motif abstraction) and Phase 10 (research augmentation). It can be implemented and deployed without either of those phases being active.

---

## 2. Capture Mechanism

The feedback is captured passively via Telegram without requiring a separate workflow.

### Trigger condition

After the assistant delivers a substantive response (not an error message, not a transcription acknowledgment, not a system notice), it appends: "Reply to this message to rate (1–5), or add a comment after the digit."

### Primary path — Telegram reply

The preferred capture path uses Telegram's native reply feature. The user taps "Reply" on the specific bot message and sends:

- A single digit (1–5): recorded as a rating, `comment = NULL`.
- A digit followed by text (e.g. `"4 Too detailed"`): digit recorded as score, remaining text stored as `comment`.
- Text with no leading digit: not treated as a rating — processed as a normal chat message.

Detection is deterministic (no LLM calls). Only a reply to the exact bot message ID that triggered the prompt is accepted.

### Fallback path — plain digit message

For backward compatibility, a plain digit message (1–5, no other characters) sent immediately after a substantive response is also accepted as a rating if the pending-feedback state is set. Comment is `NULL` in this path.

### Acknowledgment

When a rating is captured via either path, the assistant sends: "Thanks, noted." No further action is taken in that conversation turn.

### Comment capture

A comment is stored when the user appends text after the digit in the same reply (e.g. `"3 Responses are too long"`). The comment is stored in `assistant_feedback.comment` and used for system-prompt context injection (§6).

---

## 3. Data Model — assistant_feedback Table

```
assistant_feedback
├── id          uuid, primary key
├── chat_id     text, not null             — Telegram chat_id of the rating user
├── context     jsonb, not null            — snapshot of the assistant response being rated
├── score       smallint, not null         — integer 1–5
├── comment     text, nullable             — optional free-text comment
└── created_at  timestamptz, not null
```

Migration: `011_add_feedback`

The `context` JSONB field captures enough information to identify which response was rated (e.g., message ID, response summary, tool calls made). It does not store raw dream text or PII beyond what is necessary to identify the response.

---

## 4. Admin Access

`GET /feedback` provides a paginated view of stored feedback rows for admin inspection.

Behavior:
- Returns rows in reverse chronological order.
- Supports pagination via standard `limit` and `offset` query parameters.
- Returns `score`, `comment`, `chat_id`, `created_at`, and a summary of the `context` field.
- Access requires the standard API key header.

This endpoint is read-only. Feedback rows cannot be deleted or modified via the API.

---

## 5. What Is Explicitly Deferred

The following are out of scope and must not be implemented without an explicit decision:

- **Fine-tuning**: no mechanism for using feedback rows to fine-tune any model.
- **Automated model update**: feedback scores must not trigger any automated change to model parameters or tool catalogs.
- **Unsupervised training pipeline**: no pipeline that reads feedback rows and modifies system behavior without human review.
- **Reinforcement from feedback**: RLHF or similar approaches are deferred indefinitely.

Any future decision to use feedback data for model improvement beyond §6 must be documented in an ADR and implemented as a separate phase.

---

## 6. Feedback Context Injection

Recent user feedback (comments and low scores) is injected into the assistant's system prompt before each response to allow the assistant to adapt its style and depth over time.

### Query

At the start of each `handle_chat_with_metadata` call, the system loads up to 20 rows from `assistant_feedback` where:

- `comment IS NOT NULL AND comment != ''`, OR
- `score <= 2`

Rows are ordered oldest-first so the most recent signal appears at the bottom of the injected block.

### Injection format

If matching rows exist, the following section is appended to the base system prompt:

```
## Recent User Feedback
The following feedback was collected from the user over time.
Use it to adapt your response style, depth, and tone:
- [YYYY-MM-DD] score=N/5: "comment text"
- [YYYY-MM-DD] score=N/5 (no comment)
```

### Graceful degradation

If the database query fails (network error, timeout, etc.), the base `SYSTEM_PROMPT` is used unchanged. The error is logged as a warning. No response is suppressed.

### Scope boundary

This injection path is one-way read: the feedback loop reads from `assistant_feedback` to inform the system prompt. It does not write to the archive, does not alter RAG indexing, and does not modify stored motifs or research results. `assistant_feedback` remains excluded from all ingestion pipelines.
