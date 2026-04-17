---
# STRATEGY_NOTE — Phase 10 Review
_Date: 2026-04-17 · Reviewing: Phase 10 (WS-10.1–WS-10.5)_

## Recommendation: Proceed

## Check Results

| Check | Verdict | Notes |
|-------|---------|-------|
| Phase coherence | COHERENT | WS-10.1–10.5 map cleanly to the stated Phase 10 goal: on-demand external research for mythology, folklore, and cultural parallels to confirmed inducted motifs, stored in research_results, exposed via API and a bounded assistant tool. Dependency graph (WS-10.1→10.2→10.3/10.4→10.5) is complete and internally consistent. No missing tasks. No out-of-scope tasks. |
| Open findings gate | CLEAR | No P0 or P1 findings are open. Six P2 findings (CODE-1–6 / FIX-1–6) and three P3 findings (CODE-7/8/10) remain open from Cycle 9. These do not meet the P0/P1 gate threshold. Gate is not blocked. |
| Architectural drift | ALIGNED | ARCHITECTURE.md §18 and §20 pre-document ResearchRetriever, ResearchSynthesizer, and the research_results table exactly as the task graph implements them. All Phase 9 completions (motif induction layer, Telegram interface, session persistence, versioning, pattern APIs) match §§9–17 of ARCHITECTURE.md. No undocumented components are being introduced. |
| Solution shape / governance / runtime drift | ALIGNED | Workflow shape, Standard governance, and T1 runtime are maintained. Research augmentation is an external HTTP call behind RESEARCH_AUGMENTATION_ENABLED=false, executed via asyncio.to_thread — no shell mutation, no privileged execution. Bounded tool-use loop (MAX_TOOL_ROUNDS=5) is preserved; WS-10.5 adds one bounded tool, not an autonomous agent loop. |
| ADR compliance | HONOURED (all ADRs) | See ADR detail table below. |
| RAG Profile gate | READY | RAG pipeline is unchanged in Phase 10. research_results must not enter the RAG index — enforced by task spec execution rules. retrieval_eval.md contains a valid 2026-04-16 advisory row for Cycle 9. Baseline metrics carry forward (hit@3=1.00, MRR=1.00, no-answer=1.00). No rag:-tagged tasks in Phase 10 is correct: the research layer is not a retrieval change. No stale index. No schema drift. |

## ADR Compliance Detail

| ADR | Verdict | Notes |
|-----|---------|-------|
| ADR-001 Append-only annotation versioning | HONOURED | Research results write only to research_results. No annotation_versions writes are introduced in Phase 10. |
| ADR-002 Single-user API key auth | HONOURED | WS-10.4 AC-4 explicitly requires X-API-Key on both research routes. No new auth model introduced. |
| ADR-003 Telegram adapter inside core repo | HONOURED | app/research/ lives inside the same repository. No separate service or second repository. |
| ADR-004 Bounded assistant tool facade | HONOURED | WS-10.5 adds facade.research_motif_parallels() returning frozen DTOs. Tool registered via build_tools() only when flag is true. No raw ORM or DB access exposed. |
| ADR-005 Managed transcription first | HONOURED | Voice pipeline (OpenAI Whisper) is untouched in Phase 10. |
| ADR-006 Persisted bot session state | HONOURED | bot_sessions table and Redis ephemeral-only rule are unchanged. |
| ADR-007 Compose-first deployment | HONOURED | Phase 10 adds no new runtime processes. Research pipeline runs inside the existing API process. Deployment topology is unchanged. |
| ADR-008 Inducted motifs and taxonomy themes separate | HONOURED | research_results is a third independent table. WS-10.3 AC-4 explicitly prohibits writes to dream_entries, dream_themes, or dream_chunks. |
| ADR-009 Research trust boundary and confidence vocabulary | HONOURED | WS-10.2 AC-3 prohibits confirmed/high/high confidence/verified/established in synthesizer output. WS-10.4 AC-3 requires a Literal interpretation_note on every API response. WS-10.5 AC-4 requires speculative/plausible/uncertain framing in the assistant system prompt. Source URL and retrieved_at are required schema fields (WS-10.1 AC-1). |
| ADR-010 Feature flag gating | HONOURED | RESEARCH_AUGMENTATION_ENABLED defaults false. Tool is absent from the catalog when the flag is false (WS-10.5 AC-5). API returns HTTP 503 when disabled (WS-10.4 AC-2). RESEARCH_API_KEY is conditional on the flag per ADR-010 §Consequences. |

## Findings / Blockers

_None. Recommendation is Proceed._

## Warnings

Non-blocking observations the Orchestrator should note in its state block:

1. **Six open P2 findings (CODE-1–6 / FIX-1–6) are documented in the Fix Queue as "resolve before Phase 10 queue".** They do not meet the P0/P1 gate threshold but represent technical debt that should be resolved as the first execution batch before WS-10.1 begins. The highest-risk items are: FIX-1 (double-commit risk in MotifService on caller-provided session), FIX-2 (no idempotency guard in MotifService — re-ingest overwrites confirmed motif status), and FIX-3 (lru_cache on get_settings() freezes RESEARCH_AUGMENTATION_ENABLED — see warning 2 below).

2. **FIX-3 / CODE-3 has direct Phase 10 impact.** ADR-010 §Consequences already documents that both feature flags are evaluated once at process startup due to lru_cache. FIX-3 proposes either removing the lru_cache (Option A) or formally documenting the restart requirement in ADR-010 and ENVIRONMENT.md (Option B). Either path must be resolved before Phase 10 implementation is complete so the RESEARCH_AUGMENTATION_ENABLED flag behavior is unambiguous and consistent with ADR-010. The Orchestrator should confirm the chosen option and close FIX-3 before or alongside WS-10.1.

3. **Open decision OD-5 (research API provider choice) must be resolved before WS-10.1 ends.** tasks_phase10.md §4 flags this explicitly. The retriever implementation must be provider-agnostic (configurable base_url + api_key from settings). Confirm OD-5 is resolved and recorded in DECISION_LOG.md as the first action within WS-10.1.

4. **ADR-003 through ADR-010 retain Status: Proposed rather than Accepted.** These decisions are operationally in force and reflected in implemented and planned code. The Doc Updater should update each to Accepted in a documentation-only pass. ADR-009 and ADR-010 become binding in Phase 10 and should be promoted to Accepted before WS-10.1 begins. This is non-blocking but creates an audit traceability gap.

5. **retrieval_eval.md version header (Last updated: 2026-04-13) is stale** relative to the 2026-04-16 advisory row present in the Evaluation History. Content is accurate; only the header date needs updating.

6. **CI is still not configured** (CODEX_PROMPT.md §Current State: "Last CI run: not yet configured"). This is a pre-existing risk carried forward from prior phases. It does not block Phase 10 but represents increasing exposure as the test count grows beyond 200.

7. **WS-9.7 (cross-dream motif pattern queries) was deferred** and recorded in DECISION_LOG.md as D-012. Phase 10 does not depend on WS-9.7. Included for continuity: WS-9.7 remains unscheduled and will require explicit planning before any phase that depends on cross-motif pattern queries.
---
