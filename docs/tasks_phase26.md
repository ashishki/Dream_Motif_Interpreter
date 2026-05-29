# Dream Motif Interpreter - Phase 26

Version: 1.0
Last updated: 2026-05-29
Status: Planning - Dream Memory Map / Telegram mini app direction

## Purpose

Phase 26 turns the next product direction into implementation-ready work:
Dream Memory Map, a Telegram mini app and Obsidian-like motif graph for dreams,
motifs, emotions, people, places, events, and recurring patterns.

This phase is visual/structural product work, not another backend-heavy research
layer.

## WS-26.1: Dream Memory Map Product Spec

Owner: human + codex
Phase: 26
Type: product strategy
Priority: P0
Status: Done 2026-05-29

Objective:
  Define the mini app experience, privacy posture, graph entities, and
  non-diagnostic language.

Acceptance-Criteria:
  - AC-1: Product spec defines screens for dream entry, motif graph, recurring
    motif page, timeline, search, and privacy/export settings.
  - AC-2: Spec states the product is reflective journaling / pattern memory,
    not psychological diagnosis.
  - AC-3: Spec identifies what stays in Telegram bot vs Telegram mini app.

Files:
  - docs/DREAM_MEMORY_MAP.md
  - docs/PRODUCT_OVERVIEW.md
  - README.md

Result:
  Product spec created in docs/DREAM_MEMORY_MAP.md. Acceptance coverage is
  guarded by tests/unit/test_dream_memory_map_spec.py.

## WS-26.2: Graph Schema For Dreams And Motifs

Owner: codex
Phase: 26
Type: schema design
Priority: P1
Depends-On: WS-26.1

Objective:
  Define a graph schema that can power Obsidian-like visualization without
  making Obsidian a dependency.

Acceptance-Criteria:
  - AC-1: Schema defines nodes: Dream, Motif, Person, Place, Emotion, Event.
  - AC-2: Schema defines edges: appears_in, repeats_with, contradicts,
    evolves_from, user_confirmed.
  - AC-3: Schema records source dream fragments for every AI-suggested edge.
  - AC-4: User confirmation status is represented separately from model
    suggestion.

Files:
  - docs/DREAM_MEMORY_MAP.md
  - app/models/
  - tests/unit/

## WS-26.3: Mini App UX Prototype

Owner: codex
Phase: 26
Type: product demo
Priority: P1
Depends-On: WS-26.1, WS-26.2

Objective:
  Build or mock the first visual mini app flow enough to evaluate whether the
  product direction feels clear.

Acceptance-Criteria:
  - AC-1: Prototype shows dream nodes, motif nodes, and edges in one graph view.
  - AC-2: User can open a motif and see linked dreams/fragments.
  - AC-3: Prototype labels AI interpretations as suggestions and user-confirmed
    links distinctly.

Files:
  - frontend/ or docs/mockups/
  - docs/DREAM_MEMORY_MAP.md
  - tests/ if implemented in app code

## WS-26.4: Privacy, Export, And Deletion Controls

Owner: codex
Phase: 26
Type: privacy
Priority: P1
Depends-On: WS-26.1

Objective:
  Define and implement the privacy controls required before a memory graph
  becomes durable UI.

Acceptance-Criteria:
  - AC-1: User can export dream graph data in a documented format.
  - AC-2: User can delete or hide a dream/motif from graph output.
  - AC-3: AI-suggested interpretations can be rejected without deleting the
    source dream.

Files:
  - docs/DREAM_MEMORY_MAP.md
  - app/
  - tests/unit/

## Phase Gate

- [x] Product spec exists and avoids diagnostic claims.
- [ ] Graph schema is reviewable and evidence-linked.
- [ ] Mini app prototype or mockup demonstrates the visual direction.
- [ ] Privacy/export/delete controls are specified before broad UX expansion.
