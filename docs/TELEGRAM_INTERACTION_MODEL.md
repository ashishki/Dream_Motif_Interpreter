# Telegram Interaction Model

Last updated: 2026-04-14

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

## 11. Future Expansion Rule

Do not add chat-driven archive mutations until:

- the text assistant is stable
- the audit and confirmation UX is explicit
- the failure modes are well understood

Implementation sequencing for this surface is tracked in:

- [docs/tasks_phase6.md](tasks_phase6.md)
