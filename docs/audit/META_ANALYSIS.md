---
# META_ANALYSIS — Cycle 10
_Date: 2026-04-17 · Type: full_

## Project State

Phase 9 (WS-9.1–WS-9.6) complete; all P2/P3 findings from Cycle 9 remain open in the Fix Queue. Phase 10 active; no Phase 10 tasks have been implemented yet.
Next: WS-10.1 — DB Migration and ORM Model (research_results table, ResearchResult ORM).

Baseline: 200 pass, 9 skip (per CODEX_PROMPT.md v1.37, 2026-04-16).
Unit-only run (2026-04-17): 216 pass, 0 skip (integration errors are environment-only — DB/Redis unavailable in this environment; not a regression).

Previous cycle baseline (Cycle 9 REVIEW_REPORT, 2026-04-16): 238 pass, 9 skip.
Note: CODEX_PROMPT.md records 200 passing; Cycle 9 REVIEW_REPORT.md recorded 238 passing on the same date. The discrepancy likely reflects a compaction/recount artefact when CODEX_PROMPT.md was updated for Phase 10 start. Actual unit-test count (216) and CODEX_PROMPT figure (200) are consistent within the range of integration-test exclusions. No regression is indicated; PROMPT_2 should verify the actual count by running `pytest -q --ignore=tests/integration` and recording the result.

Change vs Cycle 9: no new implementation; only three doc-only patches applied (CODE-9/ARCH-5/ARCH-7 closed by Doc Updater 2026-04-16). All six P2 Fix Queue items remain open.

---

## Open Findings

Findings carried forward from Cycle 9 REVIEW_REPORT (2026-04-16). CODE-9, ARCH-5, ARCH-7 closed by Doc Updater 2026-04-16. No new findings raised since Cycle 9 close; Phase 10 has not yet produced any code to inspect.

| ID | Sev | Description | Files | Status |
|----|-----|-------------|-------|--------|
| CODE-1 | P2 | `MotifService.run()` calls `await session.commit()` on a caller-provided session; double-commit risk and silent partial writes on exception | `app/services/motif_service.py:126` | Open — Cycle 9; see FIX-1 |
| CODE-2 | P2 | No idempotency guard in `MotifService.run()`; duplicate `motif_inductions` rows on re-ingest; user-confirmed status overwritten | `app/services/motif_service.py:114–123` | Open — Cycle 9; see FIX-2 |
| CODE-3 | P2 | `get_settings()` `@lru_cache` freezes `MOTIF_INDUCTION_ENABLED` at first call; flag change requires process restart; violates ADR-010 | `app/shared/config.py:33` | Open — Cycle 9; see FIX-3; affects Phase 10 flag `RESEARCH_AUGMENTATION_ENABLED` via same mechanism |
| CODE-4 | P2 | `app/assistant/prompts.py` absent; WS-9.6 deliverable unmet; `_SYSTEM_PROMPT` inline in `chat.py`; WS-10.5 adds new framing requirements to the same file | `app/assistant/chat.py:18–42`, `app/assistant/prompts.py` (absent) | Open — Cycle 9; see FIX-4; Phase 10 dependency |
| CODE-5 | P2 | No labeled OTel counter/histogram on `ImageryExtractor` and `MotifInductor` LLM call paths; OBS-2 violation | `app/services/imagery.py`, `app/services/motif_inductor.py` | Open — Cycle 9; see FIX-5 |
| CODE-6 | P2 | Stale module-level `TOOLS` constant in `tools.py` built at import time with `motif_induction_enabled=False`; latent defect | `app/assistant/tools.py:149` | Open — Cycle 9; see FIX-6 |
| CODE-7 | P3 | No test for `MotifService.run()` idempotency (depends on CODE-2 fix) | `tests/unit/test_motif_service.py` | Open — Cycle 9 |
| CODE-8 | P3 | No test asserting `handle_chat` uses `build_tools()` and not the stale `TOOLS` constant | `tests/unit/test_assistant_chat.py` | Open — Cycle 9 |
| CODE-10 | P3 | No test for `facade.get_dream_motifs()` rejected-motifs filter | `tests/unit/test_assistant_facade.py` | Open — Cycle 9 |

Resolved since Cycle 9 open:

| ID | Sev | Description | Files | Status |
|----|-----|-------------|-------|--------|
| CODE-9 | P3 | `docs/retrieval_eval.md` Evaluation History missing Cycle 9 advisory row | `docs/retrieval_eval.md` | Closed — advisory row added 2026-04-16 |
| ARCH-5 | P3 | `docs/ARCHITECTURE.md` §17 Phase 9 listed as Planned; §16 baseline stale | `docs/ARCHITECTURE.md:306,340` | Closed — doc patch applied 2026-04-16 |
| ARCH-7 | P3 | WS-9.7 deferral not recorded in `docs/DECISION_LOG.md` | `docs/DECISION_LOG.md` | Closed — D-012 added 2026-04-16 |

Phase 10 pre-implementation risks (not yet findings — flag for PROMPT_1/PROMPT_2):

| Risk | Sev | Description | Context |
|------|-----|-------------|---------|
| RISK-1 | P2 | CODE-3 (`lru_cache` on `get_settings()`) will affect `RESEARCH_AUGMENTATION_ENABLED` via the same frozen-settings mechanism. Phase 10 tasks all depend on this flag being re-evaluated at request time. FIX-3 must be resolved before or during WS-10.1 or the flag gate will silently misbehave in production. | `app/shared/config.py:33`; see ADR-010 |
| RISK-2 | P2 | CODE-4 (`app/assistant/prompts.py` absent) creates a conflict with WS-10.5 AC-3/AC-4, which require adding new framing rules and a confirmation-before-execution system prompt clause. If the prompts module is absent when WS-10.5 is implemented, the WS-10.5 deliverable will again embed framing inline in `chat.py`, compounding the debt. FIX-4 should be resolved before WS-10.5 begins. | `app/assistant/chat.py`; `app/assistant/prompts.py` absent |
| RISK-3 | P2 | CODE-6 (stale `TOOLS` constant) interacts with WS-10.5 AC-2/AC-5, which require the `research_motif_parallels` tool to be absent when the feature flag is false. If `TOOLS` is built at import time and callers accidentally use it instead of `build_tools()`, the new tool may appear unconditionally. FIX-6 must be resolved before WS-10.5. | `app/assistant/tools.py:149` |

---

## PROMPT_1 Scope (architecture)

Phase 10 has no implemented code yet. PROMPT_1 should focus on the carry-forward P2 Fix Queue items that create Phase 10 architectural risks, plus verifying the Phase 9 baseline is stable.

- fix-queue gate: confirm FIX-1/FIX-2 (session ownership, idempotency) are resolved; if not, WS-10.3 (ResearchService session ownership) will repeat the same pattern flaw
- flag evaluation timing: verify whether `get_settings()` `lru_cache` (CODE-3/FIX-3) remains unfixed entering Phase 10; assess impact on `RESEARCH_AUGMENTATION_ENABLED` across WS-10.3, WS-10.4, WS-10.5
- prompts module gap: confirm whether `app/assistant/prompts.py` still absent (CODE-4/FIX-4); assess impact on WS-10.5 AC-3/AC-4 system prompt framing delivery
- stale `TOOLS` constant: confirm CODE-6/FIX-6 status; assess impact on WS-10.5 tool registration
- architecture conformance: `app/research/` module does not yet exist — no new architecture findings expected; validate that `docs/RESEARCH_AUGMENTATION.md`, `docs/adr/ADR-009-research-trust-boundary.md`, and `docs/adr/ADR-010-feature-flag-gating.md` exist and are consistent with WS-10.1–WS-10.5 acceptance criteria before implementation starts
- session ownership pattern: confirm that `app/services/motif_service.py` session ownership design (post-FIX-1) is documented and will be followed by `ResearchService` per WS-10.3 AC-5

---

## PROMPT_2 Scope (code, priority order)

Phase 10 has not yet produced new files. PROMPT_2 should inspect the P2 Fix Queue target files to confirm fix status and record findings before Phase 10 implementation begins.

1. `app/services/motif_service.py` (security-critical: session ownership — FIX-1/FIX-2; must confirm before WS-10.3 can follow the same pattern)
2. `app/shared/config.py` (security-critical: flag freeze risk — FIX-3; `RESEARCH_AUGMENTATION_ENABLED` will be added here in WS-10.2)
3. `app/assistant/tools.py` (changed: stale `TOOLS` constant — FIX-6; phase gate for WS-10.5)
4. `app/assistant/chat.py` (changed: prompts extraction — FIX-4; phase gate for WS-10.5 framing additions)
5. `app/services/imagery.py` (changed: OTel metrics — FIX-5)
6. `app/services/motif_inductor.py` (changed: OTel metrics — FIX-5)
7. `tests/unit/test_motif_service.py` (regression check: idempotency test — CODE-7)
8. `tests/unit/test_assistant_chat.py` (regression check: build_tools usage assertion — CODE-8)
9. `tests/unit/test_assistant_facade.py` (regression check: rejected-motifs filter — CODE-10)
10. `docs/RESEARCH_AUGMENTATION.md` (new reference: verify §2–§5 exist and are consistent with WS-10.1–WS-10.5 acceptance criteria)
11. `docs/adr/ADR-009-research-trust-boundary.md` (new reference: verify trust boundary rules align with confidence vocabulary AC in WS-10.2 AC-2/AC-3)
12. `docs/adr/ADR-010-feature-flag-gating.md` (new reference: verify flag gating strategy is consistent with WS-10.4 AC-2 503-on-disabled behaviour and WS-10.5 AC-2/AC-5)

---

## Cycle Type

Full — Phase 9 Fix Queue (FIX-1 through FIX-6, CODE-1 through CODE-10) remains open and creates concrete Phase 10 implementation risks (flag freeze, session ownership, prompts module absence, stale tool constant). Phase 10 is active but has zero implemented code; this cycle establishes the pre-implementation baseline and confirms whether the Fix Queue was resolved before Phase 10 tasks began. All six P2 items require architecture and code inspection before WS-10.1 proceeds.

---

## Notes for PROMPT_3

- Primary consolidation focus: determine whether FIX-1 through FIX-6 were resolved before Phase 10 was declared active. CODEX_PROMPT.md §Fix Queue states these must be resolved "before Phase 10 queue" but the document itself also declares "Phase 10 active". If any of FIX-1/FIX-2/FIX-3/FIX-4/FIX-6 remain open, they must be escalated and resolved before WS-10.3, WS-10.2, WS-10.5 respectively can be marked DONE.
- Secondary focus: baseline reconciliation. CODEX_PROMPT.md records 200 tests; REVIEW_REPORT Cycle 9 records 238. Confirm the real unit-test count and record it as the authoritative Cycle 10 baseline.
- Tertiary focus: Phase 10 reference document completeness. Verify `docs/RESEARCH_AUGMENTATION.md` and both ADRs exist with the sections referenced in tasks_phase10.md Context-Refs. If any are absent, this is a blocker for implementation and must be flagged as a P1 finding.
- Carry-forward for Cycle 11: after WS-10.1 through WS-10.5 are implemented, the primary trust-boundary checks are: (a) research_results rows never appear in dream archive RAG ingestion; (b) confidence vocabulary is restricted to speculative/plausible/uncertain at every layer (synthesizer prompt, DTO, API response, assistant framing); (c) `research_motif_parallels` tool absent when flag is false; (d) POST /motifs/{id}/research returns 503 when flag is false.
---
