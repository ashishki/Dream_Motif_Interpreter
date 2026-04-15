# ADR-010: Phase 9 and Phase 10 Capabilities Are Gated by Default-Off Feature Flags

Date: 2026-04-15
Status: Proposed

## Context

Phase 9 (motif induction) and Phase 10 (research augmentation) both introduce new LLM calls and new data writes during the ingest and assistant tool-use paths. These capabilities need to be deployable before they are enabled, and reversible without a code deployment if a problem is found.

## Decision

Phase 9 (`MOTIF_INDUCTION_ENABLED`) and Phase 10 (`RESEARCH_AUGMENTATION_ENABLED`) are gated by environment variable feature flags defaulting to `false`. Neither is enabled in production until manually activated by setting the flag to `true`.

## Rationale

Both phases introduce new LLM calls and new database writes in paths that are currently stable. Running with default-off allows:

- safe deployment of the new code without activating new behavior
- rollback by environment variable change without a code deployment
- controlled activation after the operator has confirmed the migrations are applied and the configuration is correct
- independent activation of each phase (Phase 9 can be enabled without Phase 10)

The alternative — enabling capabilities at deployment — would mean any deployment of Phase 9 code activates induction on all subsequent ingests. That couples code deployment to capability activation, reducing operational control.

## Consequences

- `MOTIF_INDUCTION_ENABLED` defaults to `false`. When `false`, ingest does not call `MotifService`, the `get_dream_motifs` tool is not registered, and no rows are written to `motif_inductions`.
- `RESEARCH_AUGMENTATION_ENABLED` defaults to `false`. When `false`, the `research_motif_parallels` tool is not registered and `ResearchRetriever` is never called.
- Both flags must be checked at runtime, not at startup, so that a flag change takes effect on the next operation without restarting the process.
- Migrations `009_add_motif_inductions` and `010_add_research_results` may be applied independently of the flags. The tables can exist before the features are enabled.
- `RESEARCH_API_KEY` is required only when `RESEARCH_AUGMENTATION_ENABLED=true`; it must not be required at startup if the flag is off.
