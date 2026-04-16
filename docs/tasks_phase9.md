# Task Graph — Dream Motif Interpreter Phase 9

Version: 1.0
Last updated: 2026-04-15
Status: Planned task graph for Phase 9 — Motif Abstraction and Induction

## 1. Purpose

This file is the implementation task graph for Phase 9 of Dream Motif Interpreter.

It exists so the repository can preserve:

- Phase 6–8 execution history in `docs/tasks_phase6.md`
- a clean execution source for Phase 9 motif abstraction work
- continuity between the completed backend and Telegram platform and the new induction capability

## 2. How To Use This File

- use this file as the active implementation authority for Phase 9 motif abstraction work
- treat `docs/tasks_phase6.md` as the authoritative history for Phases 6–8
- read `Context-Refs` before implementation begins
- do not start coding Phase 9 from architecture docs alone when a task here exists

Reference documents:

- `docs/MOTIF_ABSTRACTION.md`
- `docs/ARCHITECTURE.md §17`
- `docs/PHASE_PLAN.md §9`
- `docs/adr/ADR-008-motif-induction-vs-taxonomy.md`
- `docs/adr/ADR-010-feature-flag-gating.md`

Execution rule:

- inducted motifs must never be stored in or merged with `dream_themes`
- the `MOTIF_INDUCTION_ENABLED` flag must gate all ingest-time calls to `MotifService`
- `MotifGrounder` must reuse the offset-verification pattern from the existing `Grounder`

## 3. Phase 9 — Motif Abstraction and Induction

Goal: given a dream entry, inductively derive higher-order abstract motifs from concrete imagery without using a predefined taxonomy. Store results in `motif_inductions`. Expose via API and assistant tool. Gate everything behind `MOTIF_INDUCTION_ENABLED`.

Phase gate:

- induction pipeline runs end-to-end for a dream entry when `MOTIF_INDUCTION_ENABLED=true`
- inducted motifs stored in `motif_inductions`, never in `dream_themes`
- `GET /dreams/{id}/motifs` returns motifs with confidence and status
- assistant tool `get_dream_motifs` presents motifs with correct framing
- feature flag disables pipeline completely when `false`

Dependency graph:

```
WS-9.1 → WS-9.2
WS-9.1 → WS-9.3
WS-9.2 + WS-9.3 → WS-9.4
WS-9.4 → WS-9.5
WS-9.4 → WS-9.6
WS-9.5 → WS-9.7 (optional)
```

---

## WS-9.1: DB Migration and ORM Models ✅

Owner:      codex
Phase:      9
Type:       persistence
Depends-On: none

Objective: |
  Add the motif_inductions table migration and ORM model. Extend AnnotationVersion
  support to cover motif status transitions.

Acceptance-Criteria:
  - id: AC-1
    description: "Migration 009_add_motif_inductions creates the motif_inductions table with all required columns: id, dream_id, label, rationale, confidence, status, fragments (JSONB), model_version, created_at."
  - id: AC-2
    description: "ORM model for MotifInduction is defined with correct column types and the foreign key to dream_entries."
  - id: AC-3
    description: "The status column has a CHECK constraint permitting only: draft, confirmed, rejected."
  - id: AC-4
    description: "AnnotationVersion records can be written for motif status transitions."
  - id: AC-5
    description: "Migration is idempotent and does not modify dream_themes or any existing table."

Files:
  - alembic/versions/009_add_motif_inductions.py
  - app/models/motif.py
  - docs/MOTIF_ABSTRACTION.md

Context-Refs:
  - docs/MOTIF_ABSTRACTION.md §3
  - docs/ARCHITECTURE.md §17
  - docs/adr/ADR-008-motif-induction-vs-taxonomy.md

Notes: |
  The motif_inductions table must be entirely separate from dream_themes.
  Do not add any foreign key or reference from dream_themes to motif_inductions
  or vice versa at the schema level. The separation must be visible in the migration.

---

## WS-9.2: ImageryExtractor + MotifInductor LLM Pipeline

Owner:      codex
Phase:      9
Type:       service
Depends-On: WS-9.1

Objective: |
  Implement the two-stage LLM pipeline: ImageryExtractor extracts concrete imagery
  fragments from dream text; MotifInductor forms abstract motif labels from those
  fragments.

Acceptance-Criteria:
  - id: AC-1
    description: "ImageryExtractor produces a list of grounded imagery fragments with character offsets from a dream entry text."
  - id: AC-2
    description: "MotifInductor takes imagery fragments and returns a list of motif candidates, each with: label (string), rationale (string), confidence (high | moderate | low)."
  - id: AC-3
    description: "MotifInductor does not select from a predefined vocabulary. Labels are model-generated open-vocabulary strings."
  - id: AC-4
    description: "Neither component writes to dream_themes."
  - id: AC-5
    description: "Both components can be tested with a stub LLM client without real API calls."

Files:
  - app/services/imagery.py
  - app/services/motif_inductor.py
  - tests/unit/test_imagery_extractor.py
  - tests/unit/test_motif_inductor.py
  - docs/MOTIF_ABSTRACTION.md

Context-Refs:
  - docs/MOTIF_ABSTRACTION.md §2
  - docs/ARCHITECTURE.md §17
  - docs/adr/ADR-008-motif-induction-vs-taxonomy.md

Notes: |
  The LLM call in MotifInductor is the open-vocabulary induction step.
  The prompt must not include a list of existing theme_categories.
  Grounding happens in WS-9.3; this workstream produces unverified candidates only.

---

## WS-9.3: MotifGrounder

Owner:      codex
Phase:      9
Type:       service
Depends-On: WS-9.1

Objective: |
  Implement MotifGrounder, which verifies that imagery fragments cited as support
  for inducted motifs are accurately grounded in the source dream text by checking
  fragment text against source character offsets.

Acceptance-Criteria:
  - id: AC-1
    description: "MotifGrounder accepts a dream entry text and a list of imagery fragments with character offsets."
  - id: AC-2
    description: "For each fragment, MotifGrounder verifies the fragment text matches the source text at the given offsets."
  - id: AC-3
    description: "Fragments that fail offset verification are marked verified=false."
  - id: AC-4
    description: "The offset-verification logic is structurally equivalent to the existing Grounder implementation."
  - id: AC-5
    description: "MotifGrounder can be tested independently with fixture dream text and fragment data."

Files:
  - app/services/motif_grounder.py
  - tests/unit/test_motif_grounder.py

Context-Refs:
  - docs/MOTIF_ABSTRACTION.md §2 (Stage 3)
  - app/llm/grounder.py (existing offset-verification reference)

Notes: |
  Reuse the offset-verification pattern from app/llm/grounder.py. Do not copy
  the full Grounder class; adapt only the fragment-offset verification logic.
  MotifGrounder operates on imagery fragments, not theme-support fragments.

---

## WS-9.4: MotifService Orchestrator + Ingest Integration

Owner:      codex
Phase:      9
Type:       service
Depends-On: WS-9.2, WS-9.3

Objective: |
  Implement MotifService, which orchestrates ImageryExtractor, MotifInductor, and
  MotifGrounder into a single pipeline call. Wire MotifService into the ingest
  pipeline behind the MOTIF_INDUCTION_ENABLED feature flag.

Acceptance-Criteria:
  - id: AC-1
    description: "MotifService calls ImageryExtractor, then MotifInductor, then MotifGrounder in order."
  - id: AC-2
    description: "MotifService writes results to motif_inductions with status=draft and the correct model_version."
  - id: AC-3
    description: "The ingest pipeline calls MotifService only when MOTIF_INDUCTION_ENABLED=true."
  - id: AC-4
    description: "When MOTIF_INDUCTION_ENABLED=false, ingest proceeds without any call to MotifService and no motif_inductions rows are written."
  - id: AC-5
    description: "MotifService does not write to dream_themes."

Files:
  - app/services/motif_service.py
  - app/workers/ingest.py
  - app/shared/config.py
  - docs/ENVIRONMENT.md
  - docs/MOTIF_ABSTRACTION.md

Context-Refs:
  - docs/MOTIF_ABSTRACTION.md §2
  - docs/ENVIRONMENT.md §6
  - docs/adr/ADR-010-feature-flag-gating.md

Notes: |
  The MOTIF_INDUCTION_ENABLED flag must default to false. The ingest worker
  must check this flag before calling MotifService. The flag check must happen
  at ingest time, not at startup, so that a flag change takes effect without
  redeploying code.

---

## WS-9.5: API Routes

Owner:      codex
Phase:      9
Type:       api
Depends-On: WS-9.4

Objective: |
  Implement the REST API routes for motif retrieval and status updates.

Acceptance-Criteria:
  - id: AC-1
    description: "GET /dreams/{id}/motifs returns all motif_inductions rows for the dream with label, confidence, status, rationale, and fragments."
  - id: AC-2
    description: "PATCH /dreams/{id}/motifs accepts a motif ID and a target status (confirmed or rejected) and updates the row."
  - id: AC-3
    description: "GET /dreams/{id}/motifs/history returns the annotation version history for motif status changes."
  - id: AC-4
    description: "Rejected motifs are not returned in the default GET response (or are clearly marked; define the behavior explicitly)."
  - id: AC-5
    description: "API routes are covered by unit tests with a test DB or stub service."

Files:
  - app/api/motifs.py
  - app/main.py
  - tests/unit/test_motifs_api.py

Context-Refs:
  - docs/MOTIF_ABSTRACTION.md §3
  - docs/PHASE_PLAN.md §9
  - docs/ARCHITECTURE.md §17

---

## WS-9.6: Assistant Tool + Facade Method + System Prompt Update

Owner:      codex
Phase:      9
Type:       assistant
Depends-On: WS-9.4

Objective: |
  Expose inducted motifs to the Telegram assistant via a bounded tool (get_dream_motifs),
  a facade method, and an updated system prompt that defines correct framing requirements.

Acceptance-Criteria:
  - id: AC-1
    description: "AssistantFacade exposes a get_dream_motifs(dream_id) method that returns motif data without exposing ORM objects."
  - id: AC-2
    description: "The get_dream_motifs tool is registered in the tool catalog only when MOTIF_INDUCTION_ENABLED=true."
  - id: AC-3
    description: "The system prompt includes framing rules for presenting motif confidence levels and status."
  - id: AC-4
    description: "The assistant does not present draft motifs as confirmed findings."
  - id: AC-5
    description: "The assistant does not use the word 'interpretation' to describe inducted motifs."

Files:
  - app/assistant/facade.py
  - app/assistant/tools.py
  - app/assistant/prompts.py
  - docs/TELEGRAM_INTERACTION_MODEL.md

Context-Refs:
  - docs/TELEGRAM_INTERACTION_MODEL.md §12
  - docs/MOTIF_ABSTRACTION.md §6
  - docs/adr/ADR-004-bounded-assistant-tool-facade.md

Notes: |
  The tool must be absent from the catalog when MOTIF_INDUCTION_ENABLED=false.
  See docs/TELEGRAM_INTERACTION_MODEL.md §12 for the full framing requirements
  that the system prompt must encode.

---

## WS-9.7: Pattern Queries Extension (Optional)

Owner:      codex
Phase:      9
Type:       analytics
Depends-On: WS-9.5

Objective: |
  Optionally extend the pattern analysis queries to include confirmed inducted motifs,
  allowing cross-dream pattern analysis over motif labels in addition to theme categories.

Acceptance-Criteria:
  - id: AC-1
    description: "Pattern queries can optionally filter or group by confirmed motif labels."
  - id: AC-2
    description: "Motif-based pattern results are clearly distinguished from taxonomy-based pattern results in API responses."
  - id: AC-3
    description: "This extension does not modify the existing theme-based pattern query behavior."

Files:
  - app/api/patterns.py
  - app/services/patterns.py

Context-Refs:
  - docs/MOTIF_ABSTRACTION.md §5
  - docs/ARCHITECTURE.md §17

Notes: |
  This workstream is optional for the Phase 9 gate. It may be deferred to a
  Phase 9.1 or Phase 10 follow-on if the core pipeline (WS-9.1 through WS-9.6)
  consumes the available implementation window.

---

## 4. Continuity Notes

- `docs/tasks.md` remains the historical task graph for the backend build-out through Phase 5
- `docs/tasks_phase6.md` is the active task graph for Phases 6–8 (complete)
- `docs/tasks_phase9.md` is this file — the active task graph for Phase 9
- when these files diverge, use this file for Phase 9 implementation work
