---
# ARCH_REPORT — Cycle 6
_Date: 2026-04-14_

---

## Component Verdicts

| Component | Verdict | Note |
|-----------|---------|------|
| `app/api/dreams.py` | PASS | Thin handler; delegates to `InMemorySyncBackend` and DB via session factory; no business logic inline; auth middleware enforced via `app/main.py` |
| `app/api/search.py` | DRIFT | Layer-boundary drift: creates own `AsyncEngine` and `async_sessionmaker` via private `lru_cache` functions, duplicating infrastructure that should be shared (ARCH-12). Also: `interpretation_note` absent from all response models (ARCH-6 unresolved). |
| `app/api/health.py` | PASS | Thin handler; reads index age via parameterized query; staleness check uses `MAX_INDEX_AGE_HOURS` from config; OTel span present; public-route comment cites OBS-3 correctly |
| `app/api/themes.py` | N/A | File does not yet exist — T16 primary deliverable. Absence is expected pre-T16. Component is correctly declared in ARCHITECTURE.md §Component Table. |
| `app/services/segmentation.py` | DRIFT | `_segment_with_llm_fallback` comment still references "T08" (now completed). `type: ignore` comment on import. Stale reference violates FORBIDDEN ACTIONS (stale task ref / dead code). Open as CODE-13 carry-forward. |
| `app/services/taxonomy.py` | PASS | Service file present; no HTTP imports; correct layer boundary |
| `app/services/analysis.py` | PASS | Business logic layer; no HTTP dependencies |
| `app/llm/theme_extractor.py` | DRIFT | No `interpretation_note` literal field in `ThemeAssignment` dataclass or API response schema. Framing exists only in prompt text. ARCH-6 carry-forward. |
| `app/llm/grounder.py` | DRIFT | Same as theme_extractor: framing present in system prompt string but not enforced as a Pydantic literal field at the API schema level. ARCH-6 carry-forward. |
| `app/retrieval/ingestion.py` | PASS | No import of `app/retrieval/query.py`; responsibilities are chunking, embedding, upsert only; `INDEX_SCHEMA_VERSION = "v1"` declared; OTel spans present |
| `app/retrieval/query.py` | DRIFT | No import of `app/retrieval/ingestion.py` — separation rule PASS. Query expansion (LLM call) not wired — ARCH-10 carry-forward. `EvidenceBlock.matched_fragments` is `list[str]`; spec requires offsets and `match_type` — ARCH-11 carry-forward. |
| `app/retrieval/types.py` | PASS | Shared `EmbeddingClient` Protocol and `OpenAIEmbeddingClient` now present; both `ingestion.py` and `query.py` import from here. NEW-ARCH-1 from Cycle 5 is resolved. |
| `app/models/theme.py` | PASS | `DreamTheme` and `ThemeCategory` models present; CHECK constraints on both status columns; `fragments` JSONB with `server_default '[]'::jsonb`; `deprecated` boolean with `server_default false` |
| `app/models/annotation.py` | PASS | `AnnotationVersion` model present with `entity_type`, `entity_id`, `snapshot`, `changed_by`; no DELETE or UPDATE paths found |
| `app/models/dream.py` | PASS | Base models `DreamEntry`, `DreamChunk` present |
| `app/shared/config.py` | DRIFT | No `BULK_CONFIRM_TOKEN_TTL_SECONDS` config slot. T16 bulk-confirm token TTL will have no config home; hardcoding risks policy violation. See ARCH-13. |
| `app/shared/tracing.py` | PASS | Single `get_tracer()` shared module; all spans observed importing from here; no inline noop implementations |
| `app/main.py` | DRIFT | `host="0.0.0.0"` unconditional in `main()` function — CODE-7 carry-forward. `themes_router` not yet registered — expected pre-T16. `InMemorySyncBackend` in `dreams.py` (not ARQ-backed) inconsistent with declared architecture. |
| `app/workers/` | DRIFT | Only `__init__.py` present; `ingest.py` and `index.py` declared in ARCHITECTURE.md §File Layout are absent. Background job execution is not wired. Session factory pattern required for T17 cannot be assessed. See ARCH-14. |
| `alembic/versions/` | PASS | Migrations 001–006 present on disk and now correctly listed in ARCHITECTURE.md §File Layout. ARCH-9 is resolved. |

---

## Contract Compliance

| Rule | Verdict | Note |
|------|---------|------|
| SQL Safety — parameterized queries only | PASS | All `text()` calls use named parameters; no f-strings or string concatenation in query paths observed in any scoped file |
| Async Redis — `redis.asyncio` only | N/A | No Redis client code present in reviewed files; T16 will introduce Redis use for bulk-confirm tokens; rule applies at T16 implementation time |
| Authorization — every route enforces auth; public routes documented | PASS | Middleware in `app/main.py:25-30` enforces auth before all non-PUBLIC_PATHS routes; `GET /health` documented with inline comment citing OBS-3 design decision |
| PII Policy — no sensitive data in logs, spans, or errors | PASS | Observed spans use `dream_id` only; no `raw_text`, `chunk_text`, `fragment_text`, or `justification` in span attributes or structlog `extra` dicts |
| Credentials and Secrets — env vars only | PASS | No hardcoded credentials found; all secrets via `app/shared/config.py` `Settings`; `.env` pattern confirmed |
| Shared Tracing Module — single `get_tracer()` | PASS | All span creation in scoped modules imports `get_tracer` from `app/shared/tracing`; no inline noop implementations found |
| CI Gate | N/A | Cannot verify from static review; carry-forward assumption: CI is passing per Cycle 6 baseline (74 pass / 9 skip) |
| OBS-1 — every external call wrapped in a span | PASS | DB queries, embedding API calls, RAG retrieval all wrapped in spans via `get_tracer()` |
| OBS-2 — `insufficient_evidence` counter; `retrieval_ms` span | PASS | `retrieval_ms` set as span attribute at `app/retrieval/query.py:98`; `insufficient_evidence` emitted via `logger.info` with reason context at lines 87 and 102. Meets v1 structlog-based counter expectation per ARCHITECTURE.md §Observability |
| OBS-3 — health endpoint contract | PASS | Returns `{"status": "ok"\|"degraded", "index_last_updated": ISO8601\|null}`; HTTP 503 when stale; no auth required; PII not logged |
| LLM Output Framing (`interpretation_note` at API schema level) | VIOLATION | `SearchResultItem`, `SearchResultsResponse`, `DreamThemeResponseItem` in `app/api/search.py` contain no `interpretation_note` field. Framing is in LLM prompt strings only. IMPLEMENTATION_CONTRACT §LLM Output Framing requires schema-level enforcement. Open as ARCH-6 (P2, age cap approaching). |
| Annotation Versioning — write-ahead before every mutation | DRIFT | `AnnotationVersion` model is correct and present. T16 mutation endpoints do not yet exist; write-ahead enforcement cannot be confirmed until `app/api/themes.py` is implemented. This is a pre-implementation risk gate for T16, not a current violation. |
| Taxonomy Mutation Gate — no automated promotion path | PASS | No automated promotion code path found; taxonomy service requires explicit API call; no LLM output directly mutates `ThemeCategory.status` |
| Idempotent Workers — content hash + composite key | PASS (partial) | `_upsert_chunk` uses `on_conflict_do_nothing` on `(dream_id, chunk_index)` — correct for chunking idempotency. Worker job handlers (`ingest.py`, `index.py`) absent; cannot assess full idempotency of the background pipeline. |
| Ingestion/Query Separation — no cross-import | PASS | Confirmed by direct file inspection: neither `ingestion.py` nor `query.py` imports the other |
| Dream Content Isolation (Redis keys/values) | N/A | No Redis client in scope; rule applies when T16 token code is written |
| `annotation_versions` append-only | PASS | No DELETE or UPDATE against `annotation_versions` found anywhere in reviewed scope |
| `BULK_CONFIRM_TOKEN_TTL_SECONDS` config slot | VIOLATION | Missing from `app/shared/config.py`. T16 bulk-confirm token TTL must be config-driven, not hardcoded. See ARCH-13. |
| Secrets scope — no secrets in source, migrations, fixtures | PASS | No credentials observed |
| Runtime mutation boundary (T1) | PASS | No shell mutation, no ad-hoc package installs in any runtime path |

---

## ADR Compliance

| ADR | Verdict | Note |
|-----|---------|------|
| (No ADR files found — `docs/adr/` directory absent) | VIOLATION | `docs/adr/` directory does not exist. IMPLEMENTATION_CONTRACT declares ADRs required for schema changes, runtime tier expansion, and contract modifications. No formal decisions have been filed. The directory itself must exist to operationalize the ADR governance process. ARCH-15 / carry-forward of ARCH-4 from Cycle 5. |

---

## Architecture Findings

### ARCH-6 [P2] — `interpretation_note` Not Enforced at API Response Schema Level
Symptom: LLM output framing is present in system prompt text only; API response Pydantic models contain no `interpretation_note` literal field.
Evidence: `app/api/search.py:27-38` (`SearchResultItem`, `SearchResultsResponse` — no `interpretation_note`); `app/api/search.py:47-57` (`DreamThemeResponseItem` — no `interpretation_note`); `app/llm/theme_extractor.py:58-64` (framing in prompt string only); `app/llm/grounder.py:63-68` (framing in prompt string only).
Root cause: IMPLEMENTATION_CONTRACT §LLM Output Framing requires enforcement at the API response schema level (Pydantic model with a literal field), not only at the prompt level. T15 shipped without closing this gap.
Impact: API responses carry no machine-readable framing. Any downstream consumer receives interpretation data without a structured disclaimer. P2 finding; approaching age cap (open since Cycle 2+).
Fix: Add `interpretation_note: Literal["These are AI-generated draft interpretations, not authoritative conclusions."]` as a constant field to `DreamThemeResponseItem`, `SearchResultItem`, `SearchResultsResponse`, and any T16 theme-curation response models. Assign to T16 scope or create FIX-C6 item. Must close in Cycle 6 or escalate to P1.

### ARCH-10 [P3] — LLM Query Expansion Not Wired in `query.py`
Symptom: ARCHITECTURE.md §RAG Architecture declares query expansion via `claude-haiku-4-5` as a pipeline stage ("Query analyze → expanded_terms[]"). `app/api/search.py::_expand_terms()` is a deterministic regex tokenizer, not an LLM call.
Evidence: `app/api/search.py:207-223` (`_expand_terms` — regex tokenizer); `app/retrieval/query.py` — no LLM client import; ARCHITECTURE.md §Query-time pipeline declares LLM expansion as a required stage; spec.md §6 AC-5 requires `expanded_terms` in the response.
Root cause: LLM-based query expansion was deferred from T11 through T15. The `expanded_terms` field returned to clients is populated by a tokenizer, satisfying the schema shape but not the semantic intent.
Impact: Metaphor-aware retrieval (a first-class requirement per spec.md §Retrieval) is non-operational. The `expanded_terms` response field is misleading — it contains tokenized query words, not LLM-expanded metaphor synonyms. Deferred to post-T15 search API task per META_ANALYSIS.
Fix: Wire `claude-haiku-4-5` query expansion in `app/retrieval/query.py::retrieve()` before the embedding call. Confirm a task exists in `docs/tasks.md` for this work; if not, create one.

### ARCH-11 [P3] — `EvidenceBlock.matched_fragments` Partial Citation Contract
Symptom: `EvidenceBlock.matched_fragments` is `list[str]`; spec.md §Retrieval requires matched_fragments to include character offsets and `match_type` label per fragment.
Evidence: `app/retrieval/query.py:35` (`matched_fragments: list[str]`); spec.md §Retrieval: "a list of text spans from the original dream entry that matched the query, with character offsets and a `match_type` label (`literal` / `semantic`)". Note: the grounding layer in `app/llm/grounder.py:125-161` correctly stores `{text, start_offset, end_offset, match_type, verified}` in `DreamTheme.fragments` (JSONB) — the data exists in DB but is stripped to bare strings in the retrieval path.
Root cause: Fragment metadata was not plumbed from the `dream_themes.fragments` JSONB column through the SQL assembly sub-query and into `EvidenceBlock` when `query.py` was built.
Impact: API search responses cannot satisfy spec.md §6 AC-1 citation format. T16 theme responses will also be affected if this is not resolved before the curation surface is built. The `matched_fragments` in `SearchResultItem` are bare strings with no position or type metadata.
Fix: Extend `EvidenceBlock` with per-fragment objects (`{text: str, start_offset: int | None, end_offset: int | None, match_type: str}`); update the SQL fragment assembly sub-query in `_search()` to emit `start_offset`, `end_offset`, `match_type` from the JSONB; update `SearchResultItem.matched_fragments` to `list[FragmentRef]`. Assign FIX-C6 or T16 scope.

### ARCH-12 [P3] — Session Factory Duplicated Across API Routers
Symptom: `app/api/search.py` and `app/api/dreams.py` each independently create their own `AsyncEngine` and `async_sessionmaker` via private `lru_cache` functions.
Evidence: `app/api/search.py:151-163` (private `_get_engine`, `_get_session_factory`, `_get_rag_query_service`); `app/api/dreams.py:166-173` (same pattern, different module). No shared session factory in `app/main.py` or `app/shared/`.
Root cause: No centralized dependency injection or shared DB module was established when the API routers were built.
Impact: When `app/api/themes.py` is added (T16), it will either continue the duplication (three separate connection pools) or require refactoring first. Separate `lru_cache` instances per module mean DB connections are not pooled across routers in any controlled way. The session factory pattern referenced in T17 notes for `app/workers/` has no canonical location to inherit from.
Fix: Create `app/shared/db.py` (or `app/shared/session.py`) exporting `get_engine()` and `get_session_factory()`. All API routers and future worker modules import from there. Strongly recommended as pre-T16 work to avoid a third duplicate.

### ARCH-13 [P2] — `BULK_CONFIRM_TOKEN_TTL_SECONDS` Config Slot Absent Before T16
Symptom: T16 will store bulk-confirm UUID tokens in Redis with a 10-minute TTL (per spec.md §5 AC-6). There is no config slot in `app/shared/config.py` for this TTL value.
Evidence: `app/shared/config.py:1-27` — `Settings` class has no TTL field for bulk-confirm tokens. META_ANALYSIS scope item: "verify Redis client/config is shared and not duplicated; TTL policy consistency".
Root cause: T16 has not been implemented yet, but the established codebase pattern externalizes all tunable constants to `Settings`. Implementing T16 without this slot will require a hardcoded constant or a separate ad-hoc env var.
Impact: If T16 hardcodes the 600-second TTL, it violates the externalization pattern and makes the token expiry window non-configurable without a code change. The token TTL is security-adjacent (bulk-action authorization window). P2 because it is a pre-implementation contract violation risk.
Fix: Add `BULK_CONFIRM_TOKEN_TTL_SECONDS: int = 600` to `Settings` in `app/shared/config.py` as a mandatory pre-T16 step.

### ARCH-14 [P3] — Worker Files `ingest.py` and `index.py` Absent
Symptom: ARCHITECTURE.md §File Layout and §Component Table declare `app/workers/ingest.py` and `app/workers/index.py` as ARQ background job handlers. Only `app/workers/__init__.py` exists. `app/api/dreams.py` uses `InMemorySyncBackend` (in-memory dict, not ARQ).
Evidence: Glob of `app/**/*.py` — no `ingest.py` or `index.py` under `app/workers/`; `app/workers/__init__.py:1` contains only a docstring; `app/api/dreams.py:76-87` (`InMemorySyncBackend` — in-memory storage, not Redis/ARQ).
Root cause: Background worker implementation has been deferred; no task has been assigned for it in Phase 4.
Impact: Real background ingestion/indexing is not operational. T17 notes reference a "shared session factory pattern" that must be consistent with T14/T15 session handling — without worker files, this alignment cannot be assessed before T17 begins. The architecture declares ARQ as the task queue; the actual implementation uses an ephemeral in-memory store.
Fix: Implement `app/workers/ingest.py` and `app/workers/index.py` as part of the first task requiring real background execution. The session factory consolidation from ARCH-12 should precede or accompany this work.

### ARCH-15 [P3] — `docs/adr/` Directory Does Not Exist
Symptom: No ADR directory or governance records exist. IMPLEMENTATION_CONTRACT and ARCHITECTURE.md both declare ADRs as required before index schema changes, runtime tier expansion, or modifications to the contract itself.
Evidence: Bash check — `docs/adr/` directory not found; Glob of `docs/adr/**` returned no results. Also open as ARCH-4 in Cycle 5 report.
Root cause: ADR governance was never bootstrapped; no task was assigned in Phase 1–3.
Impact: Currently low risk (no schema changes or runtime escalations in T16 scope), but the Phase 5 gate requires no P1 open findings. If a schema change or runtime expansion occurs without the ADR process in place, that finding would be automatic P1. The infrastructure for governance is missing.
Fix: Create `docs/adr/` directory. File ADR-001 backfilling the index schema v1 decision before Phase 5 begins. A single documentation commit with no code change is sufficient.

---

## Right-Sizing / Runtime Checks

| Check | Verdict | Note |
|-------|---------|------|
| Solution shape (Workflow) still appropriate | PASS | System remains a bounded pipeline (ingest → segment → analyse → index → retrieve). T16 adds a curation API surface — still Workflow shape. No dynamic tool-selection loop introduced. LLM called at fixed points only. |
| Deterministic-owned areas remain deterministic | PASS | Routing, segmentation heuristics (primary boundary detection), taxonomy CRUD, salience math, annotation versioning — all remain deterministic. `_expand_terms()` in `search.py` is deterministic (regex tokenizer); query expansion LLM path is declared but not yet wired (ARCH-10). No deterministic domain has drifted to LLM. |
| Runtime tier (T1) unchanged / justified | PASS | No shell mutation, no ad-hoc package installs observed in any runtime path. `InMemorySyncBackend` is a stub; workers are not yet live. T1 tier intact. CODE-7 (`host="0.0.0.0"`) is a security config issue, not a runtime-tier escalation. |
| Human approval boundaries still valid | DRIFT | `PATCH /themes/categories/{id}/approve` (taxonomy promotion), `PATCH /dreams/{id}/themes/{theme_id}/confirm`, `PATCH /dreams/{id}/themes/{theme_id}/reject`, and bulk-confirm endpoints are all declared in spec.md and ARCHITECTURE.md but do not yet exist (`app/api/themes.py` absent). Approval boundaries are architecturally correct but not yet enforced in code. Must verify after T16 lands. |
| Minimum viable control surface still proportionate | PASS | Single-user system; auth via API key header; governance level Standard; no over-engineered RBAC. Proportionate to declared governance level. |

---

## Retrieval Architecture Checks

| Check | Verdict | Note |
|-------|---------|------|
| Ingestion / query-time separation (no cross-import) | PASS | `app/retrieval/ingestion.py` does not import `query.py`; `app/retrieval/query.py` does not import `ingestion.py`. Verified by direct inspection. |
| `insufficient_evidence` path defined | PASS | `InsufficientEvidence` dataclass at `app/retrieval/query.py:38-40`; returned on empty query (`query.py:86`) and on zero rows above threshold (`query.py:100-103`); handled in `app/api/search.py:71-76` returning `{"result": "insufficient_evidence", "query": "..."}` with HTTP 200. Path defined in ARCHITECTURE.md §Query-time pipeline and spec.md §Retrieval. |
| Evidence/citation contract defined | DRIFT | `EvidenceBlock` carries `dream_id`, `date`, `chunk_text`, `relevance_score`, `matched_fragments`. `dream_id`, `date`, `chunk_text` are present per ARCHITECTURE.md. However spec.md §Retrieval citation format requires `matched_fragments` with character offsets and `match_type` per fragment — `matched_fragments: list[str]` only. See ARCH-11. |
| Freshness / max-index-age policy (24h, health endpoint) | PASS | `MAX_INDEX_AGE_HOURS: int = 24` in `Settings` (`config.py:20`); `app/api/health.py:31-38` checks staleness against this value and returns HTTP 503 with `status="degraded"` when stale. Policy documented and enforced. |
| Index schema versioning (v1) | PASS | `INDEX_SCHEMA_VERSION = "v1"` declared at `app/retrieval/ingestion.py:21`; set as span attribute on every `index_dream` call. ARCHITECTURE.md §Index Strategy and IMPLEMENTATION_CONTRACT §Index Schema Versioning both declare v1 as current. No ADR required yet (no schema change proposed). |
| Retrieval observability expectations | PASS | `retrieval_ms` set as span attribute on the outer `rag_query.retrieve` span (`query.py:98`); `insufficient_evidence` emitted via `logger.info` with reason context at `query.py:87` and `query.py:102`; sub-spans present for embed query (`rag_query.embed_query`) and DB search (`db.query.rag_query.search`). Meets v1 observability expectations per ARCHITECTURE.md §Observability. |

---

## Doc Patches Needed

| File | Section | Change |
|------|---------|--------|
| `docs/ARCHITECTURE.md` | §File Layout — `app/workers/` | Mark `ingest.py` and `index.py` as "(planned — not yet implemented)" or add a note that these are pending until the background worker task is assigned |
| `docs/ARCHITECTURE.md` | §Component Table — `app/api/themes.py` | Add "(T16 deliverable — not yet implemented)" note to the `Theme API router` row to avoid reviewer confusion |
| `docs/audit/META_ANALYSIS.md` | §Open Findings | Mark ARCH-9 as CLOSED — migrations 005 and 006 are now correctly listed in ARCHITECTURE.md §File Layout |
| `docs/audit/META_ANALYSIS.md` | §Open Findings | Mark CODE-22 as CLOSED/SUPERSEDED — superseded by CODE-30 (DB guard added); no ambiguity should remain |
| `app/shared/config.py` | `Settings` class | Add `BULK_CONFIRM_TOKEN_TTL_SECONDS: int = 600` as a mandatory pre-T16 step (ARCH-13) |
| `docs/adr/` | (new directory) | Create directory; file ADR-001 backfilling index schema v1 decision before Phase 5 gate (ARCH-15) |

---
_ARCH_REPORT.md written. Run PROMPT_2_CODE.md._
