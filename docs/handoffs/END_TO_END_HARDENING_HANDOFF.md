# End-to-End Hardening Handoff

Updated: 2026-08-31

## Source goal

Audit the current `Dream_Motif_Interpreter` as a developer, designer, and real user; find and implement the changes that reduce operator test time without lying about persistence, delivery, indexing, or deployment state. Finish through a reviewable branch and draft PR, but never merge or push directly to `main` without separate approval.

## Git state at handoff creation

- Branch: `codex/end-to-end-hardening`
- Base: `origin/main` at `db5947968a823eab98192d7abad73430d45d952c`
- Existing hardening commit: `d18aa4fca2f68e4ad2c5ccfad86b2e1a774490db`
- Existing commit message: `feat: harden durable capture and deployment`
- `main` was not modified directly.
- The large commit already existed before this handoff and must not be split or rewritten retroactively.

## Implemented

### Safety and deployment

- Non-root production image, hashed production/dev dependency locks, deny-by-default Docker build context, pinned CI actions, `pip check`, frozen-lock verification, and container contract tests.
- Compose isolates Postgres/Redis on localhost, requires explicit database secrets, persists runtime state, supports an opt-in read-only Google service-account overlay, and gives the Telegram bot a bounded shutdown grace period.
- Production configuration fails closed for weak/missing secrets and unavailable Redis; build identity is exposed and checked.
- Quiesced rollout script stops all application writers before migration and starts them only after Alembic succeeds. Dirty worktrees and a `BUILD_SHA` different from `HEAD` are rejected.
- `/ready` is separated from diagnostic `/health`: durable index backlog no longer blocks rollout readiness, while database failure still does. Null embeddings are treated as unindexed.
- Mini App/private API responses use no-store and security headers; the Mini App shell has CSP.

### Durable capture/outbox and voice lifecycle

- Stable Telegram source-event identity distinguishes two separate messages with identical text while making replay of the same update idempotent.
- Dream and note writes create durable stage jobs atomically. Dream stages cover index, analysis, motif, and Google Docs; note stages cover index and Google Docs where applicable.
- Workers use leases, fencing tokens, compare-and-set finalization, retry state, fair supervisor turns, and startup recovery.
- Google-originated note ingest writes the note and index job in one transaction, avoids Google Docs echo, and repairs missing/null embeddings safely.
- Voice delivery stores durable receipt/lease/retry/reply cursor state. Lease loss cancels download, Whisper, assistant construction, and Telegram send. Shutdown is bounded and closes facade/Redis resources.
- Cleanup is path-confined and lease-aware, with race tests for reclaim/cleanup behavior.
- Manual sync now follows the runtime-selected Google document, applies a seven-day Redis status TTL, and marks gracefully cancelled local work failed instead of leaving an eternal queued/running promise.

### Google Docs identity and sync

- Source-slot identity is document-aware and stable across unrelated heading inserts.
- A body mutation for an already claimed source fails closed instead of silently duplicating or overwriting content.
- Telegram-to-Google delivery uses named ranges and durable receipts for replay-safe adoption/confirmation.
- Runtime document selection is persisted with cross-process file locking and merge semantics, so API, bot, and autosync share the active source.
- Google API transport uses bounded timeouts.

### Replay, retrieval, and evaluation

- Hybrid retrieval has exact/semantic outage fallbacks, stricter evidence thresholds, deduplication, offsets, and citation safety.
- Motif review is evidence-first and preserves append-only annotation history; normalized identities are unique and unsafe privacy-sensitive merges fail closed.
- Real python-telegram-bot routing replay fixtures cover start, negated dream capture, compound capture/question splitting, and authorization guard behavior.
- Public privacy-safe retrieval fixture is content-addressed and reproducible.
- Destructive evals require an explicitly suffixed disposable database and confirmation.

### Operator and end-user UX

- Natural Telegram capture, confirmation cards, full-text controls, retry actions, signed/replay-safe feedback, and pending state that survives failed durable writes.
- User-facing messages distinguish canonical save, indexing, analysis, motif, and Google Docs delivery instead of promising completion too early.
- Batch note capture reports partial/mixed outcomes honestly.
- Dream Memory UI escapes untrusted content, uses real citation URLs only, has keyboard focus, accessible live status, retry, and explicit error states.
- Russian user/operator documentation and runbooks were aligned with the durable workflow and same-text semantics.

## Files changed by `d18aa4f`

Status below is relative to `origin/main` (`A` = added, `M` = modified):

```text
A .dockerignore
A .env.example
M .github/workflows/ci.yml
M .gitignore
A Dockerfile
M README.md
M alembic/env.py
A alembic/versions/021_voice_delivery_durability.py
A alembic/versions/022_capture_idempotency.py
A alembic/versions/023_dream_processing_jobs.py
A alembic/versions/024_restore_graph_controls.py
A alembic/versions/025_note_processing_jobs.py
M app/api/dream_memory.py
M app/api/dreams.py
M app/api/health.py
M app/api/motifs.py
M app/api/research.py
M app/assistant/chat.py
M app/assistant/facade.py
M app/assistant/prompts.py
M app/assistant/session.py
M app/assistant/tools.py
M app/assistant/voice_media.py
M app/main.py
M app/models/__init__.py
M app/models/dream.py
M app/models/dream_graph_control.py
M app/models/motif.py
M app/models/note.py
A app/models/processing.py
M app/models/theme.py
M app/models/voice.py
M app/models/write_status.py
M app/research/synthesizer.py
M app/retrieval/ingestion.py
M app/retrieval/query.py
M app/services/analysis.py
M app/services/dream_memory_graph.py
M app/services/gdocs_client.py
M app/services/motif_service.py
M app/services/proof_receipts.py
M app/services/segmentation.py
M app/shared/config.py
M app/shared/tracing.py
M app/static/dream_memory_map.html
M app/telegram/__main__.py
M app/telegram/bot.py
M app/telegram/handlers.py
M app/telegram/voice.py
M app/workers/cleanup.py
A app/workers/dream_processing.py
A app/workers/dream_supervisor.py
M app/workers/ingest.py
A app/workers/note_processing.py
M app/workers/transcribe.py
A docker-compose.google-service-account.yml
M docker-compose.yml
M docs/ARCHITECTURE.md
M docs/AUTH_SECURITY.md
M docs/DECISION_LOG.md
M docs/DEPLOY.md
M docs/DREAM_MEMORY_MAP.md
M docs/ENVIRONMENT.md
M docs/FEEDBACK_LOOP.md
M docs/IMPLEMENTATION_CONTRACT.md
M docs/RUNBOOK_TELEGRAM_BOT.md
M docs/RUNBOOK_VOICE_PIPELINE.md
M docs/SYSTEMD_SETUP.md
M docs/TELEGRAM_INTERACTION_MODEL.md
M docs/TESTING_STRATEGY.md
M docs/USER_GUIDE_RU.md
A docs/adr/ADR-011-durable-work-and-ephemeral-telegram-state.md
M docs/retrieval_eval.md
M pyproject.toml
A requirements-dev.lock
A requirements.lock
M requirements.txt
A scripts/deploy_compose.sh
M scripts/eval.py
M tests/conftest.py
A tests/fixtures/telegram_conversation_replays.json
M tests/integration/test_analysis.py
M tests/integration/test_health.py
M tests/integration/test_ingestion_pipeline.py
M tests/integration/test_migrations.py
M tests/integration/test_rag_ingestion.py
M tests/integration/test_rag_query.py
M tests/integration/test_retrieval_eval.py
M tests/integration/test_segmentation.py
A tests/integration/test_telegram_conversation_replay.py
A tests/integration/test_voice_cleanup_races.py
M tests/unit/test_assistant_chat.py
M tests/unit/test_assistant_facade.py
M tests/unit/test_assistant_session.py
M tests/unit/test_ci.py
M tests/unit/test_config.py
A tests/unit/test_deployment_contract.py
M tests/unit/test_dream_graph_privacy_control_model.py
M tests/unit/test_dream_memory_export_api.py
A tests/unit/test_dream_memory_graph_service.py
M tests/unit/test_dream_memory_map_spec.py
A tests/unit/test_dream_processing_supervisor.py
A tests/unit/test_dream_processing_worker.py
M tests/unit/test_eval_script.py
M tests/unit/test_feedback_capture.py
M tests/unit/test_gdocs_client.py
A tests/unit/test_ingest_source_identity.py
M tests/unit/test_motif_model.py
M tests/unit/test_motif_service.py
M tests/unit/test_motifs_api.py
A tests/unit/test_natural_dream_capture.py
A tests/unit/test_note_processing_job_model.py
A tests/unit/test_note_processing_worker.py
M tests/unit/test_proof_receipts.py
M tests/unit/test_rag_ingestion.py
M tests/unit/test_rag_query.py
M tests/unit/test_rag_query_expansion.py
M tests/unit/test_research_api.py
M tests/unit/test_research_synthesizer.py
M tests/unit/test_retrieval_eval.py
A tests/unit/test_sync_job_enqueuer.py
M tests/unit/test_telegram_bot.py
M tests/unit/test_telegram_voice.py
M tests/unit/test_transcription_worker.py
M tests/unit/test_voice_cleanup.py
A tests/unit/test_write_status_model.py
A uv.lock
```

This handoff file is intentionally a later, separate documentation-only commit.
The full branch-level inventory therefore contains **128 files**: the 127 files
listed above plus `A docs/handoffs/END_TO_END_HARDENING_HANDOFF.md`.

## Completed checks

- `ruff check app scripts tests` — passed.
- `ruff format --check app scripts tests` — passed (176 files).
- `git diff --check` — passed.
- `python -m compileall -q app scripts tests` — passed.
- `uv lock --check` — passed; 88 packages resolved.
- `alembic heads` — exactly `025_note_processing_jobs (head)`.
- `pytest -q tests/unit` — **789 passed**.
- `pytest -q tests/integration/test_telegram_conversation_replay.py` — **4 passed**.
- `pytest -q --collect-only tests/integration` — **122 tests collected**.
- `python scripts/eval_public_fixture.py --check reports/evidence/portfolio-audit-2026-07-13/dream_motif_public_retrieval_v1.json` — **PASS: 8 cases**, content hash `sha256:e92f2925dbe1fa1af305cd1fea328575665b2f93711cab2a0863d168693dd841`.
- Focused lifecycle/voice verification — **137 passed**; deployment lifecycle subset — **3 passed**.
- Focused deploy/docs/UX verification — **33 passed**; `bash -n scripts/deploy_compose.sh` and extracted inline Mini App JavaScript `node --check` passed.
- Focused durable dream/note ingest/supervisor verification — **42 passed**.
- Focused source identity/Google Docs/Telegram replay verification — **45 passed**.
- Focused assistant/Telegram UX verification — **258 passed**.

## Known limitations

1. Local Docker is unavailable, so Compose/container runtime checks and the non-root container smoke must run in GitHub Actions.
2. Local PostgreSQL/pgvector is unavailable on the expected test port. The full migration upgrade/downgrade, deferred-trigger, vector-query, and cleanup-race integration suite must run in CI.
3. Manual `/sync` execution is still process-local. Graceful shutdown produces an honest failed/retryable status and autosync can recover data, but a hard kill between Redis state write and task execution is not a fully durable queue. A DB/Redis durable sync queue is follow-up work, not something to hide behind UI wording.
4. Failed rollout stops the new writers, but automatic restoration of a previous image/schema is intentionally not attempted. A tested backup/restore and previous-image procedure remains required before production deployment.
5. No live Telegram, Google Docs, OpenAI/Whisper, or production database mutation was performed; those require operator-owned credentials and an explicit canary window.

## Remaining work by independent phase

Each phase must be a separate small commit. After every phase, update this file under `Phase log` with `completed`, `tests`, `remaining`, and `next step`.

### A. Safety and deployment — P0/P1 gate

- Run CI container and PostgreSQL integration gates.
- Add/verify a concrete rollback preflight and documented previous-image/database restore drill without destructive automatic schema rollback.
- Validate `/ready` versus `/health` behavior in Compose and deployment-contract tests.

### B. Durable capture/outbox and voice lifecycle — P1

- Replace process-local manual `/sync` execution with a durable claim/recovery queue, or explicitly scope and implement orphan recovery with an immutable job record.
- Run PostgreSQL voice cleanup races and crash/restart recovery tests.
- Verify fencing at every irreversible external send boundary.

### C. Google Docs identity/sync — P1/P2

- Run real-but-nonproduction Google Docs canary against an operator-selected disposable document.
- Verify named-range adoption, conflict fail-closed behavior, runtime source switch, and metadata timeout in one repeatable script.

### D. Replay/evaluation — P1/P2

- Run the complete PostgreSQL/pgvector integration suite and retrieval eval in CI.
- Add replay cases from the current human tester's highest-time-cost workflows, preserving privacy-safe fixtures.
- Record evaluation artifacts and regressions without claiming live quality from synthetic fixtures.

### E. Operator UX and motif review — P2

- Perform keyboard/mobile Mini App smoke and Telegram canary with the real operator.
- Measure where the user still spends time checking persistence/delivery and remove redundant confirmation steps.
- Validate evidence-first motif review, undo/history visibility, and mixed batch-status wording with observed user sessions.

## Phase log

### Baseline hardening

- completed: large end-to-end implementation in `d18aa4fca2f68e4ad2c5ccfad86b2e1a774490db`.
- tests: local gates listed above are green.
- remaining: phases A–E and CI/live canaries described above.
- next step: publish the existing commit and this documentation-only handoff commit to `codex/end-to-end-hardening`, then open a draft PR targeting `main` and wait for CI without merging.

## Exact next command for a new agent

```bash
git fetch origin && git switch codex/end-to-end-hardening && git pull --ff-only origin codex/end-to-end-hardening && sed -n '1,320p' docs/handoffs/END_TO_END_HARDENING_HANDOFF.md
```

Then start only the first incomplete phase shown in `Phase log`, commit it separately, update this handoff, and do not merge or push directly to `main` without explicit user approval.
