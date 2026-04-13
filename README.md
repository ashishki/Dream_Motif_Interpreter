# Dream Motif Interpreter

AI-assisted analysis tool for a personal dream journal. Ingests long-form dream entries from Google Docs, segments them, assigns thematic categories, grounds themes to supporting text fragments, detects recurring symbolic patterns, and supports semantic retrieval.

---

## Current Status

**Phase 4** — Health Endpoint and Observability (T13 in progress)

- Phase 3 complete: RAG ingestion + query pipeline implemented and evaluated
- Retrieval baseline established: `hit@3=1.00`, `MRR=1.00`, `no-answer accuracy=1.00` against synthetic-20-entries corpus
- Test baseline: **48 passing, 12 skipped**
- Ruff: clean (0 violations)

---

## Features

| Feature | Status | Task |
|---------|--------|------|
| Project skeleton + CI | Complete | T01–T03 |
| Database schema (PostgreSQL + pgvector) | Complete | T04 |
| Google Docs ingestion client | Complete | T05 |
| Dream segmentation service | Complete | T06 |
| Theme taxonomy system (approval state machine) | Complete | T07 |
| Per-dream theme extraction (LLM, structured output) | Complete | T08 |
| Salience ranking and fragment grounding | Complete | T09 |
| RAG ingestion pipeline (chunk → embed → index) | Complete | T10 |
| RAG query pipeline (hybrid retrieval, insufficient_evidence gate) | Complete | T11 |
| Retrieval evaluation baseline (synthetic-20-entries) | Complete | T12 |
| Health endpoint + observability (OTel spans, structlog) | In progress | T13 |

---

## Tests

| Milestone | Passing | Skipped |
|-----------|---------|---------|
| T01 skeleton | 3 | 0 |
| T05 (end of Phase 1) | 17 | 1 |
| T09 (end of Phase 2) | 32 | 4 |
| T10 RAG ingestion | 41 | 6 |
| T11 RAG query | 42 | 10 |
| T12 retrieval eval baseline (Phase 3 gate) | **48** | **12** |

Skipped tests require live external credentials (Google OAuth, Anthropic API, OpenAI API) not present in CI.

---

## Repository Layout

```
dream_motif_interpreter/
├── app/
│   ├── main.py                    # FastAPI app factory
│   ├── api/
│   │   ├── dreams.py              # Dream CRUD + sync trigger
│   │   ├── themes.py              # Theme management + curation
│   │   ├── search.py              # Semantic + thematic search
│   │   └── health.py              # GET /health
│   ├── services/
│   │   ├── ingestion.py           # Sync orchestration, deduplication
│   │   ├── segmentation.py        # Dream boundary detection
│   │   ├── analysis.py            # Theme extraction → ranking → grounding pipeline
│   │   ├── taxonomy.py            # Theme category CRUD + approval state machine
│   │   └── patterns.py            # Archive-level pattern detection, co-occurrence
│   ├── llm/
│   │   ├── client.py              # Anthropic SDK wrapper
│   │   ├── theme_extractor.py     # Multi-label theme extraction prompts
│   │   ├── grounder.py            # Salience ranking + fragment grounding prompts
│   │   └── explainer.py           # Explanation generation prompts
│   ├── retrieval/
│   │   ├── ingestion.py           # Chunk → embed → index (offline path)
│   │   └── query.py               # Retrieve → rerank → assemble → answer (online path)
│   ├── models/
│   │   ├── dream.py               # DreamEntry, DreamChunk
│   │   ├── theme.py               # ThemeCategory, DreamTheme
│   │   └── annotation.py          # AnnotationVersion (versioned snapshots)
│   ├── workers/
│   │   ├── ingest.py              # Sync + segmentation jobs
│   │   └── index.py               # Embedding + indexing jobs
│   └── shared/
│       ├── tracing.py             # Single get_tracer() — all spans import from here
│       └── config.py              # Settings loaded from env vars; fails fast if missing
├── tests/
│   ├── conftest.py
│   ├── unit/
│   └── integration/
├── alembic/
│   └── versions/
│       ├── 001_initial_schema.py
│       ├── 002_add_deprecated_flag.py
│       ├── 003_seed_categories.py
│       ├── 004_fix_status_ck.py
│       ├── 005_add_fragments_default.py
│       └── 006_add_hnsw_index.py
├── scripts/
│   └── eval.py                    # Retrieval evaluation runner
├── docs/
│   ├── ARCHITECTURE.md
│   ├── CODEX_PROMPT.md
│   ├── IMPLEMENTATION_CONTRACT.md
│   ├── spec.md
│   ├── tasks.md
│   ├── retrieval_eval.md
│   └── audit/
│       └── REVIEW_REPORT.md
├── requirements.txt
├── requirements-dev.txt
└── pyproject.toml
```

---

## Quick Start

```bash
# Install dependencies
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# Set required environment variables (see docs/ARCHITECTURE.md §Runtime Contract)
export DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/dmi
export REDIS_URL=redis://localhost:6379/0
# ... (see docs/ARCHITECTURE.md for full list)

# Run migrations
alembic upgrade head

# Run tests
pytest -q

# Start the application
uvicorn app.main:app --reload
```

---

## Documentation

| Document | Purpose |
|----------|---------|
| `docs/ARCHITECTURE.md` | System architecture, component table, data flows, runtime contract |
| `docs/IMPLEMENTATION_CONTRACT.md` | Immutable implementation rules |
| `docs/tasks.md` | Task graph and acceptance criteria |
| `docs/CODEX_PROMPT.md` | Live session state, open findings, next task |
| `docs/retrieval_eval.md` | RAG evaluation dataset and baseline metrics |
| `PLAYBOOK.md` | AI-assisted development workflow |
