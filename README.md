# Dream Motif Interpreter

Dream Motif Interpreter is a private, single-user dream-analysis system.

It ingests dream entries from Google Docs, stores and curates dream themes, supports semantic and thematic retrieval, surfaces archive-level motif patterns, and provides a Telegram assistant interface for text and voice interaction.

**Current status: Phases 1–8 complete**

---

## What Exists Today

### Core Backend (Phases 1–5)

- FastAPI API for sync, dream browsing, search, theme curation, pattern analysis, and rollback
- PostgreSQL 16 + pgvector as the system of record
- Redis-backed job state and worker coordination
- Google Docs ingestion
- LLM-assisted theme extraction, grounding, and metaphor-aware retrieval
- append-only annotation versioning for curation and rollback
- explicit framing that interpretations are computational, not authoritative

### Telegram Interface (Phases 6–7)

- Private Telegram bot with single-user `chat_id` allowlist
- Text conversation with bounded archive tool loop (Claude via Anthropic API)
- Voice message ingestion and async transcription (OpenAI Whisper)
- Persistent chat sessions across restarts (`bot_sessions` table)
- `VoiceMediaEvent` lifecycle tracking with immediate and scheduled cleanup

### Operational Hardening (Phase 8)

- Structured logging with event IDs and status codes throughout (no raw content in logs)
- Runbooks for bot and voice pipeline operations
- All open security decisions resolved (transcript retention, media lifecycle, auth model)
- Chat-driven archive mutations explicitly deferred pending audit-safe UX design

---

## Repository Map

```text
app/
  api/           FastAPI routes (sync, dreams, search, themes, patterns, versioning)
  assistant/     bounded assistant facade, chat loop, session persistence, voice media
  llm/           model wrappers and prompts
  models/        SQLAlchemy models (dreams, themes, sessions, voice events)
  retrieval/     chunking, embedding, pgvector ingestion and query pipeline
  services/      domain services (analysis, patterns, segmentation, taxonomy, versioning)
  shared/        config, tracing, DB session factory
  telegram/      bot runtime, handlers, voice download
  workers/       background jobs (ingest, indexing, transcription, cleanup)

alembic/         schema migrations (001–008)
docs/            architecture, planning, runbooks, ADRs
tests/           unit and integration coverage (97 tests)
```

---

## Setup

**Requirements:**

- Python 3.11+
- PostgreSQL 16 with `pgvector`
- Redis

**Credentials required:**

- `ANTHROPIC_API_KEY` — bounded chat loop
- `OPENAI_API_KEY` — voice transcription (Whisper) and embeddings
- `TELEGRAM_BOT_TOKEN` + `TELEGRAM_ALLOWED_CHAT_ID` — bot runtime
- Google Docs credentials — archive ingestion

See [Environment](docs/ENVIRONMENT.md) and [Deployment](docs/DEPLOY.md) for full setup details.

**Run migrations before starting the bot:**

```bash
alembic upgrade head
python3 -m app.telegram
```

**Via Docker Compose:**

```bash
docker compose up
```

---

## Documentation

| Document | Purpose |
|----------|---------|
| [Architecture](docs/ARCHITECTURE.md) | System shape, execution boundary, capability profiles |
| [Feature Spec](docs/spec.md) | Backend and interface scope |
| [Phase Plan](docs/PHASE_PLAN.md) | Phase 1–8 decomposition and completion status |
| [Phase 6+ Task Graph](docs/tasks_phase6.md) | Execution graph for Telegram, voice, and hardening |
| [Environment](docs/ENVIRONMENT.md) | Runtime variables and credential notes |
| [Deployment](docs/DEPLOY.md) | Deployment topology and startup ordering |
| [Telegram Interaction Model](docs/TELEGRAM_INTERACTION_MODEL.md) | Bot behavior, tool catalog, and curation policy |
| [Voice Pipeline](docs/VOICE_PIPELINE.md) | Voice ingestion and transcription design |
| [Auth and Security](docs/AUTH_SECURITY.md) | Access model, media retention, and security constraints |
| [Testing Strategy](docs/TESTING_STRATEGY.md) | Test coverage expectations |
| [Decision Log](docs/DECISION_LOG.md) | Compact index of architectural decisions |
| [ADRs](docs/adr/README.md) | Durable architectural decision records |
| [Telegram Bot Runbook](docs/RUNBOOK_TELEGRAM_BOT.md) | Bot operations and failure diagnostics |
| [Voice Pipeline Runbook](docs/RUNBOOK_VOICE_PIPELINE.md) | Voice operations and failure diagnostics |
