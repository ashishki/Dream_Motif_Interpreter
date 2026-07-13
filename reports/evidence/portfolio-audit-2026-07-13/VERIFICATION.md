# Dream Motif P1 verification receipt

Date: 2026-07-13

Base commit: `a3580217a33411a18acf1443287edf64151bcbd2`

## CI diagnosis

- Failing workflow: GitHub Actions `CI`, run `27751460161`.
- Failing job: `Ruff format check`, job `82102779539`.
- Connector-fetched log identified three files: `app/assistant/facade.py`,
  `app/telegram/handlers.py`, and `tests/unit/test_assistant_facade.py`.
- Pytest was skipped because the workflow requires both Ruff jobs first.
- The repair applies Ruff's formatter and keeps the code behavior unchanged. The workflow also
  uses read-only permissions, non-persisted checkout credentials, current action runtimes,
  concurrency cancellation, and bounded timeouts.

## Local verification

All commands used placeholder credentials and a disposable pgvector PostgreSQL database. No
private Google Docs, Telegram messages, provider calls, or operator database were used.

| Check | Result |
|---|---|
| `ruff check app/ scripts/ tests/` | pass |
| `ruff format --check app/ scripts/ tests/` | pass; 159 files formatted |
| `pytest -q --tb=short tests/` | 627 passed, 6 skipped, 1 warning |
| `python scripts/eval.py --task-id CI --no-write-markdown` | pass against disposable PostgreSQL/pgvector |
| `python scripts/eval_public_fixture.py --check reports/evidence/portfolio-audit-2026-07-13/dream_motif_public_retrieval_v1.json` | pass; 8 cases |

The single warning is SQLAlchemy schema reflection not recognizing the pgvector `vector` type in
`tests/integration/test_migrations.py`; it does not fail the migration assertion.

## Public evidence boundary

- Corpus: 6 handcrafted synthetic records,
  `sha256:e92f2925dbe1fa1af305cd1fea328575665b2f93711cab2a0863d168693dd841`.
- Cases: 8 records,
  `sha256:b506eb5756c4b525c8a1c2c93fdef209b75a05b6646807f551b18523d69aa928`.
- The tracked JSON report records each ranked source, exact citation offsets, configuration,
  abstentions, metrics, gates, and evaluator content address.
- The privacy marker test is a conservative regression scan, not a general privacy proof.
- These checks do not establish live hybrid-retrieval quality, generated-answer quality,
  psychological or clinical validity, external use, longitudinal outcomes, or production
  operation.
