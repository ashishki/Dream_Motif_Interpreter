---
# META_ANALYSIS — Cycle 9
_Date: 2026-04-16 · Type: full_

## Project State

Phase 9 (WS-9.1 through WS-9.6) is functionally complete ahead of the formal gate review. All core deliverables are present in source: DB migration (009), ORM model, ImageryExtractor, MotifInductor, MotifGrounder, MotifService orchestrator, ingest feature-flag integration, REST API routes (`app/api/motifs.py`), assistant facade method (`get_dream_motifs`), tool registration with flag gate, and system prompt framing rules. WS-9.7 (Pattern Queries Extension) is optional and not yet implemented.

Next: WS-9.7 — Pattern Queries Extension (optional; may be deferred to Phase 9.1 or Phase 10).

Baseline: 238 pass, 9 skip (actual pytest run 2026-04-16).

Note: `docs/CODEX_PROMPT.md §Current State` records the baseline as "97 → 164 after WS-9.1" and lists WS-9.2 + WS-9.3 as the next task. Both figures are stale — actual baseline is 238 passing, WS-9.2 through WS-9.6 are already implemented. CODEX_PROMPT.md must be updated before implementation resumes.

Previous cycle baseline (Cycle 6 REVIEW_REPORT.md, 2026-04-14): 74 pass, 9 skip. Net +164 pass since Cycle 6 close, covering Phase 7–8 delivery (P6-T01, P6-T02, FIX-C8, FIX-C9, T17–T20) and Phase 9 WS-9.1 through WS-9.6. No intervening REVIEW_REPORT exists for T17–T20 or WS-9.1–9.6; this cycle is the first full audit covering those components.

---

## Open Findings

All 58 findings from Cycle 8 (as recorded in CODEX_PROMPT.md) are marked Closed. REVIEW_REPORT.md is from Cycle 6 (2026-04-14) and is stale with respect to T17–T20 and all Phase 9 work. The following findings are raised for this cycle based on source inspection and task-graph gap analysis.

| ID | Sev | Description | Files | Status |
|----|-----|-------------|-------|--------|
| CODE-51 | P2 | `docs/CODEX_PROMPT.md §Current State` baseline is stale: records "97 → 164 after WS-9.1" but actual baseline is 238 passing, 9 skipped. `§Next Task` lists WS-9.2 + WS-9.3 as next but both are already implemented. Must be updated before the next implementation task begins. | `docs/CODEX_PROMPT.md` | Open — new Cycle 9 |
| CODE-52 | P2 | `app/assistant/prompts.py` is listed as a required deliverable in `docs/tasks_phase9.md §WS-9.6 Files` but does not exist. Motif framing rules are embedded in `app/assistant/chat.py` as inline string literals. Confirm that this satisfies WS-9.6 AC-3 ("system prompt includes framing rules") or create `app/assistant/prompts.py` as a follow-up task. | `app/assistant/chat.py`, `app/assistant/prompts.py` (absent) | Open — new Cycle 9; verify or resolve |
| CODE-53 | P2 | WS-9.5 AC-4 requires rejected motifs to not appear in the default GET response, or the behavior must be explicitly defined. `app/api/motifs.py` must be inspected to confirm the filter is implemented and covered by a test case in `tests/unit/test_motifs_api.py`. | `app/api/motifs.py`, `tests/unit/test_motifs_api.py` | Open — new Cycle 9; inspect required |
| CODE-54 | P2 | WS-9.6 AC-2 requires `get_dream_motifs` to be absent from the tool catalog when `MOTIF_INDUCTION_ENABLED=false`. `app/assistant/tools.py:149` initialises `TOOLS` with `motif_induction_enabled=False` at module import time. WS-9.4 notes require the flag to be re-evaluated at request time, not at startup. Confirm whether `build_tools()` is called per request or once at import; if the latter, a flag change without redeploy will not take effect for the assistant tool catalog. | `app/assistant/tools.py:137–149` | Open — new Cycle 9; flag evaluation timing requires verification |
| CODE-55 | P3 | `docs/audit/REVIEW_REPORT.md` is stale (Cycle 6, 2026-04-14). Tasks T17–T20 and WS-9.1 through WS-9.6 have never been covered by a review report. This cycle's PROMPT_1 and PROMPT_2 outputs must cover the full gap. | `docs/audit/REVIEW_REPORT.md` | Open — new Cycle 9; addressed by this review cycle |
| CODE-56 | P3 | WS-9.7 (Pattern Queries Extension) is not implemented. No motif-related logic exists in `app/api/patterns.py` or `app/services/patterns.py`. The task is marked optional in `docs/tasks_phase9.md §WS-9.7`. Confirm deferral decision is recorded in `docs/DECISION_LOG.md`; if not, add an entry before Phase 10 planning begins. | `app/api/patterns.py`, `app/services/patterns.py`, `docs/DECISION_LOG.md` | Open — new Cycle 9; deferral confirmation needed |

---

## PROMPT_1 Scope (architecture)

- motif induction pipeline end-to-end: dataflow `ImageryExtractor` → `MotifInductor` → `MotifGrounder` → `MotifService` → `motif_inductions` table; verify the separation invariant from `dream_themes` at every layer (migration, ORM, service, API)
- feature flag gating: `MOTIF_INDUCTION_ENABLED` in `app/shared/config.py`; confirm the flag is read at ingest time (not startup) in `app/workers/ingest.py`; assess whether `build_tools()` in `app/assistant/tools.py` is evaluated per request or per import
- assistant tool registration: `build_tools()` call site, whether the tool catalog is rebuilt on each chat request when the flag is true, and whether a flag toggle takes effect without a redeploy
- API surface: `app/api/motifs.py` route registration in `app/main.py`; confirm GET, PATCH, and history endpoints are wired; confirm rejected-motif filter behavior
- system prompt framing: framing rules are in `app/assistant/chat.py`, not in a dedicated `prompts.py`; assess whether this satisfies WS-9.6 AC-3 and the file-list deliverable
- WS-9.7 deferral: confirm no partial or stub implementation exists in `app/api/patterns.py` or `app/services/patterns.py` that could cause confusion with taxonomy-based pattern routes

---

## PROMPT_2 Scope (code, priority order)

1. `app/services/motif_service.py` (new — WS-9.4 orchestrator; core correctness and flag-check timing)
2. `app/services/imagery.py` (new — WS-9.2 ImageryExtractor; grounded fragment production)
3. `app/services/motif_inductor.py` (new — WS-9.2 MotifInductor; open-vocabulary label generation; confirm no predefined taxonomy leak)
4. `app/services/motif_grounder.py` (new — WS-9.3 MotifGrounder; offset-verification logic vs. `app/llm/grounder.py` pattern)
5. `app/api/motifs.py` (new — WS-9.5 REST routes; GET filter, PATCH status update, history endpoint)
6. `app/models/motif.py` (new — WS-9.1 ORM model; column types, FK, CHECK constraint)
7. `alembic/versions/009_add_motif_inductions.py` (new — WS-9.1 migration; idempotency, no `dream_themes` modification)
8. `app/assistant/tools.py` (changed — WS-9.6 tool registration; `build_tools()` flag gate timing)
9. `app/assistant/facade.py` (changed — WS-9.6 `get_dream_motifs`; DTO return, no ORM leakage)
10. `app/assistant/chat.py` (changed — WS-9.6 system prompt framing rules; confirm all AC-3–AC-5 framing requirements are met)
11. `app/workers/ingest.py` (changed — WS-9.4 ingest integration; flag check at ingest time)
12. `app/shared/config.py` (changed — `MOTIF_INDUCTION_ENABLED` flag; default false confirmed)
13. `tests/unit/test_motif_service.py` (new — regression check; AC coverage)
14. `tests/unit/test_motif_grounder.py` (new — regression check; offset-verification paths)
15. `tests/unit/test_motif_inductor.py` (new — regression check; stub LLM client path)
16. `tests/unit/test_imagery_extractor.py` (new — regression check; stub LLM client path)
17. `tests/unit/test_motifs_api.py` (new — regression check; rejected-motif filter, status update)
18. `tests/unit/test_motif_model.py` (new — regression check; CHECK constraint, FK)

---

## Cycle Type

Full — Phase 9 core implementation (WS-9.1 through WS-9.6) is complete and has never been covered by a review cycle. REVIEW_REPORT.md is stale by two phases (T17–T20 and all Phase 9 work). All new components require architecture and code inspection. No hotfix queue is open; no P0 or P1 findings are outstanding entering the cycle.

---

## Notes for PROMPT_3

- Primary consolidation focus: verify that the `dream_themes` / `motif_inductions` separation invariant holds throughout the full stack. Any finding that inducted motifs can be written to or read from `dream_themes` at any layer is a stop-ship condition.
- Secondary focus: `MOTIF_INDUCTION_ENABLED` flag evaluation timing. The WS-9.4 note is explicit — the flag must be checked at ingest time, not at startup. The same timing question applies to the assistant tool catalog (`build_tools()`). Confirm both or raise a P2 finding.
- Tertiary focus: `app/assistant/prompts.py` absence. The WS-9.6 file list names it as a required deliverable. If the framing lives only in `chat.py`, either confirm the task file is wrong or raise a targeted follow-up task to extract framing to `prompts.py`.
- CODEX_PROMPT.md staleness (CODE-51) must be resolved before the next implementation session. Update baseline to 238 passing, mark WS-9.2 through WS-9.6 as complete, and set Next Task to WS-9.7 or Phase 10 planning.
- WS-9.7 deferral (CODE-56): record the deferral decision in `docs/DECISION_LOG.md` before Phase 10 planning if not already present.
- Baseline delta for PROMPT_3 snapshot: 74 pass (Cycle 6 close) → 238 pass (Cycle 9 open). Net +164.
---
