# Dream Motif Interpreter — Product Overview

## 1. What This Product Is

Dream Motif Interpreter is a private dream-analysis system for one user.
It turns a long-form dream journal into a structured archive that can be searched, curated, and reviewed over time.

It is not a generic chatbot.
It is not a public dream-sharing product.

## 2. Core Job To Be Done

When I have accumulated a large private dream journal, help me:

- ingest it reliably
- search it meaningfully
- identify recurring motifs
- curate interpretive labels carefully
- interact with it in a way that feels like talking to a knowledgeable assistant without losing archive discipline

## 3. Current Strengths

- strong backend boundaries
- explicit curation and rollback model
- retrieval and pattern-analysis orientation
- single-user simplicity

## 4. Current Weakness

The current system is backend-first.
It lacks a conversational interface, so the product value is less accessible than the underlying architecture.

## 5. Why Telegram Is the Next Interface

Telegram is the next justified surface because:

- it supports fast private interaction
- it supports both text and voice
- it matches the single-user private-deployment model
- it allows the assistant layer to become useful before a web surface is justified

## 6. What Telegram Does Not Mean

Telegram does not mean:

- the product becomes bot-only
- the backend stops being the core
- schema and domain boundaries should be rebuilt around chat

## 7. Product Boundary for the Next Phases

### In

- text assistant interaction
- voice assistant interaction
- bounded archive-backed conversational behavior
- private deployment

### Out

- multi-user collaboration
- SaaS platform work
- generalized autonomous dream therapist framing
- uncontrolled chat-driven archive mutation

## 8. Planned Capabilities (Phases 9–11)

### Motif abstraction (Phase 9)

The system will be able to inductively derive abstract motifs from concrete dream imagery. This is different from the existing theme extraction capability:

- Existing theme extraction (ThemeExtractor): assigns a dream to predefined categories from a curated taxonomy. Closed vocabulary. Model selects from known options.
- Motif induction (Phase 9): derives abstract motif labels from imagery without a predefined vocabulary. Open vocabulary. Model forms the abstraction itself. Results are stored in a separate `motif_inductions` table and never merged into the theme taxonomy.

Inducted motifs are computational suggestions, not interpretations. They are draft by default and require human confirmation before being treated as significant.

Both capabilities coexist and serve different purposes. Theme extraction answers "which known categories apply to this dream." Motif induction answers "what patterns does this dream's imagery suggest, without assuming any category exists."

### Research augmentation (Phase 10)

On user request, the system will be able to search for structural parallels in mythology, folklore, and cultural material for confirmed inducted motifs. All results are explicitly labeled as speculative and sourced with URL and retrieval timestamp.

Research results are not findings — they are parallels or suggestions. They are never presented as authoritative claims. The confidence vocabulary for research results is limited to: speculative, plausible, uncertain. The words "confirmed" and "high confidence" do not apply to research output.

This capability requires user confirmation before any external search is executed.

### Feedback loop (Phase 11)

The user will be able to rate assistant responses on a 1–5 scale with an optional comment via Telegram. Ratings provide a quality signal for human review only. They do not feed into automated retraining or any unsupervised model update pipeline.

## 9. Active Execution Source

The active implementation task graph for this product evolution is:

- [docs/tasks_phase6.md](tasks_phase6.md) — Phase 6–8 complete
- [docs/tasks_phase9.md](tasks_phase9.md) — Phase 9 planned task graph

The older [docs/tasks.md](tasks.md) remains the historical backend execution record through Phase 5.
