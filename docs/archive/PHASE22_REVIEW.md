# Phase 22 Review — Test 7/8 Sync, Notes, Titles, Interpretation

Date: 2026-05-09
Status: Passed with one documented follow-up

## Scope

- Fail-soft Google Docs ingestion when one source document contains duplicate candidates.
- Honest sync status and user notification wording.
- Live re-sync of the primary Google Doc and fish-search proof for `5.11.24 запретная рыба`.
- Note placement at the end of the target dream section.
- Title intake cleanup for `Название — ...` and recording-command stripping.
- User-approved whole-dream LLM interpretation flow.

## Verification

- `tests/unit/test_rag_ingestion.py tests/unit/test_segmentation.py tests/unit/test_auto_sync.py` -> 18 passed, 1 warning.
- `tests/unit/test_assistant_chat.py tests/unit/test_auto_sync.py tests/unit/test_ingest_notify.py` -> 92 passed, 1 warning.
- `tests/unit/test_assistant_chat.py tests/unit/test_rag_query.py tests/unit/test_retrieval_eval.py` -> 98 passed, 1 warning.
- `tests/unit/test_gdocs_client.py tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py tests/unit/test_telegram_bot.py tests/unit/test_transcription_worker.py` -> 175 passed, 1 warning.
- `tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py tests/unit/test_telegram_bot.py` -> 159 passed, 1 warning.
- Combined Phase 22 gate -> 225 passed, 1 warning.
- `ruff check app tests` -> clean.
- `ruff format --check app tests` -> clean.

## Live Checks

- Current primary Google Doc parsed successfully after duplicate-candidate fail-soft handling.
- Live auto-sync completed: `AutoSyncResult(action='synced', marker='1878', job_id='771be95e-b101-44d1-9c91-89261bac9773')`.
- Redis auto-sync state after the run: `last_sync_status='synced'`, `last_synced_at='2026-05-09T15:25:30.000120+00:00'`.
- DB contains `5.11.24 запретная рыба`.
- Exact search for `рыба` returned `5.11.24 запретная рыба`.
- Assistant `search_dreams` for `сон с рыбой` returned `5.11.24 запретная рыба` first with exact evidence text.

## Findings

No P0/P1 findings.

P2 follow-up: provider-dependent LLM title generation was not added in Phase 22. The implemented fix removes recording commands from stored text, extracts explicit titles deterministically, and generates deterministic fallback titles from cleaned dream text. This closes the observed bad-title regression but does not produce LLM-quality titles.

P3 risk: Google Docs insertion indexes are covered by unit fixtures for middle, last, and no-body sections, but should still be smoke-tested against the live document after deployment.

## Deployment Notes

- No database migration required.
- Restart `dream-motif-telegram.service` so new tool schemas, prompt rules, and pending interpretation state are live.
- Restart `dream-motif-auto-sync.service` so duplicate fail-soft ingestion is active in the scheduled loop.
