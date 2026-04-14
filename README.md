# Dream Motif Interpreter

Dream Motif Interpreter is a single-user dream-analysis system for a private dream journal.
Today it is a backend-first product: it ingests dream entries from Google Docs, stores and curates dream themes, supports semantic retrieval, and surfaces archive-level motif patterns.

The next project phase extends that core through a Telegram assistant interface for text and voice interaction.
Telegram is an interaction surface, not the product identity.

**Current repo status:** Phases 1-5 complete for the backend platform  
**Next planned evolution:** Phase 6+ Telegram interaction, then voice, then operational hardening

## What Exists Today

- FastAPI API for sync, dream browsing, search, theme curation, pattern analysis, and rollback
- PostgreSQL 16 + pgvector as the system of record
- Redis-backed job state and worker coordination
- Google Docs ingestion
- LLM-assisted theme extraction, grounding, and metaphor-aware retrieval
- append-only annotation versioning for curation and rollback
- explicit framing that interpretations are computational, not authoritative

Primary references:
- [Architecture](docs/ARCHITECTURE.md)
- [Feature Spec](docs/spec.md)
- [Phase Plan](docs/PHASE_PLAN.md)
- [Phase 6+ Task Graph](docs/tasks_phase6.md)
- [Environment](docs/ENVIRONMENT.md)
- [Deployment](docs/DEPLOY.md)

## Planned Phase 6+

The planned next phase introduces:

- Telegram bot as a new interaction surface
- text conversation with a bounded assistant layer
- voice-message ingestion and transcription
- internal assistant tools that safely invoke Dream Motif Interpreter capabilities
- private single-user bot access via Telegram allowlist

This is a product extension, not a repository merge with another bot project.
Dream Motif Interpreter remains the core product and source of truth.

Implementation reference for the interaction layer:

- `~/Documents/dev/ai-stack/projects/film-school-assistant`

That repository should be treated as the working reference for:

- Telegram bot runtime shape
- bounded chat/tool loop patterns
- voice-message ingress and processing flow
- private single-user bot operations

It should not be treated as a schema or product-logic source of truth for Dream Motif Interpreter.

## Architecture Direction

Recommended target shape:

- keep the current Dream Motif Interpreter backend as the canonical archive system
- add a Telegram adapter inside the same repository as a separate runtime/process
- route Telegram assistant behavior through a bounded internal service facade
- persist bot session state separately from the dream archive
- start with read-oriented conversational tools and explicit sync triggering
- defer risky curation mutations in chat until the text and voice interaction model is proven

See:
- [Telegram Interaction Model](docs/TELEGRAM_INTERACTION_MODEL.md)
- [Voice Pipeline](docs/VOICE_PIPELINE.md)
- [Auth and Security](docs/AUTH_SECURITY.md)
- [Phase 6+ Task Graph](docs/tasks_phase6.md)
- [Implementation Reference Map](docs/IMPLEMENTATION_REFERENCE_MAP.md)

## Current vs Target State

| Area | Current | Planned |
|------|---------|---------|
| Primary interface | HTTP API | HTTP API + Telegram |
| Voice | none | Telegram voice messages |
| Session state | none | persisted assistant sessions |
| Core storage | PostgreSQL + pgvector | unchanged |
| Background work | sync and indexing workers | sync/indexing + transcription/media jobs |
| Auth | single-user API key | API key + Telegram allowlist |
| Deployment | API + workers + Postgres + Redis | API + workers + bot + Postgres + Redis |

## Repository Map

```text
app/
  api/           FastAPI routes
  llm/           model wrappers and prompts
  models/        SQLAlchemy models
  retrieval/     ingestion and query pipeline
  services/      domain services
  shared/        config, tracing, DB factory
  workers/       background jobs
alembic/         schema migrations
docs/            architecture, planning, ops, ADRs
tests/           unit and integration coverage
```

Planned Phase 6+ additions are documented as target modules, not shipped code:

```text
app/
  assistant/     bounded assistant tool facade and session logic
  telegram/      bot runtime, handlers, presenters, voice ingress
  workers/       transcription/media cleanup jobs
```

## Setup Summary

Current backend setup requires:

- Python 3.11+
- PostgreSQL 16 with `pgvector`
- Redis
- Anthropic and OpenAI credentials
- Google Docs credentials matching the current implementation path

Detailed setup:
- [Environment](docs/ENVIRONMENT.md)
- [Deployment](docs/DEPLOY.md)

## Google Docs Credentials Note

The current implementation expects OAuth-style Google Docs credentials via environment variables.
If you already have a service-account JSON file with the document shared to that account, keep it available during implementation planning, but treat service-account auth as a deliberate implementation decision rather than something already wired into the current code.

That boundary is documented in:
- [Environment](docs/ENVIRONMENT.md)
- [Open Decisions in the Phase Plan](docs/PHASE_PLAN.md)

## Documentation Map

- [Architecture](docs/ARCHITECTURE.md): current system shape and target Telegram-enabled architecture
- [Feature Spec](docs/spec.md): current backend scope plus planned interface evolution
- [Phase Plan](docs/PHASE_PLAN.md): Phase 6, 7, 8 decomposition and milestones
- [Phase 6+ Task Graph](docs/tasks_phase6.md): active execution graph for Telegram, voice, and hardening work
- [Implementation Reference Map](docs/IMPLEMENTATION_REFERENCE_MAP.md): file-to-file guidance for reusing `film-school-assistant` interaction-layer patterns
- [Environment](docs/ENVIRONMENT.md): runtime variables and credential notes
- [Deployment](docs/DEPLOY.md): recommended deployment topology
- [Telegram Interaction Model](docs/TELEGRAM_INTERACTION_MODEL.md): assistant behavior and bot boundary
- [Voice Pipeline](docs/VOICE_PIPELINE.md): voice ingestion and transcription flow
- [Auth and Security](docs/AUTH_SECURITY.md): access model and operational security constraints
- [Testing Strategy](docs/TESTING_STRATEGY.md): test coverage expectations for Phase 6+
- [Decision Log](docs/DECISION_LOG.md): compact decision index
- [ADRs](docs/adr/README.md): durable architectural decisions
- [Telegram Bot Runbook](docs/RUNBOOK_TELEGRAM_BOT.md)
- [Voice Pipeline Runbook](docs/RUNBOOK_VOICE_PIPELINE.md)
