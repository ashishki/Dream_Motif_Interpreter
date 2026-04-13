---
# REVIEW_REPORT — Cycle 3
_Date: 2026-04-13 · Scope: T10 (partial) — RAG Ingestion Pipeline_

## Executive Summary

- **Stop-Ship: Yes** — Two P1 findings block T10 from being marked DONE. `_token_count()` uses word-count instead of tiktoken (CODE-20), violating the 512-token boundary contract. `OpenAIEmbeddingClient.embed()` has no HTTP error handling (CODE-19), causing unhandled `urllib.error.HTTPError` propagation. Both must be resolved before any real corpus embeddings are generated.
- Phase 2 (T01–T09) is fully complete. Phase 3 is in progress: `app/retrieval/ingestion.py` and associated tests are written but T10 is not yet closed.
- Baseline is 35 passing, 6 skipped (up from 32/4 at Cycle 2 close). Ruff is clean.
- `EMBEDDING_MODEL = "text-embedding-ada-002"` (CODE-21) contradicts the declared `text-embedding-3-small` in ARCHITECTURE.md. Any real embeddings generated before the fix will require a full re-index.
- Five new P2 findings this cycle (CODE-21–CODE-25). Carry-forward P2 pool (CODE-2/3/4/5/6) has been open for three cycles without resolution; concrete fix windows must now be assigned.
- T11 is double-blocked: `app/retrieval/query.py` is absent (ARCH-1) and HNSW index migration `006_add_hnsw_index.py` is absent (ARCH-2). Both must land before T11 starts.
- CODE-17 (stale CODEX_PROMPT.md baseline) is resolved by this Cycle 3 consolidation.

---

## P0 Issues

_None this cycle._

---

## P1 Issues

### CODE-19 [P1] — `OpenAIEmbeddingClient.embed()` Has No HTTP Error Handling

**Symptom:** `_send_embedding_request()` calls `urllib.request.urlopen()` with no `try/except`. Any HTTP error response (401 Unauthorized, 429 Rate Limited, 500 Server Error) raises an unhandled `urllib.error.HTTPError` that propagates raw through `asyncio.to_thread` into `_embed_chunks()` and then into `index_dream()`.

**Evidence:** `app/retrieval/ingestion.py:64–66` (urlopen call site); `app/retrieval/ingestion.py:58` (`_send_embedding_request` function definition).

**Root Cause:** No error-handling wrapper was added around the HTTP call during T10 partial implementation. No `EmbeddingServiceError` typed exception class is defined; callers cannot distinguish a transient 429 from a permanent 401.

**Impact:** Any OpenAI API failure during ingestion surfaces as an unhandled exception with no `dream_id` context in logs, no HTTP status code visibility, and no typed error shape for callers to catch. In the ARQ worker context, this will cause the worker to crash without producing a meaningful job failure record. Blocks T10 DONE gate.

**Fix:** Wrap `urlopen` in `try/except urllib.error.HTTPError`. Log `e.code` (HTTP status) and `dream_id` before raising. Define typed `EmbeddingServiceError(status_code: int, dream_id: str)` in `app/retrieval/ingestion.py` or a shared exceptions module.

**Verify:** `tests/unit/test_rag_ingestion.py::test_embed_raises_on_429`, `::test_embed_raises_on_500`, `::test_embed_logs_dream_id_on_error` — all must pass.

---

### CODE-20 [P1] — `_token_count()` Uses Whitespace Split, Not Actual Token Count — 512-Token Boundary Contract Violated

**Symptom:** `_token_count(text)` at `app/retrieval/ingestion.py:238–239` returns `len(text.split())` — a word count, not a token count. ARCHITECTURE.md §Index Strategy and IMPLEMENTATION_CONTRACT.md specify a 512-token boundary using an actual tokenizer (tiktoken `cl100k_base`). Word count is approximately 0.75× the true token count for English prose, so chunks can reach ~683 real tokens when the implementation believes they are at the 512-token limit.

**Evidence:** `app/retrieval/ingestion.py:238–239`; constant `MAX_CHUNK_TOKENS = 512` at `app/retrieval/ingestion.py:21`.

**Root Cause:** Tokenizer dependency was not added; a word-count proxy was used as an approximation during T10 partial implementation.

**Impact:** Chunks silently exceed the 512-token model context window by ~33%. Embeddings for oversized chunks are truncated by the API, producing incorrect semantic representations without any error or warning. T10-AC-3 (`test_chunking_boundary`) cannot catch this violation because it uses the same `_token_count` function. Blocks T10 DONE gate.

**Fix:** Replace `_token_count` with `len(tiktoken.get_encoding("cl100k_base").encode(text))`. Add `tiktoken` to `requirements.txt`. Cache encoder at module level. Confirm `CHUNK_OVERLAP_TOKENS` is applied in real token units. Update `test_chunking_boundary` to use input with a known real token count.

**Verify:** `tests/unit/test_rag_ingestion.py::test_token_count_uses_tiktoken`, `::test_chunks_do_not_exceed_512_real_tokens`, `::test_tiktoken_in_requirements` — all must pass.

---

## P2 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-21 | `EMBEDDING_MODEL = "text-embedding-ada-002"` contradicts ARCHITECTURE.md §Index Strategy mandate of `text-embedding-3-small`. Any embeddings before fix require full re-index. | `app/retrieval/ingestion.py:19` | Open — new Cycle 3; fix before T10 DONE gate |
| CODE-22 | Integration RAG tests skip only on missing `OPENAI_API_KEY`; DB availability not guarded. Tests can error instead of skipping in CI without a DB. | `tests/integration/test_rag_ingestion.py:85–88, 117–120` | Open — new Cycle 3 |
| CODE-23 | `test_chunking_boundary` missing 0-based `chunk_index` assertions for produced chunks. AC-3 contract not fully verified. | `tests/unit/test_rag_ingestion.py:13–27` | Open — new Cycle 3; fix before T10 DONE gate |
| CODE-24 | No per-request HTTP span on OpenAI call; OTel context not propagated into `asyncio.to_thread`. OBS-2 partially unmet. | `app/retrieval/ingestion.py:64–66, 122–126` | Open — new Cycle 3; resolves at T13 |
| CODE-25 | AC-4 cross-import test uses relative path `"app/retrieval/ingestion.py"` — brittle in non-root CWD. Use `Path(__file__).resolve().parents[2] / "app/retrieval/ingestion.py"`. | `tests/unit/test_rag_ingestion.py:31` | Open — new Cycle 3; fix before T10 DONE gate |
| CODE-2 | Non-auth `HttpError` (e.g. 500) branch in `GDocsClient.fetch_document()` untested — only 401/403 paths parametrised. | `tests/unit/test_gdocs_client.py:39–49` | Open — carry-forward Cycle 1/2/3 |
| CODE-3 | `app/api/health.py` stub `index_last_updated=None` has no `# TODO(T13):` comment. | `app/api/health.py:18` | Open — carry-forward Cycle 1/2/3; resolves at T13 |
| CODE-4 | Config fail-fast test covers only `DATABASE_URL`; other 8 required secrets untested; `tests/unit/test_config.py` absent. | `tests/unit/test_config.py` (absent) | Open — carry-forward Cycle 1/2/3; resolve before T14 |
| CODE-5 | Migration test does not assert `dream_themes.fragments IS NOT NULL` or CHECK constraint domain. | `tests/integration/test_migrations.py:156–175` | Open — carry-forward Cycle 1/2/3 |
| CODE-6 | `test_health_index_last_updated_is_none` has no `# TODO(T13): update to assert ISO8601 timestamp` comment. | `tests/integration/test_health.py:38–49` | Open — carry-forward Cycle 1/2/3; resolves at T13 |
| CODE-11 | Three integration tests in `test_analysis.py` gated on `ANTHROPIC_API_KEY` even though stub doubles are used inside them. | `tests/integration/test_analysis.py:167–170, 213–216, 250–253` | Open — new Cycle 2; resolve in next available fix window |
| CODE-12 | `StubGrounder` hardcodes `verified=True` for all fragments; second fragment not tested for `verified=False`. | `tests/integration/test_analysis.py:97–131` | Open — new Cycle 2; resolve in next available fix window |
| CODE-14 | `docs/retrieval_eval.md` §Evaluation Dataset placeholder rows; §Baseline Metrics all empty. File created Cycle 3 (zero-corpus row acceptable for T10 gate); dataset must be populated before T12. | `docs/retrieval_eval.md` | Partially addressed Cycle 3; resolves at T12 |
| CODE-15 | DB calls in `analysis.py` and `taxonomy.py` not individually spanned (OBS-1 drift). | `app/services/analysis.py:33–125`, `app/services/taxonomy.py:80–121` | Open — new Cycle 2; resolves at T13 |
| CODE-18 | `docs/retrieval_eval.md §Evaluation Dataset` uses placeholder rows. T12-AC-1 requires 10 real queries covering all four query types. | `docs/retrieval_eval.md` | Open — new Cycle 3; resolves at T12 |
| ARCH-1 | `app/retrieval/query.py` absent — T11 blocked; T10-AC-4 cross-import test cannot fully validate query-side. | `app/retrieval/query.py` (absent) | Open — expected gap; resolves at T10 completion |
| ARCH-2 | No HNSW index on `dream_chunks.embedding`; `006_add_hnsw_index.py` absent. T11 hard dependency for p95 < 3 s latency. | `alembic/versions/` | Open — carry-forward Cycle 1/2/3; urgency high; blocks T11 start |
| ARCH-6 | `interpretation_note` field not enforced at API response Pydantic model level; prompt-only framing insufficient. | `app/llm/grounder.py:67`, `app/llm/theme_extractor.py:63` | Open — new Cycle 2; resolves at T15/T16 |

---

## P3 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-7 | `app/main.py` binds `host="0.0.0.0"` unconditionally; should default to `127.0.0.1` for non-production ENV. | `app/main.py` | Open — carry-forward Cycle 1/2/3 |
| CODE-10 | `app/shared/tracing.py` dual-path singleton: `_get_provider()` mutable global vs. `get_tracer()` `lru_cache`. Inconsistent thread-safety semantics. | `app/shared/tracing.py` | Open — carry-forward Cycle 1/2/3; resolves at T13 |
| CODE-13 | `_segment_with_llm_fallback` raises `NotImplementedError` referencing stale "T08" label (now complete). No LLM fallback path test. | `app/services/segmentation.py:214–222` | Open — new Cycle 2 |
| CODE-16 | `003_seed_categories.py` seeds with `status='active'` with no governance exception comment explaining bootstrap. | `alembic/versions/003_seed_categories.py:46` | Open — new Cycle 2 |

---

## Carry-Forward Status

| ID | Sev | Description | Status | Change |
|----|-----|-------------|--------|--------|
| CODE-1 | P2 | `dream_themes.status` CHECK constraint absent. | **Closed** | FIX-1 applied Cycle 1; migration 004 confirmed. No change. |
| CODE-2 | P2 | Non-auth HttpError branch in GDocsClient untested. | Open | No change — 3rd cycle carry-forward. Assign to next available fix window. |
| CODE-3 | P2 | `health.py` `index_last_updated=None` missing TODO comment. | Open | No change — resolves at T13. |
| CODE-4 | P2 | `tests/unit/test_config.py` absent; 8 secrets untested. | Open | No change — resolve before T14. |
| CODE-5 | P2 | Migration test missing fragments IS NOT NULL and CHECK domain assertions. | Open | No change — 3rd cycle carry-forward. |
| CODE-6 | P2 | Health test missing TODO comment. | Open | No change — resolves at T13. |
| CODE-7 | P3 | `app/main.py` binds `host="0.0.0.0"` unconditionally. | Open | No change — 3rd cycle carry-forward. |
| CODE-8 | P2 | `dream_themes.fragments` missing server_default in migration 001. | Partially Closed | Migration 005 applied; model-level `server_default` confirmed (ARCH_REPORT PASS); migration test assertion (CODE-5) still absent. No new change this cycle. |
| CODE-9 | P3 | `dream_themes` missing `deprecated` boolean column. | **Closed** | FIX-2 applied Cycle 1; migration 002 confirmed. No change. |
| CODE-10 | P3 | `tracing.py` dual-path singleton. | Open | No change — resolves at T13. |
| CODE-11 | P2 | Stub-based integration tests gated on `ANTHROPIC_API_KEY`. | Open | No change since Cycle 2. |
| CODE-12 | P2 | `StubGrounder.verified=True` hardcoded. | Open | No change since Cycle 2. |
| CODE-13 | P3 | Stale `NotImplementedError` referencing T08 in segmentation.py. | Open | No change since Cycle 2. |
| CODE-14 | P2 | `retrieval_eval.md` placeholder rows. | Partially addressed | File created Cycle 3; zero-corpus row present; placeholders remain. |
| CODE-15 | P2 | DB calls not individually spanned in analysis.py and taxonomy.py. | Open | No change — resolves at T13. |
| CODE-16 | P3 | Seed migration missing governance exception comment. | Open | No change since Cycle 2. |
| CODE-17 | P2 | CODEX_PROMPT.md baseline and Next Task stale. | **Resolved** | Resolved by Cycle 3 consolidation — baseline updated to 35/6; Next Task updated to FIX-C3-1 + FIX-C3-2. |
| ARCH-2 | P2 | HNSW index migration absent — T11 hard dependency. | Open | No change — urgency elevated; T11 hard blocker. |
| ARCH-6 | P2 | `interpretation_note` not enforced in Pydantic models. | Open | No change since Cycle 2; resolves at T15/T16. |

---

## Stop-Ship Decision

**Yes.**

Two P1 findings block the T10 DONE gate:

1. **CODE-19** — Raw HTTP errors from the OpenAI embedding API are unhandled. Any network-level failure (including expected 429 rate limiting) will crash the ingestion pipeline with no logging, no typed error shape, and no `dream_id` context. This must be fixed before generating any real corpus embeddings.

2. **CODE-20** — The 512-token chunk boundary is computed using word count instead of real tokens. Chunks can silently exceed the model context window by ~33%, producing truncated or degraded embeddings with no error. This violates a named contract in ARCHITECTURE.md and IMPLEMENTATION_CONTRACT.md.

**CODE-21** (wrong embedding model constant) must also be fixed before any corpus entries are indexed, or a full re-index will be required.

T10 must not be marked DONE until CODE-19 and CODE-20 are resolved and all verification tests pass. T11 must not begin until ARCH-2 (HNSW migration `006_add_hnsw_index.py`) is also resolved.
---
