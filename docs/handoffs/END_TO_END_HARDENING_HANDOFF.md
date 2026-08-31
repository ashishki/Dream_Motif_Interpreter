# End-to-End Hardening Handoff

Updated: 2026-08-31

## Source goal

Audit the current `Dream_Motif_Interpreter` as a developer, designer, and real user; find and implement the changes that reduce operator test time without lying about persistence, delivery, indexing, or deployment state. Finish through a reviewable branch and draft PR, but never merge or push directly to `main` without separate approval.

## Git state at handoff creation

- Branch: `codex/end-to-end-hardening`
- Base: `origin/main` at `db5947968a823eab98192d7abad73430d45d952c`
- Existing hardening commit: `d3f3171889870f14a669d5d8a808162d0b8da7fe`
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

## Files changed by `d3f3171`

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
- `alembic heads` — exactly `026_manual_sync_jobs (head)`.
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
3. Manual `/sync` execution now creates a PostgreSQL `manual_sync_jobs` row before exposing queued status, and API/Telegram startup recover pending, retryable and stale-running manual sync work. A live crash/restart canary against operator-owned Google Docs credentials has not been performed locally.
4. Failed rollout keeps or returns application writers to a stopped state once quiescing has begun, and the bot/auto-sync are not restarted until the new API passes exact-`BUILD_SHA` readiness. Application images are tagged by `APP_IMAGE_REPOSITORY:BUILD_SHA`, deploy creates and verifies a pre-migration dump, and a separate restore verifier drills that dump into a disposable database. Automatic restoration of a previous image/schema is intentionally not attempted.
5. No live Telegram, Google Docs, OpenAI/Whisper, or production database mutation was performed; those require operator-owned credentials and an explicit canary window.

## Remaining work by independent phase

Each phase must be a separate small commit. After every phase, update this file under `Phase log` with `completed`, `tests`, `remaining`, and `next step`.

### A. Safety and deployment — P0/P1 gate

- Run CI container and PostgreSQL integration gates.
- Add/verify a concrete rollback preflight and documented database restore drill without destructive automatic schema rollback. Compose image tags now make previous app images addressable, deploy now needs a verified pre-migration dump before migration, and the non-production restore verifier is implemented with PR #5 CI green; a live Compose drill with operator-owned data remains pending.
- Validate `/ready` versus `/health` behavior in Compose and deployment-contract tests. The local deployment contract now verifies that Telegram/auto-sync restart only after API `/ready` succeeds; CI/container runtime still needs to execute it in a real Compose environment.

### B. Durable capture/outbox and voice lifecycle — P1

- Run a live crash/restart canary for the durable manual `/sync` queue with an operator-selected disposable Google Doc.
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

- completed: large end-to-end implementation in `d3f3171889870f14a669d5d8a808162d0b8da7fe`.
- tests: local gates listed above are green.
- remaining: phases A–E and CI/live canaries described above.
- next step: publish the existing commit and this documentation-only handoff commit to `codex/end-to-end-hardening`, then open a draft PR targeting `main` and wait for CI without merging.

### Phase A — CI repair 1

- completed: draft PR #5 opened; install, lock, Ruff, and non-root container jobs passed. Corrected six PostgreSQL-CI mismatches without weakening production invariants: order-independent grounded-theme assertion, correct generic DBAPI exception type for deliberate downgrade guards, unique-safe draft timeline fixture, non-null vector evidence for complete-index health, and BUILD_SHA isolation in the configuration test.
- tests: `ruff check` passed; 52 focused local tests passed; 51 affected PostgreSQL integration tests collected cleanly. Later PR CI completed successfully with 905 passed and 6 skipped across Ruff, container, public fixture, retrieval eval, unit, and PostgreSQL integration gates.
- remaining: GitGuardian dashboard incident `36739581` still needs to be classified as a false positive; the production rollback/restore drill remains separate Phase A work.
- next step: begin the first incomplete Phase A implementation slice below, then commit/push it separately.

### Phase A — rollout writer gate

- completed: narrowed the post-migration start sequence in `scripts/deploy_compose.sh`. The script now starts only `api`, waits for `/ready` to report `status=ok` and the exact intended `BUILD_SHA`, and only then starts `telegram-bot` plus optional `auto-sync`. The error trap now distinguishes failure before quiescing from failure after writers were stopped or partially restarted.
- tests: local contract coverage was updated in `tests/unit/test_deployment_contract.py` to assert the order `stop writers -> infra -> migrate -> api -> /ready -> telegram-bot -> auto-sync`, plus the new rollout phases/messages. `docs/DEPLOY.md` was updated to match. Local checks passed: `bash -n scripts/deploy_compose.sh`; `uv run --extra dev ruff check tests/unit/test_deployment_contract.py`; `uv run --extra dev ruff format --check tests/unit/test_deployment_contract.py`; `uv run --extra dev pytest -q tests/unit/test_deployment_contract.py` (`8 passed`); `git diff --check`.
- remaining: PR #5 CI run #193 completed successfully for remote commit `15a138e29fb7d9e59e05db0a70ffb3cb045857c4`. GitGuardian incident `36739581` remains a false-positive dashboard action; the rollback preflight/previous-image drill is still the next implementation slice.
- next step: complete the Compose password-guard cleanup slice below, then watch PR #5 CI.

### Phase A — Compose password guard / GitGuardian noise reduction

- completed: centralized the Compose required-env `POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env` guard on the `postgres` service and changed the four application `DATABASE_URL` entries to reference `${POSTGRES_PASSWORD}` without duplicating the scanner-unfriendly guard text. Added a CI container-contract step that verifies `docker compose config` fails before a placeholder `.env` is created.
- tests: local contract coverage was updated in `tests/unit/test_deployment_contract.py` to assert exactly one required password guard, four app DSNs using the shared value, no database-password fallback, and the new negative CI step. `docs/DEPLOY.md` was updated to explain the centralized guard. Local checks passed: `uv run --extra dev ruff check tests/unit/test_deployment_contract.py`; `uv run --extra dev ruff format --check tests/unit/test_deployment_contract.py`; `uv run --extra dev pytest -q tests/unit/test_deployment_contract.py` (`8 passed`); `git diff --check`.
- remaining: remote commit `9daf1873a027edb250495122b9532fb26e090770` was pushed; PR #5 CI run #195 was superseded/cancelled by the following push. The historical GitGuardian incident `36739581` still must be marked `Skip: false positive` in the GitGuardian dashboard; local code changes alone may not clear a finding attached to commit `d3f3171`.
- next step: commit/push this small Phase A slice, then watch PR #5 CI.

### Phase A — immutable app image identity

- completed: added an OCI revision label to the production Docker image and a shared Compose app-image tag `${APP_IMAGE_REPOSITORY:-dream-motif-interpreter}:${BUILD_SHA:-unknown}` for `migrate`, `api`, `telegram-bot`, and `auto-sync`. Documented `APP_IMAGE_REPOSITORY` and the requirement to retain previous release tags until rollback drill passes.
- tests: contract coverage in `tests/unit/test_deployment_contract.py` now asserts the OCI label, shared app-image anchor, four service image references, `.env.example` default, CI image-label inspection, and rollback-tag note in `docs/DEPLOY.md`. Local checks passed: `uv run --extra dev ruff check tests/unit/test_deployment_contract.py`; `uv run --extra dev ruff format --check tests/unit/test_deployment_contract.py`; `uv run --extra dev pytest -q tests/unit/test_deployment_contract.py` (`8 passed`); `git diff --check`.
- remaining: remote commit `2a95be31389233b38e53382843b1ae74670073a9` was pushed and PR #5 CI run #197 completed successfully. The next rollback slice must add a verified pre-migration `pg_dump`/manifest plus a non-production restore drill; this image-tag slice alone is not a complete rollback procedure.
- next step: complete the pre-migration backup slice below, then watch PR #5 CI.

### Phase A — pre-migration backup manifest

- completed: `scripts/deploy_compose.sh` now requires `--backup-dir` or `DEPLOY_BACKUP_DIR`, rejects relative or in-repository backup paths, captures the currently running API container/image/OCI revision when present, stops writers, starts Postgres/Redis, writes a custom-format `pg_dump`, verifies it with `pg_restore --list`, records SHA256 plus Alembic revision in a mode-0600 manifest, and only then builds/runs migrations. README, DEPLOY, Telegram runbook, voice runbook, and ENVIRONMENT were updated for the new deployment contract.
- tests: `tests/unit/test_deployment_contract.py` now asserts the new command usage, backup requirement, path guard, overwrite guard, nonempty dump guard, manifest fields, backup-before-build-before-migration order, and updated docs/runbook commands. Local checks passed: `bash -n scripts/deploy_compose.sh`; `uv run --extra dev ruff check tests/unit/test_deployment_contract.py`; `uv run --extra dev ruff format --check tests/unit/test_deployment_contract.py`; `uv run --extra dev pytest -q tests/unit/test_deployment_contract.py` (`8 passed`); `git diff --check`.
- remaining: remote commit `2a1fe76f20c4e52c27e52a527c4f6352e274d6ea` was pushed and PR #5 CI run #199 completed successfully. A non-production restore verifier/drill is still required next; this slice creates and validates the archive but does not prove restore into a disposable DB.
- next step: complete the restore verifier slice below, then watch PR #5 CI.

### Phase A — rollback restore verifier

- completed: added executable `scripts/verify_compose_rollback.sh`. It reads the deploy manifest without sourcing it, verifies the backup file is regular/private and matches SHA256, validates `pg_restore --list`, verifies the recorded previous API image and OCI revision label when present, restores into a simple database name ending `_restore_drill`, checks the restored Alembic revision when recorded, and drops the disposable database on exit. `docs/DEPLOY.md` and `docs/RUNBOOK_TELEGRAM_BOT.md` now document the drill and the refusal to restore canonical `dream_motif`.
- tests: added `tests/unit/test_rollback_preflight.py` covering restore-drill-only safety, no manifest sourcing, checksum/archive checks, previous-image OCI checks, cleanup trap, and docs references. Local checks passed: `bash -n scripts/deploy_compose.sh scripts/verify_compose_rollback.sh`; `uv run --extra dev ruff check tests/unit/test_deployment_contract.py tests/unit/test_rollback_preflight.py`; `uv run --extra dev ruff format --check tests/unit/test_deployment_contract.py tests/unit/test_rollback_preflight.py`; `uv run --extra dev pytest -q tests/unit/test_deployment_contract.py tests/unit/test_rollback_preflight.py` (`11 passed`); `git diff --check`.
- remaining: remote commit `9641d65c03144765b38074df9f75e338826726ef` was pushed and PR #5 CI run #201 completed successfully. GitGuardian incident `36739581` remains a dashboard false-positive action; live restore drill against operator-owned backup data has not been executed locally.
- next step: have the operator mark GitGuardian incident `36739581` as `Skip: false positive` and run the documented live restore drill in a non-production window. If continuing code-only work, start Phase B with durable manual `/sync` execution and commit it separately.

### Phase B — durable manual sync jobs

- completed: added Alembic revision `026_manual_sync_jobs`, the `ManualSyncJob` model, and `app/workers/sync_jobs.py` with claim/lease/retry/fenced finalize behavior for operator-triggered Google Docs sync. `LocalAsyncJobEnqueuer` now commits a PostgreSQL job before writing Redis status, starts one recovery loop instead of per-request fire-and-forget tasks, and reads durable status before Redis TTL state. FastAPI lifespan and Telegram `post_init` start the recovery loop after runtime validation. Follow-up fix bounds API-lifespan supervisor shutdown and clears the cached enqueuer factory after shutdown so repeated `TestClient`/lifespan restarts in one process cannot reuse a closed enqueuer. `tests/integration/test_dreams_api.py::test_post_sync_returns_202` now uses a recording enqueuer so the HTTP 202 smoke cannot launch real Google Docs ingestion with fake CI credentials.
- tests: added `tests/unit/test_manual_sync_jobs.py` and updated enqueuer/facade/Telegram/migration coverage for durable creation, status fallback, stale Redis precedence, claim/retry, terminal worker-reported failure, lifecycle startup, schema and downgrade guard. Local checks passed: `uv run --extra dev ruff check app/api/dreams.py app/main.py app/assistant/facade.py app/telegram/bot.py app/models/processing.py app/models/__init__.py app/workers/sync_jobs.py tests/unit/test_sync_job_enqueuer.py tests/unit/test_manual_sync_jobs.py tests/unit/test_assistant_facade.py tests/unit/test_telegram_bot.py tests/integration/test_migrations.py alembic/versions/026_manual_sync_jobs.py`; `uv run --extra dev ruff format --check ...`; `uv run --extra dev pytest -q tests/unit/test_sync_job_enqueuer.py tests/unit/test_manual_sync_jobs.py tests/unit/test_assistant_facade.py tests/unit/test_telegram_bot.py` (`168 passed`); `uv run --extra dev pytest -q tests/unit/test_auto_sync.py tests/unit/test_ingest_notify.py tests/unit/test_dream_processing_supervisor.py tests/unit/test_dream_processing_worker.py tests/unit/test_note_processing_worker.py` (`36 passed`); `python -m compileall -q app alembic tests/unit/test_manual_sync_jobs.py tests/unit/test_sync_job_enqueuer.py`; `DATABASE_URL=postgresql+asyncpg://postgres@localhost:5433/dream_motif_test uv run --extra dev alembic heads` (`026_manual_sync_jobs (head)`). Follow-up hang-fix local checks passed: `.venv/bin/ruff check app/api/dreams.py app/main.py tests/integration/test_dreams_api.py tests/unit/test_sync_job_enqueuer.py tests/unit/test_manual_sync_jobs.py tests/unit/test_assistant_facade.py tests/unit/test_telegram_bot.py`; `.venv/bin/ruff format --check ...`; `.venv/bin/pytest -q --collect-only tests/integration/test_dreams_api.py tests/integration/test_workers.py tests/integration/test_e2e.py tests/integration/test_migrations.py` (`49 tests collected`); `.venv/bin/pytest -q tests/unit --tb=short` (`804 passed`).
- remaining: remote commits `49e3e58dd5dc4e1cf0f9401b87f4f127577df843` and `8fe9541c94573ccb1eeb16da97d93f4c068d1f50` were pushed. PR #5 CI run #207 for `8fe9541c94573ccb1eeb16da97d93f4c068d1f50` remained stuck inside the `Pytest` job after earlier run #203 had completed quickly; local reproduction isolated API lifespan startup/shutdown with repeated `TestClient` uses, and code review isolated the real `/sync` API smoke launching background ingestion. Follow-up remote commit `f5754cdd8bef43b4937e62a13565ad54ad3ebd42` fixes the lifespan part; this integration-smoke isolation still needs to be committed, pushed and validated by the next PR #5 CI run. A live crash/restart canary against an operator-owned disposable Google Doc has not been executed locally.
- next step: commit/push this Phase B integration-smoke isolation slice separately, watch PR #5 CI, then continue Phase B with PostgreSQL voice cleanup races/crash-restart recovery or move to the Google Docs canary in Phase C.

## Exact next command for a new agent

```bash
git fetch origin && git switch codex/end-to-end-hardening && git pull --ff-only origin codex/end-to-end-hardening && sed -n '1,360p' docs/handoffs/END_TO_END_HARDENING_HANDOFF.md
```

Then start only the first incomplete phase shown in `Phase log`, commit it separately, update this handoff, and do not merge or push directly to `main` without explicit user approval.
