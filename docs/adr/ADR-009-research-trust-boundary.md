# ADR-009: Research Results Must Carry Speculative Confidence Labels

Date: 2026-04-15
Status: Accepted

## Context

Phase 10 introduces external research augmentation: on-demand retrieval of structural parallels from mythology, folklore, and cultural material via an external search API. This content originates outside the system and cannot be verified against the dream archive.

A decision is needed about how confidence and reliability must be communicated for this content.

## Decision

All external research results must carry confidence labels of `speculative`, `plausible`, or `uncertain`. The words `confirmed` and `high confidence` are prohibited in research output. Source URL and retrieval timestamp are required fields on every result.

## Rationale

The system's value proposition is its non-authoritative stance: it grounds responses in the user's own archive and explicitly labels computational output as computational. External research introduces content the system cannot verify. If this content were presented with the same confidence vocabulary used for archive evidence, users could not distinguish what the system knows from what it retrieved from the internet.

Labeling is the primary safety control because there is no technical mechanism to verify external content. The constraint must be enforced at the data model level (permitted values in the `parallels` JSONB schema), at the API level (response validation), and at the assistant prompt level (framing rules).

The prohibition on `confirmed` and `high confidence` is absolute. These words carry a specific meaning in the system's trust model (archive evidence and curated themes). Using them for unverified external content would undermine that model.

## Consequences

- The `parallels` field in `research_results` uses a restricted confidence vocabulary: `speculative`, `plausible`, `uncertain`.
- Validation must reject any result where confidence is not one of these three values.
- The system prompt for the assistant must explicitly instruct the model not to use `confirmed` or `high confidence` when presenting research parallels.
- Every result must include `url` and `retrieved_at` fields in `sources`.
- The assistant must open any presentation of research results with an explicit external-source disclosure.
