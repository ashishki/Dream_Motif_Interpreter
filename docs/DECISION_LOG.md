# Decision Log — Dream Motif Interpreter

Version: 2.9
Last updated: 2026-07-18 (private-beta source-of-truth and reliability audit)

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
| D-014 | 2026-04-18 | Active | WS-11.4 (optional comment capture after digit rating) deferred; rating-only feedback sufficient for current quality signal; comment capture may be added in a future phase | `docs/tasks_phase11.md §WS-11.4`, `docs/FEEDBACK_LOOP.md §2, §7` |
| D-015 | 2026-05-01 | Active | Dream recording uses deterministic intake, pending-draft state, write status tracking, and honest partial-failure responses; provider outages must not delete a committed dream | `docs/tasks_phase17.md`, ADR-011 |
| D-016 | 2026-05-01 | Active | Local AI development workflow requires explicit role ownership, prompt-file dispatch via `PROMPT=$(cat ...)`, mandatory light/deep review gates, documentation updates, and ruff/format checks before completion | `docs/prompts/ORCHESTRATOR.md`, `docs/CODEX_PROMPT.md §Instructions for Codex` |
| D-017 | 2026-05-02 | Superseded by D-020 | Telegram numeric feedback prompt remains active and shortened; emoji reactions are stored and scaffolded for semantics, but concrete emoji meaning mapping is deferred until the user supplies it | `docs/tasks_phase20.md §WS-20.2-20.3`, `docs/FEEDBACK_LOOP.md §2, §7` |
| D-018 | 2026-05-09 | Active | Phase 22 treats Google Docs freshness as a P0 user-facing invariant: duplicate source content must not abort the entire sync, and failed/stale sync states must be visible before the assistant relies on missing archive evidence | `docs/tasks_phase22.md §WS-22.1-22.3`, `docs/archive/PHASE22_REVIEW.md` |
| D-019 | 2026-05-09 | Active | Whole-dream LLM interpretation must be a separate explicit-approval flow, distinct from motif induction and external research; interpretation output is subjective and is not persisted as archive fact in Phase 22 | `docs/tasks_phase22.md §WS-22.6`, `docs/IMPLEMENTATION_CONTRACT.md §LLM Output Framing`, `docs/archive/PHASE22_REVIEW.md` |
| D-020 | 2026-05-15 | Active | Telegram numeric 1–5 feedback prompt and digit capture are disabled by default because they interfere with numbered-choice conversation; legacy capture remains behind `TELEGRAM_NUMERIC_FEEDBACK_ENABLED=true` | `docs/tasks_phase23.md §WS-23.3`, `docs/FEEDBACK_LOOP.md §2`, `docs/archive/PHASE23_REVIEW.md` |
| D-021 | 2026-05-29 | Active | Dream Memory Map is reflective journaling and pattern memory, not diagnosis; Telegram bot remains capture/conversation while the Telegram mini app owns graph, timeline, search, recurring motif, and privacy/export UX | `docs/DREAM_MEMORY_MAP.md`, `docs/tasks_phase26.md §WS-26.1` |
| D-022 | 2026-07-18 | Active | The product-managed PostgreSQL archive is the sole private-beta source of truth; Google Docs is an optional import/mirror until durable reconciliation and conflict handling exist | ADR-011 |

## Notes

- Decisions through D-016 and D-018 through D-022 are Active; D-017 is superseded by D-020.
- The presence of a decision in this log implies the corresponding implementation exists unless explicitly marked otherwise.
- D-022 clarifies, rather than migrates, the storage ownership already represented by the implemented database model.
