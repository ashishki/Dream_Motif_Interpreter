# Privacy-safe retrieval fixture v1

Status: public synthetic evaluation data

## Purpose

This fixture provides a small, deterministic replay for retrieval and citation-contract checks.
It exists so a reviewer can inspect a public corpus without receiving access to the operator's
Google Docs archive, Telegram messages, database, model prompts, or credentials.

## Construction and provenance

- All six documents were written from scratch for this fixture.
- Every record carries `provenance=handcrafted-synthetic`.
- The scenes use neutral objects and invented combinations; they are not paraphrases of the
  private archive.
- Records intentionally omit people, organizations, contact details, account identifiers,
  dates, URLs, geographic locations, and source-system identifiers.
- `tests/unit/test_public_fixture_eval.py` applies a conservative marker scan for common PII and
  local-path shapes. That scan is a regression safeguard, not a general privacy guarantee.

Schema:

- `corpus.jsonl`: `source_id`, `title`, `text`, `provenance`.
- `cases.jsonl`: `case_id`, `query`, `kind`, `expected_source_ids`.
- `kind` is either `answerable` or `no-answer`.

## Evaluation boundary

The evaluator is an in-memory lexical replay with fixed minimum token-overlap and query-coverage
thresholds plus stable source-ID tie breaking. Citations must name a retrieved source and quote
an exact character slice from it. The replay checks deterministic ranking, abstention, source
attribution, and quote integrity.

It does **not** evaluate the live PostgreSQL/pgvector hybrid ranker, embedding providers, query
expansion, generated interpretations, psychological or clinical validity, longitudinal value,
external users, or production operation. Private-corpus behavior must not be inferred from these
results.

## Reproduce

```bash
python scripts/eval_public_fixture.py \
  --check reports/evidence/portfolio-audit-2026-07-13/dream_motif_public_retrieval_v1.json
```

The tracked report contains SHA-256 content addresses for both JSONL inputs and the evaluator
source. CI recomputes the report and fails if the data, evaluator, citations, or expected results
drift without an explicit evidence update.
