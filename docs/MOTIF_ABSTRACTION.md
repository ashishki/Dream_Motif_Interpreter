# Motif Abstraction and Induction — Dream Motif Interpreter

This document defines the motif abstraction capability planned for Phase 9: what it is, what it is not, how the pipeline works, and how inducted motifs relate to the existing theme extraction system.

---

## 1. What Motif Abstraction Is (and Is Not)

### What it is

Motif abstraction is the process of deriving higher-order abstract labels from the concrete imagery present in a dream entry, without using a predefined vocabulary. The model forms the abstraction itself by grouping observed imagery into open-vocabulary labels.

Example: a dream containing "crumbling stairs," "a locked door at the top," and "my feet sinking into the floor" might yield an inducted motif label such as "obstructed vertical movement." That label was not selected from a list; it emerged from the imagery.

### What it is NOT

- **Not theme extraction**: the existing `ThemeExtractor` assigns a dream to categories from `theme_categories` — a curated, closed vocabulary. Inducted motifs use an open vocabulary and are never stored in `dream_themes` or the `theme_categories` taxonomy.
- **Not psychological interpretation**: inducted motifs describe structural and imagistic patterns. They do not claim to explain why the pattern is present or what it means for the dreamer.
- **Not a search or retrieval result**: motif induction is a generative abstraction step, not a lookup against known data.
- **Not a replacement for theme extraction**: both systems coexist. Theme extraction answers "which known categories apply?" Motif induction answers "what patterns does this imagery suggest, without assuming any category exists?"

---

## 2. The Three-Stage Pipeline

### Stage 1: ImageryExtractor

Extracts concrete imagery fragments from the raw dream text. Output is a list of grounded text spans (with character offsets) representing the literal imagery present.

Module: `app/services/imagery.py`

### Stage 2: MotifInductor

Takes the extracted imagery fragments and generates abstract motif labels. Each label is accompanied by a rationale string that explains the abstraction and a confidence assessment (`high`, `moderate`, `low`).

The model is not selecting from a vocabulary. It is forming labels. This is an open-vocabulary generative step.

Module: `app/services/motif_inductor.py`

### Stage 3: MotifGrounder

Verifies that the imagery fragments cited as support for each motif label are accurately grounded in the source dream text. Checks fragment text against source character offsets.

This stage reuses the offset-verification pattern established in the existing `Grounder` component (used for theme extraction grounding). The logic is analogous but operates on imagery fragments, not theme-support fragments.

Module: `app/services/motif_grounder.py`

### Orchestration: MotifService

Coordinates the three stages. Wired into the ingest pipeline when `MOTIF_INDUCTION_ENABLED=true`. Stores results in `motif_inductions`.

Module: `app/services/motif_service.py`

---

## 3. Data Model — motif_inductions Table

```
motif_inductions
├── id              uuid, primary key
├── dream_id        uuid, foreign key → dream_entries.id
├── label           text, not null         — the abstract motif label
├── rationale       text, not null         — explanation of the abstraction
├── confidence      text, not null         — high | moderate | low
├── status          text, not null         — draft | confirmed | rejected
├── fragments       jsonb, not null        — grounded imagery spans
├── model_version   text, not null         — model identifier used for induction
└── created_at      timestamptz, not null
```

This table is separate from `dream_themes`. Rows in `motif_inductions` must never be inserted into or merged with `dream_themes`. The two tables have different schemas, different vocabularies, and different purposes.

Migration: `009_add_motif_inductions`

---

## 4. Status Lifecycle

```
draft  →  confirmed
draft  →  rejected
```

All inducted motifs begin with `status = 'draft'`. They are computational suggestions.

- `confirmed`: the user has explicitly reviewed and accepted this motif label as worth retaining.
- `rejected`: the user has dismissed this motif as incorrect or not useful.

`draft` motifs must be presented to the user as unconfirmed suggestions. `rejected` motifs must not be surfaced in normal responses. Only `confirmed` motifs may be used as input for Phase 10 research augmentation.

There is no automated path from `draft` to `confirmed`. Human action is required.

---

## 5. Relationship to dream_themes

`dream_themes` and `motif_inductions` are separate tables that serve different purposes. They must not be merged or conflated.

| Property | dream_themes | motif_inductions |
|----------|-------------|-----------------|
| Vocabulary | Closed (theme_categories) | Open (model-derived) |
| Assigned by | ThemeExtractor selecting from known options | MotifInductor forming new labels |
| Default trust | Pending curation approval | Draft (medium trust) |
| Stored in | dream_themes | motif_inductions |
| Used for pattern queries | Yes (stable category IDs) | Not by default (optional WS-9.7) |
| Requires human confirmation | Yes (via annotation versioning) | Yes (status: draft → confirmed) |

Pattern queries that rely on `dream_themes` will not be affected by Phase 9. The stable category IDs in the taxonomy remain authoritative for pattern analysis. Inducted motifs may optionally extend pattern queries in WS-9.7.

---

## 6. Confidence Levels — Meaning and Presentation

Confidence levels (`high`, `moderate`, `low`) reflect the model's self-assessed confidence in the abstraction it formed. They do not reflect analytical ground truth.

### Presentation rules

- **high confidence**: present as "the model identified this motif with high confidence." Do not present as "this motif is correct" or "this is confirmed."
- **moderate confidence**: present as "the model identified this as a possible motif." Encourage review.
- **low confidence**: present as "the model flagged this tentatively." Recommend careful review before confirming.

Regardless of confidence level, every inducted motif is a model suggestion until `status = 'confirmed'` by a human. Confidence describes the strength of the abstraction proposal, not its analytical validity.

---

## 7. Human Curation Requirements

Phase 9 motifs require human curation before they carry weight in analysis. The following must hold:

1. No inducted motif with `status = 'draft'` should be presented as a fact or finding.
2. No inducted motif should feed into Phase 10 research augmentation unless `status = 'confirmed'`.
3. The `PATCH /dreams/{id}/motifs` API route is the correct surface for status updates; chat-driven confirmation of motifs follows the same preconditions as other chat-driven mutations (see [TELEGRAM_INTERACTION_MODEL.md §11](TELEGRAM_INTERACTION_MODEL.md)).
4. The `model_version` field must be preserved so that motifs produced by different model versions can be distinguished.

See [ADR-008](adr/ADR-008-motif-induction-vs-taxonomy.md) for the rationale behind maintaining motif_inductions as a separate data model.
