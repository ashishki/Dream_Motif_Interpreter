---
# REVIEW_REPORT — Cycle 9
_Date: 2026-04-16 · Scope: WS-9.1 through WS-9.6_

## Executive Summary

- **Stop-Ship: No** — no P0 or P1 findings raised this cycle; all critical contracts hold
- Phase 9 core implementation (WS-9.1–WS-9.6) is functionally complete; all pipeline components exist and pass the separation invariant: inducted motifs are never written to `dream_themes` at any layer (migration, ORM, service, API, assistant)
- Actual test baseline is 238 passing / 9 skipped (2026-04-16); `docs/CODEX_PROMPT.md §Current State` records a stale figure of "97 → 164 after WS-9.1" and must be corrected before the next implementation session resumes
- Four P2 architecture drifts identified: `MotifService` owns session commit on a caller-provided session (ARCH-1/CODE-1), no idempotency guard on re-ingest (ARCH-6/CODE-2), `get_settings()` `lru_cache` freezes flag values at first call in violation of ADR-010 (ARCH-4/CODE-3), and `app/assistant/prompts.py` absent despite being listed as a required WS-9.6 deliverable (ARCH-3/CODE-4)
- Two additional P2 findings from code review: no OTel metrics counters on `ImageryExtractor` and `MotifInductor` LLM call paths (OBS-2 violation, CODE-5), and a stale module-level `TOOLS` constant that could mislead future callers (ARCH-2/CODE-6)
- Four P3 findings: missing idempotency test for `MotifService.run()` (CODE-7), no test asserting `handle_chat` ignores `TOOLS` constant (CODE-8), `docs/retrieval_eval.md` has no Cycle 9 advisory row (CODE-9), no test for `facade.get_dream_motifs()` rejected-motifs filter (CODE-10)
- Three P3 doc/process gaps: `docs/ARCHITECTURE.md` §17 still lists Phase 9 as Planned and §16 baseline is stale (ARCH-5), and WS-9.7 deferral is not recorded in `docs/DECISION_LOG.md` (ARCH-7/CODE-56)
- This is the first review cycle covering T17–T20 and WS-9.1–WS-9.6; prior `REVIEW_REPORT.md` was stale from Cycle 6 (2026-04-14)

---

## P0 Issues

_None this cycle._

---

## P1 Issues

_None this cycle._

---

## P2 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-1 | `MotifService.run()` calls `await session.commit()` on a caller-provided session; double-commit risk and silent partial writes on exception | `app/services/motif_service.py:126` | Open |
| CODE-2 | No idempotency guard in `MotifService.run()`; duplicate `motif_inductions` rows on re-ingest; user-confirmed status overwritten | `app/services/motif_service.py:114–123` | Open |
| CODE-3 | `get_settings()` `@lru_cache` freezes `MOTIF_INDUCTION_ENABLED` at first call; violates ADR-010 runtime re-evaluation requirement | `app/shared/config.py:33` | Open |
| CODE-4 | `app/assistant/prompts.py` absent; WS-9.6 deliverable unmet; `_SYSTEM_PROMPT` framing lives inline in `chat.py` | `app/assistant/chat.py:18–42`, `app/assistant/prompts.py` (absent) | Open |
| CODE-5 | No labeled OTel counter/histogram for `ImageryExtractor` and `MotifInductor` LLM call paths; violates OBS-2 | `app/services/imagery.py`, `app/services/motif_inductor.py` | Open |
| CODE-6 | Stale module-level `TOOLS` constant in `tools.py` built at import time with `motif_induction_enabled=False`; latent defect for future callers | `app/assistant/tools.py:149` | Open |

---

## P3 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-7 | No test for `MotifService.run()` idempotency (required after CODE-2 fix) | `tests/unit/test_motif_service.py` | Open |
| CODE-8 | No test asserting `handle_chat` ignores `TOOLS` constant and uses `build_tools()` | `tests/unit/test_assistant_chat.py` | Open |
| CODE-9 | `docs/retrieval_eval.md` Evaluation History has no Cycle 9 advisory entry | `docs/retrieval_eval.md` | Open |
| CODE-10 | No test for `facade.get_dream_motifs()` rejected-motifs filter | `tests/unit/test_assistant_facade.py` | Open |
| ARCH-5 | `docs/ARCHITECTURE.md` §17 lists Phase 9 as Planned; §16 baseline stale (97 vs 238 actual) | `docs/ARCHITECTURE.md:306,340` | Open |
| ARCH-7 | WS-9.7 deferral not recorded in `docs/DECISION_LOG.md` | `docs/DECISION_LOG.md` | Open |

---

## Carry-Forward Status

All 58 findings from Cycle 8 (as recorded in `docs/CODEX_PROMPT.md`) remain **Closed**. No findings carry forward from prior cycles as Open.

| ID | Sev | Description | Status | Change |
|----|-----|-------------|--------|--------|
| CODE-1 through CODE-50, ARCH-1 through ARCH-15, DOC-1 | P1–P3 | All Cycle 1–8 findings | Closed | No change — all closed per Cycle 8 record |

New findings raised this cycle (Cycle 9):

| ID | Sev | Description | Status | Change |
|----|-----|-------------|--------|--------|
| CODE-1 | P2 | MotifService owns session commit on caller-provided session | Open | New Cycle 9 |
| CODE-2 | P2 | No idempotency guard in MotifService.run() | Open | New Cycle 9 |
| CODE-3 | P2 | get_settings() lru_cache freezes flag; violates ADR-010 | Open | New Cycle 9 |
| CODE-4 | P2 | app/assistant/prompts.py absent; WS-9.6 deliverable unmet | Open | New Cycle 9 |
| CODE-5 | P2 | No OTel metrics on ImageryExtractor / MotifInductor LLM paths | Open | New Cycle 9 |
| CODE-6 | P2 | Stale TOOLS module-level constant | Open | New Cycle 9 |
| CODE-7 | P3 | No idempotency test for MotifService.run() | Open | New Cycle 9 |
| CODE-8 | P3 | No test asserting handle_chat uses build_tools() not TOOLS | Open | New Cycle 9 |
| CODE-9 | P3 | retrieval_eval.md missing Cycle 9 advisory row | Open | New Cycle 9 |
| CODE-10 | P3 | No test for facade.get_dream_motifs() rejected-motifs filter | Open | New Cycle 9 |
| ARCH-5 | P3 | ARCHITECTURE.md §17 stale; §16 baseline stale | Open | New Cycle 9 |
| ARCH-7 | P3 | WS-9.7 deferral not in DECISION_LOG.md | Open | New Cycle 9 |

---

## Stop-Ship Decision

**No** — No P0 or P1 findings were raised in Cycle 9. All six P2 findings are correctness or maintainability issues that do not block deployment under current load patterns; however CODE-2 (duplicate motif rows on re-ingest) and CODE-3 (flag change requires restart) represent operational risks that must be resolved before Phase 10 tasks begin.

The separation invariant (inducted motifs never written to `dream_themes`) holds at all layers. The feature flag gate is operationally present. The assistant tool is correctly gated per-request in `chat.py`. Phase 9 gate conditions are met.

---
