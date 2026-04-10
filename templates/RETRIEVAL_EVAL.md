# Retrieval Evaluation — {{PROJECT_NAME}}

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

Version: {{N}}
Last updated: {{DATE}}
Changed by: {{TASK_ID}} — {{TASK_TITLE}}

---

## Evaluation Dataset

| ID | Query | Query Type | Expected top document(s) | Notes |
|----|-------|------------|--------------------------|-------|
| Q01 | {{query}} | simple | {{doc_id or title}} | {{e.g., canonical answer, section}} |
| Q02 | {{query}} | multi-doc | | |
| Q03 | {{query}} | multi-hop | | |
| Q-NA-01 | {{query with no good answer}} | no-answer | — (should return insufficient_evidence) | no-answer test case |

<!--
Maintain at least 10 representative queries.
Query Type values: simple | multi-doc | multi-hop | no-answer

Type coverage requirements:
- simple: single-document lookup; catches basic retrieval misses
- multi-doc: answer requires aggregating evidence from ≥2 documents; catches synthesis failures
- multi-hop: answer requires chaining facts across documents; catches reasoning and context-assembly failures
- no-answer: no document in corpus answers the query; tests the insufficient_evidence path

Cover at least 3 of the 4 types. A dataset that is all simple queries will miss entire failure classes.
Keep the dataset append-only. Add new queries; do not remove old ones.
-->

---

## Baseline Metrics

_Recorded at: {{DATE}} after {{TASK_ID}}_

| Metric | Value | Notes |
|--------|-------|-------|
| hit@3 | | Fraction of queries where correct doc is in top 3 results |
| hit@5 | | Fraction of queries where correct doc is in top 5 results |
| MRR | | Mean Reciprocal Rank across query set |
| Citation precision | | Fraction of cited docs that are relevant to the query |
| No-answer accuracy | | Fraction of no-answer queries correctly returning insufficient_evidence |
| Median retrieval latency | | p50 latency for the retrieve stage (ms) |
| p95 retrieval latency | | p95 latency for the retrieve stage (ms) |

<!--
Metrics do not need to be computed programmatically on every run.
A manual spot-check against the query set is acceptable for early phases.
Automate when the corpus and query set are stable.
-->

---

## Current Metrics

_Recorded at: {{DATE}} after {{TASK_ID}}_

| Metric | Previous | Current | Delta | Regression? |
|--------|----------|---------|-------|-------------|
| hit@3 | | | | |
| hit@5 | | | | |
| MRR | | | | |
| Citation precision | | | | |
| No-answer accuracy | | | | |
| Median retrieval latency | | | | |
| p95 retrieval latency | | | | |

---

## Answer Quality Metrics

<!--
Tracks end-to-end answer quality — a separate dimension from retrieval quality.
Retrieval metrics measure what was found. Answer quality metrics measure what was said about it.
These two dimensions can diverge: retrieval can regress while answer quality holds (easy queries mask retrieval failures),
or retrieval can be stable while answer quality regresses (prompt or model change degrades reasoning).
Both dimensions require a regression gate.

Evaluate using an LLM judge with access to (question, retrieved context, generated answer).
Do NOT give the judge access to expected answers when scoring Faithfulness — that conflates retrieval with generation.
A spot-check over the evaluation dataset (≥5 queries) is acceptable for early phases. Automate when query set is stable.
-->

_Recorded at: {{DATE}} after {{TASK_ID}}_
_Corpus version: {{CORPUS_VERSION_TAG_OR_DATE}}_

| Metric | Description | Baseline | Previous | Current | Delta | Regression? |
|--------|-------------|----------|----------|---------|-------|-------------|
| Faithfulness | Answer contains only claims supported by the retrieved context | — | — | — | — | — |
| Answer Completeness | Answer addresses the full question given the retrieved context | — | — | — | — | — |
| Answer Relevance | Answer is on-topic and appropriately scoped to the query | — | — | — | — | — |

Scoring: 0.0–1.0 per metric, averaged across the evaluation query set.
Judge: {{LLM_JUDGE_MODEL_AND_PROMPT_REF}}

<!--
Security note: this file contains ground-truth query→document mappings.
If answer quality evaluation is automated, keep expected answers in a separate file not accessible to the implementation agent.
Exposing expected answers in the same file the agent reads during implementation creates a contamination risk.
-->

---

## Regression Notes

<!--
Record any metrics that regressed and why.
If a regression is acceptable (e.g., latency increased due to reranking that improved quality),
document the trade-off explicitly.
If a regression is not acceptable, add a retrieval finding to CODEX_PROMPT.md ## RAG State.
-->

{{none | description of regressions and their justification}}

---

## No-Answer Behavior Quality

Did no-answer queries correctly trigger `insufficient_evidence`?

| Query ID | Result | Expected | Pass? |
|----------|--------|----------|-------|
| Q-NA-01 | | insufficient_evidence | |

Notes: {{any patterns or failure modes observed}}

---

## Evidence / Citation Correctness

For a sample of successful queries, verify that the assembled evidence matches the source:

| Query ID | Citation present? | Source matches? | Notes |
|----------|-------------------|-----------------|-------|
| Q01 | | | |
| Q02 | | | |

---

## Experiments

Use this section to track deliberate retrieval changes and their outcomes.
Test one variable at a time. Record results before deciding.

| ID | Hypothesis | Change | Metric(s) targeted | Result vs. baseline | Decision |
|----|-----------|--------|--------------------|---------------------|----------|
| EXP-01 | {{e.g., smaller chunks improve MRR on short queries}} | {{chunking: 512→256 tokens}} | {{MRR, hit@3}} | {{+0.04 MRR, −0.01 hit@3}} | {{adopted / rejected / pending}} |

Rules:
- One variable per experiment.
- Record result before deciding. Decision comes after data, not before.
- If adopted: update Baseline Metrics to reflect the new state.
- If rejected: keep the row as a record that this path was tried.

---

## Open Retrieval Findings

<!--
Record retrieval-specific issues here. Copy to CODEX_PROMPT.md ## RAG State > Open retrieval findings.
Format matches the Open Findings format in CODEX_PROMPT.md.
-->

none

---

## Evaluation History

<!--
Append a one-line summary after each evaluation run.
-->

| Date | Task | Corpus Version | Eval Source | hit@3 | MRR | No-answer acc. | Faithfulness | Completeness | Note |
|------|------|----------------|-------------|-------|-----|----------------|--------------|--------------|------|
| {{DATE}} | {{TASK_ID}} | {{CORPUS_VERSION_TAG_OR_DATE}} | {{command or method}} | — | — | — | — | — | initial baseline |

<!--
Corpus Version: tag, date, or hash that identifies the document corpus active at time of evaluation.
Required so metric changes can be attributed to code changes vs. corpus changes.
If the corpus never changes, record a static tag (e.g., "v1.0-static") and note it once.
-->
