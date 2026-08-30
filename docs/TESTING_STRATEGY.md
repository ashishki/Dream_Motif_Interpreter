# Testing Strategy

Last updated: 2026-08-30

## 1. Current Testing Posture

Dream Motif Interpreter already has a stronger backend testing posture than many small assistant projects:

- unit tests
- integration tests
- migration tests
- retrieval tests
- end-to-end seeded backend flow tests
- Telegram bot tests
- voice pipeline tests
- motif/research/feedback tests

This should remain a project strength during Telegram UX hardening and Google Docs sync work.

Current local checkpoint:

- `.venv/bin/ruff check app/ scripts/ tests/`
- `.venv/bin/ruff format --check app/ scripts/ tests/`
- `.venv/bin/pytest tests/unit -q`
- `python scripts/eval_public_fixture.py --check reports/evidence/portfolio-audit-2026-07-13/dream_motif_public_retrieval_v1.json`

Interpretation:

- unit and privacy-safe replay checks are deterministic and should pass without live provider keys
- full `pytest tests/` mirrors CI more closely and requires the disposable PostgreSQL/pgvector
  environment used by GitHub Actions
- live Google Docs, Telegram, Anthropic, and OpenAI behavior must be smoke-tested separately on
  the operator deployment

## 2. Phase 6 Test Expansion

Telegram text interaction adds new required test areas:

- Telegram authorization guard
- session load/save behavior
- assistant tool-routing correctness
- insufficient-evidence conversational response path
- sync-trigger behavior from chat

## 3. Phase 7 Test Expansion

Voice support adds:

- media metadata persistence
- download/transcription orchestration
- transcription error handling
- duplicate-job handling
- media cleanup

## 4. Recommended Test Layers

### Unit

- bot auth guard
- assistant routing logic
- tool schema and policy checks
- session-state helpers
- media-retention calculations

### Integration

- bot runtime against fake Telegram updates
- assistant calls into real service layer with test DB
- voice job orchestration with provider test doubles

### End-to-End

- authorized user asks text question and receives grounded answer
- authorized user sends voice note and receives transcript-based answer
- unauthorized user is blocked

## 5. Risk-Based Priorities

Highest-priority new tests:

- chat cannot bypass mutation policy
- assistant does not fabricate when search returns weak evidence
- session state survives restart
- voice jobs do not leak media files indefinitely

## 6. Local CI Equivalent

Before pushing maintenance or Telegram UX changes, run the same classes of checks as CI:

```bash
.venv/bin/ruff check app/ scripts/ tests/
.venv/bin/ruff format --check app/ scripts/ tests/
.venv/bin/pytest tests/ -q --tb=short
.venv/bin/python scripts/eval_public_fixture.py \
  --check reports/evidence/portfolio-audit-2026-07-13/dream_motif_public_retrieval_v1.json
.venv/bin/python scripts/eval.py --task-id CI --no-write-markdown
```

Use the same placeholder env values as `.github/workflows/ci.yml` for tests/evals that should not
touch live providers. Do not rely on production `.env` to prove CI safety.

## 7. Live Smoke Boundary

Green CI does not prove live integrations. After deployment, run the relevant smoke checklist in:

- [Telegram bot runbook](RUNBOOK_TELEGRAM_BOT.md)
- [Voice pipeline runbook](RUNBOOK_VOICE_PIPELINE.md)

At minimum after Telegram handler changes, verify:

- one running polling process
- `/health` reports zero unindexed dreams/notes
- reply notes work on one displayed dream and one newly saved dream confirmation
- full-text button count matches the visible dream list
