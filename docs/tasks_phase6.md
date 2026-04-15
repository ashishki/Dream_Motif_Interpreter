# Task Graph — Dream Motif Interpreter Phase 6+

Version: 1.0  
Last updated: 2026-04-14  
Status: Active execution graph for Telegram-enabled evolution

## 1. Purpose

This file is the active implementation task graph for the post-Phase-5 evolution of Dream Motif Interpreter.

It exists so the repository can preserve:

- historical Phase 1-5 execution history in `docs/tasks.md`
- a clean execution source for Phase 6, 7, and 8 work
- continuity between what was already built and what is being built now

## 2. How To Use This File

- use this file as the active implementation authority for Telegram, voice, and Phase 6+ operational work
- treat `docs/tasks.md` as the historical backend task graph
- read `Context-Refs` before implementation begins
- do not start coding against Phase 6+ from architecture docs alone when a task here exists

Implementation reference for the interaction layer:

- `~/Documents/dev/ai-stack/projects/film-school-assistant`
- `docs/IMPLEMENTATION_REFERENCE_MAP.md`

Execution rule:

- if that repository already contains a proven Telegram-first pattern, port and adapt it
- do not generate a fresh interaction layer from scratch unless no workable reference pattern exists
- adapt the reference to Dream Motif Interpreter domain services rather than copying its schema or product logic

## 3. Phase 6 — Telegram Interaction Foundation

Goal: add a private Telegram text interface that allows the single user to interact with the dream archive conversationally while preserving Dream Motif Interpreter as the system of record.

Phase gate:

- authorized Telegram text flow works end-to-end
- bot uses a bounded assistant tool facade
- insufficient-evidence behavior is preserved in chat
- bot sessions survive restart
- env and deployment docs remain consistent with implementation

---

## P6-T01: Reconcile Backend Execution Boundary

Owner:      codex
Phase:      6
Type:       architecture
Depends-On: none

Objective: |
  Reconcile the documented ingest -> analyse -> index backend flow with the currently
  visible worker/service wiring so Phase 6 work is built on an explicit, verified core path.

Acceptance-Criteria:
  - id: AC-1
    description: "The implementation path for sync, analysis, and indexing is documented in code-facing terms and matches the active runtime wiring."
  - id: AC-2
    description: "Any mismatch between docs and code is resolved either by code change or by explicit documentation."
  - id: AC-3
    description: "The Phase 6 assistant design is not forced to guess whether new dream entries are analysed and indexed automatically."

Files:
  - app/workers/ingest.py
  - app/workers/index.py
  - app/services/analysis.py
  - docs/ARCHITECTURE.md
  - docs/IMPLEMENTATION_JOURNAL.md

Context-Refs:
  - docs/ARCHITECTURE.md
  - docs/spec.md
  - docs/PHASE_PLAN.md
  - ~/Documents/dev/ai-stack/projects/film-school-assistant

Notes: |
  This task is a prerequisite sanity step. Telegram integration should not proceed on top
  of an ambiguous backend execution path.

---

## P6-T02: Assistant Service Facade

Owner:      codex
Phase:      6
Type:       architecture
Depends-On: P6-T01

Objective: |
  Introduce a bounded internal assistant-facing service facade so Telegram and future
  assistant surfaces do not call raw route handlers or unrestricted DB logic.

Acceptance-Criteria:
  - id: AC-1
    description: "A dedicated assistant-facing service boundary exists for read-oriented archive operations."
  - id: AC-2
    description: "The facade exposes only approved operations such as search, dream lookup, pattern lookup, theme history lookup, and sync trigger."
  - id: AC-3
    description: "Chat-driven mutation operations remain absent or explicitly gated."

Files:
  - app/services/
  - app/assistant/
  - docs/ARCHITECTURE.md
  - docs/TELEGRAM_INTERACTION_MODEL.md

Context-Refs:
  - docs/ARCHITECTURE.md
  - docs/TELEGRAM_INTERACTION_MODEL.md
  - docs/adr/ADR-004-bounded-assistant-tool-facade.md
  - ~/Documents/dev/ai-stack/projects/film-school-assistant

---

## P6-T03: Telegram Bot Runtime

Owner:      codex
Phase:      6
Type:       interface
Depends-On: P6-T02

Objective: |
  Add a dedicated Telegram runtime inside the repository that can receive text messages,
  authenticate the allowed user, and route requests into the assistant service facade.

Acceptance-Criteria:
  - id: AC-1
    description: "The bot runtime starts independently from the API process."
  - id: AC-2
    description: "Unauthorized chat traffic is blocked safely."
  - id: AC-3
    description: "Authorized text requests can reach the assistant service path and return responses."

Files:
  - app/telegram/
  - app/shared/config.py
  - docs/ENVIRONMENT.md
  - docs/DEPLOY.md
  - docs/RUNBOOK_TELEGRAM_BOT.md

Context-Refs:
  - docs/TELEGRAM_INTERACTION_MODEL.md
  - docs/AUTH_SECURITY.md
  - docs/adr/ADR-003-telegram-adapter-inside-core-repo.md
  - ~/Documents/dev/ai-stack/projects/film-school-assistant

Notes: |
  Start from the proven runtime and handler patterns in `film-school-assistant`.
  Replace only the domain layer and persistence assumptions that are specific to
  the film-school product.

---

## P6-T04: Text Conversation Flow

Owner:      codex
Phase:      6
Type:       assistant
Depends-On: P6-T03

Objective: |
  Implement the bounded conversational flow for Telegram text so the user can query
  the archive naturally without reverting to raw command-only UX.

Acceptance-Criteria:
  - id: AC-1
    description: "Natural-language text questions can trigger bounded archive tools."
  - id: AC-2
    description: "Responses remain grounded in archive-backed evidence."
  - id: AC-3
    description: "When evidence is weak, the assistant returns an insufficient-evidence style response."

Files:
  - app/assistant/
  - app/telegram/
  - docs/TELEGRAM_INTERACTION_MODEL.md
  - docs/TESTING_STRATEGY.md

Context-Refs:
  - docs/spec.md
  - docs/TELEGRAM_INTERACTION_MODEL.md
  - docs/VOICE_PIPELINE.md
  - ~/Documents/dev/ai-stack/projects/film-school-assistant

Notes: |
  Prefer porting the bounded chat/tool loop structure from `film-school-assistant`
  rather than inventing a new assistant runtime shape.

---

## P6-T05: Session Persistence

Owner:      codex
Phase:      6
Type:       persistence
Depends-On: P6-T03

Objective: |
  Persist bot session state durably so active conversational context and pending actions
  survive process restart.

Acceptance-Criteria:
  - id: AC-1
    description: "Session state persists across bot restarts."
  - id: AC-2
    description: "Redis is not the sole source of session truth."
  - id: AC-3
    description: "Session history remains operational state, not archive truth."

Files:
  - alembic/
  - app/models/
  - app/assistant/
  - docs/ARCHITECTURE.md
  - docs/adr/ADR-006-persisted-bot-session-state.md

Context-Refs:
  - docs/ARCHITECTURE.md
  - docs/AUTH_SECURITY.md
  - docs/adr/ADR-006-persisted-bot-session-state.md
  - ~/Documents/dev/ai-stack/projects/film-school-assistant

Notes: |
  The in-memory state approach in `film-school-assistant` is useful as a behavioral
  reference, but not as the final persistence model for Dream Motif Interpreter.

---

## P6-T06: Deployment and Config Wiring

Owner:      codex
Phase:      6
Type:       ops
Depends-On: P6-T03, P6-T05

Objective: |
  Make the Telegram-enabled text stack deployable with a documented process topology,
  environment contract, and startup ordering.

Acceptance-Criteria:
  - id: AC-1
    description: "Deployment docs reflect the actual service topology."
  - id: AC-2
    description: "Telegram runtime configuration is documented and wired."
  - id: AC-3
    description: "Operators can start API, workers, and bot coherently in a private deployment."

Files:
  - docker-compose.yml
  - docs/DEPLOY.md
  - docs/ENVIRONMENT.md
  - docs/RUNBOOK_TELEGRAM_BOT.md

Context-Refs:
  - docs/DEPLOY.md
  - docs/ENVIRONMENT.md
  - docs/adr/ADR-007-compose-first-telegram-deployment.md
  - ~/Documents/dev/ai-stack/projects/film-school-assistant

---

## P6-T07: Phase 6 Test Coverage

Owner:      codex
Phase:      6
Type:       testing
Depends-On: P6-T04, P6-T05

Objective: |
  Add the minimum automated coverage required to trust the Telegram text interface.

Acceptance-Criteria:
  - id: AC-1
    description: "Authorization guard coverage exists for Telegram access."
  - id: AC-2
    description: "Assistant routing coverage exists for text interaction."
  - id: AC-3
    description: "Insufficient-evidence behavior is covered in the Telegram interaction path."

Files:
  - tests/
  - docs/TESTING_STRATEGY.md

Context-Refs:
  - docs/TESTING_STRATEGY.md
  - docs/IMPLEMENTATION_CONTRACT.md
  - ~/Documents/dev/ai-stack/projects/film-school-assistant

---

## 4. Phase 7 — Voice Interaction and Media Pipeline

Goal: extend the Telegram assistant to voice messages via an async transcription path with explicit retention and cleanup behavior.

Phase gate:

- voice note processing works end-to-end
- transcription failures are observable
- media cleanup is implemented and documented

---

## P7-T01: Voice Ingress and Media Persistence

Owner:      codex
Phase:      7
Type:       interface
Depends-On: P6-T03, P6-T05

Objective: |
  Add Telegram voice ingress, media-event persistence, and temporary file handling.

Acceptance-Criteria:
  - id: AC-1
    description: "Voice updates are accepted from the authorized user."
  - id: AC-2
    description: "Media metadata is persisted before transcription starts."
  - id: AC-3
    description: "The bot acknowledges that voice processing is in progress."

Files:
  - app/telegram/
  - app/assistant/
  - docs/VOICE_PIPELINE.md
  - docs/RUNBOOK_VOICE_PIPELINE.md

Context-Refs:
  - docs/VOICE_PIPELINE.md
  - docs/AUTH_SECURITY.md
  - ~/Documents/dev/ai-stack/projects/film-school-assistant

Notes: |
  Use the existing voice-handler sequencing in `film-school-assistant` as the
  starting reference, then adapt it to Dream Motif Interpreter job, retention,
  and provider decisions.

---

## P7-T02: Async Transcription Pipeline

Owner:      codex
Phase:      7
Type:       worker
Depends-On: P7-T01

Objective: |
  Add an async transcription path that converts voice messages into text and routes
  the transcript through the standard assistant flow.

Acceptance-Criteria:
  - id: AC-1
    description: "A transcription job can be queued and processed asynchronously."
  - id: AC-2
    description: "Transcript text is handled by the same assistant path as normal text messages."
  - id: AC-3
    description: "Provider failure results in a recoverable, observable error path."

Files:
  - app/workers/
  - app/telegram/
  - docs/VOICE_PIPELINE.md
  - docs/adr/ADR-005-managed-transcription-first.md

Context-Refs:
  - docs/VOICE_PIPELINE.md
  - docs/adr/ADR-005-managed-transcription-first.md
  - ~/Documents/dev/ai-stack/projects/film-school-assistant

---

## P7-T03: Media Retention and Cleanup

Owner:      codex
Phase:      7
Type:       ops
Depends-On: P7-T02

Objective: |
  Implement retention and cleanup rules for raw voice media and transcription artifacts.

Acceptance-Criteria:
  - id: AC-1
    description: "Raw media retention is bounded and configurable."
  - id: AC-2
    description: "Cleanup logic is documented and operational."
  - id: AC-3
    description: "Voice processing does not leave unbounded file growth."

Files:
  - app/workers/
  - docs/VOICE_PIPELINE.md
  - docs/RUNBOOK_VOICE_PIPELINE.md
  - docs/ENVIRONMENT.md

Context-Refs:
  - docs/VOICE_PIPELINE.md
  - docs/RUNBOOK_VOICE_PIPELINE.md
  - docs/AUTH_SECURITY.md
  - ~/Documents/dev/ai-stack/projects/film-school-assistant

---

## P7-T04: Voice Test Coverage

Owner:      codex
Phase:      7
Type:       testing
Depends-On: P7-T02, P7-T03

Objective: |
  Add automated coverage for the voice-message path and cleanup behavior.

Acceptance-Criteria:
  - id: AC-1
    description: "Voice success path is covered."
  - id: AC-2
    description: "Transcription failure path is covered."
  - id: AC-3
    description: "Cleanup or retention behavior is covered."

Files:
  - tests/
  - docs/TESTING_STRATEGY.md

Context-Refs:
  - docs/TESTING_STRATEGY.md
  - docs/VOICE_PIPELINE.md
  - ~/Documents/dev/ai-stack/projects/film-school-assistant

---

## 5. Phase 8 — Hardening and Controlled Expansion

Goal: harden operations, observability, and optional controlled extension of chat capabilities after text and voice foundations are stable.

---

## P8-T01: Bot and Voice Observability Hardening

Owner:      codex
Phase:      8
Type:       ops
Depends-On: P6-T07, P7-T04

Objective: |
  Extend observability, tracing, and operational diagnostics for the Telegram and
  voice runtimes.

Acceptance-Criteria:
  - id: AC-1
    description: "Bot and voice failure paths are traceable without leaking sensitive content."
  - id: AC-2
    description: "Runbooks match actual operational behavior."
  - id: AC-3
    description: "Operators can diagnose auth, transcription, and session-state failures."

Files:
  - app/shared/
  - docs/RUNBOOK_TELEGRAM_BOT.md
  - docs/RUNBOOK_VOICE_PIPELINE.md
  - docs/AUTH_SECURITY.md

Context-Refs:
  - docs/AUTH_SECURITY.md
  - docs/RUNBOOK_TELEGRAM_BOT.md
  - docs/RUNBOOK_VOICE_PIPELINE.md

---

## P8-T02: Controlled Evaluation of Chat Curation

Owner:      codex
Phase:      8
Type:       product
Depends-On: P8-T01

Objective: |
  Decide whether any curation actions should be exposed in Telegram and, if so,
  do so only through an explicit, audit-safe UX.

Acceptance-Criteria:
  - id: AC-1
    description: "A clear allow/deny decision exists for chat-driven curation actions."
  - id: AC-2
    description: "If enabled, curation UX is explicit and auditable."
  - id: AC-3
    description: "If deferred, documentation remains explicit that chat is read-oriented."

Files:
  - docs/spec.md
  - docs/PHASE_PLAN.md
  - docs/TELEGRAM_INTERACTION_MODEL.md
  - docs/AUTH_SECURITY.md

Context-Refs:
  - docs/spec.md
  - docs/AUTH_SECURITY.md
  - docs/IMPLEMENTATION_CONTRACT.md

## 6. Continuity Notes

- `docs/tasks.md` remains the historical task graph for the backend build-out through Phase 5
- `docs/tasks_phase6.md` is the active task graph for Telegram, voice, and Phase 6+ work
- when these files diverge, use this file for current implementation work unless the task explicitly targets historical backend follow-up

## 7. Phase 9 Task Graph

Phase 9 (Motif Abstraction and Induction) workstreams are tracked in:

- [docs/tasks_phase9.md](tasks_phase9.md)
