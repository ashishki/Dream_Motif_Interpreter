# Architecture — Dream Motif Interpreter

Version: 2.0  
Last updated: 2026-04-14  
Status: Active for current backend; target-state guidance for Phase 6+

## 1. System Definition

Dream Motif Interpreter is a private, single-user dream-analysis system.

Its current implemented center of gravity is a backend platform:

- ingestion from Google Docs
- structured dream archive storage
- LLM-assisted theme extraction and grounding
- semantic and thematic retrieval
- archive-level pattern analysis
- versioned theme curation and rollback

The next planned evolution adds a Telegram assistant interface for text and voice interaction.
That addition does not change the product’s source of truth:
the dream archive, retrieval layer, and curation rules remain owned by Dream Motif Interpreter.

## 2. Product Category

### Current

Single-user dream-analysis backend for a private dream journal

### Planned

Single-user dream-analysis system with a Telegram conversational interface

The planned Telegram layer is an interface extension, not a reclassification into “bot script”.

## 3. Observed Current Architecture

The current repository implements:

- FastAPI application entry point in [app/main.py](/home/ashishki/Documents/dev/ai-stack/projects/Dream_Motif_Interpreter/app/main.py)
- HTTP routers for sync, dreams, search, themes, patterns, and versioning
- PostgreSQL models for dreams, chunks, themes, categories, and annotation versions
- retrieval ingestion and query modules over pgvector
- background worker functions for sync and indexing
- shared config, tracing, and DB session factory

Current runtime dependencies:

- PostgreSQL 16 + `pgvector`
- Redis
- Google Docs API
- Anthropic API
- OpenAI embeddings API

Current storage ownership:

- PostgreSQL is the canonical system of record
- Redis stores job state and approval-token state

## 4. Important Current-State Caveat

The repository documentation from Phases 1-5 describes a complete ingest -> analyse -> index path.
The codebase clearly contains the required service pieces, but the currently visible worker wiring does not yet show the full orchestration path in one place.

Observed examples:

- `AnalysisService` exists in [app/services/analysis.py](/home/ashishki/Documents/dev/ai-stack/projects/Dream_Motif_Interpreter/app/services/analysis.py)
- indexing exists in [app/retrieval/ingestion.py](/home/ashishki/Documents/dev/ai-stack/projects/Dream_Motif_Interpreter/app/retrieval/ingestion.py)
- the sync worker in [app/workers/ingest.py](/home/ashishki/Documents/dev/ai-stack/projects/Dream_Motif_Interpreter/app/workers/ingest.py) visibly stores entries, but does not visibly call analysis or indexing

This mismatch should be resolved before Phase 6 implementation begins.

## 5. Core Architectural Principles

- Dream Motif Interpreter remains the core product and source of truth.
- The dream archive is not owned by the interface layer.
- Deterministic code owns persistence, approval gates, rollback, search execution, and policy enforcement.
- LLMs are used only for bounded interpretation tasks.
- Any assistant interface must use explicit internal tools or service boundaries.
- Conversational convenience must not bypass curation and audit guarantees.

## 6. Current Capability Profiles

| Profile | Status | Notes |
|---------|--------|-------|
| RAG | ON | Hybrid retrieval over dream archive is core product behavior |
| Tool-Use | OFF in current backend | no assistant tool loop in the shipped backend |
| Agentic | OFF | current system uses bounded workflows, not an autonomous loop |
| Planning | OFF | no plan artifact governs execution |
| Compliance | OFF | privacy-sensitive, but no named regulated framework |

## 7. Current Runtime Tier

`T1`

Why:

- bounded application processes
- persistent DB and queue
- no shell mutation at runtime
- no privileged autonomous execution

Phase 6+ does not change the runtime tier.
Adding a Telegram bot process still fits `T1`.

## 8. Recommended Phase 6+ Target Architecture

### 8.1 Recommended Shape

Introduce a Telegram adapter inside the same repository as a separate internal application module and runtime process.

Recommended process topology:

- API process
- worker process
- Telegram bot process
- PostgreSQL
- Redis

Optional later support:

- scheduled sync process
- media cleanup process

### 8.2 Why This Shape Is Recommended

- keeps domain logic close to the existing codebase
- avoids a second repository drifting from the core product
- avoids loopback HTTP where a direct internal service call is simpler and safer
- preserves the option to add another interface later without rebuilding the core
- matches the current single-user private-deployment model

### 8.3 Implementation Reference Rule

The Telegram-first repository at:

- `~/Documents/dev/ai-stack/projects/film-school-assistant`

is the implementation reference for the interaction layer.

That means Phase 6+ work should prefer:

- porting proven bot-runtime patterns
- porting handler decomposition patterns
- porting bounded tool-loop structure
- porting voice-ingress sequencing
- porting private bot operations patterns

over generating an all-new Telegram layer from scratch.

This is a reference for interface and operations patterns only.
It is not the source of truth for:

- Dream Motif Interpreter domain models
- dream archive storage
- retrieval logic
- curation rules
- taxonomy semantics

### 8.4 Rejected Alternatives

Separate external Telegram service calling the public API only:

- cleaner isolation in theory
- worse operational duplication
- higher drift risk
- weaker reuse of internal business rules

Telegram handlers embedded directly into the FastAPI process:

- weaker fault isolation
- conflates HTTP and bot lifecycles
- makes voice/media processing harder to reason about

## 9. Target Components

| Component | Responsibility | Status |
|-----------|----------------|--------|
| `app/api/` | public HTTP API for archive access and curation | current |
| `app/services/` | domain services and business rules | current |
| `app/retrieval/` | chunking, embeddings, retrieval | current |
| `app/workers/` | sync and indexing workers | current |
| `app/assistant/` | bounded internal assistant tool facade and session policy | planned |
| `app/telegram/` | Telegram runtime, routing, presenters, voice ingress | planned |
| `app/workers/transcription*` | async voice transcription jobs | planned |

## 10. Assistant Boundary

Phase 6+ should not expose raw ORM access or unrestricted domain operations to a conversational loop.

The assistant layer should call a bounded service facade such as:

- `search_dreams`
- `get_dream`
- `list_recent_dreams`
- `get_patterns`
- `get_theme_history`
- `trigger_sync`

Deferred or tightly gated tools:

- confirm theme
- reject theme
- rollback theme
- approve category

Initial recommendation:

- Phase 6 bot tools are read-oriented plus explicit sync triggering
- mutation tools are deferred until the conversational UX and audit surface are proven

## 11. Telegram Interface Layer

Telegram is the planned primary interaction surface for the next phase because:

- it fits the private single-user model
- text and voice are the highest-leverage interaction paths
- it avoids inventing a web layer before the conversational flow is validated

The bot layer should provide:

- text conversation
- voice-message handling
- bounded assistant routing
- acknowledgements for long-running tasks
- clear “insufficient evidence” behavior

Implementation guidance:

- use `film-school-assistant` as the primary reference for bot runtime structure and flow control
- replace its domain-specific storage and prompts with Dream Motif Interpreter assistant services and policies

See [Telegram Interaction Model](TELEGRAM_INTERACTION_MODEL.md).

## 12. Voice Processing Strategy

Recommended Phase 7 direction:

- Telegram voice message arrives
- bot validates sender
- media event is persisted
- file is downloaded to temporary storage
- transcription job is queued
- transcript flows through the same text assistant path
- raw media is deleted on a short retention schedule

Recommended initial posture:

- managed transcription API first
- local Whisper as a later optimization or privacy-driven alternative

See [Voice Pipeline](VOICE_PIPELINE.md).

## 13. Session and State Model

Current backend:

- no conversational state

Planned bot layer:

- one conversation/session stream per allowed Telegram chat
- persisted session metadata and pending actions in PostgreSQL
- Redis for locks, deduplication, and short-lived job state only

Important rule:

- bot session history is interaction state, not dream-archive truth

## 14. Auth and Authorization

Current backend auth:

- single-user API key header

Planned Telegram auth:

- allowlisted Telegram `chat_id`
- preferably allowlisted Telegram `user_id` as well

Authorization policy recommendation:

- read/query operations broadly available to the allowed user
- archive mutations remain explicitly gated and initially deferred from natural chat

See [Auth and Security](AUTH_SECURITY.md).

## 15. Deployment Model

Recommended canonical deployment documentation:

- Compose-first for the multi-process stack
- systemd as an optional private-VPS operating mode

Reason:

- Compose expresses the full service topology clearly
- DMI is already naturally a multi-service private system

See [Deployment](DEPLOY.md).

## 16. Testing Implications

Phase 6+ expands testing scope to include:

- Telegram auth guard behavior
- tool-routing correctness
- insufficient-evidence conversational handling
- session persistence across restart
- voice pipeline success and failure paths

See [Testing Strategy](TESTING_STRATEGY.md).

## 17. Documentation and Governance Implications

Phase 6+ requires:

- new product framing documents
- new deployment and env docs
- Telegram and voice operational docs
- ADR coverage for the major new boundaries
- an active execution graph for Phase 6+ implementation work: [docs/tasks_phase6.md](tasks_phase6.md)

Required architecture-affecting ADR topics:

- Telegram adapter placement
- bounded assistant tool facade
- transcription strategy
- session persistence
- deployment topology

## 18. Open Architectural Decisions

- whether Phase 6 remains read-only plus sync trigger
- whether transcription starts managed or local
- final retention periods for media and transcripts
- whether polling or webhook is the canonical Telegram ingress mode
- whether Google Docs auth remains OAuth env vars or later adopts service-account JSON
