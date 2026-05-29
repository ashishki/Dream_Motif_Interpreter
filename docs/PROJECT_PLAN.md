# Dream Motif Interpreter - Project Plan

Status: active creative experiment
Role: private dream memory system and future Telegram mini app
Priority: P1

## Strategic Role

Dream Motif Interpreter should evolve from a backend-heavy private assistant
into a visually strong reflective memory product.

The strongest future form is **Dream Memory Map**: Telegram mini app + Obsidian-
like graph structure for dreams, motifs, emotions, people, places, and recurring
patterns.

## Product Direction

Reference Obsidian for:

- graph view
- backlinks
- tags
- note/motif relationships
- local-first feeling
- "vault" metaphor

Do not make Obsidian a dependency. Use the structural/visual idea only.

## Near-Term Roadmap

### P0 - User Feedback Stabilization

- Continue incorporating real user test feedback.
- Separate bug fixes from new interpretation features.
- Preserve privacy and reversibility.

### P1 - Telegram Mini App Concept

- Define mini app screens:
  - dream entry
  - motif graph
  - recurring motif page
  - timeline
  - search
  - privacy/export settings
- Add a README/product doc section with visual direction.

### P1 - Graph Schema

- Define nodes:
  - Dream
  - Motif
  - Person
  - Place
  - Emotion
  - Event
- Define edges:
  - appears_in
  - repeats_with
  - contradicts
  - evolves_from
  - user_confirmed

### P2 - Reflective UX

- Add gentle language: pattern memory, not diagnosis.
- Add user controls for accepting/rejecting interpretations.
- Add export/import and data deletion path.
- Use `docs/entropy_core_reference.md` if memory actions need receipt-style
  verification. Do not apply Gensyn swarm/training patterns by default.

## AI-Development Tasks

- Use AI to propose motifs and reflective summaries.
- Require user confirmation for durable motif memory.
- Keep all interpretations marked as suggestions.
- Use evidence links back to dream fragments.

## Stop Conditions

- Do not present psychological diagnosis.
- Do not overbuild research enrichment before the graph UX exists.
