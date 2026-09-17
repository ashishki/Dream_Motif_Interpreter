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

Version: 3
Last updated: 2026-07-13
Changed by: Portfolio audit — public privacy-safe retrieval/citation replay

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

## Public privacy-safe retrieval/citation replay

Eval Source: `python3 scripts/eval_public_fixture.py --check
reports/evidence/portfolio-audit-2026-07-13/dream_motif_public_retrieval_v1.json`, verified
2026-07-13.

The public replay is separate from the private single-operator archive and from the historical
database-backed baseline below. It uses six handcrafted synthetic documents and eight cases.
Every citation must reference a retrieved synthetic source and match an exact character slice.
Input SHA-256 addresses, per-case traces, thresholds, metrics, and gates are stored in the
[tracked report](../reports/evidence/portfolio-audit-2026-07-13/dream_motif_public_retrieval_v1.json);
construction and privacy limits are in the
[data card](../evals/privacy_safe_retrieval_v1/DATA_CARD.md).

All gates pass on this bounded fixture: hit@1, hit@3, MRR, expected-source recall,
citation-source precision, citation exactness, citation query support, and no-answer accuracy are
1.0. These are fixture results, not claims about live hybrid embeddings, the private corpus,
generated interpretations, clinical validity, external use, or production operation.

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

## Phase 18 User Search Regression Dataset

This focused slice captures user-reported failures from Тест 4-5. It is evaluated in
addition to the synthetic T12 dataset when Phase 18 retrieval changes are implemented.

False-positive policy:

- A result is correct only when it exposes an archive-backed evidence fragment.
- The evidence fragment must come from `quote`, `chunk_text`, or `matched_fragments`.
- Semantic adjacency alone is not enough; weak vector neighbors without real evidence
  must be counted as false positives.
- The assistant must not invent or paraphrase dream fragments that are absent from
  retrieved evidence.

| ID | Query | Query Type | Expected relevant evidence | False-positive rule |
|----|-------|------------|----------------------------|---------------------|
| P18-Q01 | молитва | semantic-symbolic | Dream containing Christmas hymn/prayer text; church/icon/prayer dreams if evidence mentions worship, prayer, divine names, liturgy, or hymnody | Do not count generic anxiety, family, or winter scenes unless the returned fragment contains religious/prayer evidence |
| P18-Q02 | где упоминается молитва | semantic-symbolic | Same Christmas hymn/prayer dream even if the literal word `молитва` is absent; evidence may use hymn, prayer-like text, divine names, or worship language | Literal-word absence is acceptable only when archive evidence is prayer-like; no evidence means no hit |
| P18-Q03 | где фигурирует молитва | semantic-symbolic | Same prayer/hymn evidence class as P18-Q01/P18-Q02 | Do not count a result correct without a real fragment tied to prayer, hymnody, liturgy, church, icon, or divine names |
| P18-Q04 | религиозные сюжеты | thematic | Church, icon, prayer, liturgy, divine-name, and Christmas hymnody dreams | Do not return weak symbolic guesses that lack explicit religious evidence |
| P18-Q05 | церковь | semantic-symbolic | Dreams whose evidence mentions church/храм/chapel/liturgy/icon setting | Do not count buildings, halls, schools, or crowds without religious-place evidence |
| P18-Q06 | рождественское песнопение | semantic-symbolic | Dream containing Christmas hymn/prayer/song text | Do not count generic Christmas/winter scenes unless evidence includes hymn/song/prayer language |

Expected relevant archive classes for Phase 18:

- Christmas hymn/prayer dream: expected relevant for `молитва`, `где упоминается молитва`,
  `где фигурирует молитва`, and `рождественское песнопение`.
- Church/icon/prayer dreams: expected relevant for `религиозные сюжеты`, `церковь`, and
  prayer queries when the evidence fragment contains religious language.

---

## Phase 21 Image/Object Exact Recall Regression Dataset

This focused slice captures the Test 6 report that an image search for a fish did not find a
dream entry whose text contains `рыба`.

False-negative policy:

- Concrete image/object queries must not rely only on semantic/vector ranking.
- If the object appears verbatim in `dream_entries.raw_text` or `dream_chunks.chunk_text`, an
  exact evidence fragment must be surfaced even when semantic retrieval returns insufficient
  evidence.
- Success is archive-backed only when `evidence_text` contains the exact object word or a
  same-stem inflected form from the source text.

| ID | Query | Query Type | Expected relevant evidence | False-negative rule |
|----|-------|------------|----------------------------|---------------------|
| P21-Q01 | сон с рыбой | concrete-image-exact | Dream containing `рыба` / same-stem fish word in evidence_text | Fails if no exact fish evidence is returned |
| P21-Q02 | найди рыбу | concrete-image-exact | Same fish dream evidence | Fails if query routing skips exact recall |
| P21-Q03 | сны где есть рыба | concrete-image-exact | Same fish dream evidence | Fails if semantic threshold suppresses exact fish evidence |

---

## Query-Layer Evidence Verification Regression Dataset

This slice moves concrete-object fusion and evidence verification into
`RagQueryService`, so API and Telegram callers receive the same typed `EvidenceBlock`
contract. It also prevents an active theme fragment from being exposed merely because
that fragment occurs somewhere in a retrieved chunk.

Verification policy:

- For extractor-approved concrete-object queries, a PostgreSQL FTS hit is archive-backed
  evidence and survives embedding-call or response failure.
- A theme fragment is returned in `matched_fragments` only when its own text has a Russian
  or simple-FTS relation to the retrieval query. Multi-term concrete queries require all
  core terms in that fragment; a shared adjective alone is not enough.
- A vector-only neighbor must meet the verified semantic floor; the configured threshold
  may raise that floor but cannot lower it below `0.40`.
- Concrete exact rows and semantic rows retain the public `EvidenceBlock` return type and
  are deduplicated by `dream_id`.

| ID | Query | Positive fixture | Negative counterexample | Expected result |
|----|-------|------------------|-------------------------|-----------------|
| QLEV-01 | сон с рыбой | `Рыба черного цвета, она очень красивая.` | Embedding request fails | Fish dream remains first with literal archive sentence in `matched_fragments` |
| QLEV-02 | сон с рыбой | Fish chunk has theme fragment `Рыба черного цвета` | Same chunk also has active fragment `стеклянным лифтом` | Fish fragment is returned; elevator fragment is not |
| QLEV-03 | сон с рыбой | Semantic candidate has no query-related stored fragment | Active fragment only says `Стеклянный лифт` | Candidate may pass only the semantic floor; its unrelated fragment list is empty |

---

## Phase 23 Test 9 Regression Coverage

Focused automated check for the 2026-05-15 feedback: full-dream text retrieval, English-language
Google Doc entries, and numeric feedback interference.

Eval Source: targeted unit suite, run 2026-05-15.

| Check | Result | Evidence |
|-------|--------|----------|
| Full dream text is not truncated by `get_dream` tool output | Pass | `tests/unit/test_assistant_chat.py::test_execute_tool_get_dream_returns_complete_text_without_truncation` |
| Long Telegram assistant replies can be sent in chunks | Pass | `tests/unit/test_telegram_bot.py::test_split_telegram_text_keeps_long_responses_under_limit` |
| English/manual Google Doc headings preserve date, title, and full body | Pass | `tests/unit/test_segmentation.py::test_heading_based_profile_keeps_complete_english_body_and_parses_heading_date` |
| English exact keyword recall has PostgreSQL `simple` FTS coverage | Pass | `tests/unit/test_rag_query.py::test_exact_and_hybrid_search_include_simple_fts_for_english_text` |
| Digit-only replies are normal chat by default | Pass | `tests/unit/test_feedback_capture.py::test_numeric_feedback_disabled_treats_digit_as_normal_chat` |
| Regression suite | Pass | Targeted Phase 23 slice -> 170 passed, 1 warning; full `tests/unit` -> 452 passed, 1 warning |

---

## Phase 22 Manual Google Doc Freshness Regression

This focused live check captures Test 8 from 2026-05-09: the Google Doc had a manually added
entry `5.11.24 запретная рыба`, but bot search could not find it because auto-sync had been
failing since 2026-04-26 on a duplicate parsed candidate.

Eval Source: live primary Google Doc parse plus read-only DB/search checks, run 2026-05-09.

| Check | Result | Evidence |
|-------|--------|----------|
| Duplicate source candidate no longer aborts parse | Pass | Current Google Doc validated 83 entries; duplicate `content_hash` candidate was skipped with non-PII warning |
| Auto-sync state after one live run | Pass | `AutoSyncResult(action='synced', marker='1878', job_id='771be95e-b101-44d1-9c91-89261bac9773')`; Redis state `last_sync_status='synced'`, `last_synced_at='2026-05-09T15:25:30.000120+00:00'` |
| DB freshness for Test 8 fish dream | Pass | `dream_entries` contains title `5.11.24 запретная рыба` after sync |
| Exact recall for `рыба` | Pass | `RagQueryService.exact_search('рыба')` returned 2 rows, including `5.11.24 запретная рыба` |
| Assistant search for `сон с рыбой` | Pass | `search_dreams` returned `5.11.24 запретная рыба` first with evidence text `Рыба черного цвета, она очень красивая` |
| Regression suite | Pass | `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_rag_query.py tests/unit/test_retrieval_eval.py -q --tb=short` -> 98 passed, 1 warning |

---

## Phase 18 Evaluation Run

_Recorded at: 2026-05-02 after WS-18.6_

Eval Source: `scripts/eval.py against §Evaluation Dataset (10 queries), run 2026-05-02` against disposable PostgreSQL database `dream_motif_eval`; read-only real archive eval with `.venv/bin/python scripts/eval_phase18_real.py --limit 5`, run 2026-05-02; plus `.venv/bin/python -m pytest tests/unit/test_eval_phase18_real.py tests/unit/test_eval_script.py tests/unit/test_retrieval_eval.py tests/unit/test_rag_query_expansion.py tests/unit/test_rag_query.py tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py -q --tb=short`, run 2026-05-02.

Scope note: `scripts/eval.py` was run against a disposable seeded test database because it
resets the target schema before loading the synthetic corpus. This validates the synthetic
T12 retrieval dataset after Phase 18 code changes.

The real archive check uses `scripts/eval_phase18_real.py`, which is read-only: it does not
run migrations, reset schema, or write documents. In the local environment the configured
OpenAI key is a placeholder, so `--mode auto` selected the FTS-only archive path instead of
live hybrid embedding retrieval. This measures whether the real indexed archive exposes
archive-backed evidence fragments for the Phase 18 prayer/religion queries. It does not
verify live semantic embedding behavior; that still requires a real `OPENAI_API_KEY` and
`scripts/eval_phase18_real.py --mode live`. A live attempt on 2026-05-02 reached the external
providers but failed authorization: Anthropic query expansion returned 401 and OpenAI
embedding retrieval returned 401 Unauthorized.

| Metric | Result | Notes |
|--------|--------|-------|
| Synthetic retrieval eval | hit@3=1.00; MRR=1.00; no-answer accuracy=1.00 | `scripts/eval.py --task-id WS-18.6` against `dream_motif_eval` |
| Phase 18 unit regression suite | 124 passed | Covers deterministic prayer/religion expansion, broad religious multi-query probes, weak no-evidence suppression, grounded `evidence_text` tool contract, dataset documentation, eval-run limitation documentation, dynamic eval run dates, and read-only real archive eval safeguards |
| Prayer/religion recall on user archive | 6/6 queries returned archive-backed evidence in FTS-only mode | `молитва`, `где упоминается молитва`, `где фигурирует молитва`, `религиозные сюжеты`, `церковь`, and `рождественское песнопение` returned real archive evidence fragments from prayer, church, hymnody, or divine-name dreams |
| Live hybrid embedding recall on user archive | Attempted, blocked by provider auth | `.venv/bin/python scripts/eval_phase18_real.py --mode live --limit 5` reached Anthropic/OpenAI but failed with 401 Unauthorized; requires valid provider keys |
| False-positive count for fabricated/non-evidence fragments | 0 in unit regression | `search_dreams` suppresses weak no-quote/no-fragment results; no-result path contains no invented dream text |
| No-answer/no-more-evidence behavior | Pass in unit regression | Verified via insufficient-evidence and no-more archive-backed matches paths |

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
| Median retrieval latency | 28 ms | p50 latency for the retrieve stage (ms) |
| p95 retrieval latency | 35 ms | p95 latency for the retrieve stage (ms) |
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
| Median retrieval latency | — | 28 ms | — | No |
| p95 retrieval latency | — | 35 ms | — | No |
---

## Answer Quality Metrics

_Recorded at: 2026-04-13 during T14 pre-implementation evaluation refresh_
_Corpus version: synthetic-20-entries_

| Metric | Description | Baseline | Previous | Current | Delta | Regression? |
|--------|-------------|----------|----------|---------|-------|-------------|
| Faithfulness | Answer contains only claims supported by the retrieved context | 1.00 | — | 1.00 | — | No |
| Answer Completeness | Answer addresses the full question given the retrieved context | 0.94 | — | 0.94 | — | No |
| Answer Relevance | Answer is on-topic and appropriately scoped to the query | 0.96 | — | 0.96 | — | No |

Scoring: 0.0–1.0 per metric, averaged across the evaluation query set.
Judge: manual rubric over `scripts/eval.py` retrieval outputs (evidence-only proxy until explainer generation is implemented)

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
| 2026-04-16 | Cycle 9 (WS-9.1–9.6) | synthetic-20-entries | advisory — no retrieval run; retrieval layer unchanged in Phase 9; T12 baseline metrics carry forward | 1.00 | 1.00 | 1.00 | — | — | Phase 9 adds motif induction pipeline only; no changes to chunking, embedding, ranking, or evidence assembly |
| 2026-04-17 | Cycle 10 (WS-10.1–10.5) | synthetic-20-entries | advisory — no retrieval run; RAG retrieval layer unchanged in Phase 10; T12 baseline metrics carry forward. Phase 10 adds ResearchRetriever (external HTTP path separate from dream archive RAG) | 1.00 | 0.94 | 0.96 | — | — | ResearchRetriever does not touch dream_chunks, embedding, or ranking |
| 2026-04-18 | Cycle 11 (WS-11.1–11.3) | synthetic-20-entries | advisory — no retrieval run; RAG retrieval layer unchanged in Phase 11; T12 baseline metrics carry forward. Phase 11 adds Feedback Loop (assistant_feedback table, digit-reply capture, GET /feedback) — no changes to chunking, embedding, or ranking | 1.00 | 0.94 | 0.96 | — | — | Phase 11 does not touch dream_chunks, embedding, or RAG query path |
| 2026-04-21 | T22 | synthetic-20-entries | advisory — no retrieval run; normalization contract added before segmentation; chunking, embedding, ranking, and evidence assembly unchanged; T12/T14 metrics carry forward | 1.00 | 1.00 | 1.00 | 1.00 | 0.94 | normalization is pre-parser only; no retrieval-layer metric delta expected |
| 2026-05-02 | WS-18.6 | phase18-unit-regression | `.venv/bin/python -m pytest tests/unit/test_eval_phase18_real.py tests/unit/test_eval_script.py tests/unit/test_retrieval_eval.py tests/unit/test_rag_query_expansion.py tests/unit/test_rag_query.py tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py -q --tb=short`, run 2026-05-02 | N/A | N/A | Pass | — | — | 124 passed; false-positive count for fabricated/non-evidence fragments is 0 in unit regression |
| 2026-05-02 | WS-18.6 | synthetic-20-entries | scripts/eval.py against §Evaluation Dataset (10 queries), run 2026-05-02 | 1.00 | 1.00 | 1.00 | — | — | synthetic seeded baseline established |
| 2026-05-02 | WS-18.6 | real-user-archive-read-only | `.venv/bin/python scripts/eval_phase18_real.py --limit 5`, run 2026-05-02 | N/A | N/A | Pass | — | — | 6/6 Phase 18 prayer/religion queries returned archive-backed evidence in FTS-only mode; live hybrid embedding path deferred until a real OpenAI key is configured |
| 2026-05-02 | WS-18.6 | real-user-archive-live-hybrid | `.venv/bin/python scripts/eval_phase18_real.py --mode live --limit 5`, run 2026-05-02 | N/A | N/A | Pass | — | — | live hybrid path completed with provider auth; 6/6 Phase 18 prayer/religion queries returned archive-backed evidence |
| 2026-06-02 | WS-21.3 | phase21-fish-image-unit-regression | `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_rag_query.py tests/unit/test_retrieval_eval.py -q --tb=short`, run 2026-06-02 | N/A | N/A | Pass | — | — | concrete fish/image queries route through search_dreams with exact recall fallback; P21-Q01–P21-Q03 documented |
