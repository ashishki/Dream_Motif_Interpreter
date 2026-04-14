# Decision Log — Dream Motif Interpreter

Version: 2.0  
Last updated: 2026-04-14

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
| D-009 | 2026-04-14 | Proposed | Voice support enters as a separate Phase 7 with async transcription | ADR-005 |
| D-010 | 2026-04-14 | Proposed | Bot session state should be persisted durably, with Redis used only for ephemeral coordination | ADR-006 |
| D-011 | 2026-04-14 | Proposed | Compose-first is the canonical deployment documentation for the Telegram-enabled stack | ADR-007 |

## Notes

- Decisions marked `Proposed` are intentional planning decisions for Phase 6+ and should be confirmed during implementation.
- The presence of a decision in this log does not imply the corresponding implementation already exists.
