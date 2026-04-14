# Implementation Reference Map

Last updated: 2026-04-14

## 1. Purpose

This document maps the Telegram-first reference repository to the planned Dream Motif Interpreter implementation areas for Phase 6+.

Reference repository:

- `~/Documents/dev/ai-stack/projects/film-school-assistant`

Use this file when implementing the interaction layer so the work ports proven patterns instead of regenerating the whole Telegram stack from scratch.

## 2. Rule of Use

Use `film-school-assistant` as the implementation reference for:

- Telegram runtime structure
- handler layering
- bounded assistant tool-loop patterns
- voice ingress sequencing
- private single-user bot operations

Do not treat it as the source of truth for:

- Dream Motif Interpreter schema
- archive storage
- retrieval logic
- theme curation rules
- dream-domain prompts or semantics

## 3. File-to-Target Map

| Reference repo file | Why it matters | Planned DMI target area |
|---------------------|----------------|--------------------------|
| `src/bot.py` | bot bootstrap, handler registration, auth gate, runtime flow | `app/telegram/bot.py`, `app/telegram/handlers.py` |
| `src/handlers/chat_handler.py` | bounded chat loop and tool invocation shape | `app/assistant/router.py`, `app/assistant/tools.py` |
| `src/tools.py` | explicit tool catalog design | `app/assistant/tools.py`, `app/assistant/policy.py` |
| `src/state.py` | session/state behavior reference | `app/assistant/sessions.py` |
| `src/voice.py` | voice file lifecycle and temp-file handling pattern | `app/telegram/voice.py` |
| `src/transcriber.py` | transcription boundary shape | `app/workers/` transcription jobs and provider adapters |
| `src/config.py` | bot/runtime env contract pattern | `app/shared/config.py`, bot-specific config module |
| `docs/DEPLOY.md` | private bot deployment and process supervision reference | `docs/DEPLOY.md`, bot runbooks |
| `systemd/*.service`, `systemd/*.timer` | operational decomposition pattern | DMI deploy/runbook guidance, optional systemd appendix |
| `docs/ARCHITECTURE.md` | interaction-layer boundaries and deterministic-vs-LLM split | DMI Phase 6+ architecture alignment |
| `docs/WORKFLOW_BOUNDARIES.md` | bounded assistant and approval thinking | DMI assistant/tool policy docs |

## 4. Port, Adapt, Do Not Copy

### Port Directly in Shape

- bot process structure
- handler separation
- allowed-user authorization pattern
- bounded tool-calling loop structure
- voice ingress lifecycle
- user acknowledgement for long-running operations

### Adapt Heavily

- session persistence
- env/config shape
- error texts and assistant wording
- deployment details
- transcription provider implementation

### Do Not Copy Mechanically

- SQLite schema
- projects/notes/deadlines/homework model
- film-school domain prompts
- in-memory-only state as final persistence model
- any domain logic that bypasses Dream Motif Interpreter service boundaries

## 5. Recommended Implementation Order

1. Read `docs/tasks_phase6.md`
2. Read DMI architecture and Telegram docs
3. Read the mapped `film-school-assistant` files for the current task
4. Port the runtime pattern
5. Replace domain-specific logic with Dream Motif Interpreter service calls
6. Add DMI-specific persistence, auth policy, and tests

## 6. Companion Documents

- [Architecture](ARCHITECTURE.md)
- [Phase Plan](PHASE_PLAN.md)
- [Telegram Interaction Model](TELEGRAM_INTERACTION_MODEL.md)
- [Voice Pipeline](VOICE_PIPELINE.md)
- [Phase 6+ Task Graph](tasks_phase6.md)
