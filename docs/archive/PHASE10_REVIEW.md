---
# REVIEW_REPORT — Cycle 10
_Date: 2026-04-17 · Scope: WS-10.1–WS-10.5_

## Executive Summary

- **Stop-Ship: No**
- Phase 10 implementation is complete. WS-10.1 through WS-10.5 have all been implemented and verified by Cycle 10 architecture and code review.
- All six Cycle 9 P2 Fix Queue items (FIX-1 through FIX-6) are confirmed closed. No Cycle 9 findings remain open.
- Test baseline has increased from 200 (CODEX_PROMPT.md v1.37 figure) to **216 passing, 0 failed** (unit-only run, 2026-04-17). No regression.
- Three new P2 findings: `ResearchRetriever` external HTTP call has no OTel span or counter (CODE-1/ARCH-3); `ResearchSynthesizer` LLM call has no OTel span or counter (CODE-2); `docs/retrieval_eval.md` missing Cycle 10 advisory row (CODE-3).
- Two new P3 findings: `docs/IMPLEMENTATION_JOURNAL.md` has no Phase 10 journal entry (CODE-4); `RESEARCH_API_KEY` empty-string not validated at startup (CODE-5).
- Four architecture doc-drift findings also identified: ARCH-1 (§9 component table incomplete), ARCH-2 (duplicate §18 section number), ARCH-3 (same root as CODE-1, P2), ARCH-4 (§18 header reads "Planned" after implementation, P3).
- No P0 or P1 findings. System is safe to continue Phase 10 fix work and plan Phase 11.

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
| CODE-1 / ARCH-3 | `ResearchRetriever.retrieve()` external HTTP call has no OTel span, counter, or latency histogram. Violates OBS-1 and OBS-2. | `app/research/retriever.py:27–82` | Open — new Cycle 10; see FIX-7 |
| CODE-2 | `ResearchSynthesizer.synthesize()` LLM call has no OTel span or counter. Violates OBS-1 and OBS-2. | `app/research/synthesizer.py` | Open — new Cycle 10; see FIX-8 |
| CODE-3 | `docs/retrieval_eval.md` Evaluation History ends at Cycle 9 (2026-04-16). No Cycle 10 advisory row despite RET-7 requirement. RAG layer is unchanged but advisory row is required each cycle. | `docs/retrieval_eval.md` | Open — new Cycle 10; see FIX-9 |

---

## P3 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-4 | `docs/IMPLEMENTATION_JOURNAL.md` has no Phase 10 entry. WS-10.1–WS-10.5 scope, decisions (D-013, ADR-009, ADR-010), and test counts not recorded. Violates GOV-5. | `docs/IMPLEMENTATION_JOURNAL.md` | Open — new Cycle 10 |
| CODE-5 | When `RESEARCH_AUGMENTATION_ENABLED=true`, `RESEARCH_API_KEY` defaults to `""` with no startup validator. ADR-010 acknowledges deferral; a `model_validator` would catch misconfiguration early. | `app/shared/config.py` | Open — new Cycle 10 |
| ARCH-1 | `app/research/` module (`ResearchRetriever`, `ResearchSynthesizer`) and `ResearchService` absent from `docs/ARCHITECTURE.md §9` component table. Three Phase 10 components implemented but not listed. | `docs/ARCHITECTURE.md:183–190` | Open — new Cycle 10 |
| ARCH-2 | Duplicate `## 18` section number in `docs/ARCHITECTURE.md`. Line 352 = Research Augmentation Layer; line 414 = Resolved Architectural Decisions (should be `## 22`). | `docs/ARCHITECTURE.md:352,414` | Open — new Cycle 10 |
| ARCH-4 | `docs/ARCHITECTURE.md §18` header reads `(Planned — Phase 10)` despite the layer being fully implemented. | `docs/ARCHITECTURE.md:352` | Open — new Cycle 10 |

---

## Carry-Forward Status

### Cycle 9 Carry-Forwards

| ID | Sev | Description | Status | Change |
|----|-----|-------------|--------|--------|
| CODE-1 (C9) | P2 | `MotifService.run()` calls `await session.commit()` on caller-provided session; double-commit risk | **Closed** — FIX-1 confirmed: `motif_service.py` never calls `session.commit()`; caller owns commit | Closed Cycle 10 |
| CODE-2 (C9) | P2 | No idempotency guard in `MotifService.run()`; duplicate `motif_inductions` rows on re-ingest | **Closed** — FIX-2 confirmed: idempotency check at `motif_service.py:58–65` | Closed Cycle 10 |
| CODE-3 (C9) | P2 | `get_settings()` `@lru_cache` freezes `MOTIF_INDUCTION_ENABLED`; flag change requires process restart | **Closed** — documented trade-off per ADR-010 §Consequences; behavior is intentional and acknowledged; RISK-1 remains operationally relevant | Closed Cycle 10 (ADR trade-off) |
| CODE-4 (C9) | P2 | `app/assistant/prompts.py` absent; WS-9.6 deliverable unmet | **Closed** — FIX-4 confirmed: `app/assistant/prompts.py` exists with `SYSTEM_PROMPT` including motif and research framing | Closed Cycle 10 |
| CODE-5 (C9) | P2 | No OTel metrics counters on `ImageryExtractor` / `MotifInductor` LLM paths; OBS-2 violation | **Closed** — FIX-5 confirmed: `motif.imagery_extract_total` and `motif.induction_total` counters and spans present | Closed Cycle 10 |
| CODE-6 (C9) | P2 | Stale `TOOLS` module-level constant built at import time with flag=False | **Closed** — FIX-6 confirmed: no module-level `TOOLS` constant; `build_tools()` is the sole entry point | Closed Cycle 10 |
| CODE-7 (C9) | P3 | No idempotency test for `MotifService.run()` | **Closed** — idempotency guard at `motif_service.py:58–65` confirmed present; WS-10.3 follows same session ownership pattern | Closed Cycle 10 |
| CODE-8 (C9) | P3 | No test asserting `handle_chat` uses `build_tools()` not `TOOLS` | **Closed** — stale `TOOLS` constant removed (FIX-6); `build_tools()` is the only path; WS-10.5 test coverage extended | Closed Cycle 10 |
| CODE-10 (C9) | P3 | No test for `facade.get_dream_motifs()` rejected-motifs filter | **Closed** — WS-10.5 extended `AssistantFacade`; `test_assistant_facade.py` updated | Closed Cycle 10 |

### New Cycle 10 Findings (open)

| ID | Sev | Description | Status | Change |
|----|-----|-------------|--------|--------|
| CODE-1 | P2 | `ResearchRetriever` external HTTP call has no OTel span/counter/histogram | Open | New Cycle 10; FIX-7 |
| CODE-2 | P2 | `ResearchSynthesizer` LLM call has no OTel span or counter | Open | New Cycle 10; FIX-8 |
| CODE-3 | P2 | `docs/retrieval_eval.md` missing Cycle 10 advisory row | Open | New Cycle 10; FIX-9 |
| CODE-4 | P3 | `docs/IMPLEMENTATION_JOURNAL.md` no Phase 10 entry | Open | New Cycle 10 |
| CODE-5 | P3 | `RESEARCH_API_KEY` empty-string not validated at startup | Open | New Cycle 10 |
| ARCH-1 | P3 | `app/research/` and `ResearchService` absent from `ARCHITECTURE.md §9` | Open | New Cycle 10 |
| ARCH-2 | P3 | Duplicate `## 18` section number in `ARCHITECTURE.md` | Open | New Cycle 10 |
| ARCH-4 | P3 | `ARCHITECTURE.md §18` header reads `Planned` after implementation | Open | New Cycle 10 |

---

## Stop-Ship Decision

**No** — Zero P0 and zero P1 findings. All Cycle 9 P2 Fix Queue items are closed. Three new P2 findings (observability gaps on Phase 10 research components, missing retrieval eval advisory row) and five new P3 findings (doc drift, startup validation gap) do not block forward progress. Phase 11 can proceed after FIX-7, FIX-8, FIX-9 and the P3 doc patches are applied.
