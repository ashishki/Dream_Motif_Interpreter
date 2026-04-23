# Telegram Interaction Model

Last updated: 2026-04-23 (Phase 12 — research flow simplified, response formatting rules added)

## 1. Purpose

This document defines how Telegram should be used as an interface layer for Dream Motif Interpreter.

It does not define the dream-analysis core itself.

## 2. Design Goal

The user should be able to interact with the dream archive as if talking to a careful assistant:

- ask by text
- send voice notes
- get grounded responses
- avoid raw command-only UX

## 3. Core Boundary

Telegram is an interface adapter.
It does not own:

- dream storage
- theme curation rules
- retrieval logic
- archive truth

Those stay in Dream Motif Interpreter core services.

## 4. Implementation Reference

The repository:

- `~/Documents/dev/ai-stack/projects/film-school-assistant`

is the implementation reference for Telegram interaction patterns.

Use it as the primary code reference for:

- bot bootstrap and runtime organization
- authorization guard shape
- handler layering
- bounded conversational tool routing
- voice-update lifecycle

Do not port mechanically:

- SQLite persistence model
- notes/projects/deadlines schema
- film-school prompts or UX wording
- domain-specific tool catalog

## 5. Recommended Phase 6 Behavior

The Telegram assistant should:

- greet and orient the authorized user
- accept natural-language text questions
- use a bounded internal tool catalog
- return archive-backed answers
- preserve interpretation disclaimers where relevant
- say when evidence is insufficient

## 6. Recommended Initial Tool Catalog

- `search_dreams`
- `get_dream`
- `list_recent_dreams`
- `get_patterns`
- `get_theme_history`
- `trigger_sync`

Phase 6 boundary note:

- Telegram should call the bounded `AssistantFacade` in `app/assistant/`
- the facade returns DTO-style values and owns its DB sessions internally
- raw ORM/session access is not part of the assistant surface

Deferred tools:

- `confirm_theme`
- `reject_theme`
- `rollback_theme`
- `approve_category`

## 7. Conversational UX Rules

- concise, calm, grounded tone
- no authoritative interpretation claims
- no pretending to remember facts outside the archive
- no hidden archive mutations
- explicit distinction between “what the archive contains” and “what the assistant infers”

## 8. Session Model

Recommended:

- one persisted session per allowed chat
- short recent history retained for conversational continuity
- pending action state stored durably

Do not:

- treat chat history as dream memory
- silently create archive content from casual chat without an explicit domain flow

## 9. Authorization

Telegram access should be restricted by:

- allowed chat ID
- ideally allowed Telegram user ID

Unauthorized traffic should be dropped or minimally logged without leaking details.

## 10. Failure Handling

If a request cannot be fulfilled:

- say so directly
- prefer grounded partial help over fabricated confidence
- preserve the same `insufficient_evidence` philosophy used in the backend

## 11. Chat-Driven Curation — Deferred (P8-T02 Decision)

**Decision (2026-04-15):** chat-driven archive mutations are deferred beyond Phase 8.

Telegram is currently **read-oriented**. The active tool catalog contains only:
- `search_dreams`, `get_dream`, `list_recent_dreams`, `get_patterns`, `get_theme_history` — read-only
- `trigger_sync` — write (re-import), not curation

The following tools remain deferred and are not implemented:
- `confirm_theme`
- `reject_theme`
- `rollback_theme`
- `approve_category`

Rationale for continued deferral:
- the text assistant is stable (Phase 6–7 complete) ✓
- an explicit, auditable confirmation UX is NOT yet designed ✗
- failure modes for conversational mutations are NOT yet documented ✗

Preconditions before enabling any curation tool:
1. Design a two-phase confirmation UX (intent → explicit confirmation message → execute).
2. Ensure all mutation calls produce an `AnnotationVersion` audit record.
3. Define rollback UX for cases where the user issues an erroneous confirm.
4. Document the failure modes (partial failure, concurrent mutations, sync conflicts).

Until all four preconditions are met, chat-driven mutation tools must not be added to the TOOLS catalog or AssistantFacade.

Implementation sequencing for this surface is tracked in:

- [docs/tasks_phase6.md](tasks_phase6.md)

## 12. Phase 9 Tool — get_dream_motifs (Planned)

`get_dream_motifs` returns the inducted motifs for a specific dream entry.

### What it returns

- the list of motif labels with confidence (`high`, `moderate`, `low`) and status (`draft`, `confirmed`, `rejected`)
- the rationale string for each motif as produced by the induction pipeline
- the grounded imagery fragments that support each motif label

### Confidence framing requirements

The assistant must frame motif results according to their confidence level and status:

- `draft` motifs must be presented as unconfirmed model suggestions, not as conclusions
- `confirmed` motifs may be presented with slightly more weight, but still as computational abstractions — never as interpretations
- `rejected` motifs must not be presented in normal responses
- The word "interpretation" must not be used to describe inducted motifs; use "abstraction" or "suggestion"

Example framing: "The induction pipeline flagged [label] as a possible abstract motif for this dream with [confidence] confidence. This is a computational suggestion derived from the imagery, not a curated finding."

The distinction between these motifs and the existing theme taxonomy must be preserved in responses. Inducted motifs and taxonomy-based themes are different things.

### Availability

This tool is only available when `MOTIF_INDUCTION_ENABLED=true`. If the flag is off, the tool must not appear in the tool catalog.

## 13. Phase 10 Tool — research_motif_parallels

`research_motif_parallels` searches for structural parallels in mythology, folklore, cultural, and taboo material for a confirmed inducted motif.

### Interaction flow (revised in Phase 12)

1. User asks for mythological parallels for a dream.
2. Assistant calls `get_dream_motifs(dream_id)` — receives motifs with UUIDs.
3. Assistant presents motifs and asks: **"Выберите, по каким мотивам провести поиск"** — no lengthy technical preamble.
4. User names the motif(s). Assistant calls `research_motif_parallels(motif_id)` for each.
5. Results shown as a plain numbered list — one entry per parallel.

The previous "state what you will search for + explicit confirmation" pattern is replaced by motif selection. The user's choice of motifs IS the confirmation.

### Language and framing rules (revised in Phase 12)

- Do not use the word «архетип» or «паттерн» unless the user used it first
- Do not add evaluative adjectives («глубокий», «интересный», «мощный») to results
- Do not add a summary paragraph at the end («Общий архетип: ...»)
- All results remain speculative — never "confirmed" or "verified"
- If `research_motif_parallels` returns empty — present what is available from `get_dream_motifs`, do not block on a "technical barrier" message

### Speculative framing requirements

All results returned by this tool must be framed as speculative:

- every parallel must carry its source URL and retrieval timestamp
- confidence values are limited to: speculative, plausible, uncertain
- the assistant must not present any result as a finding or as confirmed

### What the tool does not do

- it is not a search engine the user can query freely
- it is not a reference source
- it does not make truth claims about the dream's meaning
- results must never be stored in or treated as equivalent to archive evidence

### Availability

This tool is only available when `RESEARCH_AUGMENTATION_ENABLED=true`. If the flag is off, the tool must not appear in the tool catalog.

### Known bug fixed in Phase 12

`get_dream_motifs` previously did not include the motif UUID in its output, making it impossible to call `research_motif_parallels`. Fixed in WS-12.1.

## 15. Phase 12 — Response Formatting Rules

These rules apply to all assistant responses in Telegram. They override any default Claude formatting behaviour.

### Plain text only

- No markdown: no `**bold**`, no `*italic*`, no `__underline__`, no inline code
- Lists use numbered format: `1.`, `2.`, `3.`
- No grouping results by section headers (e.g. "Сильная связь:", "Умеренная связь:") — use inline labels instead

### Date format

- User-facing dates: `дд.мм.гг` (e.g. `22.04.26`)
- Internal tool output uses ISO format (YYYY-MM-DD); Claude converts for the user

### Dream listing format

```
1. дд.мм.гг, без названия: о чём сон (краткое описание)
2. дд.мм.гг, Название: о чём сон
```

### Search results format

```
1. дд.мм.гг, без названия: описание (сильная связь)
2. дд.мм.гг, Название: описание (умеренная связь)
```

Connection strength verbal labels: ≥0.7 — сильная, 0.4–0.69 — умеренная, <0.4 — слабая.

### Dream title format (when saving)

| User provides | Resulting title |
|--------------|----------------|
| date + name | `дд.мм.гг - Название` |
| date only | `дд.мм.гг, без названия` |
| name only | use name as-is |
| neither | `дд.мм.гг, без названия` (use save date) |

## 14. Phase 11 — Feedback Capture UX (Planned)

### When the rating prompt appears

After the assistant delivers a substantive response (not an error message, not a transcription acknowledgment), it may append a brief rating prompt. The exact wording is: "Rate this response: reply with 1–5."

### What digit-only replies do

A message containing only a single digit (1–5) sent immediately after a substantive response is captured as a rating for that response. The system stores: the chat ID, the score, the context snapshot of the preceding response, and the creation timestamp.

Messages containing anything other than a single digit are not treated as ratings, even if they contain a digit among other characters.

### Acknowledgment message

When a rating is captured, the assistant sends a brief acknowledgment: "Thanks, noted." No further action is taken in the conversation.

### What ratings do not do

Ratings do not alter assistant behavior in the current session. They do not feed into automated retraining. They are stored for human review only via the `GET /feedback` admin endpoint.
