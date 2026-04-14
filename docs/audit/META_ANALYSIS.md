---
# META_ANALYSIS — Cycle 6
_Date: 2026-04-14 · Type: full_

## Project State

Phase 4 (T13–T17) is in progress: T13, T14, T15 complete; T16 and T17 remain. Next: T16 — User Curation API (Theme Confirmation and Taxonomy Management).

Baseline: 74 pass, 9 skip.
Previous cycle (Cycle 5) close: 55 pass, 9 skip (after FIX-C5 patches); subsequently T13 → 57 pass, T14 → 70 pass, T15 → 74 pass. Net +19 pass since Cycle 5 close. No regressions recorded.

---

## Open Findings

| ID | Sev | Description | Files | Status |
|----|-----|-------------|-------|--------|
| CODE-7 | P3 | `app/main.py` binds `host="0.0.0.0"` unconditionally; should default to `127.0.0.1` for non-production ENV. | `app/main.py` | Open — carry-forward Cycles 1–5 |
| CODE-13 | P3 | `_segment_with_llm_fallback` stale `NotImplementedError` comment still references "T08" (now complete); no LLM fallback path test. Remove `type:ignore`; update comment to correct future task. | `app/services/segmentation.py:214–222` | Open — carry-forward Cycle 2+ |
| CODE-16 | P3 | `003_seed_categories.py` inserts with `status='active'` with no governance exception comment. Add bootstrap-exception inline comment. | `alembic/versions/003_seed_categories.py:46` | Open — carry-forward Cycle 2+ |
| CODE-22 | P2 | Integration RAG tests skip only on missing `OPENAI_API_KEY`; DB guard absent. (Superseded in practice by CODE-30, now Closed — needs explicit status reconciliation.) | `tests/integration/test_rag_ingestion.py` | Open — verify closure via CODE-30; mark superseded if confirmed |
| CODE-40 | P3 | `scripts/eval.py` hard-codes `TASK_ID = "T12"`. Should be a runtime argument or derived from context. | `scripts/eval.py` | Open — new Cycle 5 |
| CODE-41 | P3 | `scripts/eval.py` `_evaluation_history_table` overwrites full history on every write run instead of appending. | `scripts/eval.py` | Open — new Cycle 5 |
| ARCH-6 | P2 | `interpretation_note` literal field not enforced in Pydantic API response models; LLM output framing is prompt-level only. Resolves at T15/T16. | `app/llm/grounder.py:67`, `app/llm/theme_extractor.py:63` | Open — T15 shipped without explicit closure; re-check in T16 scope |
| ARCH-9 | P3 | `ARCHITECTURE.md §File Layout` migration listing ends at `004_fix_status_ck.py`; migrations 005 and 006 absent from diagram. | `docs/ARCHITECTURE.md:366–370` | Open — doc drift; Cycle 4+ |
| ARCH-10 | P3 | Query expansion (LLM call to `claude-haiku-4-5`) not wired in `query.py`; declared in ARCHITECTURE.md §RAG Architecture. | `app/retrieval/query.py:84–110` | Open — Cycle 4+; resolves at post-T15 search API task |
| ARCH-11 | P3 | `EvidenceBlock.matched_fragments` is `list[str]`; spec.md §Retrieval requires `match_type` labels and character offsets per fragment. Partial contract. | `app/retrieval/query.py:28–34` | Open — Cycle 4+; was flagged must-resolve before T15; T15 shipped; confirm state and assign FIX-C6 or T16 scope |

---

## PROMPT_1 Scope (architecture)

- **T16 curation API surface**: New endpoints `PATCH /dreams/{id}/themes/{theme_id}/confirm`, `PATCH /dreams/{id}/themes/{theme_id}/reject`, `POST /curate/bulk-confirm`, `POST /curate/bulk-confirm/{token}/approve`, `PATCH /themes/categories/{id}/approve` — all absent from current `app/api/` (`themes.py` not yet present). Review endpoint design, auth boundary, and AnnotationVersion write-ahead contract.
- **Bulk-confirm token flow**: UUID token in Redis with 10-minute TTL; two-phase commit pattern — assess state-machine correctness and token lifecycle (happy path, expiry returning HTTP 410, concurrent approve race).
- **AnnotationVersion write contract**: Every mutation must write an `AnnotationVersion` row before the mutation commits — transactional ordering, rollback safety, and whether the existing schema supports this without a new migration.
- **ARCH-6 resolution path**: Verify whether T15 `app/api/search.py` + `app/api/dreams.py` now enforce `interpretation_note` in Pydantic response models, or whether the gap persists into T16 (theme-level responses).
- **ARCH-11 resolution path**: Confirm whether `EvidenceBlock.matched_fragments` contract was strengthened in T15; if not, assess impact on T16 theme responses and assign remediation.
- **Redis dependency consolidation**: T14 introduced sync job status in Redis; T16 adds bulk-confirm tokens — verify Redis client/config is shared and not duplicated; TTL policy consistency.
- **`app/workers/` readiness for T17**: Workers directory currently has only `__init__.py`; T16 does not add workers, but the shared session factory pattern referenced in T17 notes should be confirmed as consistent with T14/T15 session handling before T17 begins.

---

## PROMPT_2 Scope (code, priority order)

1. `app/api/themes.py` (new — T16 primary deliverable; does not yet exist)
2. `tests/integration/test_curation_api.py` (new — T16 test file; does not yet exist)
3. `app/api/search.py` (changed at T15 — verify ARCH-6 `interpretation_note` enforcement; check ARCH-11 fragment metadata in response models)
4. `app/api/dreams.py` (changed at T14/T15 — confirm rejected-theme exclusion logic absent pre-T16; no regression introduced)
5. `app/models/theme.py` + `alembic/versions/` (regression check — AnnotationVersion model present; `ck_dream_themes_status` CHECK constraint live via migration 004; assess whether T16 mutations require a new migration)
6. `app/shared/config.py` (regression check — Redis settings present; confirm bulk-confirm token TTL config slot exists or needs addition)
7. `scripts/eval.py` (CODE-40/CODE-41 — P3 open findings; low priority but scope for targeted fix)
8. `app/services/segmentation.py:214–222` (CODE-13 — stale NotImplementedError comment; trivial P3 carry-forward)
9. `alembic/versions/003_seed_categories.py:46` (CODE-16 — missing governance comment; trivial P3 carry-forward)
10. `app/main.py` (CODE-7 — host binding; P3 carry-forward; security-adjacent; check before any deploy step)

---

## Cycle Type

Full — Phase 4 mid-cycle checkpoint. T13, T14, and T15 are all complete with a clean baseline (74 pass / 9 skip). T16 and T17 are the remaining Phase 4 tasks. No hotfix queue is open; no P1 findings are outstanding. Cycle 6 covers T16 implementation plus resolution or explicit carry-forward disposition of ARCH-6, ARCH-11, and CODE-22.

---

## Notes for PROMPT_3

- **ARCH-6 disposition**: CODEX_PROMPT.md listed ARCH-6 as resolving at T15/T16. T15 shipped without explicit closure. PROMPT_2 must verify `app/api/search.py` for `interpretation_note` enforcement; if still open, assign to T16 scope or create FIX-C6 item.
- **ARCH-11 disposition**: Same pattern — flagged "must resolve before T15" but T15 is now closed. Confirm actual state in `app/retrieval/query.py` and flag for T16 or FIX-C6 if contract is still partial.
- **CODE-22 cleanup**: CODE-30 is Closed (DB guard added). CODE-22 should be explicitly marked superseded or confirmed closed to eliminate ambiguity in the findings table.
- **Baseline delta tracking**: +19 pass from Cycle 5 close to current (55 → 74). PROMPT_3 consolidation should snapshot this clearly; CODEX_PROMPT.md version should be bumped to v1.11 after Cycle 6 closes.
- **Phase 4 gate proximity**: T16 + T17 complete Phase 4. Phase gate requires: no P1 open findings; all T16/T17 ACs passing; RAG eval baseline held (currently 1.00/1.00/1.00). PROMPT_3 should confirm Phase 5 entry readiness checklist after both tasks land.
- **Redis as hard dependency**: Bulk-confirm token (T16) is the first user-facing Redis state not tied to a background job. Consolidation note: Redis is already a dependency (T14 sync status) — T16 deepens this dependency; T17 further extends it. Ensure Redis failure modes are documented before Phase 5.

---
