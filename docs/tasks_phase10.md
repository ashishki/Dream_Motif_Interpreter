# Task Graph — Dream Motif Interpreter Phase 10

Version: 1.0
Last updated: 2026-04-16
Status: Planned task graph for Phase 10 — Research Augmentation

## 1. Purpose

This file is the implementation task graph for Phase 10 of Dream Motif Interpreter.

It exists so the repository can preserve:

- Phase 9 execution history in `docs/tasks_phase9.md`
- a clean execution source for Phase 10 research augmentation work
- continuity between the motif abstraction layer and the new external research capability

## 2. How To Use This File

- use this file as the active implementation authority for Phase 10 research augmentation work
- treat `docs/tasks_phase9.md` as the authoritative history for Phase 9
- read `Context-Refs` before implementation begins
- do not start coding Phase 10 from architecture docs alone when a task here exists

Reference documents:

- `docs/RESEARCH_AUGMENTATION.md`
- `docs/ARCHITECTURE.md §18`
- `docs/PHASE_PLAN.md §10`
- `docs/adr/ADR-009-research-trust-boundary.md`
- `docs/adr/ADR-010-feature-flag-gating.md`

Execution rules:

- research results must never be stored in dream archive tables (dream_entries, dream_themes, dream_chunks)
- all confidence values must be: speculative, plausible, or uncertain — never confirmed/high/verified
- every result must carry source URL and retrieved_at timestamp
- the research_motif_parallels tool must require explicit user confirmation before any external call
- the RESEARCH_AUGMENTATION_ENABLED flag must gate all research pipeline calls

## 3. Phase 10 — Research Augmentation

Goal: enable on-demand external search for mythology, folklore, cultural, and taboo parallels to confirmed inducted motifs. Store results in research_results. Expose via API and assistant tool with full trust-boundary labeling.

Phase gate:

- ResearchRetriever executes external search and returns results when RESEARCH_AUGMENTATION_ENABLED=true
- ResearchSynthesizer produces labeled parallel objects with permitted confidence vocabulary
- research_results rows stored with source URL, retrieved_at, triggered_by
- GET /motifs/{id}/research returns stored research results for a motif
- assistant tool research_motif_parallels requires confirmation before executing
- all results explicitly framed as external and speculative
- feature flag disables pipeline completely when false

Dependency graph:

```
WS-10.1 → WS-10.2
WS-10.2 → WS-10.3
WS-10.2 → WS-10.4
WS-10.3 + WS-10.4 → WS-10.5
```

---

## WS-10.1: DB Migration and ORM Model

Owner:      codex
Phase:      10
Type:       persistence
Depends-On: none

Objective: |
  Add the research_results table migration and ORM model.

Acceptance-Criteria:
  - id: AC-1
    description: "Migration 010_add_research_results creates the research_results table with all required columns: id (UUID PK), motif_id (UUID FK → motif_inductions.id ON DELETE CASCADE), dream_id (UUID FK → dream_entries.id ON DELETE CASCADE), query_label (TEXT NOT NULL), parallels (JSONB NOT NULL DEFAULT '[]'), sources (JSONB NOT NULL DEFAULT '[]'), triggered_by (TEXT NOT NULL), created_at (TIMESTAMPTZ DEFAULT now())."
  - id: AC-2
    description: "ORM model ResearchResult is defined in app/models/research.py with correct column types and FKs."
  - id: AC-3
    description: "Migration does not modify any existing table."
  - id: AC-4
    description: "Model and migration can be imported cleanly."

Files:
  - alembic/versions/010_add_research_results.py
  - app/models/research.py
  - app/models/__init__.py

Context-Refs:
  - docs/RESEARCH_AUGMENTATION.md §5
  - docs/adr/ADR-009-research-trust-boundary.md

Notes: |
  research_results must not be added to any RAG ingestion pipeline.
  It is a separate store, never retrieved by the dream archive search.

---

## WS-10.2: ResearchRetriever + ResearchSynthesizer

Owner:      codex
Phase:      10
Type:       service
Depends-On: WS-10.1

Objective: |
  Implement ResearchRetriever (external search API wrapper) and ResearchSynthesizer
  (LLM-based parallel extraction from retrieved content).

Acceptance-Criteria:
  - id: AC-1
    description: "ResearchRetriever accepts a query_label (str) and returns a list of raw source objects: [{url: str, excerpt: str, retrieved_at: str ISO8601}]. Returns at most 5 results. Enforces a 5-second timeout."
  - id: AC-2
    description: "ResearchSynthesizer accepts a motif label and a list of source objects, calls Claude to extract structural parallels, and returns a list of parallel objects: [{domain: str, label: str, source_url: str, relevance_note: str, confidence: 'speculative'|'plausible'|'uncertain'}]."
  - id: AC-3
    description: "ResearchSynthesizer prompt explicitly prohibits confidence values: confirmed, high, high confidence, verified, established. The prompt uses the words 'parallels' and 'suggestions', not 'findings' or 'results'."
  - id: AC-4
    description: "Both components are testable with stub HTTP client and stub LLM client without real API calls."
  - id: AC-5
    description: "ResearchRetriever raises ResearchAPIError on HTTP failure; ResearchSynthesizer raises ResearchSynthesisError on LLM parse failure. Both errors are typed."

Files:
  - app/research/__init__.py
  - app/research/retriever.py
  - app/research/synthesizer.py
  - tests/unit/test_research_retriever.py
  - tests/unit/test_research_synthesizer.py

Context-Refs:
  - docs/RESEARCH_AUGMENTATION.md §2 §3 §4
  - docs/adr/ADR-009-research-trust-boundary.md
  - app/shared/config.py (RESEARCH_API_KEY, RESEARCH_AUGMENTATION_ENABLED)

Notes: |
  For ResearchRetriever, use a configurable provider — the implementation should
  accept a base_url and api_key from settings so the provider can be swapped.
  Use asyncio.to_thread for the HTTP call (same pattern as OpenAIEmbeddingClient).
  The synthesizer must use claude-sonnet-4-6 and must never return a parallel
  with confidence outside the permitted vocabulary.
  Add RESEARCH_API_KEY and RESEARCH_AUGMENTATION_ENABLED to app/shared/config.py
  if not already present.

---

## WS-10.3: ResearchService Orchestrator + Persistence

Owner:      codex
Phase:      10
Type:       service
Depends-On: WS-10.2

Objective: |
  Implement ResearchService which orchestrates ResearchRetriever and
  ResearchSynthesizer and persists results to research_results.

Acceptance-Criteria:
  - id: AC-1
    description: "ResearchService.run(motif_id, session) queries motif_inductions to get the confirmed motif, calls ResearchRetriever, then ResearchSynthesizer, then persists a ResearchResult row."
  - id: AC-2
    description: "ResearchService raises an error if the motif status is not 'confirmed'."
  - id: AC-3
    description: "ResearchService sets triggered_by to the caller-supplied value (e.g. chat_id or 'user')."
  - id: AC-4
    description: "ResearchService does not write to dream_entries, dream_themes, or dream_chunks."
  - id: AC-5
    description: "The caller (not ResearchService) commits the session."

Files:
  - app/services/research_service.py
  - tests/unit/test_research_service.py

Context-Refs:
  - docs/RESEARCH_AUGMENTATION.md §3
  - app/services/motif_service.py (session ownership pattern from FIX-1)

---

## WS-10.4: API Routes

Owner:      codex
Phase:      10
Type:       api
Depends-On: WS-10.2

Objective: |
  Expose research results via REST API.

Acceptance-Criteria:
  - id: AC-1
    description: "GET /motifs/{motif_id}/research returns all research_results rows for the motif, ordered by created_at desc."
  - id: AC-2
    description: "POST /motifs/{motif_id}/research triggers ResearchService.run() synchronously and returns the new result. Requires RESEARCH_AUGMENTATION_ENABLED=true; returns 503 if disabled."
  - id: AC-3
    description: "Response model carries a Literal interpretation_note field: 'Research results are external suggestions. They have not been verified and do not constitute claims about the dream.'"
  - id: AC-4
    description: "Routes are protected by existing X-API-Key auth middleware."
  - id: AC-5
    description: "Routes are covered by unit tests."

Files:
  - app/api/research.py
  - app/main.py
  - tests/unit/test_research_api.py

Context-Refs:
  - docs/RESEARCH_AUGMENTATION.md §5
  - app/api/motifs.py (pattern to follow)

---

## WS-10.5: Assistant Tool + Facade Method

Owner:      codex
Phase:      10
Type:       assistant
Depends-On: WS-10.3, WS-10.4

Objective: |
  Expose research augmentation to the Telegram assistant via a bounded tool
  (research_motif_parallels) with confirmation-before-execution pattern.

Acceptance-Criteria:
  - id: AC-1
    description: "AssistantFacade has research_motif_parallels(motif_id, triggered_by) method returning frozen DTOs."
  - id: AC-2
    description: "The research_motif_parallels tool is registered in build_tools() ONLY when RESEARCH_AUGMENTATION_ENABLED=true."
  - id: AC-3
    description: "The assistant system prompt includes a confirmation-before-execution rule: before calling research_motif_parallels, the assistant must state what it will search for and ask for explicit confirmation."
  - id: AC-4
    description: "The system prompt instructs the assistant to frame all results as 'external suggestions' and to use confidence vocabulary: speculative, plausible, uncertain."
  - id: AC-5
    description: "The tool is absent from the catalog when RESEARCH_AUGMENTATION_ENABLED=false."

Files:
  - app/assistant/facade.py
  - app/assistant/tools.py
  - app/assistant/prompts.py
  - tests/unit/test_assistant_facade.py
  - tests/unit/test_assistant_chat.py

Context-Refs:
  - docs/RESEARCH_AUGMENTATION.md §3 §4
  - docs/TELEGRAM_INTERACTION_MODEL.md §13
  - app/assistant/tools.py (build_tools pattern from WS-9.6)

Notes: |
  The confirmation-before-execution pattern must be encoded in the system prompt,
  not in the tool schema. The tool executes only when the user has confirmed.
  See docs/TELEGRAM_INTERACTION_MODEL.md §13 for the full framing requirements.

---

## 4. Continuity Notes

- `docs/tasks_phase9.md` is the active task graph for Phase 9 (complete)
- `docs/tasks_phase10.md` is this file — the active task graph for Phase 10
- open decision OD-5 (research API provider choice) must be resolved before WS-10.1 ends;
  the retriever implementation must be provider-agnostic (configurable base_url + api_key)
- when files diverge, use this file for Phase 10 implementation work
