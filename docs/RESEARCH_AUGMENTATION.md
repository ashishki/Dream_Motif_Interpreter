# Research Augmentation — Dream Motif Interpreter

This document defines the research augmentation capability planned for Phase 10: its purpose, trust model, trigger model, confidence vocabulary, data model, and feature flag behavior.

---

## 1. Purpose

Research augmentation enables on-demand external search for structural parallels to confirmed inducted motifs in mythology, folklore, cultural material, and taboo narratives.

The goal is to surface associative parallels that may enrich understanding of a motif's structural character — not to explain the dream, not to validate the motif, and not to provide authoritative scholarly references.

This capability depends on Phase 9. A motif must exist in `motif_inductions` with `status = 'confirmed'` before research augmentation can be triggered for it.

---

## 2. Trust Model

All external research results operate under an explicitly low trust level.

The system's value proposition is its non-authoritative stance and its grounding in the user's own archive. External research introduces content the system cannot verify. Labeling is the primary safety control.

Rules that must never be violated:

- Every research result must carry a source URL and a retrieval timestamp.
- Confidence vocabulary is restricted to: **speculative**, **plausible**, **uncertain**.
- The words `confirmed` and `high confidence` are prohibited in research output. They must not appear in result fields, assistant framing, or API responses from this layer.
- Results must never be stored in dream archive tables (`dream_entries`, `dream_themes`, `dream_chunks`).
- Results must never be presented as findings — use "parallels" or "suggestions."
- The assistant must make explicit that results are retrieved from external sources and have not been verified.

See [ADR-009](adr/ADR-009-research-trust-boundary.md) for the architectural rationale.

---

## 3. Trigger Model

Research augmentation is on-demand only. It is never triggered automatically during ingest or analysis.

The `research_motif_parallels` assistant tool follows a confirmation-before-execution pattern:

1. User asks about parallels for a motif.
2. Assistant states what it will search for and why.
3. Assistant asks for explicit user confirmation.
4. User confirms.
5. `ResearchRetriever` executes the external search.
6. `ResearchSynthesizer` processes results and returns labeled parallels.
7. Assistant presents results with required speculative framing.

If the user does not confirm in step 4, no external call is made.

---

## 4. Confidence Vocabulary

Valid confidence values for research results:

| Value | Meaning |
|-------|---------|
| `speculative` | The parallel is loosely associative; structural similarity is observed but uncertain |
| `plausible` | The parallel has reasonable structural similarity to the motif |
| `uncertain` | The parallel is present in retrieved sources but its relevance is unclear |

Prohibited values: `confirmed`, `high`, `high confidence`, `verified`, `established`.

This vocabulary applies to the `parallels` JSONB field in `research_results` and to all assistant framing of results.

---

## 5. Data Model — research_results Table

```
research_results
├── id              uuid, primary key
├── motif_id        uuid, foreign key → motif_inductions.id
├── dream_id        uuid, foreign key → dream_entries.id
├── query_label     text, not null         — the motif label used as the search query
├── parallels       jsonb, not null        — list of parallel objects with confidence and text
├── sources         jsonb, not null        — list of {url, retrieved_at} objects
├── triggered_by    text, not null         — identifier of the user or session that triggered the search
└── created_at      timestamptz, not null
```

Migration: `010_add_research_results`

Each item in `parallels` must include a confidence value from the permitted vocabulary. Each item in `sources` must include `url` (string) and `retrieved_at` (ISO8601 timestamp).

---

## 6. What This Layer Is Not

- **Not a search engine**: users cannot use it to freely query external knowledge bases. It is bound to confirmed inducted motifs.
- **Not a reference source**: results are not citeable claims. They are associative parallels from retrieved content.
- **Not a truth claim**: no result from this layer should ever be presented as a fact about the dream or the dreamer.
- **Not an archive layer**: results are stored in `research_results`, never in the dream archive tables. They do not appear in RAG retrieval over the archive.
- **Not a substitute for human scholarship**: the system retrieves and labels; it does not curate or validate.

---

## 7. Feature Flag Behavior

`RESEARCH_AUGMENTATION_ENABLED` controls the availability of this entire layer.

When `false` (default):
- `ResearchRetriever` is not called under any circumstances.
- The `research_motif_parallels` assistant tool is not registered in the tool catalog.
- No external network calls are made for research purposes.
- `research_results` table may exist (migration applied) but is never written.

When `true`:
- `RESEARCH_API_KEY` must be set; the tool will fail at startup or first call if it is absent.
- The `research_motif_parallels` tool becomes available in the assistant catalog.
- The confirmation-before-execution pattern still applies; enabling the flag does not bypass it.

See [ADR-010](adr/ADR-010-feature-flag-gating.md) for the rationale behind default-off gating.
