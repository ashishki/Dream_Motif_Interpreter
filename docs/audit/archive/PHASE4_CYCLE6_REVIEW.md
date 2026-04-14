---
# REVIEW_REPORT — Cycle 6
_Date: 2026-04-14 · Scope: T13–T16 (Phase 4 mid-cycle checkpoint)_

---

## Executive Summary

- **Stop-Ship: No**
- Phase 4 is in progress: T13, T14, T15 complete; T16 and T17 remain. Baseline: 74 passing / 9 skip. Net +19 pass since Cycle 5 close. No regressions recorded.
- No P0 or P1 findings are open. All five new cycle findings are P2. No stop-ship condition is triggered.
- Two pre-implementation contract violations are confirmed for T16: `app/api/themes.py` does not yet exist (expected) and `BULK_CONFIRM_TOKEN_TTL_SECONDS` is absent from `app/shared/config.py` (must be added before T16 is coded).
- ARCH-6 (`interpretation_note` not in Pydantic response models) remains open after T15 shipped without resolving it. Assigned to T16 scope; escalates to P1 if not closed in Cycle 7.
- CODE-22 is formally closed as superseded by CODE-30 (DB guard added in FIX-C4; verified at `tests/integration/test_rag_ingestion.py`).
- ARCH-9 is confirmed closed: migrations 005 and 006 are now correctly listed in `ARCHITECTURE.md §File Layout`.
- `_redact_pii` in the search path strips only `raw_text`; `chunk_text` and `justification` are not redacted — a code change is required before T16 ships.
- Carry-forward P3 findings (CODE-7, CODE-13, CODE-16, CODE-40, CODE-41) remain open with no change in severity.

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
| CODE-42 | T16 primary deliverable `app/api/themes.py` absent — pre-implementation expected; assigned to T16 | `app/api/themes.py` | Open — new Cycle 6; assigned to T16 |
| CODE-43 | `BULK_CONFIRM_TOKEN_TTL_SECONDS` config slot absent from `Settings`; T16 bulk-confirm token TTL has no config home. Must add before T16 implementation. | `app/shared/config.py` | Open — new Cycle 6; pre-T16 blocker |
| CODE-44 | `interpretation_note` not present in any API response Pydantic model (`SearchResultItem`, `SearchResultsResponse`, `DreamThemeResponseItem`). ARCH-6 carry-forward; T15 shipped without closure. Assign to T16; escalate to P1 if not closed in Cycle 7. | `app/api/search.py:27–57`, `app/llm/theme_extractor.py:63`, `app/llm/grounder.py:67` | Open — new Cycle 6 (ARCH-6 carry-forward) |
| CODE-45 | `tests/integration/test_curation_api.py` absent — T16 integration test file not yet created. Expected pre-implementation; must exist when T16 is marked DONE. | `tests/integration/test_curation_api.py` | Open — new Cycle 6; assigned to T16 |
| CODE-46 | `_redact_pii` strips only `raw_text`; `chunk_text` and `justification` fields in search and theme responses are not stripped. PII policy gap. | `app/api/search.py` (redact helper) | Open — new Cycle 6; code change required |
| CODE-47 | CODE-22 explicit disposition absent — formally closed this cycle as superseded by CODE-30 | `tests/integration/test_rag_ingestion.py` | **Closed** — superseded by CODE-30 (DB guard verified in FIX-C4) |

---

## Carry-Forward Status

| ID | Sev | Description | Status | Change |
|----|-----|-------------|--------|--------|
| CODE-7 | P3 | `app/main.py` binds `host="0.0.0.0"` unconditionally | Open | No change — carry-forward Cycles 1–6 |
| CODE-13 | P3 | `_segment_with_llm_fallback` stale T08 comment in `segmentation.py:214–222` | Open | No change — carry-forward Cycles 2–6 |
| CODE-16 | P3 | `003_seed_categories.py` inserts `status='active'` without bootstrap-exception comment | Open | No change — carry-forward Cycles 2–6 |
| CODE-22 | P2 | Integration RAG tests skip only on missing `OPENAI_API_KEY`; DB guard absent | **Closed** — superseded by CODE-30; DB guard added in FIX-C4 | Formally closed this cycle |
| CODE-40 | P3 | `scripts/eval.py` hardcodes `TASK_ID = "T12"` | Open | No change — carry-forward Cycles 5–6 |
| CODE-41 | P3 | `_evaluation_history_table` overwrites history on every write | Open | No change — carry-forward Cycles 5–6 |
| ARCH-6 | P2 | `interpretation_note` not enforced at API response schema level | Open — tracked as CODE-44 | Escalation warning added: P1 if not closed Cycle 7 |
| ARCH-9 | P3 | `ARCHITECTURE.md §File Layout` missing migrations 005/006 | **Closed** — migrations 005 and 006 now correctly listed (verified by ARCH_REPORT Cycle 6) | Closed this cycle |
| ARCH-10 | P3 | LLM query expansion not wired in `query.py` | Open | No change — carry-forward Cycles 4–6 |
| ARCH-11 | P3 | `EvidenceBlock.matched_fragments` partial contract (no offsets/match_type) | Open | No change — carry-forward Cycles 4–6; T15 shipped without closure |
| ARCH-12 | P3 | Session factory duplicated in `search.py` and `dreams.py` | Open | New Cycle 6 |
| ARCH-13 | P2 | `BULK_CONFIRM_TOKEN_TTL_SECONDS` absent — tracked as CODE-43 | Open | New Cycle 6 |
| ARCH-14 | P3 | Worker files `ingest.py`/`index.py` absent | Open | New Cycle 6 |
| ARCH-15 | P3 | `docs/adr/` directory does not exist | Open | New Cycle 6 |

---

## Stop-Ship Decision

**No** — Zero P0 and zero P1 open findings. All active P2 findings are either pre-implementation placeholders correctly assigned to T16 or code changes that do not block the current baseline. The fix for CODE-43 (`BULK_CONFIRM_TOKEN_TTL_SECONDS`) must land as a mandatory pre-T16 step, but it is a one-line config addition and does not warrant a stop-ship. CODE-44 (ARCH-6) will escalate to P1 — and thus trigger stop-ship — if it is not resolved when T16 is marked DONE.

---
_REVIEW_REPORT.md written. Cycle 6 complete._
