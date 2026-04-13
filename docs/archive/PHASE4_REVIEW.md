---
# REVIEW_REPORT — Cycle 4
_Date: 2026-04-13 · Scope: T11 (RAG Query Pipeline)_

## Executive Summary

- **Stop-Ship: No** — one P1 finding (CODE-26) requires a fix before T12 can be marked DONE; T12 may start but must not close until CODE-26 is resolved. No P0 issues.
- T11 delivered `app/retrieval/query.py` with hybrid search (pgvector cosine + FTS RRF), `InsufficientEvidence` sentinel (dataclass), and `MAX_INDEX_AGE_HOURS` health degradation — all T11 ACs verified PASS by ARCH review.
- ARCH-2 (HNSW index migration) resolved; `alembic/versions/006_add_hnsw_index.py` confirmed present with correct `autocommit_block()` pattern for `CREATE INDEX CONCURRENTLY`.
- ARCH-1 (query.py absent) closed. ARCH-1 and ARCH-2 are no longer blockers.
- Baseline: **42 passing, 10 skipped** — net +1 pass, +4 skip from Cycle 3 close (41/6). No regressions.
- New CODE findings: CODE-26 (P1, embedding HTTP errors unhandled in query.py), CODE-27 (P2, OBS-2 RAG violation — `retrieval_ms` and `insufficient_evidence` counter absent), CODE-28 (P2, CODEX_PROMPT.md stale), CODE-29 (P2, EVIDENCE_INDEX stale), CODE-30 (P2, DB guard missing in integration RAG tests), CODE-31 (P2, empty-query unit test missing), CODE-32 (P2, duplicate embedding client).
- New ARCH findings: ARCH-7 (P3, health.py T13 handoff comment absent), ARCH-8 (P2, OBS-2 RAG violation — same root as CODE-27), ARCH-9 (P3, ARCHITECTURE.md migration listing drift), ARCH-10 (P3, query expansion not wired), ARCH-11 (P3, EvidenceBlock citation contract partial).
- Aging carry-forwards: CODE-2, CODE-5, CODE-11, CODE-12 have been open 2–3 cycles with no assigned fix window; must be assigned before Phase 4 begins.

---

## P0 Issues

_None._

---

## P1 Issues

### P1-1 — CODE-26: `query.py` Embedding HTTP Errors Unhandled; No `QueryEmbeddingError`

**Symptom:** `app/retrieval/query.py` embeds the user query via `_send_embedding_request()` but has no `urllib.error` import, no `try/except` around `urlopen`, and no typed exception class analogous to `EmbeddingServiceError` in `ingestion.py`. An HTTP 429 or 500 from the OpenAI embeddings endpoint propagates as a raw `urllib.error.HTTPError` to the caller.

**Evidence:**
- `app/retrieval/query.py:9` — no `from urllib import error` import
- `app/retrieval/query.py:256–258` — `urlopen` call with no `try/except`
- `app/retrieval/query.py:63` — `await asyncio.to_thread(...)` call has no exception wrapping

**Root Cause:** T11 implemented the embedding request in `query.py` following the same structural pattern as `ingestion.py`, but did not port the error-handling fix applied in FIX-C3-1 (CODE-19) to `ingestion.py`.

**Impact:** P1 — any transient 429 or 500 from the OpenAI endpoint during retrieval causes an unhandled exception at the service boundary, producing a 500 to the API caller with no structured error context. Mirrors CODE-19 which was Stop-Ship in Cycle 3.

**Fix:** Add `from urllib import error` import. Wrap `urlopen` call in `_send_embedding_request()` with `try/except urllib.error.HTTPError`. Define typed `QueryEmbeddingError(status_code, query_length)` — log `status_code` and `query_length` (NOT query text, per PII policy) before raising. Add unit tests for 429 and 500 responses.

**Verify:** `tests/unit/test_rag_query.py::test_query_embed_raises_on_429` and `test_query_embed_raises_on_500` pass; raw `urllib.error.HTTPError` cannot be observed at caller boundary.

---

## P2 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-27 | `query.py` missing `retrieval_ms` span attribute and `insufficient_evidence` structured log counter — OBS-2 RAG violation. **RAG P2 age cap: 1 cycle. Must resolve in Cycle 5.** | `app/retrieval/query.py:84–110` | Open — new Cycle 4 |
| CODE-28 | `CODEX_PROMPT.md` stale after T11: baseline shows 41/6, Next Task still T11, version still v1.4. | `docs/CODEX_PROMPT.md:12,32` | Open — new Cycle 4; resolved by this consolidation |
| CODE-29 | `EVIDENCE_INDEX.md` EV-002/EV-003 still Pending after T10/T11; IMPLEMENTATION_JOURNAL T11 entry absent. | `docs/EVIDENCE_INDEX.md:20–21` | Open — new Cycle 4 |
| CODE-30 | Integration RAG tests skip only on missing `OPENAI_API_KEY`; DB availability not guarded. Carry-forward of CODE-22. | `tests/integration/test_rag_ingestion.py:85–88, 117–120` | Open — carry-forward Cycle 3/4 |
| CODE-31 | `tests/unit/test_rag_query.py` has only the cross-import test; no unit test for empty-query `InsufficientEvidence` path (no DB or API needed). | `tests/unit/test_rag_query.py` | Open — new Cycle 4 |
| CODE-32 | `OpenAIEmbeddingClient` duplicated across `ingestion.py` and `query.py` with diverging implementations. Deferred to T13-area refactor via `app/retrieval/types.py`. | `app/retrieval/query.py:23–66`, `app/retrieval/ingestion.py:32–80` | Open — new Cycle 4; deferred to T13 |
| ARCH-8 | `retrieval_ms` span attribute and `insufficient_evidence` rate counter absent from `query.py` (same root as CODE-27). **RAG P2 age cap: 1 cycle.** | `app/retrieval/query.py:84–110` | Open — new Cycle 4; tracked under CODE-27 |

---

## Carry-Forward Status

| ID | Sev | Description | Status | Change |
|----|-----|-------------|--------|--------|
| CODE-2 | P2 | Non-auth `HttpError` (e.g. 500) branch in `GDocsClient.fetch_document()` untested | Open | No change — 3rd/4th cycle. Must assign fix window before Phase 4. |
| CODE-3 | P2 | `app/api/health.py` stub missing `# TODO(T13):` comment | Open | No change; resolves at T13 |
| CODE-4 | P2 | `tests/unit/test_config.py` absent; 8 required secrets untested | Open | No change; resolve before T14 |
| CODE-5 | P2 | Migration test missing `fragments IS NOT NULL` and CHECK constraint assertions | Open | No change — 3rd/4th cycle. Must assign fix window before Phase 4. |
| CODE-6 | P2 | `test_health_index_last_updated_is_none` missing `# TODO(T13):` comment | Open | No change; resolves at T13 |
| CODE-7 | P3 | `app/main.py` unconditional `host="0.0.0.0"` | Open | No change — 3rd/4th cycle carry-forward |
| CODE-10 | P3 | `app/shared/tracing.py` dual-path singleton inconsistent thread-safety | Open | No change; resolves at T13 |
| CODE-11 | P2 | Three integration tests gated on `ANTHROPIC_API_KEY` despite using stubs | Open | No change — 2nd/3rd/4th cycle. Must assign fix window before Phase 4. |
| CODE-12 | P2 | `StubGrounder` hardcodes `verified=True`; second fragment not tested for `verified=False` | Open | No change — 2nd/3rd/4th cycle. Must assign fix window before Phase 4. |
| CODE-13 | P3 | `_segment_with_llm_fallback` raises `NotImplementedError` with stale T08 label | Open | No change |
| CODE-14 | P2 | `docs/retrieval_eval.md §Evaluation Dataset` placeholder rows; resolves at T12 | Open | No change; resolves at T12 |
| CODE-15 | P2 | DB calls in `analysis.py` and `taxonomy.py` not OTel-spanned individually | Open | No change; resolves at T13 |
| CODE-16 | P3 | `003_seed_categories.py` missing governance exception comment | Open | No change |
| CODE-18 | P2 | `docs/retrieval_eval.md §Evaluation Dataset` placeholder rows (10-query requirement for T12) | Open | No change; resolves at T12 |
| CODE-22 | P2 | Integration RAG tests skip only on missing `OPENAI_API_KEY`; DB not guarded — superseded by CODE-30 | Open | Subsumed into CODE-30; retained for traceability |
| CODE-24 | P2 | No per-request HTTP span on OpenAI call in `ingestion.py`; OTel not in `asyncio.to_thread` | Open | No change; resolves at T13 |
| ARCH-4 | P3 | `docs/adr/` directory absent | Open | No change; governance gap persists |
| ARCH-5 | P2 | `docs/retrieval_eval.md §Evaluation Dataset` placeholder rows | Open | Same as CODE-14/CODE-18; resolves at T12 |
| ARCH-6 | P2 | `interpretation_note` not enforced in Pydantic response models | Open | No change; resolves at T15/T16 |
| ARCH-7 | P3 | `health.py` missing T13 handoff comment | Open | New Cycle 4; low impact |
| ARCH-9 | P3 | `ARCHITECTURE.md §File Layout` missing migrations 005 and 006 | Open | New Cycle 4; doc drift only |
| ARCH-10 | P3 | Query expansion (LLM) not wired in `query.py` | Open | New Cycle 4; not a T11 AC violation; resolves at search API task |
| ARCH-11 | P3 | `EvidenceBlock.matched_fragments` lacks `match_type` and character offsets | Open | New Cycle 4; partial contract; resolves before `app/api/search.py` |

---

## Stop-Ship Decision

**No** — Stop-Ship criteria are not met. There are no P0 findings. There is one P1 finding (CODE-26) which must be resolved as FIX-C4-1 before T12 closes Phase 3 (it does not block T12 start, but T12 cannot be marked DONE without it). All T11 acceptance criteria are verified PASS. The system is in a deployable state for the retrieval pipeline.

---
_Cycle 4 complete. Next: archive this file to `docs/audit/archive/PHASE3_CYCLE4_REVIEW.md` before Cycle 5._
