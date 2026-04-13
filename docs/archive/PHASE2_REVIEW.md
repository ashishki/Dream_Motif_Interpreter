---
# REVIEW_REPORT — Cycle 2
_Date: 2026-04-12 · Scope: T06–T09_

## Executive Summary

- **Stop-Ship: No** — Zero P0 or P1 findings. Phase 2 (T06–T09) complete with no regressions (+15 passing, +3 skipped vs Cycle 1 close).
- FIX-1 (CODE-1) and FIX-2 (CODE-9) confirmed closed: `ck_dream_themes_status` CHECK constraint applied via migration 004 and `deprecated boolean NOT NULL DEFAULT false` added via migration 002; both integration tests passing.
- Architecture layer separation, annotation versioning ordering (T09-AC4), hallucination guards, and `verified=False` fragment path all verified PASS for new Phase 2 code (`grounder.py`, `theme_extractor.py`, `analysis.py`, `segmentation.py`, `taxonomy.py`).
- Nine P2 findings remain open: six carry-forwards from Cycle 1 (CODE-2, CODE-3, CODE-4, CODE-5, CODE-6, CODE-8) and three new this cycle (CODE-11, CODE-12, CODE-14). CODE-8 urgency elevated — T10 starts next.
- Four P3 findings remain open: two carry-forwards (CODE-7, CODE-10) and two new (CODE-13, CODE-16).
- `docs/retrieval_eval.md` does not exist; this is a P2 gate requirement (CODE-14 / RET-7) that must be resolved — at minimum initialised from template — before T10 is marked DONE.
- Pre-T10 mandatory patches: (1) new migration for `server_default='[]'::jsonb` on `dream_themes.fragments` (CODE-8 / ARCH-4); (2) initialise `docs/retrieval_eval.md` from `templates/RETRIEVAL_EVAL.md` (CODE-14). HNSW index migration (ARCH-2) is a T11 hard dependency; recommended pre-T11 but does not block T10 start.
- Baseline at Cycle 2 close: **32 passing, 4 skipped**.

---

## P0 Issues

_None._

---

## P1 Issues

_None._

---

## P2 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-2 | Non-auth `HttpError` (e.g. 500) in `GDocsClient.fetch_document()` is untested — only 401/403 paths are parametrised. Add parametrised case asserting the error is re-raised as-is. | `tests/unit/test_gdocs_client.py:39–49` | Open — carry-forward from Cycle 1 |
| CODE-3 | `app/api/health.py` stub `index_last_updated=None` has no `# TODO(T13):` comment. | `app/api/health.py:18` | Open — carry-forward from Cycle 1 |
| CODE-4 | Config fail-fast test covers only `DATABASE_URL`; `tests/unit/test_config.py` is absent; 8 other required secrets untested. Create file with parametrised `ValidationError` test for all 9 required secrets. | `tests/unit/test_config.py` (absent) | Open — carry-forward from Cycle 1 |
| CODE-5 | Migration test does not assert `dream_themes.fragments IS NOT NULL` or CHECK constraint domain (`'draft','confirmed','rejected'`). Add `column_metadata` assertions. | `tests/integration/test_migrations.py:156–175` | Open — carry-forward from Cycle 1 |
| CODE-6 | `test_health_index_last_updated_is_none` has no `# TODO(T13): update to assert ISO8601 timestamp` comment. | `tests/integration/test_health.py:38–49` | Open — carry-forward from Cycle 1 |
| CODE-8 | `dream_themes.fragments` has no `server_default` in migration 001. New migration required: `ALTER TABLE dream_themes ALTER COLUMN fragments SET DEFAULT '[]'::jsonb`. Urgency elevated — T10 starts next. | `alembic/versions/001_initial_schema.py:143` | Open — carry-forward from Cycle 1; urgency elevated |
| CODE-11 | Three integration tests in `test_analysis.py` are 100% gated on `ANTHROPIC_API_KEY` even though stub doubles are used inside them. Remove `skipif` guards from those three tests. | `tests/integration/test_analysis.py:167–170, 213–216, 250–253` | Open — new this cycle |
| CODE-12 | `StubGrounder` hardcodes `verified=True` for all fragments; second fragment not tested for `verified=False`. Have `StubGrounder` set `verified=False` for second fragment; assert `fragments[1]["verified"] is False`. | `tests/integration/test_analysis.py:97–131` | Open — new this cycle |
| CODE-14 | `docs/retrieval_eval.md` §Answer Quality Metrics has no completed evaluation run. Before T10, run at least one evaluation (synthetic corpus acceptable); populate Eval Source, Date, scores. | `docs/retrieval_eval.md` (absent) | Open — new this cycle; P2 per RET-7 |
| CODE-15 | DB calls in `analysis.py` and `taxonomy.py` not individually spanned (OBS-1 drift). `session.get`, `session.execute`, `session.commit` calls lack per-call child spans. | `app/services/analysis.py:33–125`, `app/services/taxonomy.py:80–121` | Open — new this cycle |
| ARCH-1 | `app/retrieval/ingestion.py` and `app/retrieval/query.py` do not exist; cross-import enforcement tests cannot run; OBS-2 metrics cannot be assessed. Expected pre-T10 state. | `app/retrieval/` | Open — expected gap; resolves at T10/T11 |
| ARCH-2 | No HNSW index on `dream_chunks.embedding` — T11 hard dependency for p95 < 3s retrieval latency. New migration `005_add_hnsw_index.py` required before T11. | `alembic/versions/001_initial_schema.py` | Open — carry-forward ARCH-5; urgency elevated |
| ARCH-6 | LLM output framing present at prompt level only; `"interpretation_note"` literal field not enforced in API response Pydantic models. Must be enforced when `app/api/themes.py` and `app/api/search.py` are implemented. | `app/llm/grounder.py:67`, `app/llm/theme_extractor.py:63` | Open — expected gap; must be enforced at T15/T16 |

---

## P3 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-7 | `app/main.py` binds `host="0.0.0.0"` unconditionally; should default to `127.0.0.1` for non-production ENV. | `app/main.py` | Open — carry-forward from Cycle 1 |
| CODE-10 | Dual-path singleton in `app/shared/tracing.py`: `_get_provider()` uses mutable global; `get_tracer()` uses `lru_cache`. Inconsistent thread-safety semantics. | `app/shared/tracing.py` | Open — carry-forward from Cycle 1 |
| CODE-13 | `_segment_with_llm_fallback` in `segmentation.py` catches `ImportError` and raises `NotImplementedError` referencing "T08" (now complete). Comment is stale; no `NotImplementedError` test exists for the LLM fallback path. | `app/services/segmentation.py:214–222` | Open — new this cycle |
| CODE-16 | `003_seed_categories.py` inserts with `status='active'` with no governance exception comment explaining the bootstrap exception. | `alembic/versions/003_seed_categories.py:46` | Open — new this cycle |
| ARCH-3 | Dual-path singleton in `app/shared/tracing.py` (architectural evidence for CODE-10). | `app/shared/tracing.py:7, 15–22, 25–29` | Open — carry-forward |
| ARCH-7 | `003_seed_categories.py` seeds with `status='active'` bypassing taxonomy mutation gate; no governance exception comment (architectural evidence for CODE-16). | `alembic/versions/003_seed_categories.py:46` | Open — new this cycle |

---

## Carry-Forward Status

| ID | Sev | Description | Status | Change |
|----|-----|-------------|--------|--------|
| CODE-1 | P2 | `dream_themes.status` CHECK constraint | **Closed** — FIX-1 applied 2026-04-12 | Closed Cycle 1; confirmed Cycle 2 |
| CODE-2 | P2 | Non-auth `HttpError` (500) in `GDocsClient.fetch_document()` untested | Open | Unchanged |
| CODE-3 | P2 | `app/api/health.py` stub has no TODO comment | Open | Unchanged |
| CODE-4 | P2 | Config fail-fast test covers only `DATABASE_URL` | Open | Unchanged; `tests/unit/test_config.py` still absent |
| CODE-5 | P2 | Migration test missing `fragments IS NOT NULL` / CHECK domain assertions | Open | Unchanged |
| CODE-6 | P2 | `test_health_index_last_updated_is_none` has no TODO comment | Open | Unchanged |
| CODE-7 | P3 | `app/main.py` binds `host="0.0.0.0"` unconditionally | Open | Unchanged |
| CODE-8 | P2 | `dream_themes.fragments` has no `server_default` | Open | Urgency elevated — T10 starts next; `alembic/versions/001_initial_schema.py:143` confirmed unfixed |
| CODE-9 | P3 | `dream_themes` missing `deprecated` boolean column | **Closed** — FIX-2 applied 2026-04-12 | Closed Cycle 1; confirmed Cycle 2 |
| CODE-10 | P3 | Dual-path singleton in `app/shared/tracing.py` | Open | Unchanged |
| ARCH-5 | P2 | No HNSW index on `dream_chunks.embedding` (now tracked as ARCH-2) | Open | Urgency elevated — T11 hard dependency confirmed; carry-forward from Cycle 1 |

---

## Stop-Ship Decision

**No** — Zero P0 or P1 findings. Phase 2 (T06–T09) architecturally sound; all contract compliance checks PASS. Codex may proceed to T10 after completing pre-T10 mandatory patches: (1) migration for `server_default` on `dream_themes.fragments` (CODE-8) and (2) initialising `docs/retrieval_eval.md` from template with at least one evaluation run (CODE-14). HNSW index migration (ARCH-2) must be in place before T11 begins.
---
