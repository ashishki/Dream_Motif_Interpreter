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

After the assistant delivers a substantive response (not an error message, not a transcription acknowledgment, not a system notice), it may append a brief prompt: "Rate this response: reply with 1–5."

### Digit-only reply detection

A message containing exactly one digit (1, 2, 3, 4, or 5) sent as the next message in the conversation after a substantive response is interpreted as a rating for that response.

Detection rules:
- The message must contain only a single digit character (no spaces, no other characters).
- The digit must be in the range 1–5.
- The message must immediately follow a substantive assistant response in the conversation flow.
- Messages that contain digits alongside other characters are not treated as ratings.

### Acknowledgment

When a rating is captured, the assistant sends: "Thanks, noted." No further action is taken in that conversation turn.

### Optional comment

The user may optionally send a follow-up message with a text comment after submitting a digit rating. If the system is configured to capture it, the comment is stored in the `comment` field of the `assistant_feedback` row. Comment capture is optional and must be implemented explicitly; it is not implied by digit capture alone.

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

The following are out of scope for Phase 11 and must not be implemented without an explicit decision:

- **Fine-tuning**: no mechanism for using feedback rows to fine-tune any model.
- **Automated model update**: feedback scores must not trigger any automated change to model parameters, prompts, or tool catalogs.
- **Unsupervised training pipeline**: no pipeline that reads feedback rows and modifies system behavior without human review.
- **Reinforcement from feedback**: RLHF or similar approaches are not part of this phase and are deferred indefinitely.
- **Feedback-driven prompt modification**: the system prompt and tool catalog must not be automatically adjusted based on feedback scores.

Any future decision to use feedback data for model improvement must be made explicitly, documented in an ADR, and implemented as a separate phase.
