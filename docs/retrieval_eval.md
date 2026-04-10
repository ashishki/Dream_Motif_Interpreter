# Retrieval Evaluation — Dream Motif Interpreter

Version: 1
Last updated: 2026-04-10
Changed by: STRATEGIST — Architecture Package Initialized

---

## Evaluation Validity Rule

An evaluation entry is **invalid** and must be rejected if either of the following is true:

- `Eval Source` is absent or blank — every metrics entry must identify the exact command, script, or method that produced the numbers.
- `Date` / timestamp is absent or blank.

An invalid entry is treated as a missing evaluation. The task is not complete.

Acceptable `Eval Source` examples:
- `scripts/eval.py against §Evaluation Dataset (10 queries), run YYYY-MM-DD`
- `manual spot-check: retrieved docs inspected for Q01–Q05, run YYYY-MM-DD`
- `pytest tests/integration/test_retrieval_eval.py::test_eval_script_writes_baseline_metrics, run YYYY-MM-DD`

---

## Retrieval Quality vs. Answer Quality

These are not the same thing and must be evaluated independently.

A strong language model can produce fluent, confident answers even when the retrieved evidence is wrong, incomplete, or off-topic. Conversely, correct retrieval does not guarantee a correct answer.

- **Retrieval quality:** did the system surface the right evidence? (this file)
- **Answer quality:** did the system reason correctly over that evidence? (separate concern)

A passing answer-quality check with declining retrieval metrics is a warning sign, not a green light.

---

## Corpus Description

- **Source:** Personal dream journal — single Google Doc
- **Index schema version:** v1
- **Embedding model:** text-embedding-3-small (OpenAI, 1536 dimensions)
- **Chunking strategy:** one chunk per dream entry; entries > 512 tokens split at paragraph boundaries with 50-token overlap
- **Max index age:** 24 hours

---

## Evaluation Dataset

_To be populated in T12._

| ID | Query | Query Type | Expected top document(s) | Notes |
|----|-------|------------|--------------------------|-------|
| Q01 | TBD | simple | TBD | Literal keyword present in dream text |
| Q02 | TBD | simple | TBD | Theme name matches confirmed category |
| Q03 | TBD | multi-doc | TBD | Theme appears across 2+ dreams |
| Q04 | TBD | multi-doc | TBD | Co-occurring themes in same dream |
| Q05 | TBD | multi-hop | TBD | Answer requires linking theme across dreams |
| Q06 | TBD | multi-hop | TBD | Temporal pattern across entries |
| Q07 | TBD | simple | TBD | Metaphor-aware: symbolic match |
| Q08 | TBD | simple | TBD | Semantic match without keyword |
| Q09 | TBD | no-answer | — | Query with no relevant document in corpus |
| Q10 | TBD | no-answer | — | Query with no relevant document (different topic) |

---

## Baseline Metrics

_Not yet recorded — will be populated in T12._

| Metric | Value | Notes |
|--------|-------|-------|
| hit@3 | — | Fraction of queries where correct doc is in top 3 results |
| hit@5 | — | Fraction of queries where correct doc is in top 5 results |
| MRR | — | Mean Reciprocal Rank across query set |
| Citation precision | — | Fraction of cited docs that are relevant to the query |
| No-answer accuracy | — | Fraction of no-answer queries correctly returning insufficient_evidence |
| Median retrieval latency | — | p50 latency for the retrieve stage (ms) |
| p95 retrieval latency | — | p95 latency for the retrieve stage (ms) |

---

## Current Metrics

_Not yet recorded._

| Metric | Previous | Current | Delta | Regression? |
|--------|----------|---------|-------|-------------|
| hit@3 | — | — | — | — |
| hit@5 | — | — | — | — |
| MRR | — | — | — | — |
| Citation precision | — | — | — | — |
| No-answer accuracy | — | — | — | — |
| Median retrieval latency | — | — | — | — |
| p95 retrieval latency | — | — | — | — |

---

## Answer Quality Metrics

_Not yet recorded — required from Phase 2 onward._

| Metric | Description | Baseline | Previous | Current | Delta | Regression? |
|--------|-------------|----------|----------|---------|-------|-------------|
| Faithfulness | Answer contains only claims supported by retrieved context | — | — | — | — | — |
| Answer Completeness | Answer addresses the full question given the retrieved context | — | — | — | — | — |
| Answer Relevance | Answer is on-topic and appropriately scoped to the query | — | — | — | — | — |

Scoring: 0.0–1.0 per metric, averaged across evaluation query set.
Judge: TBD — LLM judge model and prompt reference to be specified in T12.

---

## Regression Notes

none

---

## No-Answer Behavior Quality

_Not yet measured._

| Query ID | Result | Expected | Pass? |
|----------|--------|----------|-------|
| Q09 | — | insufficient_evidence | — |
| Q10 | — | insufficient_evidence | — |

---

## Evidence / Citation Correctness

_Not yet measured._

| Query ID | Citation present? | Source matches? | Notes |
|----------|-------------------|-----------------|-------|
| Q01 | — | — | — |
| Q02 | — | — | — |

---

## Experiments

| ID | Hypothesis | Change | Metric(s) targeted | Result vs. baseline | Decision |
|----|-----------|--------|--------------------|---------------------|----------|

---

## Open Retrieval Findings

none

---

## Evaluation History

| Date | Task | Corpus Version | Eval Source | hit@3 | MRR | No-answer acc. | Faithfulness | Completeness | Note |
|------|------|----------------|-------------|-------|-----|----------------|--------------|--------------|------|
| 2026-04-10 | STRATEGIST | pre-implementation | — | — | — | — | — | — | initial file; no data yet |
