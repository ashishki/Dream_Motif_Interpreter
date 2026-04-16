# Phase Report — Phase 9: Motif Abstraction and Induction
Date: 2026-04-16
Health: OK

## What was built

Phase 9 delivered the open-vocabulary motif abstraction pipeline from scratch.

**WS-9.1 — DB Migration + ORM Models**
New `motif_inductions` table with CHECK constraints (`status: draft/confirmed/rejected`, `confidence: high/moderate/low`), FK to `dream_entries` (RESTRICT), and JSONB `fragments` column. `MotifInduction` ORM model. `AnnotationVersion` extended to cover `entity_type='motif_induction'`. The table is completely separate from `dream_themes` — this separation is architecturally enforced and tested.

**WS-9.2 — ImageryExtractor + MotifInductor**
`ImageryExtractor` (Claude Haiku) extracts concrete physical imagery fragments with character offsets from raw dream text. `MotifInductor` (Claude Sonnet 4.6) inductively forms abstract motif labels from those fragments using open-vocabulary generation — no predefined taxonomy is consulted. Both components are dependency-injectable for testing.

**WS-9.3 — MotifGrounder**
Deterministic offset-verification service. Checks that imagery fragment text matches the source dream text at the claimed character positions. No LLM calls. Returns verified/unverified flags per fragment.

**WS-9.4 — MotifService + Ingest Integration**
`MotifService` orchestrates the three-stage pipeline and persists `motif_inductions` rows (status=draft). Wired into `workers/ingest.py` behind `MOTIF_INDUCTION_ENABLED` env flag (default false). LLM failures are isolated — ingest job continues if induction fails.

**WS-9.5 — Motifs API**
`GET /dreams/{id}/motifs` (rejected excluded by default), `PATCH /dreams/{id}/motifs/{id}` (confirm/reject + AnnotationVersion), `GET /dreams/{id}/motifs/history`. Auth via existing middleware.

**WS-9.6 — Assistant Tool + Facade + System Prompt**
`AssistantFacade.get_dream_motifs()` returns frozen DTOs. `build_tools()` conditionally includes `get_dream_motifs` when flag is on. System prompt updated with 6 framing rules: motifs are "abstractions" not "interpretations", confidence levels must be communicated, draft motifs presented as suggestions not findings.

**WS-9.7 — deferred** (Pattern Queries Extension): meaningful only after confirmed motif accumulation. Recorded in DECISION_LOG.md D-012.

## Test delta
- Before Phase 9: 97 unit tests
- After Phase 9: 187 unit tests (+90), ~238 total
- No regressions across all cycles

## Open findings (Cycle 9)
- P2 (6): FIX-1–FIX-6 in Fix Queue — session commit ownership, idempotency guard, lru_cache/ADR-010 alignment, prompts.py extraction, OTel metrics counters, stale TOOLS constant
- P3 (3 open): CODE-7 (idempotency test), CODE-8 (build_tools test), CODE-10 (facade filter test)

## Health verdict
OK — no P0/P1 findings. Phase gate passed. P2 fixes required before Phase 10 implementation.

## Next
Fix Queue FIX-1 through FIX-6, then Phase 10 (Research Augmentation) or Phase 11 (Feedback Loop).
