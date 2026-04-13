# Retrieval Evaluation — Dream Motif Interpreter

<!--
Copy to docs/retrieval_eval.md in your project when RAG Profile = ON.
Update this file whenever retrieval logic changes (chunking, embedding, ranking, evidence assembly).
Retrieval quality is evaluated separately from code quality — a green test suite does not imply good retrieval.
-->

## Evaluation Validity Rule

An evaluation entry is **invalid** and must be rejected if either of the following is true:

- `Eval Source` is absent or blank — every metrics entry must identify the exact command, script, or method that produced the numbers.
- `Date` / timestamp is absent or blank.

An invalid entry is treated as a missing evaluation. The task is not complete.

Acceptable `Eval Source` examples:
- `scripts/eval.py against §Evaluation Dataset (10 queries), run YYYY-MM-DD`
- `manual spot-check: retrieved docs inspected for Q01–Q05, run YYYY-MM-DD`
- `pytest tests/test_retrieval_eval.py::test_hit_at_3, run YYYY-MM-DD`

`"Ran evaluation"` or `"updated metrics"` without specifics is **not acceptable**.

---

## Retrieval Quality vs. Answer Quality

These are not the same thing and must be evaluated independently.

A strong language model can produce fluent, confident answers even when the retrieved evidence
is wrong, incomplete, or off-topic. Conversely, correct retrieval does not guarantee a correct
answer. Evaluating only the final answer masks retrieval failures.

**Retrieval evaluation measures what was retrieved, not what was said.**

- Retrieval quality: did the system surface the right evidence? (this file)
- Answer quality: did the system reason correctly over that evidence? (separate concern)

A passing answer-quality check with declining retrieval metrics is a warning sign, not a green light.

---

Version: 1
Last updated: 2026-04-13
Changed by: T12 — Retrieval Evaluation Baseline

---

## Schema Version

- Index schema version: `v1`

---

## Corpus Description

- Source corpus: `dream_entries`
- Estimated corpus size: 20–200 entries
- Ownership model: single-user archive
- Index readiness: 20 seeded dream entries indexed for the synthetic baseline

---

## Chunking Strategy

- Primary unit: one chunk per dream entry
- Split rule: entries longer than 512 tokens split at paragraph boundaries
- Overlap: 50 tokens between adjacent chunks

---

## Retrieval Configuration

- Vector similarity: cosine similarity
- Fusion strategy: PostgreSQL FTS plus vector retrieval via reciprocal rank fusion
- Relevance threshold: 0.35
- Candidate set: top 5 fused results after filtering

---

## Evaluation Dataset

| ID | Query | Query Type | Expected top document(s) | Notes |
|----|-------|------------|--------------------------|-------|
| Q01 | flying dream | simple | Sky Bridge Flying Dream | direct motif lookup |
| Q02 | water symbolism | simple | Flooded Library Dream | explicit symbolism phrasing present in corpus |
| Q03 | locked rooms in childhood house | simple | Locked Rooms Childhood House Dream | single-document retrieval anchored in title and body |
| Q04 | recurring labyrinth across multiple dreams | multi-doc | Glass Labyrinth Dream; Hotel Corridor Labyrinth Dream | recurring labyrinth motif spans two entries |
| Q05 | red thread motif across different dreams | multi-doc | Glass Labyrinth Dream; Red Thread Reunion Dream | shared symbol across distinct settings |
| Q06 | water and lantern imagery appearing in more than one dream | multi-doc | Lighthouse Staircase Dream; Ocean Cliff Lantern Dream | cross-entry imagery aggregation |
| Q07 | transformation theme following shadow encounter | multi-hop | Shadow Riverbank Dream; Moth Transformation Dream | transformation is grounded by prior shadow encounter |
| Q08 | guidance after descent into darkness | multi-hop | Desert Well Dream; White Wolf Guide Dream | requires chaining descent and later guidance motifs |
| Q09 | quantum physics notation | no-answer | — (should return insufficient_evidence) | out-of-corpus technical domain |
| Q10 | stock market analysis | no-answer | — (should return insufficient_evidence) | unrelated analytical domain |

---

## Baseline Metrics

_Recorded at: 2026-04-13 after T12_

| Metric | Value | Notes |
|--------|-------|-------|
| hit@3 | 1.00 | Fraction of queries where correct doc is in top 3 results |
| hit@5 | 1.00 | Fraction of queries where correct doc is in top 5 results |
| MRR | 1.00 | Mean Reciprocal Rank across query set |
| Citation precision | 0.72 | Fraction of cited docs that are relevant to the query |
| No-answer accuracy | 1.00 | Fraction of no-answer queries correctly returning insufficient_evidence |
| Median retrieval latency | 35 ms | p50 latency for the retrieve stage (ms) |
| p95 retrieval latency | 156 ms | p95 latency for the retrieve stage (ms) |
---

## Current Metrics

_Recorded at: 2026-04-13 after T12_

| Metric | Previous | Current | Delta | Regression? |
|--------|----------|---------|-------|-------------|
| hit@3 | — | 1.00 | — | No |
| hit@5 | — | 1.00 | — | No |
| MRR | — | 1.00 | — | No |
| Citation precision | — | 0.72 | — | No |
| No-answer accuracy | — | 1.00 | — | No |
| Median retrieval latency | — | 35 ms | — | No |
| p95 retrieval latency | — | 156 ms | — | No |
---

## Answer Quality Metrics

_Recorded at: 2026-04-13 after T12_
_Corpus version: synthetic-20-entries_

| Metric | Description | Baseline | Previous | Current | Delta | Regression? |
|--------|-------------|----------|----------|---------|-------|-------------|
| Faithfulness | Answer contains only claims supported by the retrieved context | — | — | — | — | — |
| Answer Completeness | Answer addresses the full question given the retrieved context | — | — | — | — | — |
| Answer Relevance | Answer is on-topic and appropriately scoped to the query | — | — | — | — | — |

Scoring: 0.0–1.0 per metric, averaged across the evaluation query set.
Judge: TBD

---

## Regression Notes

No retrieval regression is recorded for T12. This baseline uses the synthetic 20-entry corpus and falls back to stub embeddings plus lexical ranking when `OPENAI_API_KEY` is absent or starts with `test-`, so the local evaluation remains executable without live OpenAI access.

---

## No-Answer Behavior Quality

Did no-answer queries correctly trigger `insufficient_evidence`?

| Query ID | Result | Expected | Pass? |
|----------|--------|----------|-------|
| Q09 | insufficient_evidence | insufficient_evidence | Yes |
| Q10 | insufficient_evidence | insufficient_evidence | Yes |

Notes: Both no-answer queries stayed outside the seeded dream corpus and correctly terminated at `insufficient_evidence`.

---

## Evidence / Citation Correctness

For a sample of successful queries, verify that the assembled evidence matches the source:

| Query ID | Citation present? | Source matches? | Notes |
|----------|-------------------|-----------------|-------|
| Q01 | Yes | Yes | Top result is the flying entry itself |
| Q04 | Yes | Yes | Top-3 includes both labyrinth documents |

---

## Experiments

Use this section to track deliberate retrieval changes and their outcomes.
Test one variable at a time. Record results before deciding.

| ID | Hypothesis | Change | Metric(s) targeted | Result vs. baseline | Decision |
|----|-----------|--------|--------------------|---------------------|----------|
| EXP-01 | Smaller chunks may improve retrieval for short motif queries | No experiment run yet | hit@3, MRR | — | pending |

Rules:
- One variable per experiment.
- Record result before deciding. Decision comes after data, not before.
- If adopted: update Baseline Metrics to reflect the new state.
- If rejected: keep the row as a record that this path was tried.

---

## Open Retrieval Findings

none

---

## Evaluation History

| Date | Task | Corpus Version | Eval Source | hit@3 | MRR | No-answer acc. | Faithfulness | Completeness | Note |
|------|------|----------------|-------------|-------|-----|----------------|--------------|--------------|------|
| 2026-04-12 | T10 | 0 indexed dream_entries | pre-T11 synthetic baseline — no corpus indexed yet | N/A | N/A | — | — | — | zero-corpus placeholder |
| 2026-04-13 | T11 | local-test-db-fixtures-2026-04-13 | `pytest tests/ -q --tb=short` and `pytest tests/integration/test_rag_query.py -q --tb=short`, run 2026-04-13; retrieval cases requiring real OpenAI embeddings skipped by env gate | SKIPPED | SKIPPED | SKIPPED | — | — | query path implemented; metric run deferred until real-key environment |
| 2026-04-13 | T12 | synthetic-20-entries | scripts/eval.py against §Evaluation Dataset (10 queries), run 2026-04-13 | 1.00 | 1.00 | 1.00 | — | — | synthetic seeded baseline established |