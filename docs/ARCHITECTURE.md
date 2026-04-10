# Architecture — Dream Motif Interpreter

Version: 1.0
Last updated: 2026-04-10
Status: Draft

---

## System Overview

Dream Motif Interpreter is an AI-assisted analysis tool for a personal dream journal. It ingests long-form dream entries from Google Docs, segments them into individual records, assigns multi-label thematic categories to each dream ranked by salience, links each theme to supporting text fragments, detects recurring symbolic patterns across the archive, and supports semantic and metaphor-aware retrieval. The system serves a single user who is simultaneously the journal owner and the curator of the thematic taxonomy. All persistent state lives in PostgreSQL (with pgvector extension) and Redis; the application tier is stateless between requests.

---

## Solution Shape

| Decision | Selection | Justification |
|----------|-----------|---------------|
| Primary shape | Workflow | Bounded, ordered pipelines (ingest → segment → analyse → index → retrieve). No dynamic tool-selection loop; LLM is called at fixed points in each pipeline with structured inputs and outputs. |
| Governance level | Standard | Single user, personal data, no multi-tenancy or compliance framework. Sufficient control surface: human approval gates for taxonomy changes, immutable contract, CI-enforced quality. Lean is insufficient because retrieval quality requires an evaluation lifecycle. Strict is disproportionate without a regulatory obligation. |
| Runtime tier | T1 | Stateful web application + background workers. No shell/toolchain mutation at runtime. Persistent state in DB and vector index. No privileged actions, no long-lived mutable worker state beyond what Celery/ARQ provides. T0 is insufficient because background ingestion/indexing workers require a durable task queue and persistent DB. T2/T3 are not justified — no shell mutation, no privileged runtime management. |

### Rejected Lower-Complexity Options

| Rejected option | Why it is insufficient |
|-----------------|------------------------|
| Deterministic-only | Theme extraction, salience ranking, fragment grounding, and metaphor-aware retrieval require LLM reasoning over natural language. Keyword rules cannot express symbolic abstraction or multi-label classification across a personal vocabulary. |
| Human-in-the-loop assistant (chat) | Chat produces interpretations that are ephemeral, non-persistent, and not linked to a structured archive. This was the status quo the user is explicitly replacing. |
| Simple tool use without pipelines | The system has two distinct pipelines (ingestion and query) each with multiple ordered stages. Flat prompt-in/response-out does not support chunking, embedding, indexing, salience ranking, or fragment grounding as a durable, reusable system. |

### Minimum Viable Control Surface

- Human approval required before any theme category is promoted, renamed, merged, or deleted
- Human approval required before bulk relabeling (more than one dream reassigned at once)
- Draft status for all LLM-generated theme assignments until user confirms
- No LLM-generated output is presented as authoritative or objective truth (framing requirement in all responses)
- Retrieval quality evaluated independently from code quality (retrieval_eval.md lifecycle)

### Human Approval Boundaries

| Boundary | Human approval required? | Why |
|----------|--------------------------|-----|
| Promote a new theme category to stable | Yes | Silent taxonomy mutation would invalidate prior annotations and mislead archive analysis |
| Rename or merge existing theme categories | Yes | Same risk; past associations lose meaning if categories shift silently |
| Delete a theme category | Yes | Irreversible loss of annotation context |
| Bulk relabeling of dreams (>1 dream) | Yes | High blast radius; wrong bulk relabeling corrupts the archive |
| Change interpretation logic (prompts, models) | Yes | Changes output distribution; past and future results become incomparable |
| Export interpretive conclusions framed as objective meaning | Yes | Ethical boundary — the system is explicitly not an authoritative interpreter |
| Ingestion and segmentation of new entries | No | Deterministic, reversible, idempotent |
| Draft theme extraction and ranking | No | Outputs are drafts; human reviews before promotion |
| Retrieval and search | No | Read-only; no state mutation |
| Suggested correlations and pattern summaries | No | Presented as suggestions, not conclusions |

### Deterministic vs LLM-Owned Subproblems

| Subproblem | Owner | Reason |
|------------|-------|--------|
| Sync validation, deduplication, deletion rules | Deterministic | Policy checks must be auditable and consistent; no model variance acceptable |
| Date parsing, metadata extraction from headers | Deterministic | Structured data; regex / deterministic parsing is sufficient and cheaper |
| Segmentation heuristics (boundary detection) | Deterministic (primary) + LLM (fallback) | Most boundaries are explicit (date headers, delimiters); LLM used only for ambiguous cases |
| Dream text normalization | Deterministic | Format-only transformation; no semantic reasoning needed |
| Theme category CRUD, taxonomy mutation rules | Deterministic | Governed by human approval; no LLM involvement in state mutation |
| Salience normalization, co-occurrence counts, ranking formulas | Deterministic | Calculations over LLM-produced scores; the math is deterministic even when inputs are model-generated |
| Annotation versioning, rollback, audit triggers | Deterministic | Idempotency and audit correctness require deterministic code paths |
| Confidence thresholds, pipeline routing decisions | Deterministic | Routing must be predictable; thresholds are tunable constants |
| Theme extraction (multi-label classification) | LLM | Requires semantic reasoning and subjective interpretation of narrative |
| Salience ranking (per-dream) | LLM | Requires understanding of narrative prominence; not reducible to keyword counts |
| Fragment grounding (linking themes to text spans) | LLM | Requires reading comprehension and span identification |
| Query expansion for metaphor-aware retrieval | LLM | Metaphor requires semantic abstraction beyond lexical matching |
| Explanation generation (why was this theme assigned) | LLM | Natural language generation with grounded evidence |
| Archive summary and emergent category suggestion | LLM | Creative synthesis over structured data; human approves before acting |

### Runtime and Isolation Model

| Property | Decision |
|----------|----------|
| Isolation boundary | Managed boundary — FastAPI application + ARQ worker processes managed by a process supervisor (systemd or Docker Compose). No ephemeral container per request. |
| Persistence model | DB-backed — all dream records, annotations, taxonomy, and embeddings persisted in PostgreSQL (with pgvector). Redis for task queue and query-result cache only. |
| Network model | Outbound egress required to: Google Docs API (OAuth2), Anthropic API (LLM inference), OpenAI API (embeddings). All other egress denied by default. No inbound except the HTTP API port. |
| Secrets model | All secrets via environment variables. No secrets in source, migrations, or fixtures. Required secrets listed in §Runtime Contract. |
| Runtime mutation boundary | No shell mutation at runtime. Package installation is build-time only. Workers execute deterministic job handlers; they do not install packages or modify the filesystem beyond the database. |
| Rollback / recovery model | Re-ingestion is idempotent — same Google Doc content re-synced produces the same result. Annotation versioning allows rollback to any prior state. Full DB restore from backup for catastrophic failure. |

---

## Inference / Model Strategy

| Path / Task | Model class | Why this class | Fallback / escalation | Budget / latency constraint |
|-------------|-------------|----------------|-----------------------|-----------------------------|
| Dream segmentation (ambiguous boundary detection) | Small / fast — claude-haiku-4-5 | Boundary disambiguation is a simple classification task; full reasoning is not needed | Return ambiguous boundary markers for human review | < $0.01 / document; p95 < 3s |
| Theme extraction — multi-label classification | Small / fast — claude-haiku-4-5 with structured output | Produces a bounded JSON response (theme IDs + justification); structured output keeps variance low | Escalate to claude-sonnet-4-6 when confidence below threshold | < $0.05 / dream; p95 < 8s |
| Salience ranking and fragment grounding | Mid / reasoning — claude-sonnet-4-6 | Requires reading comprehension to rank by narrative prominence and locate supporting spans | No automatic fallback; surface low-confidence results as drafts | < $0.10 / dream; p95 < 15s |
| Query expansion (metaphor-aware) | Small / fast — claude-haiku-4-5 | Produces a list of semantically related terms; does not require deep reasoning | Fall back to unmodified query if expansion fails | < $0.005 / query; p95 < 2s |
| Explanation generation | Mid / reasoning — claude-sonnet-4-6 | Requires grounded, coherent explanation referencing evidence fragments | No fallback — surface raw fragments if generation fails | < $0.05 / request; p95 < 10s |
| Archive summary / emergent category suggestions | Mid / reasoning — claude-sonnet-4-6 | Creative synthesis over many dreams requires broader reasoning | Present as suggestions only; human reviews | Async / batch; no interactive latency target |

Validation metric: precision@3 on the 10-query evaluation set for retrieval; theme extraction consistency score (same dream re-processed twice produces ≥80% overlap in top-3 themes) measured per phase boundary.

---

## Capability Profiles

| Profile    | Status | Declared in Phase | Notes |
|------------|--------|-------------------|-------|
| RAG        | ON     | 1                 | Hybrid retrieval over dream entries and annotations is a first-class requirement |
| Tool-Use   | OFF    | 1                 | Google Docs API and DB are called by application code, not by the LLM at inference time |
| Agentic    | OFF    | 1                 | Bounded workflows; LLM is called once per pipeline stage with deterministic routing |
| Planning   | OFF    | 1                 | Primary deliverables are analyses and annotations, not structured plans consumed by downstream systems |
| Compliance | OFF    | 1                 | No named regulatory framework (not HIPAA, GDPR, PCI-DSS); privacy-first practices via §PII Policy |

**RAG Profile: ON**
Justification: The system must answer thematic queries grounded in a corpus of personal dream entries (100–2000 tokens each, growing incrementally). Fragment-level citation is a first-class requirement (each theme must link to supporting text spans). Metaphor-aware retrieval requires hybrid lexical + embedding-based search. Prompt-stuffing the full archive into each request is not viable beyond a handful of entries. Retrieval quality is an independent evaluation lifecycle from code quality.

**Tool-Use Profile: OFF**
Justification: The LLM is never given tools to call at inference time. Google Docs API, database reads, and vector index queries are all initiated by deterministic application code. The LLM receives a prompt (possibly including retrieved text) and returns a structured JSON response. No tool schema, idempotency gate, or unsafe-action confirmation is needed at the LLM boundary.

**Agentic Profile: OFF**
Justification: Each user request results in a bounded, ordered pipeline execution. The LLM is called at fixed points (segmentation fallback, theme extraction, grounding, query expansion, explanation). There is no multi-step decision loop where the LLM decides its own next action. No handoff protocol or loop termination contract is needed.

**Planning Profile: OFF**
Justification: The system produces dream analyses, theme annotations, and retrieval results — not structured plans consumed by downstream systems. No plan schema, validation gate, or plan-to-execution contract applies.

**Compliance Profile: OFF**
Justification: No named regulatory framework applies. The user is the sole operator and data subject. Privacy-first practices (dream content not exposed in logs or spans, user-controlled deletion, minimal data retention policy) are enforced via §PII Policy and §Project-Specific Rules, not a compliance framework.

### Profile: RAG

#### RAG Architecture

**Ingestion pipeline** (offline / scheduled via background worker):
```
extract → normalize → chunk → embed → index
```

| Stage | Description | Technology |
|-------|-------------|------------|
| Extract | Fetch dream journal document from Google Docs API using OAuth2; return raw text with paragraph structure | Google Docs API v1 (Python client) |
| Normalize | Strip formatting artifacts; detect entry boundaries (date headers, delimiter lines); emit normalized text per dream entry | Deterministic Python parsing |
| Chunk | Each dream entry is one primary chunk. Long entries (> 512 tokens) are split at paragraph boundaries with 50-token overlap | Custom splitter in `app/retrieval/ingestion.py` |
| Embed | Generate dense vector per chunk using text-embedding-3-small (1536 dimensions) | OpenAI Embeddings API |
| Index | Store chunk text, vector, dream_id, chunk_index, and metadata in pgvector table `dream_chunks` | PostgreSQL 16 + pgvector |

**Query-time pipeline** (online / per-request):
```
query analyze → retrieve → rerank/filter → assemble evidence → answer | insufficient_evidence
```

| Stage | Description | Technology |
|-------|-------------|------------|
| Query analyze | Expand query with semantically related terms and archetypal synonyms for metaphor-aware matching (LLM call); produce (original_query, expanded_terms[]) | claude-haiku-4-5 |
| Retrieve | Hybrid search: pgvector cosine similarity (top-20 candidates) + PostgreSQL full-text search (BM25 via `ts_rank`); fuse scores with RRF (Reciprocal Rank Fusion) | pgvector + PostgreSQL FTS |
| Rerank/filter | Filter by minimum relevance score (configurable threshold, default 0.35); retain top-5 after fusion | Deterministic score filter |
| Assemble evidence | Format retained chunks as numbered XML-tagged blocks including dream_id, date, chunk text, and theme annotations already linked to that entry | Python string assembly |
| Answer / insufficient_evidence | If 0 chunks survive the relevance threshold, return `insufficient_evidence`. If 1–5 chunks pass, proceed to answer generation. | Deterministic count check |

The `insufficient_evidence` path is **not optional**. When retrieved evidence does not support an answer, the system must return `insufficient_evidence` rather than fabricating a response.

#### Corpus Description

| Property | Value |
|----------|-------|
| Source documents | Personal dream journal stored in a single Google Doc (multi-page) |
| Update frequency | Incremental — user adds new entries; no documents are removed without explicit deletion |
| Estimated size | 100–5000 dream entries at index time; grows incrementally over months |
| Access control | Single-user system; no cross-user isolation required. All indexed content belongs to the same owner. |

#### Index Strategy

- **Embedding model:** `text-embedding-3-small` (OpenAI, 1536 dimensions) — rationale: cost-efficient, strong semantic performance on personal narrative text, small enough for local pgvector without a dedicated vector DB
- **Chunking:** One chunk per dream entry; entries > 512 tokens split at paragraph boundaries with 50-token overlap — rationale: preserves narrative coherence; dream entries are the natural retrieval unit
- **Index schema version:** v1 — changes require ADR; re-indexing of the full corpus required on schema change
- **Max index age:** 24 hours — staleness beyond this threshold must produce a warning on the health endpoint; the index is rebuilt incrementally by the sync worker after each Google Docs pull

#### Risks (RAG-specific)

| Risk | Mitigation |
|------|------------|
| Hallucination on weak evidence | Relevance threshold at retrieval (default 0.35); `insufficient_evidence` path required and tested |
| Schema drift (embedding model / chunk format change) | Version index schema (v1); ADR required before model change; full re-index required on schema change |
| Stale index | Max age 24 hours; health endpoint exposes `index_last_updated`; staleness beyond threshold returns degraded status |
| Corpus isolation failure | Single-user system; no cross-user isolation risk. All queries access the same namespace. |
| Retrieval latency regression | p95 retrieval latency acceptance criterion per RAG task; tracked in `docs/retrieval_eval.md` |

---

## Component Table

| Component | File / Directory | Responsibility |
|-----------|-----------------|----------------|
| FastAPI app factory | `app/main.py` | Creates and configures the FastAPI application; registers routers and middleware |
| Config | `app/shared/config.py` | Loads and validates all environment variables at startup; fails fast on missing required vars |
| Shared tracing | `app/shared/tracing.py` | Single `get_tracer()` function; all spans import from here |
| Dream API router | `app/api/dreams.py` | HTTP endpoints for dream CRUD, sync trigger, browsing |
| Theme API router | `app/api/themes.py` | HTTP endpoints for theme management and curation |
| Search API router | `app/api/search.py` | HTTP endpoints for semantic and thematic search |
| Health router | `app/api/health.py` | `GET /health` — liveness + index freshness check |
| Ingestion service | `app/services/ingestion.py` | Orchestrates sync from Google Docs; deduplication; triggers downstream analysis |
| Segmentation service | `app/services/segmentation.py` | Deterministic boundary detection; LLM fallback for ambiguous boundaries |
| Analysis service | `app/services/analysis.py` | Orchestrates per-dream theme extraction → ranking → grounding pipeline |
| Pattern service | `app/services/patterns.py` | Archive-level recurrence detection, co-occurrence counts, emergent category suggestions |
| Taxonomy service | `app/services/taxonomy.py` | Theme category CRUD; approval state machine; mutation rules |
| Google Docs client | `app/services/gdocs_client.py` | OAuth2 auth; document fetch and paragraph extraction |
| LLM client | `app/llm/client.py` | Thin wrapper around Anthropic SDK; handles retries and structured output parsing |
| Theme extractor | `app/llm/theme_extractor.py` | LLM prompts for multi-label theme extraction with structured JSON output |
| Grounding model | `app/llm/grounder.py` | LLM prompts for salience ranking and fragment-to-theme linking |
| Explainer | `app/llm/explainer.py` | LLM prompts for explanation generation grounded in retrieved evidence |
| RAG ingestion | `app/retrieval/ingestion.py` | Chunking, embedding, pgvector upsert |
| RAG query | `app/retrieval/query.py` | Hybrid retrieval, evidence assembly, `insufficient_evidence` gate |
| Dream models | `app/models/dream.py` | SQLAlchemy models: `DreamEntry`, `DreamChunk` |
| Theme models | `app/models/theme.py` | SQLAlchemy models: `ThemeCategory`, `DreamTheme` (junction with salience + fragments) |
| Annotation models | `app/models/annotation.py` | SQLAlchemy models: `AnnotationVersion` (versioned snapshots for rollback) |
| Background workers | `app/workers/` | ARQ job handlers for ingestion and indexing |
| Alembic migrations | `alembic/` | All schema migrations; versioned, never applied manually |

---

## Data Flow — Primary Request Path

The following describes the end-to-end path for a **semantic search query**:

1. Client sends `GET /search?q=separation+from+mother` with session cookie (or API key header).
2. Auth middleware validates the session; rejects unauthenticated requests with HTTP 401.
3. Request reaches `app/api/search.py::search_handler`. Params extracted: query string, optional filters (date range, theme IDs).
4. Handler calls `app/retrieval/query.py::retrieve(query, filters)`.
5. `retrieve()` calls `app/llm/client.py` → `claude-haiku-4-5` for query expansion; receives `expanded_terms[]`.
6. `retrieve()` executes hybrid pgvector cosine + PostgreSQL FTS query against `dream_chunks`; fuses scores via RRF; retains top-5 above threshold.
7. If 0 chunks pass threshold: returns `{"result": "insufficient_evidence", "query": "..."}` — HTTP 200.
8. If 1–5 chunks pass: assembles XML-tagged evidence block; calls `app/llm/explainer.py` → `claude-sonnet-4-6` for grounded explanation.
9. Response returned as `{"result": [...dreams with matched fragments, theme annotations, explanation], "citations": [...]}`.

**Background ingestion path** (async, triggered by sync API):

1. `POST /sync` accepted; job enqueued in ARQ / Redis queue.
2. Worker calls `app/services/ingestion.py::sync_from_gdocs()`.
3. Google Docs API fetched; raw text extracted.
4. `app/services/segmentation.py` segments into dream entries; deduplication check against existing records.
5. New entries saved to `dream_entries` table.
6. For each new entry: `app/services/analysis.py` called → theme extraction → grounding → annotation saved with `status=draft`.
7. `app/retrieval/ingestion.py` chunks, embeds, and upserts into `dream_chunks` + pgvector.
8. Sync status updated; `index_last_updated` timestamp refreshed.

---

## Tech Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python 3.11 | Standard for AI/ML projects; strong async support; matches the Anthropic and Google API SDKs |
| Framework | FastAPI 0.111+ | Async-first; native Pydantic validation; OpenAPI generation; lightweight for a single-user tool |
| Database | PostgreSQL 16 + pgvector | Relational schema for structured archive data + native vector similarity search in one system, eliminating a separate vector database |
| ORM / query layer | SQLAlchemy 2.x async | Async support matches FastAPI; mature migration tooling via Alembic; parameterized queries enforced by the ORM layer |
| Task queue | ARQ (async Redis Queue) | Lightweight async worker compatible with Python asyncio; no Celery overhead for a single-user tool |
| Cache | Redis 7 | ARQ backend; query result cache for repeated searches |
| LLM inference | Anthropic API (claude-haiku-4-5, claude-sonnet-4-6) | claude-haiku-4-5 for cost-efficient structured output; claude-sonnet-4-6 for reasoning-heavy tasks |
| Embeddings | OpenAI text-embedding-3-small | Cost-efficient (< $0.002 / 1M tokens), strong semantic performance on narrative text, 1536 dimensions compatible with pgvector |
| External data | Google Docs API v1 | User's journal is in Google Docs; OAuth2 access grants read access to the specific document |
| Observability | OpenTelemetry + structlog | OpenTelemetry for spans; structlog for structured JSON logs with trace_id injection |
| Lint / format | ruff | Unified linter and formatter; zero configuration drift |
| Test framework | pytest + pytest-asyncio | Industry standard; async fixture support for FastAPI and ARQ tests |
| Migrations | Alembic | SQLAlchemy-native; version-controlled schema history |
| CI | GitHub Actions | Free tier sufficient for single-user project; integrates with repository |
| Deployment | Docker Compose (local) or single-host container | Lightweight single-user tool; no Kubernetes overhead |

---

## Security Boundaries

### Authentication

The system is single-user. Authentication is enforced via a session cookie set after Google OAuth2 login, or via an API key header (`X-API-Key`) for programmatic access. All routes except `GET /health` and `GET /auth/callback` require a valid session or API key. Sessions expire after 24 hours of inactivity. The API key is stored as a hashed value in the database; the plaintext key is shown only once at generation.

### Tenant Isolation

This is a single-user system. Tenant isolation is not applicable. All data belongs to the owner.

### PII Policy

Dream content is treated as highly sensitive personal data. The following fields are classified as sensitive personal data in this system: `dream_text`, `dream_title`, `theme_notes`, `fragment_text`.

- These fields are **never** written to log messages, span attributes, or metrics labels.
- Log messages reference dream entries by `dream_id` (UUID) only.
- Span attributes include `dream_id`, `chunk_count`, `theme_count` — never raw text.
- Error messages returned to clients do not include dream content.
- Full-text search indexes are not exposed in logs or observability.

---

## Observability

| Dimension | Choice | Notes |
|-----------|--------|-------|
| Tracing | OpenTelemetry (noop exporter for v1; switchable to Jaeger) | Shared module: `app/shared/tracing.py::get_tracer()` |
| Metrics | structlog-based event counters (v1); Prometheus in v2 | Required labels: `service`, `env`, `operation` |
| Logging | structlog JSON | Required fields: `trace_id`, `span_id`, `env`, `service`; dream content never logged |
| Dashboards | N/A (v1 is single-user, local) | |
| Alerting | N/A for v1; index staleness surfaced via health endpoint | |

### Observability Invariants

- No dream content (personal sensitive data) in spans, metrics labels, or log messages.
- Health endpoint: `GET /health` returns `{"status": "ok", "index_last_updated": "ISO8601"}`.
- All external calls instrumented: DB queries, Redis, Google Docs API, Anthropic API, OpenAI embeddings.

---

## External Integrations

| Integration | Purpose | Auth method | Rate limit / SLA |
|-------------|---------|-------------|-----------------|
| Google Docs API v1 | Fetch dream journal document content | Google OAuth2 (refresh token stored in env) | 300 req/min per project; single doc fetch per sync cycle |
| Anthropic API | LLM inference (theme extraction, grounding, explanation, query expansion) | API key in `ANTHROPIC_API_KEY` env var | Tier 1 rate limits; auto-retry with exponential backoff |
| OpenAI Embeddings API | Generate dense vectors for dream chunks | API key in `OPENAI_API_KEY` env var | Tier 1 limits; batch embedding during ingestion |

---

## File Layout

```
dream_motif_interpreter/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app factory
│   ├── api/                       # Route handlers (thin — delegate to services)
│   │   ├── __init__.py
│   │   ├── dreams.py              # Dream CRUD + sync trigger
│   │   ├── themes.py              # Theme management + curation
│   │   ├── search.py              # Semantic + thematic search
│   │   └── health.py              # GET /health
│   ├── services/                  # Business logic (no HTTP dependencies)
│   │   ├── __init__.py
│   │   ├── ingestion.py           # Sync orchestration, deduplication
│   │   ├── segmentation.py        # Dream boundary detection
│   │   ├── analysis.py            # Theme extraction → ranking → grounding pipeline
│   │   ├── taxonomy.py            # Theme category CRUD + approval state machine
│   │   └── patterns.py            # Archive-level pattern detection, co-occurrence
│   ├── llm/                       # LLM client and prompt modules
│   │   ├── __init__.py
│   │   ├── client.py              # Anthropic SDK wrapper with retry + structured output
│   │   ├── theme_extractor.py     # Multi-label theme extraction prompts
│   │   ├── grounder.py            # Salience ranking + fragment grounding prompts
│   │   └── explainer.py           # Explanation generation prompts
│   ├── retrieval/                 # RAG components (strictly separated)
│   │   ├── __init__.py
│   │   ├── ingestion.py           # Chunk → embed → index (offline path)
│   │   └── query.py               # Retrieve → rerank → assemble → answer (online path)
│   ├── models/                    # SQLAlchemy async models
│   │   ├── __init__.py
│   │   ├── dream.py               # DreamEntry, DreamChunk
│   │   ├── theme.py               # ThemeCategory, DreamTheme (with salience + fragments)
│   │   └── annotation.py          # AnnotationVersion (versioned snapshots for rollback)
│   ├── workers/                   # ARQ background job handlers
│   │   ├── __init__.py
│   │   ├── ingest.py              # Sync + segmentation jobs
│   │   └── index.py               # Embedding + indexing jobs
│   └── shared/                    # Shared utilities
│       ├── __init__.py
│       ├── tracing.py             # Single get_tracer() — all spans import from here
│       └── config.py              # Settings loaded from env vars; fails fast if missing
├── tests/
│   ├── conftest.py                # Shared fixtures (DB, async client)
│   ├── unit/                      # Unit tests (no I/O)
│   └── integration/               # Integration tests (with DB, Redis)
├── alembic/                       # Database migrations
│   ├── env.py
│   └── versions/
├── docs/
│   ├── ARCHITECTURE.md            # This file
│   ├── spec.md
│   ├── tasks.md
│   ├── CODEX_PROMPT.md
│   ├── IMPLEMENTATION_CONTRACT.md
│   ├── DECISION_LOG.md
│   ├── IMPLEMENTATION_JOURNAL.md
│   ├── EVIDENCE_INDEX.md
│   ├── retrieval_eval.md
│   ├── prompts/
│   │   ├── ORCHESTRATOR.md
│   │   └── PROMPT_S_STRATEGY.md
│   └── audit/
│       ├── PROMPT_0_META.md
│       ├── PROMPT_1_ARCH.md
│       ├── PROMPT_2_CODE.md
│       ├── PROMPT_3_CONSOLIDATED.md
│       └── AUDIT_INDEX.md
├── .github/
│   └── workflows/
│       └── ci.yml
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
└── README.md
```

---

## Runtime Contract

| Variable | Description | Example value | Required |
|----------|-------------|---------------|----------|
| `DATABASE_URL` | PostgreSQL DSN with pgvector | `postgresql+asyncpg://user:pass@localhost:5432/dmi` | Yes |
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379/0` | Yes |
| `ANTHROPIC_API_KEY` | Anthropic API key for LLM inference | `sk-ant-...` | Yes |
| `OPENAI_API_KEY` | OpenAI API key for embeddings | `sk-...` | Yes |
| `GOOGLE_CLIENT_ID` | Google OAuth2 client ID | `123456.apps.googleusercontent.com` | Yes |
| `GOOGLE_CLIENT_SECRET` | Google OAuth2 client secret | `GOCSPX-...` | Yes |
| `GOOGLE_REFRESH_TOKEN` | OAuth2 refresh token for the journal owner | `1//...` | Yes |
| `GOOGLE_DOC_ID` | Google Docs document ID of the dream journal | `1BxiM...` | Yes |
| `SECRET_KEY` | App session secret (32+ random bytes) | `a9f3...` | Yes |
| `ENV` | Runtime environment | `development` or `production` | Yes |
| `EMBEDDING_MODEL` | OpenAI embedding model name | `text-embedding-3-small` | No (default: `text-embedding-3-small`) |
| `RETRIEVAL_THRESHOLD` | Minimum relevance score for retrieved chunks | `0.35` | No (default: `0.35`) |
| `MAX_INDEX_AGE_HOURS` | Max allowed hours since last index update | `24` | No (default: `24`) |

---

## Continuity and Retrieval Model

### Canonical Truth

| Artifact | Authority |
|----------|-----------|
| `docs/ARCHITECTURE.md` | Architecture and boundary decisions |
| `docs/IMPLEMENTATION_CONTRACT.md` | Immutable implementation rules |
| `docs/tasks.md` | Execution contract and task graph |
| `docs/CODEX_PROMPT.md` | Live session state and open findings |
| `docs/adr/` | Formal decision changes |
| `docs/audit/` + `docs/retrieval_eval.md` | Review and retrieval proof history |

### Retrieval Convenience

| Artifact | Purpose | Required? |
|----------|---------|-----------|
| `docs/DECISION_LOG.md` | Quick recall of why key decisions were made | Yes |
| `docs/IMPLEMENTATION_JOURNAL.md` | Cross-session implementation handoff | Yes |
| `docs/EVIDENCE_INDEX.md` | Proof lookup across retrieval evals and review cycles | Yes — RAG profile active |

### Scoped Retrieval Rules

- Tasks that touch architecture, runtime, auth, retrieval semantics, or open findings must include `Context-Refs` in `docs/tasks.md`.
- Agents read task `Context-Refs` first, then only the linked canonical documents.
- Retrieval artifacts summarize and index; they do not overrule canonical files.

---

## Non-Goals (v1)

- Clinical, psychiatric, or therapeutic interpretation of any kind
- Claims of objective symbolic meaning — all outputs are explicitly framed as suggestions
- Multi-user collaboration or shared journals
- Social features or public export
- Multimodal analysis (images, audio)
- Authoritative taxonomy (the system may suggest; the user decides)
- Real-time sync (ingestion is async / manual trigger)
- Mobile or native application (web API only)
- No autonomous taxonomy evolution without user approval — the system never silently renames, merges, or promotes theme categories
- No T2/T3 runtime expansion without an ADR — shell mutation and privileged runtime behavior are out of scope
