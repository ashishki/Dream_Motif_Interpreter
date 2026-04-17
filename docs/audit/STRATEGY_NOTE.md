---
# STRATEGY_NOTE — Phase 11 Review
_Date: 2026-04-17 · Reviewing: Phase 11 (Feedback Loop)_

## Recommendation: Proceed

## Check Results

| Check | Verdict | Notes |
|-------|---------|-------|
| Phase coherence | COHERENT | Phase 11 scope is precisely and consistently defined across PHASE_PLAN.md §11, FEEDBACK_LOOP.md, and ARCHITECTURE.md §§19–20. Three deliverables — `assistant_feedback` table + migration `011_add_feedback`, digit-reply capture in the Telegram handler, and `GET /feedback` admin route — map directly to the stated goal of a lightweight quality signal for human review. No tasks are missing; no out-of-scope tasks are implied. The spec explicitly defers fine-tuning, RLHF, and automated model updates, which is consistent with the system's workflow shape. |
| Open findings gate | CLEAR | Fix Queue is marked clear in CODEX_PROMPT.md §Next Task: "FIX-7, FIX-8, FIX-9 are CLOSED (applied 2026-04-17)." Current Open Findings table lists 0 P0, 0 P1 findings. Remaining open items are CODE-1 through CODE-5, ARCH-1, ARCH-2, ARCH-4 — all P2 or P3 severity. The P0/P1 gate is not blocked. |
| Architectural drift | ALIGNED | ARCHITECTURE.md §19 pre-documents the `assistant_feedback` table and its purpose as a quality signal only. §20 planned storage table lists `assistant_feedback` for Phase 11. The digit-reply capture pattern fits the existing Telegram handler module (`app/telegram/handlers.py`). `GET /feedback` follows the same pattern as all existing routers in `app/api/`. No undocumented components are being introduced. Existing component table (§9) will require a new `app/api/feedback.py` row after implementation — a doc update, not an architectural gap that blocks this phase. |
| Solution shape / governance / runtime drift | ALIGNED | Workflow shape, Standard governance, and T1 runtime are preserved. The feedback table is a simple write-only append path triggered by a deterministic digit-detection rule in the Telegram handler — no LLM behavior is introduced. `GET /feedback` is a read-only paginated query behind the existing API key auth. No shell mutation, no privileged execution, no autonomous tool use. The spec explicitly states feedback scores must not alter model behavior automatically, which keeps the bounded tool-use loop (MAX_TOOL_ROUNDS=5) and the assistant system prompt unchanged. No drift into agentic or planning profiles. |
| ADR compliance | HONOURED (all ADRs) | See ADR detail table below. |
| RAG Profile gate | READY | Phase 11 introduces no changes to chunking, embedding, ranking, or evidence assembly. `assistant_feedback` must not be added to the RAG ingestion pipeline (same isolation rule applied to `research_results` in Phase 10). Cycle 10 advisory row is present in `retrieval_eval.md` (2026-04-17). T12 baseline metrics carry forward (hit@3=1.00, MRR=1.00, no-answer=1.00). No rag:-tagged tasks are required in Phase 11. No stale index. No schema drift risk to the RAG layer. |

## ADR Compliance Detail

| ADR | Verdict | Notes |
|-----|---------|-------|
| ADR-001 Append-only annotation versioning | HONOURED | `assistant_feedback` is a new independent table. No writes to `annotation_versions` are implied by Phase 11. The feedback path does not interact with the theme curation or rollback system. |
| ADR-002 Single-user API key auth | HONOURED | `GET /feedback` requires the standard `X-API-Key` header per FEEDBACK_LOOP.md §4. No new auth model is introduced. The existing middleware in `app/main.py` covers this without modification. |
| ADR-003 Telegram adapter inside core repo | HONOURED | Digit-reply detection lives inside `app/telegram/handlers.py`. Persistence goes through `app/assistant/facade.py` or a new `app/models/feedback.py` model — all inside the same repository. |
| ADR-004 Bounded assistant tool facade | HONOURED | Feedback capture is triggered by a detection rule in the Telegram handler, not by adding a new tool to the bounded tool-use loop. The `AssistantFacade` may gain a `record_feedback()` method returning a frozen DTO; no raw ORM or DB access is exposed to the conversation layer. The tool catalog is unchanged. |
| ADR-005 Managed transcription first | HONOURED | Voice pipeline (OpenAI Whisper) is untouched in Phase 11. |
| ADR-006 Persisted bot session state | HONOURED | `bot_sessions` table and Redis ephemeral-only rule are unchanged. Feedback rows go to `assistant_feedback`, not `bot_sessions`. |
| ADR-007 Compose-first deployment | HONOURED | Phase 11 adds no new runtime processes. The feedback persistence path runs inside the existing Telegram bot process. `GET /feedback` runs inside the existing API process. No docker-compose topology change is required. |
| ADR-008 Inducted motifs and taxonomy themes separate | HONOURED | `assistant_feedback` is a fourth independent table. No writes to `dream_themes`, `dream_entries`, or `motif_inductions` are introduced. The feedback layer has no analytical relationship to the motif or taxonomy subsystems. |
| ADR-009 Research trust boundary and confidence vocabulary | HONOURED | Phase 11 does not use external search or the research pipeline. The confidence vocabulary constraint is not implicated. |
| ADR-010 Feature flag gating | N/A with note | Phase 11 as specified does not introduce a feature flag. FEEDBACK_LOOP.md and PHASE_PLAN.md §11 do not define one. This is a conscious scope choice: feedback capture is a passive UX addition with no new LLM calls and no new ingest-path writes, so the default-off gate rationale from ADR-010 does not apply. If the Orchestrator prefers a `FEEDBACK_ENABLED` flag for consistency with prior phases, this is an open decision to make before implementation begins (see Warnings §1). |

## Findings / Blockers

_None. Recommendation is Proceed._

## Warnings

Non-blocking observations the Orchestrator should note in its state block:

1. **No feature flag defined for Phase 11.** ADR-010 introduced default-off flags for Phases 9 and 10 because both added LLM calls during ingest or tool-use paths. Phase 11 adds no LLM calls and no ingest-path side effects; the digit-detection logic is deterministic. A feature flag is not architecturally required. However, for operational consistency, the Orchestrator may choose to add `FEEDBACK_ENABLED` (default `true`, since the feature is lightweight and always-safe). This decision should be made explicitly before WS-11.1 begins and recorded in `DECISION_LOG.md`. If no flag is added, that is also a valid explicit choice.

2. **`context` JSONB field content must be defined before implementation.** FEEDBACK_LOOP.md §3 states the `context` field "captures enough information to identify which response was rated (e.g., message ID, response summary, tool calls made)" but does not specify an exact schema. Before WS-11.1 (DB migration), the Orchestrator should record the exact JSONB structure in the task spec or in FEEDBACK_LOOP.md §3 to prevent ambiguity during implementation. Minimum fields: `message_id` (Telegram message ID of the assistant response), `response_summary` (truncated first N chars of the response text). Tool call log is optional.

3. **Digit-reply detection interacts with session state.** FEEDBACK_LOOP.md §2 requires the rating message to "immediately follow a substantive assistant response." The current `handle_chat()` flow in `app/assistant/chat.py` does not maintain a "last response was substantive" flag in `bot_sessions`. The Telegram handler will need a mechanism to track whether the previous bot message was a substantive response eligible for rating. This is an implementation detail, but the task graph (tasks_phase11.md) must include it explicitly to avoid an ambiguity blocker during implementation. One clean approach: store `last_response_type` in the session or as a short-lived in-memory flag in `bot_data`.

4. **Optional comment capture is explicitly deferred.** FEEDBACK_LOOP.md §2 states "Comment capture is optional and must be implemented explicitly; it is not implied by digit capture alone." The Phase 11 task graph should explicitly mark comment capture as in-scope or out-of-scope. If out-of-scope, the `comment` column is still included in the migration (as nullable) but no capture logic is wired. This prevents scope ambiguity during implementation.

5. **Eight open findings (CODE-1/2/3/4/5, ARCH-1/2/4) from Cycle 10 remain open.** They are all P2 or P3. They do not block Phase 11. The Orchestrator should resolve the P2 items (CODE-1, CODE-2, CODE-3) as the first fix batch before WS-11.1 begins, consistent with the pattern established in prior phases. CODE-5 (`RESEARCH_API_KEY` missing model_validator) and ARCH-1/2/4 (doc patches) can be batched into a single pre-phase fix pass.

6. **CI is still not configured** (CODEX_PROMPT.md §Current State: "Last CI run: not yet configured"). This is a pre-existing risk carried forward from prior phases. Test count is now 216; the absence of automated CI represents increasing exposure. Not a Phase 11 blocker, but the risk grows with each phase.

7. **ADR-003 through ADR-008 retain Status: Proposed rather than Accepted.** ADR-009 and ADR-010 are Accepted. The remaining ADRs are operationally in force. A documentation-only pass to update their status to Accepted would improve audit traceability. Non-blocking; can be included in the pre-phase doc patch (Warning §5).
---
