# Decision Log — Dream Motif Interpreter

Version: 2.4
Last updated: 2026-05-02 (Phase 20 emoji mapping deferral)

## Rules

- keep entries short
- link every decision to a more detailed canonical doc or ADR
- supersede explicitly rather than silently rewriting history

## Decision Index

| ID | Date | Status | Decision | Canonical source |
|----|------|--------|----------|------------------|
| D-001 | 2026-04-10 | Active | Dream Motif Interpreter uses a workflow-shaped backend, not an open agent loop | `docs/ARCHITECTURE.md` |
| D-002 | 2026-04-10 | Active | Runtime tier remains `T1` | `docs/ARCHITECTURE.md` |
| D-003 | 2026-04-10 | Active | PostgreSQL + pgvector remain the canonical archive store | `docs/ARCHITECTURE.md` |
| D-004 | 2026-04-10 | Active | Annotation versioning is append-only and mandatory before mutations | `docs/IMPLEMENTATION_CONTRACT.md`, ADR-001 |
| D-005 | 2026-04-14 | Active | The backend remains the core product; Telegram is an interface layer | `docs/ARCHITECTURE.md`, `docs/PRODUCT_OVERVIEW.md` |
| D-006 | 2026-04-14 | Active | Telegram should be added inside the same repository as a separate runtime/process | ADR-003 |
| D-007 | 2026-04-14 | Active | The conversational layer must use a bounded internal assistant-tool facade | ADR-004 |
| D-008 | 2026-04-14 | Active | Phase 6 Telegram scope should start read-oriented plus explicit sync trigger | `docs/PHASE_PLAN.md` |
| D-009 | 2026-04-14 | Active | Voice support entered as Phase 7 with async transcription via OpenAI Whisper | ADR-005 |
| D-010 | 2026-04-14 | Active | Bot session state persisted in PostgreSQL `bot_sessions`; Redis for ephemeral only | ADR-006 |
| D-011 | 2026-04-14 | Active | Compose-first is the canonical deployment; `telegram-bot` service added to docker-compose.yml | ADR-007 |
| D-012 | 2026-04-16 | Active | WS-9.7 (Pattern Queries Extension) deferred to Phase 9.1 / Phase 10; pattern analysis over inducted motifs is only meaningful after a confirmed motif accumulation period that has not yet occurred | `docs/tasks_phase9.md §WS-9.7`, `docs/ARCHITECTURE.md §17` |
| D-013 | 2026-04-17 | Active | ResearchRetriever uses a provider-agnostic design (configurable base_url + api_key from settings); Tavily is the reference external search provider but the implementation does not hard-code it | `docs/tasks_phase10.md §WS-10.2 Notes`, ADR-009 |
| D-014 | 2026-04-18 | Active | WS-11.4 (optional comment capture after digit rating) deferred; rating-only feedback sufficient for current quality signal; comment capture may be added in a future phase | `docs/tasks_phase11.md §WS-11.4`, `docs/FEEDBACK_LOOP.md §2` |
| D-015 | 2026-05-01 | Planned | Dream recording reliability must move from prompt-only behavior to deterministic intake, pending-draft state, write status tracking, and honest success/failure responses | `docs/tasks_phase17.md` |
| D-016 | 2026-05-01 | Active | Local AI development workflow requires explicit role ownership, prompt-file dispatch via `PROMPT=$(cat ...)`, mandatory light/deep review gates, documentation updates, and ruff/format checks before completion | `docs/prompts/ORCHESTRATOR.md`, `docs/CODEX_PROMPT.md §Instructions for Codex` |
| D-017 | 2026-05-02 | Active | Telegram numeric feedback prompt remains active and shortened; emoji reactions are stored and scaffolded for semantics, but concrete emoji meaning mapping is deferred until the user supplies it | `docs/tasks_phase20.md §WS-20.2-20.3`, `docs/FEEDBACK_LOOP.md §2, §7` |

## Notes

- Decisions through D-014 and D-016 through D-017 are Active; D-015 is planned and becomes Active when Phase 17 lands.
- The presence of a decision in this log implies the corresponding implementation exists unless explicitly marked otherwise.
