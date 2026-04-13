---
# REVIEW_REPORT — Cycle 1
_Date: 2026-04-12 · Scope: T01–T05_

## Executive Summary

- **Stop-Ship: No** — zero P0/P1 findings; Phase 1 baseline intact (17 pass, 1 skip).
- Phase 1 (T01–T05) is structurally sound: factory pattern, config fail-fast, tracing singleton, DB schema, and GDocs client all pass architectural review.
- Six P2 findings require resolution before the affected downstream tasks (T07, T08, T11/T13) are implemented. No finding blocks the immediate next task (T06).
- Four P3 findings are carry-forwards from META/ARCH analysis; all are low-urgency forward-risk items with no current runtime impact.
- Light-review status for T04 and T05 is formally closed: Cycle 1 review found no P0/P1 issues in either task's deliverables; both are now marked reviewed.
- `GDocsClient.fetch_document()` returning `list[str]` is confirmed as a stable Phase 2 interface contract for T06 (no breaking change anticipated).
- Key schema gaps (missing CHECK constraint on `dream_themes.status`, missing `deprecated` boolean on `dream_themes`, and absent `server_default` on `fragments`) must be patched before T07/T08 proceed.

---

## P0 Issues

None.

---

## P1 Issues

None.

---

## P2 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-1 | `dream_themes` table has no CHECK constraint on the `status` column — invalid status values can be persisted silently. Fix: add `sa.CheckConstraint("status IN ('active','deprecated')", name='ck_dream_themes_status')` in the migration and ORM model; add an `IntegrityError` test. | `app/models/theme.py`, `alembic/versions/001_initial_schema.py` | Open |
| CODE-2 | `GDocsClient.fetch_document()` non-auth `HttpError` branch (e.g. 500) is untested — only 401/403 paths are parametrised. Fix: add a unit test asserting a non-auth `HttpError` propagates rather than being swallowed or re-wrapped as `GDocsAuthError`. | `tests/unit/test_gdocs_client.py` | Open |
| CODE-3 | `app/api/health.py` stub `index_last_updated=None` has no `# TODO(T11/T13):` comment — future implementor has no in-code signal. Fix: add the TODO comment directly above the `index_last_updated=None` line. | `app/api/health.py` | Open |
| CODE-4 | `tests/unit/test_config.py` fail-fast test covers only `DATABASE_URL`, not all nine required secrets — a future accidental default on any other secret would go undetected. Fix: parametrise the test over all nine required secret names. | `tests/unit/test_config.py` | Open |
| CODE-5 | `tests/integration/test_migrations.py` does not assert `dream_themes.fragments IS NOT NULL` or the presence of the `ck_theme_categories_status` CHECK constraint. Fix: extend the migration test to assert the NOT NULL constraint and both CHECK constraints (add `ck_dream_themes_status` after CODE-1 is fixed). | `tests/integration/test_migrations.py` | Open |
| CODE-6 | `tests/integration/test_health.py::test_health_index_last_updated_is_none` has no comment distinguishing "intentionally null now" from "must be a timestamp after T11/T13". Fix: add an inline comment `# Phase 1 stub — will return ISO8601 timestamp after T11/T13`. | `tests/integration/test_health.py` | Open |

---

## P3 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-7 | `app/main.py` unconditionally binds `host="0.0.0.0"` regardless of ENV — a dev run should default to `127.0.0.1`. Recommendation: resolve in T01 patch or document in ARCHITECTURE.md §Runtime Contract before Phase 3. | `app/main.py` | Open (ARCH-6 carry-forward) |
| CODE-8 | `DreamTheme.fragments` is `nullable=False` with no `server_default='[]'::jsonb` — any INSERT before T09 grounding that omits `fragments` will raise a NOT NULL DB error. Recommendation: add `server_default=sa.text("'[]'::jsonb")` in the migration and ORM model before T08. | `app/models/theme.py`, `alembic/versions/001_initial_schema.py` | Open (META F-03 / ARCH-2 carry-forward) |
| CODE-9 | `dream_themes` table has no `deprecated` boolean column required by T07-AC3. Ambiguity persists: flag could be a column or derived from `ThemeCategory.status`. Recommendation: add `deprecated boolean NOT NULL DEFAULT false` in a migration patch; update T07-AC3; resolve ARCH-3. | `app/models/theme.py`, `alembic/versions/001_initial_schema.py`, `docs/tasks.md T07-AC3` | Open (META F-01 / ARCH-3 carry-forward) |
| CODE-10 | `app/shared/tracing.py` uses module-level mutable global in `_get_provider()` while `get_tracer()` uses `@lru_cache` — inconsistent patterns, safe only for single-process async. Recommendation: collapse `_get_provider()` into the `lru_cache` call in `get_tracer()`. | `app/shared/tracing.py` | Open (ARCH-1 carry-forward) |

---

## Carry-Forward Status

| ID | Sev | Description | Status | Change |
|----|-----|-------------|--------|--------|
| META F-01 / ARCH-3 | P2 | Missing `deprecated` boolean column on `dream_themes`; T07-AC3 ambiguity unresolved. | Open → CODE-9 (P3 in code review; was P2 in META/ARCH) | No change in resolution; escalation deferred; still must be resolved before T07 |
| META F-02 / ARCH-4 | P2 | `health.py` returns `index_last_updated: null` unconditionally; stub has no TODO comment. | Partially addressed by CODE-3 (adds TODO comment). Full staleness implementation deferred to T11/T13. | CODE-3 added in this cycle |
| META F-03 / ARCH-2 | P3 | `DreamTheme.fragments` has no `server_default` — forward risk for T08. | Open → CODE-8 | No change in resolution; must be patched before T08 |
| META F-04 | P3 | Light review pending for T04/T05 in CODEX_PROMPT.md. | Closed — Cycle 1 review found no P0/P1; T04 and T05 are now fully reviewed. | Closed this cycle |
| ARCH-1 | P3 | Tracing `_get_provider()` global vs `lru_cache` inconsistency. | Open → CODE-10 | No change in resolution |
| ARCH-5 | P3 | No pgvector HNSW index in migration 001. | Open — must be added before T11. | No change; tracked for T11 |
| ARCH-6 | P3 | Hardcoded `host="0.0.0.0"` in `app/main.py`. | Open → CODE-7 | No change in resolution |

---

## Stop-Ship Decision

**No** — there are zero P0 and zero P1 findings. Phase 1 baseline is intact. Six P2 findings must be resolved before their respective downstream tasks (T07, T08, T11/T13) but none block T06 (Dream Segmentation Service), which is the immediate next task. Phase 2 work may proceed.

---
