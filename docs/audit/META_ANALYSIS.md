---
# META_ANALYSIS — Cycle 5
_Date: 2026-04-13 · Type: full_

## Project State

Phase 3 (T10–T12) complete. Next: T13 — Health Endpoint and Observability.
Baseline: 48 pass, 12 skip.

**Change from Cycle 4:** +2 pass (46→48), +2 skip (10→12). No regressions. T12 (Retrieval Evaluation Baseline) closed Phase 3; RAG evaluation recorded (`hit@3=1.00`, `MRR=1.00`, `no-answer accuracy=1.00`) against synthetic-20-entries corpus. FIX-C4-1 (CODE-26, P1 query HTTP error handling) resolved prior to T12 close.

---

## Open Findings

| ID | Sev | Description | Files | Status |
|----|-----|-------------|-------|--------|
| CODE-2 | P2 | Non-auth `HttpError` (e.g. 500) branch in `GDocsClient.fetch_document()` untested; no parametrised re-raise test. | `tests/unit/test_gdocs_client.py:39–49` | Open — 4 cycles; must assign fix window now (Phase 4 boundary) |
| CODE-3 | P2 | `app/api/health.py` stub `index_last_updated=None` has no `# TODO(T13):` comment. | `app/api/health.py:18` | Open — resolves at T13 |
| CODE-4 | P2 | `tests/unit/test_config.py` absent; 8 required secrets untested for `ValidationError`. | `tests/unit/test_config.py` (absent) | Open — must resolve before T14 |
| CODE-5 | P2 | Migration test missing `fragments IS NOT NULL` and CHECK constraint domain assertions. | `tests/integration/test_migrations.py:156–175` | Open — 4 cycles; must assign fix window now (Phase 4 boundary) |
| CODE-6 | P2 | `test_health_index_last_updated_is_none` missing `# TODO(T13): update to assert ISO8601 timestamp` comment. | `tests/integration/test_health.py:38–49` | Open — resolves at T13 |
| CODE-7 | P3 | `app/main.py` binds `host="0.0.0.0"` unconditionally; should default to `127.0.0.1` for non-production ENV. | `app/main.py` | Open — 4 cycles carry-forward; schedule before T14 deploy |
| CODE-10 | P3 | `app/shared/tracing.py` dual-path singleton: `_get_provider()` mutable global vs `get_tracer()` `lru_cache` — inconsistent thread-safety. | `app/shared/tracing.py` | Open — resolves at T13 |
| CODE-11 | P2 | Three integration tests in `test_analysis.py` skip on missing `ANTHROPIC_API_KEY` despite using stub doubles. Remove `skipif` guards. | `tests/integration/test_analysis.py:167–170, 213–216, 250–253` | Open — 3 cycles; must assign fix window now (Phase 4 boundary) |
| CODE-12 | P2 | `StubGrounder` hardcodes `verified=True`; second fragment not tested for `verified=False`. | `tests/integration/test_analysis.py:97–131` | Open — 3 cycles; must assign fix window now (Phase 4 boundary) |
| CODE-13 | P3 | `_segment_with_llm_fallback` raises `NotImplementedError` with stale "T08" comment; no LLM fallback path test. | `app/services/segmentation.py:214–222` | Open — 2 cycles |
| CODE-15 | P2 | DB calls in `analysis.py` and `taxonomy.py` not individually OTel-spanned. | `app/services/analysis.py:33–125`, `app/services/taxonomy.py:80–121` | Open — resolves at T13 |
| CODE-16 | P3 | `003_seed_categories.py` inserts with `status='active'` with no governance exception comment. | `alembic/versions/003_seed_categories.py:46` | Open — 2 cycles; trivial doc fix |
| CODE-24 | P2 | No per-request HTTP span on OpenAI call in `ingestion.py`; OTel context not propagated into `asyncio.to_thread`. | `app/retrieval/ingestion.py:64–66, 122–126` | Open — resolves at T13 |
| CODE-32 | P2 | `OpenAIEmbeddingClient` duplicated across `ingestion.py` and `query.py` with diverging implementations. | `app/retrieval/query.py:23–66`, `app/retrieval/ingestion.py:32–80` | Open — deferred to T13-area refactor via `app/retrieval/types.py` |
| ARCH-4 | P3 | `docs/adr/` directory absent; no ADR governance records. | `docs/adr/` (absent) | Open — governance gap; no assigned task |
| ARCH-6 | P2 | `interpretation_note` literal field not enforced in Pydantic response models. | `app/llm/grounder.py:67`, `app/llm/theme_extractor.py:63` | Open — resolves at T15/T16 |
| ARCH-7 | P3 | `app/api/health.py` missing `# TODO(T13): instrument _fetch_index_last_updated with OTel span and p95 latency tracking` comment. | `app/api/health.py:27–61` | Open — resolves at T13 |
| ARCH-9 | P3 | `ARCHITECTURE.md §File Layout` migration listing ends at `004_fix_status_ck.py`; migrations 005 and 006 absent. | `docs/ARCHITECTURE.md:366–370` | Open — doc drift; low impact |
| ARCH-10 | P3 | Query expansion (LLM call to `claude-haiku-4-5`) not wired in `query.py`; declared in ARCHITECTURE.md and spec.md §6 AC-5. | `app/retrieval/query.py:84–110` | Open — resolves at T15 (search API task) |
| ARCH-11 | P3 | `EvidenceBlock.matched_fragments` is `list[str]`; spec requires `match_type` labels and character offsets per fragment. Partial contract. | `app/retrieval/query.py:28–34` | Open — resolves before `app/api/search.py` (T15) |

---

## PROMPT_1 Scope (architecture)

- **T13 target: health endpoint freshness** — `app/api/health.py` must replace `index_last_updated=None` stub with a real DB query; add HTTP 503 on staleness > `MAX_INDEX_AGE_HOURS`. T11-AC-5 may have introduced a partial stub; confirm the ownership boundary and whether the 503 path is already wired before T13 reimplements it.
- **T13 target: shared tracing module** — `app/shared/tracing.py` dual-path singleton (CODE-10) must be resolved; a single concurrency-safe pattern (prefer `lru_cache` or module-level init, not both) must govern all `get_tracer()` callers across the codebase.
- **T13 target: OTel span coverage** — all five external call sites (DB per-call in `analysis.py` and `taxonomy.py`, Redis, Google Docs, Anthropic, OpenAI in `ingestion.py` and `query.py`) must have child spans. Assess current coverage gap and whether CODE-24 (`asyncio.to_thread` OTel propagation) requires architectural guidance on context propagation pattern.
- **CODE-32 deferred refactor: retrieval types module** — `app/retrieval/types.py` shared `OpenAIEmbeddingClient` should ship with T13 or as FIX-C5-1; if deferred past T14 the diverging implementations will be called from the search API and workers, compounding the refactor scope.
- **Phase 4 API contracts readiness** — T14/T15/T16 require: authentication middleware (X-API-Key, hashed in DB), ARQ worker wiring, Redis TTL for bulk-confirm tokens. Verify no conflicting stubs or scaffolding exist in `app/main.py`, `app/api/`, or `app/workers/` that would constrain T14 implementation.
- **Aging carry-forwards (CODE-2, CODE-5, CODE-11, CODE-12)** — four findings have been open 3–4 cycles with no assigned fix window. These must each be assigned to a FIX task before Phase 4 work begins; leaving them to accumulate further increases review debt entering the API layer.

---

## PROMPT_2 Scope (code, priority order)

1. `app/api/health.py` (new T13 target — stub replacement, 503 semantics, OTel span comment; also CODE-3, CODE-6, ARCH-7)
2. `app/shared/tracing.py` (new T13 target — dual-path singleton fix, CODE-10)
3. `app/retrieval/query.py` (changed — CODE-32 shared client gap, ARCH-10 query expansion absent, ARCH-11 fragment metadata partial contract)
4. `app/retrieval/ingestion.py` (changed — CODE-24 OTel span on OpenAI call; CODE-32 client duplication source)
5. `app/services/analysis.py` (changed — CODE-15 per-call DB spans missing)
6. `app/services/taxonomy.py` (changed — CODE-15 per-call DB spans missing)
7. `tests/integration/test_analysis.py` (regression check — CODE-11 spurious `skipif` guards, CODE-12 `StubGrounder verified=True` hardcoded)
8. `tests/unit/test_gdocs_client.py` (regression check — CODE-2 non-auth HttpError untested branch, now 4 cycles old)
9. `tests/integration/test_migrations.py` (regression check — CODE-5 fragments IS NOT NULL and CHECK constraint assertions absent, now 4 cycles old)
10. `tests/unit/test_config.py` (absent — CODE-4; required before T14)
11. `app/main.py` (security carry-forward — CODE-7 unconditional `host="0.0.0.0"`)
12. `app/services/segmentation.py:214–222` (regression check — CODE-13 stale `NotImplementedError` T08 reference)

---

## Cycle Type

Full — Phase 3 boundary complete (T10–T12 all done, RAG evaluation baseline established, FIX-C4-1 closed). Phase 4 begins with T13. All aging carry-forward findings (CODE-2, CODE-5, CODE-11, CODE-12) must be triaged and assigned at the start of this cycle.

---

## Notes for PROMPT_3

1. **Aging carry-forward triage is mandatory before T13 closes.** CODE-2, CODE-5, CODE-11, CODE-12 have been open 3–4 cycles. PROMPT_3 consolidation must either assign each to a concrete FIX task (preferred: group as FIX-C5-1 covering all four) or escalate to P1 if they represent unacceptable test-coverage gaps entering the API layer. Suggested assignments: CODE-2 → parametrised `HttpError` test (one test); CODE-5 → add two column assertions to existing migration test file; CODE-11 → remove three `skipif` decorators; CODE-12 → one line change in `StubGrounder` plus one assertion.
2. **CODE-32 deferred refactor timing.** `app/retrieval/types.py` shared client should ship with T13 or as FIX-C5-1; if it slips past T14 the diverging implementations will be called from the search API and workers. PROMPT_3 should confirm the refactor is either in T13 scope or explicitly assigned as a pre-T14 fix.
3. **T13 closes six standing findings atomically.** CODE-3, CODE-6, CODE-10, CODE-15, CODE-24, ARCH-7 all resolve at T13. PROMPT_3 should verify all six are individually confirmed closed when T13 is reviewed, not just the four ACs.
4. **ARCHITECTURE.md and ADR gap.** ARCH-9 (migration listing drift) and ARCH-4 (no `docs/adr/` directory) are both doc-only and could be addressed as a single `docs` commit in Cycle 5 without a dedicated task slot.
5. **RAG evaluation baseline is clean.** No regression action needed entering Phase 4; next evaluation trigger is T15 (search API, `rag:query` type). PROMPT_3 should confirm the evaluation state section in `CODEX_PROMPT.md` accurately reflects the T12 baseline for the next Codex session.
6. **REVIEW_REPORT archival.** The Cycle 4 REVIEW_REPORT footer requests archival to `docs/audit/archive/PHASE3_CYCLE4_REVIEW.md` before Cycle 5. PROMPT_3 should confirm this archival is completed as part of Cycle 5 consolidation.

---
_Cycle 5 scope set. Run PROMPT_1_ARCH.md._
