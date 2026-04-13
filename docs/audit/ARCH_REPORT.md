---
# ARCH_REPORT — Cycle 5
_Date: 2026-04-13_

---

## Component Verdicts

| Component | Verdict | Note |
|-----------|---------|------|
| `app/api/health.py` | PASS | Thin handler; delegates to `_fetch_index_last_updated()`; 503 on staleness wired; OTel span present; public-route comment cites OBS-3 correctly |
| `app/shared/tracing.py` | DRIFT | Dual-path singleton persists: `_get_provider()` uses mutable global + `trace.set_tracer_provider()`; `get_tracer()` uses `lru_cache`. Not thread-safe under concurrent initialization — CODE-10 unresolved; resolves T13 |
| `app/retrieval/ingestion.py` | PASS | Layer boundary respected; no cross-import from `query.py`; OTel spans on `index_dream`, `load_dream`, `embed`, `upsert_chunk`. `INDEX_SCHEMA_VERSION = "v1"` declared. CODE-24 (no per-HTTP-request span inside `asyncio.to_thread`) and CODE-32 (duplicated `OpenAIEmbeddingClient`) remain open |
| `app/retrieval/query.py` | DRIFT | Layer boundary respected; no cross-import from `ingestion.py`. Query expansion (LLM call, ARCH-10) absent. `EvidenceBlock.matched_fragments` is `list[str]`; spec requires character offsets + `match_type` per fragment (ARCH-11). CODE-32 (`OpenAIEmbeddingClient` duplicated) unresolved |
| `app/services/analysis.py` | DRIFT | Business logic only; no HTTP imports. DB calls not individually OTel-spanned below the parent `analysis.analyse_dream` span — CODE-15 unresolved; resolves T13 |
| `app/services/taxonomy.py` | DRIFT | Business logic only; correct layer. DB calls inside `_transition_category` share a single parent span with no per-call child spans — CODE-15 unresolved; resolves T13 |
| `app/services/segmentation.py` | DRIFT | `_segment_with_llm_fallback` raises `NotImplementedError` with stale "T08" comment; T08 was completed cycles ago — CODE-13 unresolved |
| `app/main.py` | DRIFT | `host="0.0.0.0"` unconditional; should default to `127.0.0.1` for non-production `ENV` — CODE-7 unresolved |
| `app/api/dreams.py` | N/A | File absent; not yet implemented |
| `app/workers/ingest.py`, `app/workers/index.py` | N/A | Worker files absent; only `__init__.py` present. No conflicting stubs found that would constrain T14 |
| `app/retrieval/types.py` | N/A | File absent; CODE-32 shared-client refactor deferred. No cross-import violation yet, but diverging implementations will compound when search API and workers are wired at T14/T15 |
| `app/llm/theme_extractor.py` | DRIFT | System prompt carries framing ("draft suggestion, not a fact") but `ThemeAssignment` response model has no `interpretation_note` literal field — ARCH-6 unresolved |
| `app/llm/grounder.py` | DRIFT | Same framing gap; `GroundedTheme` model has no `interpretation_note` literal field — ARCH-6 unresolved |
| `alembic/versions/` | DRIFT | Migrations 005 and 006 present on disk but absent from `docs/ARCHITECTURE.md §File Layout` — ARCH-9 unresolved |
| `docs/adr/` | VIOLATION | Directory absent; no ADR governance records exist — ARCH-4 unresolved |

---

## Contract Compliance

| Rule | Verdict | Note |
|------|---------|------|
| SQL Safety — parameterized queries only | PASS | All `text()` calls use named parameters; no string interpolation found in scoped files |
| Async Redis — `redis.asyncio` only | N/A | Redis not yet wired; ARQ worker scaffolding absent |
| Authorization — every route enforces auth; public routes documented | PASS (partial) | `health.py` correctly documents unauthenticated access citing OBS-3. Other routers not yet implemented; no bypass introduced |
| PII Policy — no sensitive data in logs, spans, or errors | PASS | No `raw_text`, `chunk_text`, or `fragment_text` found in span attributes or log `extra` dicts in scoped files. `theme_extractor.py` passes `raw_text` to LLM prompt (not a log/span); `justification` field may contain dream content but is not written to spans |
| Shared Tracing Module — single `get_tracer()`, no inline noop | PASS | All scoped modules import `get_tracer` from `app/shared/tracing`; no inline noop implementations found |
| CI Gate | PASS | Baseline 48 pass, 12 skip, 0 fail |
| OBS-1 — every external call wrapped in a span | DRIFT | DB calls in `analysis.py` and `taxonomy.py` lack per-call child spans (CODE-15). OpenAI HTTP call in `ingestion.py` inside `asyncio.to_thread` lacks a per-request HTTP span (CODE-24) |
| OBS-2 — success/error counters + latency histograms; RAG `insufficient_evidence` counter | DRIFT | `retrieval_ms` span attribute present in `query.py`. `insufficient_evidence` emitted as `logger.info` only — no labeled counter. Prometheus metrics not yet wired (v1 scope) |
| OBS-3 — health endpoint contract | PASS | Returns `{"status": "ok"|"degraded", "index_last_updated": ISO8601|null}`; HTTP 503 on staleness; no auth; OTel span present |
| Dream Content Isolation | PASS | No classified PII fields found in span attributes or log `extra` dicts |
| LLM Output Framing | DRIFT | Framing present in LLM system prompt strings; absent as structural `interpretation_note` literal field in Pydantic response models — ARCH-6 open |
| Annotation Versioning | PASS | `AnnotationVersion` written before every mutation in `analysis.py` and `taxonomy.py`; append-only; no DELETE/UPDATE against `annotation_versions` found |
| Taxonomy Mutation Gate | PASS | `approve_category` and `deprecate_category` require explicit API calls; no automated LLM path calls these directly |
| Idempotent Workers | PASS (partial) | `_upsert_chunk` uses `on_conflict_do_nothing` on `(dream_id, chunk_index)`; worker job handlers not yet implemented; no conflicting code found |
| Ingestion/Query Separation | PASS | No cross-imports between `app/retrieval/ingestion.py` and `app/retrieval/query.py` confirmed |
| Index Schema Versioning | PASS | `INDEX_SCHEMA_VERSION = "v1"` in `ingestion.py:21`; documented in ARCHITECTURE.md |
| Max Index Age (24h, health endpoint) | PASS | `MAX_INDEX_AGE_HOURS` from settings; staleness check and HTTP 503 wired in `health.py:31–34` |
| P2 Age Cap — CODE-2, CODE-5, CODE-11, CODE-12 (3–4 cycles) | VIOLATION | Four P2 findings exceed the 3-cycle age cap per IMPLEMENTATION_CONTRACT §P2 Age Cap. Must be closed, escalated to P1, or formally deferred before Phase 4 |

---

## ADR Compliance

| ADR | Verdict | Note |
|-----|---------|------|
| `docs/adr/` directory | VIOLATION | Directory absent; no ADRs have been filed. IMPLEMENTATION_CONTRACT states changes to the contract require an ADR; ARCHITECTURE.md lists `docs/adr/` as a canonical authority source. Index schema v1 protection and contract immutability both depend on ADR governance (ARCH-4) |

---

## Architecture Findings

### ARCH-4 [P3] — No ADR directory or governance records
Symptom: `docs/adr/` directory absent; no ADR files exist.
Evidence: `docs/adr/` (absent — confirmed by glob search)
Root cause: ADR governance was never bootstrapped; no task assigned.
Impact: Cannot verify any architecture-change decisions have been formally recorded. Index schema versioning, contract immutability, and any future runtime-tier changes all require ADRs, with no place to file them. Entering Phase 4 (API layer, auth, worker wiring) without ADR governance increases risk of undocumented boundary changes.
Fix: Create `docs/adr/` directory; file ADR-001 backfilling index schema v1 decision. Can be a single `docs` commit in Cycle 5 without a dedicated task slot.
Status: Open — carry-forward; no assigned task.

### ARCH-6 [P2] — `interpretation_note` not structurally enforced in response models
Symptom: LLM output framing exists in system prompt strings only; not enforced as a Pydantic literal field in `ThemeAssignment` or `GroundedTheme`.
Evidence: `app/llm/theme_extractor.py:58–64` (system prompt framing only); `app/llm/grounder.py:64–68` (system prompt framing only); no `interpretation_note` field in either response model.
Root cause: Framing rule from IMPLEMENTATION_CONTRACT §LLM Output Framing was applied at the prompt level, not the schema level.
Impact: API responses downstream of theme extraction and grounding may not carry the framing requirement through to the client. Contract requires either an `interpretation_note` field or schema-level enforcement.
Fix: Add `interpretation_note: Literal["These are computational patterns, not authoritative interpretations."]` to `ThemeAssignment` and `GroundedTheme` Pydantic models, or enforce at the API response schema level.
Status: Open — resolves at T15/T16.

### ARCH-9 [P3] — ARCHITECTURE.md §File Layout migration listing incomplete
Symptom: `docs/ARCHITECTURE.md §File Layout` lists migrations through `004_fix_status_ck.py`; migrations `005_add_fragments_default.py` and `006_add_hnsw_index.py` are absent.
Evidence: `docs/ARCHITECTURE.md:366–370`; `alembic/versions/005_add_fragments_default.py` and `alembic/versions/006_add_hnsw_index.py` present on disk.
Root cause: Doc not updated when T10/T11 added migrations 005 and 006.
Impact: Low — doc drift only; does not affect runtime behavior. Misleading to reviewers.
Fix: Update `docs/ARCHITECTURE.md §File Layout` to add both missing migration entries.
Status: Open — carry-forward.

### ARCH-10 [P3] — Query expansion absent from `query.py`
Symptom: `RagQueryService.retrieve()` embeds and searches without any prior LLM-based query expansion step.
Evidence: `app/retrieval/query.py:102–137` — no LLM client import or expansion call present.
Root cause: Query expansion deferred from T11; assigned to T15 (search API).
Impact: ARCHITECTURE.md §RAG query-time pipeline "query analyze" step unimplemented; spec.md §6 AC-5 (`expanded_terms[]` in response) not satisfied. Current retrieval is embedding-only without metaphor-aware expansion.
Fix: Wire `claude-haiku-4-5` query expansion call in `retrieve()` before `_embed_query()`.
Status: Open — resolves at T15.

### ARCH-11 [P3] — `EvidenceBlock.matched_fragments` partial citation contract
Symptom: `EvidenceBlock.matched_fragments` is `list[str]`; spec §Retrieval citation format requires character offsets and `match_type` label per fragment.
Evidence: `app/retrieval/query.py:32–38` (`EvidenceBlock` dataclass).
Root cause: Fragment metadata (offsets, `match_type`) not included when `EvidenceBlock` was designed at T11.
Impact: Spec §6 AC-1 and §Retrieval citation format not fully satisfied. Will require a schema change to `EvidenceBlock` before `app/api/search.py` (T15) can return a compliant response.
Fix: Add `match_type: str`, `start_offset: int | None`, `end_offset: int | None` fields to `EvidenceBlock`; update SQL fragment assembly and `_coerce_fragments` accordingly. Must resolve before T15.
Status: Open — must resolve before T15.

### NEW-ARCH-1 [P2] — `OpenAIEmbeddingClient` duplicated with diverging implementations; `app/retrieval/types.py` absent
Symptom: `OpenAIEmbeddingClient` independently implemented in both `app/retrieval/ingestion.py:51–80` and `app/retrieval/query.py:55–84` with diverging Protocol signatures, error types, and log fields.
Evidence: `app/retrieval/ingestion.py:32–80` (`EmbeddingClient` Protocol with `dream_id` kwarg; `EmbeddingServiceError`); `app/retrieval/query.py:23–66` (`EmbeddingClient` Protocol without `dream_id`; `QueryEmbeddingError`).
Root cause: Shared client deferred as CODE-32; `app/retrieval/types.py` proposed but never created.
Impact: When T14/T15 wire the search API and background workers, both codepaths call different implementations of the same service boundary. Divergence compounds; a correctness or security fix to one implementation may not be applied to the other. Testing both independently doubles the surface.
Fix: Create `app/retrieval/types.py` with a unified `OpenAIEmbeddingClient` and shared `EmbeddingClient` Protocol (reconcile `dream_id` kwarg — recommend keeping it for tracing). Both `ingestion.py` and `query.py` import from `types.py`. Must ship with T13 or as FIX-C5-1 before T14.
Status: Open — P2 age cap applies; deferral past T14 not acceptable.

### NEW-ARCH-2 [P2] — P2 age cap breached: CODE-2, CODE-5, CODE-11, CODE-12
Symptom: Four P2 findings have been open 3–4 consecutive review cycles with no assigned fix window.
Evidence: META_ANALYSIS.md open findings — CODE-2 (4 cycles), CODE-5 (4 cycles), CODE-11 (3 cycles), CODE-12 (3 cycles).
Root cause: No concrete FIX task assigned in prior cycles; carry-forward pattern repeated without triage.
Impact: IMPLEMENTATION_CONTRACT §P2 Age Cap requires action. CODE-11 (spurious `skipif` guards) and CODE-12 (`StubGrounder verified=True` hardcoded) directly compromise integration test validity.
Fix: Group as FIX-C5-1 before T13 closes. CODE-2: one parametrised `HttpError` re-raise test in `test_gdocs_client.py`. CODE-5: add `fragments IS NOT NULL` + CHECK constraint assertions in `test_migrations.py`. CODE-11: remove three `skipif` decorators in `test_analysis.py`. CODE-12: add `verified=False` path to `StubGrounder` + one assertion. All are isolated; a single commit suffices.
Status: MUST assign and close before Phase 4 begins.

---

## Right-Sizing / Runtime Checks

| Check | Verdict | Note |
|-------|---------|------|
| Solution shape (Workflow) still appropriate | PASS | Bounded ingestion and query pipelines; LLM called at fixed points; no dynamic tool-selection loop introduced in scoped code |
| Deterministic-owned areas remain deterministic | PASS | Segmentation (primary), taxonomy CRUD, calculations, routing — all remain deterministic; no LLM drift into governed areas detected |
| Runtime tier (T1) unchanged / justified | PASS | No shell mutation, no ad-hoc package installs in scoped code. `host="0.0.0.0"` (CODE-7) is a security config issue, not a runtime-tier escalation |
| Human approval boundaries still valid | PASS | `approve_category` and `deprecate_category` require explicit API calls; no automated promotion path in `taxonomy.py`; workers not wired; no bypass path found |
| Minimum viable control surface still proportionate | PASS | All taxonomy mutations gated; annotation versioning enforced; no new uncontrolled governance surface added |

---

## Retrieval Architecture Checks

| Check | Verdict | Note |
|-------|---------|------|
| Ingestion / query-time separation (no cross-import) | PASS | Confirmed: no cross-imports between `app/retrieval/ingestion.py` and `app/retrieval/query.py` |
| `insufficient_evidence` path defined | PASS | `InsufficientEvidence` dataclass in `query.py:41–43`; returned on empty query and on zero rows above threshold; defined in ARCHITECTURE.md and spec.md |
| Evidence/citation contract defined | DRIFT | `EvidenceBlock` has `dream_id`, `date`, `chunk_text`, `relevance_score`, `matched_fragments`. `matched_fragments` is `list[str]`; spec requires `match_type` + character offsets per fragment — ARCH-11 |
| Freshness / max-index-age policy (24h, health endpoint) | PASS | `MAX_INDEX_AGE_HOURS` from settings; staleness check and HTTP 503 in `health.py:31–34`; policy documented in ARCHITECTURE.md §Index Strategy |
| Index schema versioning (v1) | PASS | `INDEX_SCHEMA_VERSION = "v1"` in `ingestion.py:21`; ARCHITECTURE.md documents v1 and ADR requirement for changes |
| Retrieval observability expectations | DRIFT | `retrieval_ms` set as span attribute in `query.py`. `insufficient_evidence` emitted as `logger.info` only — no OBS-2 labeled counter. OpenAI HTTP call in `ingestion.py` inside `asyncio.to_thread` has no per-request HTTP child span (CODE-24); OTel context propagation into `asyncio.to_thread` requires architectural guidance at T13 |

---

## Doc Patches Needed

| File | Section | Change |
|------|---------|--------|
| `docs/ARCHITECTURE.md` | §File Layout — alembic/versions | Add `005_add_fragments_default.py` and `006_add_hnsw_index.py` to migration listing |
| `docs/adr/` | (new directory) | Create directory; file ADR-001 backfilling index schema v1 decision |
| `docs/ARCHITECTURE.md` | §Component Table | Add `app/retrieval/types.py` entry once FIX-C5-1 / T13 creates the file |

---
_ARCH_REPORT.md written. Run PROMPT_2_CODE.md._
