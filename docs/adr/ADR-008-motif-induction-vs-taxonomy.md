# ADR-008: Inducted Motifs and Taxonomy Themes Are Separate Data Models

Date: 2026-04-15
Status: Proposed

## Context

Phase 9 introduces motif induction: the process of deriving abstract motif labels from dream imagery using an open vocabulary, without selecting from a predefined category list. The system already has a taxonomy-based theme extraction pipeline that assigns dreams to curated categories stored in `theme_categories` and `dream_themes`.

A question arises: should inducted motifs be stored alongside taxonomy-based themes, or in a separate table?

## Decision

Inducted motifs and taxonomy-based themes are maintained as separate data models (`motif_inductions` vs `dream_themes`) and must not be merged.

## Rationale

Taxonomy-based themes are curated human-approved categories with stable IDs. They are used for pattern queries, rollback, and annotation versioning. Their vocabulary is closed and deliberately controlled. Merging open-vocabulary, dream-specific, emergent motif labels into this table would:

- corrupt the stable category IDs relied upon by pattern queries
- introduce draft, unconfirmed model output into a table designed for curated data
- make rollback semantics ambiguous (annotation versioning was designed for curation mutations, not open-vocabulary generation)
- make it impossible to distinguish taxonomy-assigned themes from model-inducted abstractions in audit history

Keeping them separate preserves the integrity of both systems. The taxonomy remains a curated, stable, pattern-queryable vocabulary. The motif_inductions table is an open-vocabulary, per-dream abstraction layer with its own lifecycle (draft → confirmed / rejected).

## Consequences

- `motif_inductions` is a new table with its own schema, migration, and status lifecycle.
- `dream_themes` is never written by the motif induction pipeline.
- Pattern queries over taxonomy themes are unaffected by Phase 9.
- Cross-dream motif pattern queries (WS-9.7) must operate against `motif_inductions`, not `dream_themes`.
- The assistant must not conflate taxonomy themes and inducted motifs in responses.
