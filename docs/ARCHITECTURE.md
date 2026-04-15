# Architecture — Dream Motif Interpreter

Version: 3.0
Last updated: 2026-04-15 (Phase 8 complete — all target state implemented)
Status: Active — reflects implemented system through Phase 8

## 1. System Definition

Dream Motif Interpreter is a private, single-user dream-analysis system.

The implemented system is:

- ingestion from Google Docs
- structured dream archive storage
- LLM-assisted theme extraction and grounding
- semantic and thematic retrieval
- archive-level pattern analysis
- versioned theme curation and rollback
- Telegram assistant interface for text and voice interaction

The Telegram layer does not change the product’s source of truth:
the dream archive, retrieval layer, and curation rules remain owned by Dream Motif Interpreter.

## 2. Product Category

Single-user dream-analysis system with a Telegram conversational interface for text and voice.

The Telegram layer is an interface extension, not a reclassification into “bot script”.
The backend remains the core product and source of truth.

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

## 4. Current Backend Execution Boundary

The active runtime wiring is now explicit:

1. `POST /sync` in `app/api/dreams.py` enqueues `app.workers.ingest.ingest_document`.
2. `ingest_document()` fetches Google Docs paragraphs and calls `_store_entries()`.
3. `_store_entries()` segments the document, upserts `DreamEntry` rows by `content_hash`, and returns the resolved `dream_id` values for both newly inserted and already-known entries.
4. `_collect_pipeline_targets()` inspects downstream state for those `dream_id` values:
   - if a dream has no `DreamTheme` rows, it is queued for analysis
   - if a dream has no `DreamChunk` rows, it is queued for indexing
5. `_run_post_store_pipeline()` runs the missing downstream stages in order:
   - `AnalysisService.analyse_dream_with_session_factory()` for dreams missing analysis
   - `app.workers.index.index_dream()` for dreams missing indexed chunks
6. `index_dream()` delegates to `RagIngestionService.index_dream()`, which chunks the dream text, embeds it, and upserts `DreamChunk` rows on `(dream_id, chunk_index)`.

Resulting runtime contract:

- Newly synced dreams are analysed and indexed automatically.
- Re-syncing the same dream does not create duplicate `DreamEntry` or `DreamChunk` rows because storage uses `content_hash` and `(dream_id, chunk_index)` idempotency keys.
- Re-syncing a dream that already has both themes and chunks skips those downstream stages.
- Re-syncing a dream that is present but missing themes or chunks repairs the missing stage on the next sync run.

This is the boundary Phase 6 should rely on.

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
| Tool-Use | ON (bounded) | Telegram assistant uses a bounded tool-use loop (MAX_TOOL_ROUNDS=5); no autonomous tool use |
| Agentic | OFF | system uses bounded workflows, not an autonomous loop |
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
| `app/api/` | public HTTP API for archive access and curation | implemented |
| `app/services/` | domain services and business rules | implemented |
| `app/retrieval/` | chunking, embeddings, retrieval | implemented |
| `app/workers/` | sync, indexing, transcription, and cleanup workers | implemented |
| `app/assistant/` | bounded assistant facade, chat loop, session persistence, voice media helpers | implemented (Phase 6–7) |
| `app/telegram/` | bot runtime, auth guard, text/voice handlers, file download | implemented (Phase 6–7) |

## 10. Assistant Boundary

Phase 6+ should not expose raw ORM access or unrestricted domain operations to a conversational loop.

The assistant layer should call a bounded service facade such as:

- `search_dreams`
- `get_dream`
- `list_recent_dreams`
- `get_patterns`
- `get_theme_history`
- `trigger_sync`

Phase 6 now introduces `app/assistant/facade.py::AssistantFacade` as that backend boundary.
It wraps internal services and read queries directly, returns DTO-style values rather than ORM objects, and keeps session ownership inside the facade.

Deferred or tightly gated tools:

- confirm theme
- reject theme
- rollback theme
- approve category

Initial recommendation:

- Phase 6 bot tools are read-oriented plus explicit sync triggering
- mutation tools are deferred until the conversational UX and audit surface are proven

## 11. Telegram Interface Layer (Implemented — Phase 6–7)

Telegram is the primary interaction surface for the single user.

The implemented bot layer provides:

- text conversation via bounded tool-use loop (`app/assistant/chat.py`)
- voice-message handling via async transcription task (`app/workers/transcribe.py`)
- `chat_id` allowlist authorization guard (`app/telegram/handlers.py`)
- acknowledgements for in-progress transcription tasks
- “insufficient evidence” behavior preserved in chat

Runtime: `python3 -m app.telegram` (long polling, separate process from the API).

See [Telegram Interaction Model](TELEGRAM_INTERACTION_MODEL.md) and [Telegram Bot Runbook](RUNBOOK_TELEGRAM_BOT.md).

## 12. Voice Processing (Implemented — Phase 7)

Implemented flow:

1. Telegram voice update arrives.
2. Bot validates sender via `chat_id` allowlist.
3. `VoiceMediaEvent` is persisted with `received` status.
4. Voice file is downloaded to `VOICE_MEDIA_DIR`.
5. Bot acknowledges “Processing your voice note...”
6. `asyncio.create_task(transcribe_and_reply(...))` enqueues background transcription.
7. Worker calls OpenAI Whisper API (`whisper-1`, via `asyncio.to_thread`).
8. Transcript routes through `handle_chat()` — same path as text messages.
9. Bot sends reply via standalone `Bot(token=...)`.
10. Raw audio is deleted immediately after successful reply; sweep cleanup handles survivors.

Provider: **OpenAI Whisper API** (managed). Local Whisper deferred.

See [Voice Pipeline](VOICE_PIPELINE.md) and [Voice Pipeline Runbook](RUNBOOK_VOICE_PIPELINE.md).

See [Voice Pipeline](VOICE_PIPELINE.md).

## 13. Session and State Model

Backend:

- no conversational state

Telegram bot layer (implemented — Phase 6):

- one conversation/session stream per allowed Telegram chat
- session history persisted in `bot_sessions` table (PostgreSQL)
- trimmed to `MAX_HISTORY_MESSAGES=20` on each save
- Redis for locks, deduplication, and short-lived job state only

Rule: bot session history is interaction state, not dream-archive truth.

## 14. Auth and Authorization

Backend auth:

- single-user API key header

Telegram auth (implemented — Phase 6):

- allowlisted Telegram `chat_id` via `TELEGRAM_ALLOWED_CHAT_ID`
- user_id allowlisting deferred to a future phase

Authorization policy:

- read/query operations broadly available to the allowed user
- archive mutations remain explicitly gated and deferred from natural chat (see [Telegram Interaction Model](TELEGRAM_INTERACTION_MODEL.md) §11)

See [Auth and Security](AUTH_SECURITY.md).

## 15. Deployment Model

Recommended canonical deployment documentation:

- Compose-first for the multi-process stack
- systemd as an optional private-VPS operating mode

Reason:

- Compose expresses the full service topology clearly
- DMI is already naturally a multi-service private system

See [Deployment](DEPLOY.md).

## 16. Testing

Current coverage (Phase 8 baseline): **97 unit tests passing**.

Covered areas:

- Telegram auth guard behavior
- tool-routing correctness and bounded loop guard
- insufficient-evidence conversational handling
- session load/save and history trimming
- voice pipeline success and failure paths
- cleanup worker (immediate deletion + sweep)
- transcription worker status progression

See [Testing Strategy](TESTING_STRATEGY.md).

## 17. ADR Coverage

Architecture-affecting decisions are documented in `docs/adr/`:

- ADR-001: append-only annotation versioning
- ADR-002: single-user API key auth
- ADR-003: Telegram adapter inside the same repository
- ADR-004: bounded assistant tool facade
- ADR-005: managed transcription first (OpenAI Whisper)
- ADR-006: persisted bot session state
- ADR-007: Compose-first Telegram deployment

## 18. Resolved Architectural Decisions

All Phase 6–8 decisions are resolved:

| Decision | Outcome |
|----------|---------|
| Phase 6 write scope | Read-only plus `trigger_sync`; mutations deferred |
| Transcription provider | OpenAI Whisper API (managed) |
| Media retention | Immediate deletion after transcription; sweep via `VOICE_RETENTION_SECONDS` |
| Telegram ingress mode | Long polling (no public webhook required) |
| Session persistence | PostgreSQL `bot_sessions` table |
| Deployment topology | Docker Compose with `telegram-bot` service |
| Google Docs auth | OAuth env vars (current code path); service-account JSON deferred |
