# Dream Motif Interpreter

An AI-assisted analysis backend for a personal dream journal. Ingests long-form dream entries from Google Docs, extracts and curates recurring themes, supports semantic search, and surfaces archive-level patterns — all with a human approval layer over every taxonomy change.

**Status:** All 5 phases complete · 98 tests passing · 0 open findings

---

## What it does

You keep a dream journal in Google Docs. This system reads it, understands it, and builds a structured, searchable archive you can query and analyse.

### Ingestion pipeline

1. **Fetch** — pulls the source document from Google Docs via OAuth2 refresh token
2. **Segment** — splits the raw text into individual dream entries by date headers and delimiters
3. **Extract themes** — calls `claude-sonnet-4-6` to assign multi-label thematic categories (e.g. "descent", "pursuit", "transformation") ranked by salience
4. **Ground themes** — links each theme to the exact text fragment that supports it, with a confidence score
5. **Embed & index** — chunks each entry with tiktoken (512-token chunks, cl100k_base), embeds with `text-embedding-3-small`, and stores vectors in PostgreSQL via `pgvector` with an HNSW index for fast retrieval

All theme assignments start as **draft** and require human confirmation before becoming part of the archive.

### Semantic search

- `GET /search?q=...` — hybrid retrieval: vector similarity + keyword matching + LLM query expansion (via `claude-haiku-4-5`) for metaphor-aware results
- Returns ranked evidence blocks with the matching text fragment, salience score, match type, and character offset
- Every response includes an interpretation note framing results as computational, not authoritative
- Falls back gracefully to "insufficient evidence" rather than returning low-confidence results

### Theme curation

- Confirm or reject individual theme assignments via `PATCH /dreams/{id}/themes/{theme_id}/confirm`
- Bulk-confirm multiple dreams via a two-step token flow with a configurable TTL
- Approve new theme categories — requires explicit human action; no automated path can promote a category

### Annotation versioning and rollback

Every mutation (confirm, reject, approve) writes an append-only `AnnotationVersion` snapshot before changing the record. You can inspect the full change history and roll back any theme to any prior state. No version record is ever deleted or modified — enforced by a static code scan in the test suite.

### Archive-level pattern detection

- `GET /patterns/recurring` — theme categories sorted by appearance count across all confirmed dreams, with percentage of dreams
- `GET /patterns/co-occurrence` — pairs of themes that appear together in at least two dreams, sorted by frequency
- `GET /patterns/timeline?theme_id=...` — salience over time for a specific theme, sorted by date

All pattern responses include: `"interpretation_note": "These are computational patterns, not authoritative interpretations."` and a `generated_at` ISO8601 timestamp.

### Background workers (ARQ / Redis)

- `ingest_document` — fetches a Google Doc, segments it, runs LLM analysis, stores dream entries; idempotent via `content_hash` (`ON CONFLICT DO NOTHING`)
- `index_dream` — embeds and indexes a dream entry into pgvector; safe to re-run

Job status is tracked in Redis (`queued → running → done / failed`). Workers fall back to an in-memory store in test environments (`ENV=test`).

### Health and observability

- `GET /health` — returns `index_last_updated` timestamp; returns HTTP 503 if the index is stale (> `MAX_INDEX_AGE_HOURS` hours, default 24)
- All external calls (DB, Redis, OpenAI, Anthropic, Google Docs) wrapped in named OpenTelemetry child spans
- Structured JSON logs via `structlog`; PII (raw dream text, chunk text, justification) stripped before emission
- Trace ID and span ID injected into every log line

---

## API surface

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/health` | Index freshness check | Public |
| POST | `/sync` | Trigger document ingestion | Required |
| GET | `/sync/{job_id}` | Poll sync job status | Required |
| GET | `/dreams` | Paginated list of dream entries | Required |
| GET | `/dreams/{id}` | Single dream with metadata | Required |
| GET | `/dreams/{id}/themes` | Themes assigned to a dream | Required |
| GET | `/dreams/{id}/themes/history` | Full annotation version history | Required |
| POST | `/dreams/{id}/themes/{theme_id}/rollback/{version_id}` | Restore theme to prior snapshot | Required |
| GET | `/search` | Semantic + keyword search | Required |
| PATCH | `/dreams/{id}/themes/{theme_id}/confirm` | Confirm a draft theme | Required |
| PATCH | `/dreams/{id}/themes/{theme_id}/reject` | Reject a draft theme | Required |
| POST | `/curate/bulk-confirm` | Issue bulk-confirm approval token | Required |
| POST | `/curate/bulk-confirm/{token}/approve` | Execute bulk confirmation | Required |
| PATCH | `/themes/categories/{id}/approve` | Promote pending category to active | Required |
| GET | `/patterns/recurring` | Most frequent themes in the archive | Required |
| GET | `/patterns/co-occurrence` | Co-occurring theme pairs (count ≥ 2) | Required |
| GET | `/patterns/timeline` | Theme salience over time | Required |

Authentication: `X-API-Key: <SECRET_KEY>` header on all non-public endpoints.

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Web framework | FastAPI (async) |
| Database | PostgreSQL 16 + pgvector extension (HNSW index) |
| ORM / migrations | SQLAlchemy 2 (async) + Alembic |
| Task queue | ARQ (Redis-backed async workers) |
| Cache / job state | Redis |
| LLM — analysis | Anthropic `claude-sonnet-4-6` |
| LLM — query expansion | Anthropic `claude-haiku-4-5-20251001` |
| Embeddings | OpenAI `text-embedding-3-small` (1536 dimensions) |
| Tokenisation | tiktoken `cl100k_base`, 512-token chunks |
| Tracing | OpenTelemetry SDK |
| Logging | structlog (JSON output) |
| Document source | Google Docs API (OAuth2 refresh token) |
| Test runner | pytest + pytest-asyncio |
| Linter / formatter | Ruff |
| CI | GitHub Actions (pgvector/pgvector:pg16 service) |

---

## Project structure

```
app/
  api/           # FastAPI routers
    health.py        # GET /health
    dreams.py        # sync, dream list, job status
    search.py        # GET /search, GET /dreams/{id}/themes
    themes.py        # confirm, reject, bulk-confirm, approve
    patterns.py      # recurring, co-occurrence, timeline
    versioning.py    # history, rollback
  models/        # SQLAlchemy ORM models
    dream.py         # DreamEntry, DreamChunk
    theme.py         # DreamTheme, ThemeCategory
    annotation.py    # AnnotationVersion
  services/      # Business logic
    analysis.py      # theme extraction + grounding pipeline
    segmentation.py  # dream entry boundary detection
    taxonomy.py      # category approval, deprecation
    patterns.py      # recurring pattern queries
    versioning.py    # history retrieval, rollback
    gdocs_client.py  # Google Docs API wrapper
  retrieval/     # RAG pipeline
    ingestion.py     # chunking, embedding, pgvector upsert
    query.py         # hybrid retrieval + query expansion
    types.py         # shared OpenAI embedding client
  workers/       # ARQ background workers
    ingest.py        # ingest_document — fetch, segment, analyse, store
    index.py         # index_dream — embed + index
  llm/           # LLM wrappers
    theme_extractor.py   # multi-label theme extraction
    grounder.py          # fragment grounding
  shared/        # Cross-cutting concerns
    config.py        # pydantic-settings env config
    tracing.py       # OTel provider, structlog JSON, PII redaction
    database.py      # shared async session factory
alembic/
  versions/      # 001 initial schema → 006 HNSW index
docs/
  ARCHITECTURE.md             # Full architectural decisions
  IMPLEMENTATION_CONTRACT.md  # Invariants every change must uphold
  DECISION_LOG.md             # Durable design decisions (D-001 … D-010)
  adr/                        # Architectural Decision Records
  audit/                      # 8 review cycle reports across 5 phases
  retrieval_eval.md           # Retrieval evaluation dataset and baseline metrics
tests/
  unit/          # Pure unit tests (no DB, no network)
  integration/   # Full integration tests against real PostgreSQL + pgvector
  fixtures/      # Seed data for e2e tests
scripts/
  eval.py        # Retrieval evaluation script — accepts --task-id
```

---

## Retrieval quality

Evaluated against a synthetic 20-entry corpus with 10 queries (simple, multi-doc, multi-hop, no-answer):

| Metric | Score | Baseline |
|--------|-------|---------|
| hit@3 | 1.00 | T12 |
| MRR | 1.00 | T12 |
| No-answer accuracy | 1.00 | T12 |

No regression across T12 → T15. Query expansion (LLM) active; falls back to original query on API failure.

---

## Setup

### Prerequisites

- Python 3.11+
- PostgreSQL 16 with `pgvector` extension (`CREATE EXTENSION vector;`)
- Redis

### Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt -e .
```

### Environment variables

```env
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/dmi
REDIS_URL=redis://localhost:6379/0
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REFRESH_TOKEN=...
GOOGLE_DOC_ID=...                     # Google Docs document ID
SECRET_KEY=...                        # ≥32 bytes; used as the API key
ENV=development                       # "production" → 0.0.0.0; anything else → 127.0.0.1

# Optional tuning
EMBEDDING_MODEL=text-embedding-3-small
RETRIEVAL_THRESHOLD=0.35
MAX_INDEX_AGE_HOURS=24
BULK_CONFIRM_TOKEN_TTL_SECONDS=600
```

### Database setup

```bash
alembic upgrade head
```

### Run the API

```bash
uvicorn app.main:app --reload
```

### Run background workers

```bash
arq app.workers.ingest.WorkerSettings
arq app.workers.index.WorkerSettings
```

### Tests

```bash
export TEST_DATABASE_URL=postgresql+asyncpg://dmi_test:dmi_test@localhost:5432/dmi_test
export ENV=test
pytest -q
```

CI runs automatically on every push. Requires no secrets — placeholder values are injected. Real Anthropic and OpenAI API tests are skipped in CI.

---

## Design constraints

**Interpretation framing.** Every API response containing LLM-derived data carries an `interpretation_note` field. The system never presents theme assignments or pattern detections as objective truth.

**Append-only annotation history.** `AnnotationVersion` records are never modified or deleted. A static code scan in the test suite verifies there are no `DELETE FROM annotation_versions` or `UPDATE annotation_versions` statements anywhere in the codebase.

**Human approval gate.** No theme category reaches `active` status without an explicit `PATCH /themes/categories/{id}/approve` call. No worker, scheduled job, or LLM call can bypass this gate.

**Idempotent workers.** Ingesting or indexing the same content twice is always safe. Deduplication is by `content_hash` with `ON CONFLICT DO NOTHING`.

**PII policy.** Raw dream text, chunk text, and grounding justifications are stripped from all logs and OpenTelemetry span attributes before emission.

---

## Architectural decisions

See [`docs/adr/`](docs/adr/) for formal ADRs and [`docs/DECISION_LOG.md`](docs/DECISION_LOG.md) for the full log.

| ID | Decision |
|----|---------|
| D-001 | Workflow shape — ordered pipelines, no agentic loop |
| D-003 | RAG retrieval ON — pgvector + HNSW index |
| D-007 | Append-only `AnnotationVersion` for all theme and category mutations |
| D-008 | Human approval required for all taxonomy changes |
