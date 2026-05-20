# Implementation Journal — Dream Motif Interpreter

Version: 1.22
Last updated: 2026-05-20
Status: append-only

---

## Journal Entry Template

```markdown
### YYYY-MM-DD — T{NN} — Short Title

- Scope: {files / directories / task IDs}
- Why this work happened: {reason or trigger}
- Decisions applied: {Decision Log / ADR refs or "none"}
- Evidence collected: {tests / evals / review reports / manual checks}
- Follow-ups: {next task, open risk, or "none"}
- Notes for next agent: {only the context worth carrying forward}
```

---

## Entries

### 2026-05-20 — Phase 25 Implementation — Backdated Writes and Duplicate Rewrites

- Scope: `app/services/gdocs_client.py`, `app/assistant/{facade,tools,prompts}.py`, `app/telegram/handlers.py`, Phase 25 unit tests and docs.
- Why this work happened: a user asked the bot to add a dream for `19.05`; the bot claimed success, but the Google Doc did not show the entry in the expected date position. The user also requested repeated writes even when the dream already exists in the archive.
- Decisions applied: none.
- Evidence collected: targeted Phase 25 suite -> `195 passed, 1 warning`; full unit suite -> `470 passed, 1 warning`; ruff check and format-check clean for touched files.
- Follow-ups: live-smoke a backdated write against the deployed Google Doc after rollout.
- Notes for next agent: Google Doc writes now insert before the first later dated heading/paragraph; duplicate `content_hash` still deduplicates the archive row but reattempts the Google Doc write for the existing dream.

### 2026-05-20 — Phase 24 Implementation — Test 10 Titles and Dream-Set Patterns

- Scope: `app/assistant/{facade,tools,chat,session,prompts}.py`, Phase 24 unit tests and docs.
- Why this work happened: Test 10 reported poor auto-generated dream titles and a frustrating pattern-analysis flow where the bot asked whether to fetch full texts instead of doing the work.
- Decisions applied: none.
- Evidence collected: targeted Phase 24 suite -> `158 passed, 1 warning`; full unit suite -> `463 passed, 1 warning`; ruff check clean for touched files; review archived in `docs/archive/PHASE24_REVIEW.md`.
- Follow-ups: consider a persisted recent-result-set table if cross-restart follow-up analysis becomes important; consider historical title backfill for already-created poor titles.
- Notes for next agent: missing-title Telegram dreams now use a narrow LLM title generator; `create_dream` ignores model-supplied titles unless the current user message has an explicit title marker. Recent search result IDs are cached per chat for 120 minutes and used by direct dream-set pattern analysis.

### 2026-05-15 — Phase 23 Implementation — Test 9 Full Text, English Entries, Numeric Feedback

- Scope: `app/assistant/{tools,prompts}.py`, `app/telegram/handlers.py`, `app/shared/config.py`, `app/services/segmentation.py`, `app/retrieval/query.py`, Phase 23 unit tests and docs.
- Why this work happened: Test 9 reported truncated full-dream responses, newly added English Google Doc entries needing verification, and the 1–5 Telegram rating UX interfering with numbered choices.
- Decisions applied: none.
- Evidence collected: targeted Phase 23 suite -> `170 passed, 1 warning`; full unit suite -> `452 passed, 1 warning`; ruff check clean for touched files; review archived in `docs/archive/PHASE23_REVIEW.md`.
- Follow-ups: run a live smoke against the user's English Google Doc entries after deployment.
- Notes for next agent: numeric feedback is disabled by default via `TELEGRAM_NUMERIC_FEEDBACK_ENABLED=false`; legacy capture still exists behind the flag. `get_dream` now emits full `raw_text`, so future full-text UX issues are likely model-compliance or Telegram delivery issues rather than tool truncation.

### 2026-05-14 — Phase 22 Follow-up — Multi-Doc Sync UX

- Scope: `app/services/auto_sync.py`, `app/api/dreams.py`, `app/workers/ingest.py`, `app/services/gdocs_client.py`, `app/assistant/{facade,prompts,tools}.py`, sync tests and docs.
- Why this work happened: user feedback on 2026-05-10 showed sync still felt opaque and frustrating when multiple Google Docs were involved; manual restart could report a document finished with 0 entries while the user could not tell whether the correct file was actually processed.
- Decisions applied: D-018.
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_auto_sync.py tests/unit/test_ingest_notify.py tests/unit/test_assistant_chat.py tests/unit/test_assistant_facade.py tests/integration/test_workers.py -q --tb=short` -> 152 passed, 1 warning; ruff check/format clean for touched files; services restarted and active.
- Follow-ups: run a live smoke against a non-primary connected Google Doc after the next manual source edit.
- Notes for next agent: `GDocsClient.fetch_document(document_id)` now accepts an optional document ID; `ingest_document` must pass the target `doc_id`. Normal user sync copy must not expose `job_id` unless the user asks for technical detail.

### 2026-05-09 — Phase 22 Planning — Test 7/8 Sync, Notes, Titles, Interpretation

- Scope: `docs/tasks_phase22.md`, `docs/CODEX_PROMPT.md`, `docs/PHASE_PLAN.md`, `docs/DECISION_LOG.md`, `docs/EVIDENCE_INDEX.md`
- Why this work happened: user Test 7/8 reported broken notes to the latest dream, opaque/stuck Google Docs sync, missing fish search for a manually added dream, poor title extraction/generation, and a new request for approved LLM dream interpretation.
- Decisions applied: D-018, D-019.
- Evidence collected: live audit on 2026-05-09 confirmed all services active, Redis auto-sync state `failed`, last successful sync `2026-04-26T10:16:43.458320+00:00`, journal logs repeating `auto_sync.loop_iteration_failed`, live Google Doc parse failure `DreamEntryValidationError: Dream entry candidates must not duplicate content_hash values within one document`, duplicate candidate `25.04.26 - подвальчик в Тбилиси`, Google Doc candidate `5.11.24 запретная рыба` absent from DB, and recent title regressions such as `о запиши название пирог`.
- Follow-ups: start `docs/tasks_phase22.md` with WS-22.1; do not attempt fish-search or latest-dream-note validation until sync can ingest the current Google Doc.
- Notes for next agent: the main user-visible failures are downstream of sync freshness; fix duplicate fail-soft ingestion first, then prove sync state is `synced` and only then validate search/notes against current Google Doc content.

### 2026-05-09 — Phase 22 Implementation — Test 7/8 Closure

- Scope: `app/retrieval/ingestion.py`, `app/assistant/{facade,prompts,session,tools}.py`, `app/services/gdocs_client.py`, `app/telegram/handlers.py`, Phase 22 unit tests, user/runbook/retrieval docs.
- Why this work happened: Test 7/8 runtime failures required sync freshness recovery, honest sync UX, exact fish recall from manually added Google Doc material, note placement at the end of dreams, robust title intake, and an approved LLM interpretation flow.
- Decisions applied: D-018, D-019.
- Evidence collected: targeted WS suites passed; live auto-sync completed with `last_sync_status='synced'`; DB contains `5.11.24 запретная рыба`; `search_dreams` returns that entry first for `сон с рыбой`; Phase 22 deep review archived in `docs/archive/PHASE22_REVIEW.md`.
- Follow-ups: provider-dependent LLM title generation was not added; deterministic title cleanup is active. Interpretation persistence remains out of scope.
- Notes for next agent: no migration was required. Restart `dream-motif-telegram.service` and `dream-motif-auto-sync.service` after deployment so in-memory pending-state and prompt/tool changes are live.

### 2026-06-02 — WS-21.5 — Regression Gate and Deep Review

- Scope: `docs/RUNBOOK_TELEGRAM_BOT.md`, `docs/USER_GUIDE_RU.md`, `docs/archive/PHASE21_REVIEW.md`, `app/assistant/tools.py`, `tests/unit/test_assistant_chat.py`, `docs/tasks_phase21.md`, `docs/CODEX_PROMPT.md`
- Why this work happened: Phase 21 needed the Test 6 manual smoke checklist, user-facing behavior docs, final combined regression gate, and mandatory deep review before close.
- Decisions applied: none.
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_assistant_facade.py tests/unit/test_rag_query.py tests/unit/test_retrieval_eval.py tests/unit/test_telegram_bot.py tests/unit/test_telegram_voice.py tests/unit/test_transcription_worker.py -q --tb=short` -> `174 passed, 1 warning`; `ruff check` and matching `ruff format --check` passed for touched Phase 21 code/tests.
- Follow-ups: run the documented Test 6 Telegram smoke checklist against deployed credentials; concrete `TELEGRAM_REACTION_FEEDBACK_MAPPING` remains pending user-provided emoji meanings.
- Notes for next agent: CODE-18 was found and fixed in-review; concrete image exact recall now survives semantic retrieval failure when exact evidence exists.

### 2026-06-02 — WS-21.4 — Full Dream by Title and Date

- Scope: `app/assistant/tools.py`, `app/assistant/prompts.py`, `app/assistant/facade.py`, `tests/unit/test_assistant_chat.py`, `tests/unit/test_assistant_facade.py`, `docs/tasks_phase21.md`, `docs/CODEX_PROMPT.md`
- Why this work happened: Test 6 showed the assistant could list a known dream by title/date but claim it could not retrieve the full text without a UUID.
- Decisions applied: none.
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_assistant_facade.py -q --tb=short` -> `120 passed, 1 warning`; `ruff check` and matching `ruff format --check` passed for touched WS-21.4 files.
- Follow-ups: WS-21.5 should document the Test 6 smoke checklist, run the combined gate, archive the deep review, and close Phase 21.
- Notes for next agent: `list_recent_dreams` now includes `dream_id`; `search_dreams_by_title` accepts date disambiguation and `04.04.26` resolves to `2026-04-04` before calling `get_dream`.

### 2026-06-02 — WS-21.3 — Fish/Image Exact Recall

- Scope: `app/assistant/tools.py`, `app/assistant/prompts.py`, `app/retrieval/query.py`, `tests/unit/test_assistant_chat.py`, `tests/unit/test_rag_query.py`, `tests/unit/test_retrieval_eval.py`, `docs/retrieval_eval.md`, `docs/tasks_phase21.md`, `docs/CODEX_PROMPT.md`
- Why this work happened: Test 6 showed image search could miss a dream containing the exact word `рыба`.
- Decisions applied: none.
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_rag_query.py tests/unit/test_retrieval_eval.py -q --tb=short` -> `92 passed, 1 warning`; `ruff check` and matching `ruff format --check` passed for touched WS-21.3 files.
- Follow-ups: WS-21.4 should make list/title/date flows resolve `dream_id` and retrieve full dream text without asking the user for UUIDs.
- Notes for next agent: `search_dreams` now detects concrete image/object phrasings and calls `search_dreams_exact` with normalized object terms, e.g. `сон с рыбой` -> `рыба`, then merges exact and semantic results by `dream_id`.

### 2026-06-02 — WS-21.2 — Honest Google Doc Save Confirmation

- Scope: `app/telegram/handlers.py`, `app/assistant/tools.py`, `app/assistant/prompts.py`, `tests/unit/test_assistant_chat.py`, `tests/unit/test_telegram_bot.py`, `tests/unit/test_telegram_voice.py`, `tests/unit/test_transcription_worker.py`, `docs/tasks_phase21.md`, `docs/CODEX_PROMPT.md`
- Why this work happened: Test 6 showed the bot could say a dream was added to Google Doc even when it was not visible there, and the success message could expose fallback document IDs.
- Decisions applied: none.
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_telegram_bot.py tests/unit/test_telegram_voice.py tests/unit/test_transcription_worker.py tests/unit/test_assistant_facade.py -q --tb=short` -> `153 passed, 1 warning`; `ruff check` and matching `ruff format --check` passed for touched WS-21.2 files.
- Follow-ups: WS-21.3 should fix concrete image/object search recall, starting with the reported `рыба` regression.
- Notes for next agent: Telegram create confirmations now hide doc labels and only say `Сон сохранён и добавлен в документ` when `written_to_google_doc=True`; failed writes keep the archive-only retry message, and assistant tool create/retry success results no longer include `written_to_doc_name`.

### 2026-06-02 — WS-21.1 — Short Natural Dream Recording

- Scope: `app/assistant/tools.py`, `app/telegram/handlers.py`, `app/workers/transcribe.py`, `tests/unit/test_assistant_chat.py`, `tests/unit/test_telegram_bot.py`, `tests/unit/test_transcription_worker.py`, `docs/tasks_phase21.md`, `docs/CODEX_PROMPT.md`
- Why this work happened: Test 6 showed short dreams beginning with natural phrases such as `сегодня мне приснилось` could be routed into clarification and then reported as saved without reliable persistence.
- Decisions applied: none.
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_telegram_bot.py tests/unit/test_transcription_worker.py -q --tb=short` -> `94 passed, 1 warning`; `ruff check` and matching `ruff format --check` passed for touched WS-21.1 files.
- Follow-ups: WS-21.2 must make Google Doc write confirmation text truthful and remove fallback document IDs from user-facing success messages.
- Notes for next agent: natural text and voice transcripts now bypass the assistant loop and call `create_dream` directly when at least one content word follows the opening; pending dream confirmation remains only for already stored drafts.

### 2026-06-02 — PHASE21-PLAN — Test 6 Recording/Search Regressions

- Scope: `docs/tasks_phase21.md`, `docs/CODEX_PROMPT.md`
- Why this work happened: Test 6 reported live regressions: short dreams are not saved deterministically, Google Doc write success is overstated or exposes fallback IDs, fish/image search misses exact evidence, and full dream retrieval by title/date still fails in conversation.
- Decisions applied: none.
- Evidence collected: code inspection of `app/assistant/tools.py`, `app/assistant/prompts.py`, `app/assistant/facade.py`, `app/telegram/handlers.py`, `app/workers/transcribe.py`; no tests run because this is planning only.
- Follow-ups: start WS-21.1 with short natural dream recording for text and voice.
- Notes for next agent: some capabilities exist (`search_dreams_by_title`, `search_dreams_exact`, write status), but Test 6 requires stricter deterministic routing and regression tests.

### 2026-05-02 — POST-PHASE20-CLEANUP — Carry-Forward Tech Debt Closure

- Scope: `app/telegram/handlers.py`, `app/shared/config.py`, `tests/unit/test_telegram_bot.py`, `tests/unit/test_config.py`, `docs/CODEX_PROMPT.md`
- Why this work happened: User requested closing remaining planned work and available technical debt after Phase 20 completion.
- Decisions applied: D-014 already records WS-11.4 deferral; D-017 keeps concrete emoji mapping deferred until user supplies meanings.
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_telegram_bot.py tests/unit/test_config.py -q --tb=short` -> `32 passed`; `.venv/bin/ruff check app/telegram/handlers.py app/shared/config.py tests/unit/test_telegram_bot.py tests/unit/test_config.py` -> clean; matching `ruff format --check` -> clean.
- Follow-ups: concrete `TELEGRAM_REACTION_FEEDBACK_MAPPING` remains product-input blocked; no code blocker remains for it.
- Notes for next agent: CODE-4, CODE-5, and CODE-6 are closed in code; CODE-7, CODE-9, and CODE-10 were already resolved and are marked closed in `docs/CODEX_PROMPT.md`.

### 2026-05-02 — PHASE20-REVIEW — Deep Review and Close

- Scope: `app/services/feedback_service.py`, `app/services/reaction_feedback.py`, `tests/unit/test_feedback_context.py`, `tests/unit/test_reaction_model.py`, `docs/archive/PHASE20_REVIEW.md`, `docs/tasks_phase20.md`, `docs/CODEX_PROMPT.md`
- Why this work happened: Phase 20 reached the mandatory phase-boundary deep review gate.
- Decisions applied: D-017 — concrete emoji mapping remains deferred until user supplies meanings.
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_gdocs_client.py tests/unit/test_assistant_facade.py tests/unit/test_reaction_model.py tests/unit/test_feedback_context.py tests/unit/test_telegram_bot.py -q --tb=short` -> `85 passed`; `ruff check` and matching `ruff format --check` passed for the touched Phase 20 slice.
- Follow-ups: pick next phase or configure `TELEGRAM_REACTION_FEEDBACK_MAPPING` after the user provides emoji meanings.
- Notes for next agent: CODE-17 was found and fixed in-review; feedback context now selects recent rows first and returns prompt context oldest-first.

### 2026-05-02 — WS-20.3 — Feedback Prompt UX Decision

- Scope: `app/telegram/handlers.py`, `tests/unit/test_telegram_bot.py`, `docs/FEEDBACK_LOOP.md`, `docs/USER_GUIDE_RU.md`, `docs/tasks_phase20.md`, `docs/CODEX_PROMPT.md`, `docs/DECISION_LOG.md`
- Why this work happened: Phase 20 needed a concrete UX decision for the recurring Telegram feedback prompt after the reaction semantics scaffold landed.
- Decisions applied: D-017 — numeric feedback prompt remains active and shortened; concrete emoji meaning mapping is deferred.
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_telegram_bot.py -q --tb=short` -> `15 passed`; `.venv/bin/ruff check app/telegram/handlers.py tests/unit/test_telegram_bot.py` -> clean; matching `ruff format --check` -> clean.
- Follow-ups: run Phase 20 deep review; remind the user that emoji reactions remain raw until `TELEGRAM_REACTION_FEEDBACK_MAPPING` is configured.
- Notes for next agent: visible prompt is now `Ответьте 1–5, можно с коротким комментарием.`; handler parsing behavior did not change.

### 2026-05-02 — WS-20.2 — Emoji Reaction Feedback Scaffold

- Scope: `app/shared/config.py`, `app/services/reaction_feedback.py`, `app/services/feedback_service.py`, `app/assistant/prompts.py`, `tests/unit/test_reaction_model.py`, `tests/unit/test_feedback_context.py`, `docs/FEEDBACK_LOOP.md`, `docs/tasks_phase20.md`, `docs/CODEX_PROMPT.md`
- Why this work happened: Phase 20 needs Telegram reactions to become qualitative feedback once the user supplies emoji meanings, but the code path can be prepared before final product mapping exists.
- Decisions applied: none.
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_reaction_model.py tests/unit/test_feedback_context.py tests/unit/test_telegram_bot.py -q --tb=short` -> `28 passed`; `.venv/bin/ruff check app/shared/config.py app/services/reaction_feedback.py app/services/feedback_service.py app/assistant/prompts.py app/telegram/bot.py tests/unit/test_reaction_model.py tests/unit/test_feedback_context.py tests/unit/test_telegram_bot.py` -> clean; matching `ruff format --check` -> clean.
- Follow-ups: configure `TELEGRAM_REACTION_FEEDBACK_MAPPING` after the user provides concrete emoji meanings; then rerun the same targeted slice and `ruff format --check`.
- Notes for next agent: the default mapping is empty, so unknown emoji remain raw `message_reactions`; removed reactions are excluded by `removed_at IS NULL`.

### 2026-05-02 — WS-20.1 — Target-Aware Dream Notes in Google Docs

- Scope: `app/services/gdocs_client.py`, `app/assistant/facade.py`, `tests/unit/test_gdocs_client.py`, `tests/unit/test_assistant_facade.py`, `docs/tasks_phase20.md`, `docs/CODEX_PROMPT.md`
- Why this work happened: Phase 20 needed `add_dream_note` to place notes under the target dream heading in Google Docs when possible instead of always appending to the document end.
- Decisions applied: none.
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_gdocs_client.py tests/unit/test_assistant_facade.py -q --tb=short` -> `54 passed`; `.venv/bin/ruff check app/services/gdocs_client.py app/assistant/facade.py tests/unit/test_gdocs_client.py tests/unit/test_assistant_facade.py` -> clean; matching `ruff format --check` -> clean.
- Follow-ups: WS-20.2 is blocked until the user provides emoji reaction meanings.
- Notes for next agent: note rows are committed before Google Docs writes; `insert_text_under_heading()` returns `False` for a missing Heading 1 so the facade can append and tell the user that fallback happened.

### 2026-05-02 — WS-19.3 — Full Dream Retrieval by Title Flow

- Scope: `app/assistant/tools.py`, `tests/unit/test_assistant_chat.py`, `docs/tasks_phase19.md`, `docs/CODEX_PROMPT.md`
- Why this work happened: Phase 19 needed a complete user flow where a title-like request can produce the full dream, not only a UUID-bearing intermediate result.
- Decisions applied: D-007 (bounded internal assistant-tool facade).
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_assistant_facade.py -q --tb=short` -> `106 passed`; `.venv/bin/ruff check app/assistant/tools.py app/assistant/prompts.py app/assistant/facade.py tests/unit/test_assistant_chat.py tests/unit/test_assistant_facade.py` -> clean; `.venv/bin/ruff format --check app/assistant/tools.py app/assistant/prompts.py app/assistant/facade.py tests/unit/test_assistant_chat.py tests/unit/test_assistant_facade.py` -> clean; light review PASS.
- Follow-ups: Phase 19 deep review is archived; Phase 20 may begin.
- Notes for next agent: `search_dreams_by_title` now calls `get_dream` for a single title match, does not call `get_dream` for ambiguous matches, and clearly prefixes content fallback with "No title match found".

### 2026-05-02 — WS-19.2 — Assistant Tool `search_dreams_by_title`

- Scope: `app/assistant/tools.py`, `app/assistant/prompts.py`, `tests/unit/test_assistant_chat.py`, `docs/tasks_phase19.md`, `docs/CODEX_PROMPT.md`
- Why this work happened: Phase 19 needs the assistant to map user-provided dream titles to UUIDs before calling `get_dream`; the facade method from WS-19.1 was not yet exposed as a tool.
- Decisions applied: D-007 (bounded internal assistant-tool facade).
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_assistant_facade.py -q --tb=short` -> `104 passed`; `.venv/bin/ruff check app/assistant/tools.py app/assistant/prompts.py app/assistant/facade.py tests/unit/test_assistant_chat.py tests/unit/test_assistant_facade.py` -> clean; `.venv/bin/ruff format --check app/assistant/tools.py app/assistant/prompts.py app/assistant/facade.py tests/unit/test_assistant_chat.py tests/unit/test_assistant_facade.py` -> clean; light review PASS.
- Follow-ups: WS-19.3 should make the full title flow retrieve the full dream on a single clear match and ask for clarification when title matches are ambiguous.
- Notes for next agent: `search_dreams_by_title` tool output includes `dream_id`, date, title, and preview; ambiguous matches include a no-guessing instruction in the tool result and system prompt.

### 2026-05-02 — WS-19.1 — Title Search Facade Method

- Scope: `app/assistant/facade.py`, `tests/unit/test_assistant_facade.py`, `docs/tasks_phase19.md`, `docs/CODEX_PROMPT.md`
- Why this work happened: Phase 19 requires direct lookup of a specific dream by title because content search does not query `dream_entries.title` and `get_dream` requires a UUID.
- Decisions applied: D-007 (bounded internal assistant-tool facade); no RAG retrieval semantics changed.
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_assistant_facade.py -q --tb=short` -> `40 passed`; `.venv/bin/ruff check app/assistant/facade.py tests/unit/test_assistant_facade.py` -> clean; `.venv/bin/ruff format --check app/assistant/facade.py tests/unit/test_assistant_facade.py` -> clean; light review PASS.
- Follow-ups: WS-19.2 should expose `search_dreams_by_title` as an assistant tool and prompt route title/name lookup to title search first.
- Notes for next agent: title search now returns `DreamTitleSearchResult` with `dream_id`, date, title, and preview; matching uses `dream_entries.title`, case-insensitive partial lookup, and punctuation-insensitive normalization for titles such as `Я и дети. Тайное общество`.

### 2026-05-02 — WS-18.6 — Retrieval Eval Run and Phase Gate

- Scope: `docs/retrieval_eval.md`, `tests/unit/test_retrieval_eval.py`, `scripts/eval_phase18_real.py`, `tests/unit/test_eval_phase18_real.py`, `docs/tasks_phase18.md`, `docs/CODEX_PROMPT.md`, `docs/IMPLEMENTATION_JOURNAL.md`
- Why this work happened: Phase 18 requires a recorded retrieval eval before closing the search quality and hallucination suppression phase.
- Decisions applied: none.
- Evidence collected: `TEST_DATABASE_URL=postgresql+asyncpg://postgres@localhost:5433/dream_motif_eval OPENAI_API_KEY=test-key EVAL_DATE=2026-05-02 .venv/bin/python scripts/eval.py --task-id WS-18.6` -> synthetic metrics hit@3=1.00, MRR=1.00, no-answer accuracy=1.00; `.venv/bin/python scripts/eval_phase18_real.py --limit 5` -> 6/6 Phase 18 prayer/religion queries returned archive-backed evidence in read-only FTS-only mode; `.venv/bin/python scripts/eval_phase18_real.py --mode live --limit 5` -> attempted live hybrid path, blocked by provider auth with Anthropic 401 and OpenAI embedding 401 Unauthorized; `.venv/bin/python -m pytest tests/unit/test_eval_phase18_real.py tests/unit/test_eval_script.py tests/unit/test_retrieval_eval.py tests/unit/test_rag_query_expansion.py tests/unit/test_rag_query.py tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py -q --tb=short` -> 124 passed; `.venv/bin/python -m ruff check scripts/eval_phase18_real.py scripts/eval.py app/retrieval/query.py app/assistant/facade.py app/assistant/tools.py app/assistant/prompts.py tests/unit/test_eval_phase18_real.py tests/unit/test_eval_script.py tests/unit/test_rag_query.py tests/unit/test_rag_query_expansion.py tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py tests/unit/test_retrieval_eval.py` -> clean; light review PASS.
- Follow-ups: before starting Phase 19 WS-19.1, rerun `scripts/eval_phase18_real.py --mode live --limit 5` on a machine with valid `ANTHROPIC_API_KEY` and `OPENAI_API_KEY`. Phase 19 title search work starts only after that live gate is recorded.
- Notes for next agent: `scripts/eval.py` now records the run date dynamically; it still resets the target schema, so only run it against an explicit disposable test database. `scripts/eval_phase18_real.py` is the safe read-only checker for the existing archive.

### 2026-05-02 — WS-18.5 — Grounded Search Response Contract

- Scope: `app/assistant/tools.py`, `app/assistant/prompts.py`, `tests/unit/test_assistant_chat.py`, `docs/tasks_phase18.md`, `docs/CODEX_PROMPT.md`
- Why this work happened: Phase 18 requires search tool output to reduce the assistant's opportunity to invent fragments by exposing a stricter citation-like evidence contract.
- Decisions applied: none.
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_rag_query_expansion.py tests/unit/test_rag_query.py tests/unit/test_retrieval_eval.py tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py -q --tb=short` -> 115 passed; `.venv/bin/ruff check app/retrieval/query.py app/assistant/facade.py app/assistant/tools.py app/assistant/prompts.py tests/unit/test_rag_query.py tests/unit/test_rag_query_expansion.py tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py` -> clean; `.venv/bin/ruff format --check app/retrieval/query.py app/assistant/facade.py app/assistant/tools.py app/assistant/prompts.py tests/unit/test_rag_query.py tests/unit/test_rag_query_expansion.py tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py` -> clean; light review PASS.
- Follow-ups: WS-18.6 retrieval eval run and phase gate is next.
- Notes for next agent: search result payloads now expose `result_id`, `date`, `title`, `strength`, and `evidence_text`; final answers should cite only `evidence_text`.

### 2026-05-02 — WS-18.4 — Evidence Verification and Weak-Result Suppression

- Scope: `app/assistant/facade.py`, `app/assistant/tools.py`, `tests/unit/test_assistant_facade.py`, `tests/unit/test_assistant_chat.py`, `docs/tasks_phase18.md`, `docs/CODEX_PROMPT.md`
- Why this work happened: Phase 18 requires the assistant not to present weak vector neighbors when there is no query-related evidence.
- Decisions applied: none.
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_rag_query_expansion.py tests/unit/test_rag_query.py tests/unit/test_retrieval_eval.py tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py -q --tb=short` -> 114 passed; `.venv/bin/ruff check app/retrieval/query.py app/assistant/facade.py app/assistant/tools.py tests/unit/test_rag_query.py tests/unit/test_rag_query_expansion.py tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py` -> clean; `.venv/bin/ruff format --check app/retrieval/query.py app/assistant/facade.py app/assistant/tools.py tests/unit/test_rag_query.py tests/unit/test_rag_query_expansion.py tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py` -> clean; light review PASS.
- Follow-ups: WS-18.5 grounded search response contract is next.
- Notes for next agent: `search_dreams` now filters weak no-quote/no-fragment results before tool output; tool output labels remaining results with `strength=strong|moderate|weak`.

### 2026-05-02 — WS-18.3 — Multi-Query Retrieval in Code

- Scope: `app/retrieval/query.py`, `tests/unit/test_rag_query.py`, `tests/unit/test_rag_query_expansion.py`, `docs/tasks_phase18.md`, `docs/CODEX_PROMPT.md`
- Why this work happened: Phase 18 requires broad motif/theme search to issue deterministic retrieval probes in code instead of relying on prompt-owned repeated `search_dreams` calls.
- Decisions applied: none.
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_rag_query_expansion.py tests/unit/test_rag_query.py tests/unit/test_retrieval_eval.py tests/unit/test_assistant_facade.py -q --tb=short` -> 54 passed; `.venv/bin/ruff check app/retrieval/query.py tests/unit/test_rag_query.py tests/unit/test_rag_query_expansion.py tests/unit/test_assistant_facade.py` -> clean; `.venv/bin/ruff format --check app/retrieval/query.py tests/unit/test_rag_query.py tests/unit/test_rag_query_expansion.py tests/unit/test_assistant_facade.py` -> clean; light review PASS.
- Follow-ups: WS-18.4 evidence verification and weak-result suppression is next.
- Notes for next agent: broad religious queries now fan out into church/place-of-worship, prayer/hymn/Christmas, and icon/divine-name probes; merged rows are deduped by `dream_id` and preserve all distinct evidence chunks.

### 2026-05-01 — WS-18.2 — Deterministic Query Expansion Profiles

- Scope: `app/retrieval/query.py`, `tests/unit/test_rag_query_expansion.py`, `docs/tasks_phase18.md`, `docs/CODEX_PROMPT.md`
- Why this work happened: Phase 18 requires prayer/religion recall to be deterministic rather than relying only on prompt-owned multi-search or live LLM query expansion.
- Decisions applied: none.
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_rag_query_expansion.py tests/unit/test_rag_query.py tests/unit/test_retrieval_eval.py -q --tb=short` -> 13 passed; `.venv/bin/ruff check app/retrieval/query.py tests/unit/test_rag_query_expansion.py tests/unit/test_rag_query.py tests/unit/test_retrieval_eval.py` -> clean; `.venv/bin/ruff format --check app/retrieval/query.py tests/unit/test_rag_query_expansion.py tests/unit/test_rag_query.py tests/unit/test_retrieval_eval.py` -> clean.
- Follow-ups: WS-18.3 multi-query retrieval in code is next.
- Notes for next agent: `_expand_query_terms()` now applies deterministic religious/prayer profile terms before embedding and FTS search, then merges optional LLM expansion when it succeeds.

### 2026-05-01 — WS-18.1 — User Search Regression Dataset

- Scope: `docs/retrieval_eval.md`, `tests/unit/test_retrieval_eval.py`, `docs/tasks_phase18.md`, `docs/CODEX_PROMPT.md`
- Why this work happened: Phase 18 starts by freezing user-reported search failures around `молитва`, religious scenes, Christmas hymnody, church/icon/prayer evidence, and false-positive suppression.
- Decisions applied: none.
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_retrieval_eval.py -q --tb=short` -> 3 passed.
- Follow-ups: WS-18.2 deterministic query expansion profiles is next.
- Notes for next agent: the Phase 18 dataset is a separate section in `docs/retrieval_eval.md`; it is not yet part of `scripts/eval.py` metrics, and WS-18.6 should record a Phase 18 eval row after retrieval changes land.

### 2026-05-01 — FIX-13..FIX-17 — Phase 17 Audit Follow-ups

- Scope: `app/assistant/facade.py`, `app/assistant/voice_media.py`, `app/assistant/session.py`, `app/shared/config.py`, `docs/RUNBOOK_TELEGRAM_BOT.md`, `docs/ARCHITECTURE.md`, `tests/unit/test_assistant_facade.py`, `tests/unit/test_assistant_session.py`, `docs/CODEX_PROMPT.md`, `docs/audit/*`
- Why this work happened: Cycle 13 deep audit found stale failed write-status rows after retry, missing Phase 17 DB spans, unbounded pending dream draft state, undocumented `APP_TIMEZONE`, and stale architecture storage inventory.
- Decisions applied: D-015 — dream recording reliability requires deterministic write state and honest retry behavior.
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_assistant_facade.py tests/unit/test_assistant_session.py tests/unit/test_telegram_voice.py tests/unit/test_transcription_worker.py -q --tb=short` -> 68 passed; `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_assistant_facade.py tests/unit/test_feedback_context.py tests/unit/test_gdocs_client.py tests/unit/test_assistant_session.py tests/unit/test_telegram_bot.py tests/unit/test_telegram_voice.py tests/unit/test_transcription_worker.py tests/integration/test_migrations.py -q --tb=short` -> 169 passed; `.venv/bin/ruff check app/ tests/ alembic/versions/015_add_dream_write_statuses.py alembic/versions/016_add_voice_transcript_text.py` -> clean; `.venv/bin/ruff format --check app/ tests/ alembic/versions/015_add_dream_write_statuses.py alembic/versions/016_add_voice_transcript_text.py` -> clean.
- Follow-ups: none for Cycle 13 findings; live Telegram smoke checklist still remains a deployment/manual verification step.
- Notes for next agent: retry now passes the selected failed `DreamWriteStatus` row into the write path and updates that row in place; `APP_TIMEZONE` is a typed settings field with default `Asia/Tbilisi`.

### 2026-05-01 — WS-17.1 — Deterministic Dream Intake Classifier

- Scope: `app/assistant/tools.py`, `tests/unit/test_assistant_chat.py`, `tests/unit/test_transcription_worker.py`, `docs/CODEX_PROMPT.md`, `docs/tasks_phase17.md`
- Why this work happened: Phase 17 D1/P0 — natural Russian dream narration such as "сегодня мне приснилось" was being rejected unless the user used exact save-command wording.
- Decisions applied: D-015 — dream recording reliability moves from prompt-only behavior to deterministic intake and state.
- Evidence collected: targeted tests passed: `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_transcription_worker.py -q --tb=short` -> 60 passed; `ruff check app/ tests/` -> clean; `ruff format --check app/ tests/` -> clean.
- Follow-ups: WS-17.2 pending dream draft state is next; full suite should be re-run on the working/live test instance because local non-live run failed on missing PostgreSQL at `127.0.0.1:5433` and `tests/unit/test_ci.py::test_ruff_check_passes` expects `ruff` on PATH.
- Notes for next agent: classifier accepts natural openings only when at least two narrative words follow the opening; short mentions like "мне приснилось?" are still rejected.

### 2026-05-01 — WS-17.2 — Pending Dream Draft State for Confirmation

- Scope: `app/assistant/session.py`, `app/telegram/handlers.py`, `app/workers/transcribe.py`, `tests/unit/test_assistant_session.py`, `tests/unit/test_telegram_bot.py`, `tests/unit/test_transcription_worker.py`, `docs/CODEX_PROMPT.md`, `docs/tasks_phase17.md`
- Why this work happened: Phase 17 D2/P0 — after "записать?" the bot had no typed pending candidate, so a later "да" had to infer from chat history and could save the wrong text or nothing at all.
- Decisions applied: D-015 — dream recording reliability moves from prompt-only behavior to deterministic intake and state; ADR-006 consulted, but this WS uses the smaller TTL-bounded in-memory implementation first rather than introducing schema work mid-phase.
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_assistant_session.py tests/unit/test_telegram_bot.py tests/unit/test_transcription_worker.py -q --tb=short` -> 86 passed; `.venv/bin/ruff check app/ tests/` -> clean; `.venv/bin/ruff format --check app/ tests/` -> clean.
- Follow-ups: WS-17.3 deterministic relative date and auto-title resolution is next; Phase 17 still needs honest Google Doc write status and reply-to-voice explicit-save handling before the phase can close.
- Notes for next agent: pending drafts are keyed by `chat_id`, include `source_kind` (`text` / `voice_transcript`), expire after 30 minutes, and are consumed only on explicit confirmation/decline rather than by rereading LLM history.

### 2026-05-01 — WS-17.3 — Deterministic Relative Date and Auto-Title Resolution

- Scope: `app/assistant/facade.py`, `app/assistant/tools.py`, `app/assistant/chat.py`, `tests/unit/test_assistant_facade.py`, `tests/unit/test_assistant_chat.py`, `tests/unit/test_feedback_context.py`, `tests/unit/test_gdocs_client.py`, `docs/CODEX_PROMPT.md`, `docs/tasks_phase17.md`
- Why this work happened: Phase 17 D5/P1 — dream date and fallback title handling was mostly prompt-driven; missing dates stayed null and missing titles became generic `без названия`.
- Decisions applied: D-015 — dream recording reliability moves from prompt-only behavior to deterministic intake and state.
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_assistant_facade.py tests/unit/test_feedback_context.py tests/unit/test_gdocs_client.py tests/unit/test_assistant_session.py tests/unit/test_telegram_bot.py tests/unit/test_transcription_worker.py -q --tb=short` -> 139 passed; `.venv/bin/ruff check app/ tests/` -> clean; `.venv/bin/ruff format --check app/ tests/` -> clean.
- Follow-ups: WS-17.4 write outbox and honest success messages is next; retry still needs to target a failed write record rather than a loosely inferred latest dream.
- Notes for next agent: application date is resolved through `APP_TIMEZONE` with default `Asia/Tbilisi`; relative marker precedence matters because `позавчера` contains `вчера`.

### 2026-05-01 — WS-17.4 — Write Outbox and Honest Success Messages

- Scope: `app/models/write_status.py`, `app/models/__init__.py`, `alembic/versions/015_add_dream_write_statuses.py`, `app/assistant/facade.py`, `app/assistant/tools.py`, `tests/unit/test_assistant_facade.py`, `tests/unit/test_assistant_chat.py`, `tests/integration/test_migrations.py`, `docs/CODEX_PROMPT.md`, `docs/tasks_phase17.md`
- Why this work happened: Phase 17 D3/D4/P0 — Google Doc write attempts were not tracked, retry without `dream_id` used the latest dream globally, and failure output was too easy for the final assistant message to misstate as success.
- Decisions applied: D-015 — dream recording reliability moves from prompt-only behavior to deterministic intake and state.
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_assistant_facade.py tests/unit/test_feedback_context.py tests/unit/test_gdocs_client.py tests/unit/test_assistant_session.py tests/unit/test_telegram_bot.py tests/unit/test_transcription_worker.py -q --tb=short` -> 143 passed; `.venv/bin/python -m pytest tests/integration/test_migrations.py -q --tb=short` -> 12 passed; `.venv/bin/ruff check app/ tests/ alembic/versions/015_add_dream_write_statuses.py` -> clean; `.venv/bin/ruff format --check app/ tests/ alembic/versions/015_add_dream_write_statuses.py` -> clean.
- Follow-ups: WS-17.5 reply-to-voice explicit save is next; Phase 17 still needs final regression/user-doc pass after WS-17.5.
- Notes for next agent: retry is scoped by `DreamEntry.source_doc_id == telegram:<chat_id>` when `chat_id` is available; failed write errors are sanitized and truncated before persistence.

### 2026-05-01 — WS-17.5 — Reply-to-Voice "запиши сон"

- Scope: `app/models/voice.py`, `app/assistant/voice_media.py`, `app/telegram/handlers.py`, `app/workers/transcribe.py`, `alembic/versions/016_add_voice_transcript_text.py`, `tests/unit/test_telegram_voice.py`, `tests/unit/test_transcription_worker.py`, `tests/integration/test_migrations.py`, `docs/CODEX_PROMPT.md`, `docs/tasks_phase17.md`
- Why this work happened: Phase 17 D6/P1 — text replies like "запиши сон" to a previous voice message could not resolve the replied-to transcript and therefore could not save the intended dream.
- Decisions applied: D-015 — dream recording reliability moves from prompt-only behavior to deterministic intake and state.
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_assistant_facade.py tests/unit/test_feedback_context.py tests/unit/test_gdocs_client.py tests/unit/test_assistant_session.py tests/unit/test_telegram_bot.py tests/unit/test_telegram_voice.py tests/unit/test_transcription_worker.py tests/integration/test_migrations.py -q --tb=short` -> 167 passed; `.venv/bin/ruff check app/ tests/ alembic/versions/015_add_dream_write_statuses.py alembic/versions/016_add_voice_transcript_text.py` -> clean; `.venv/bin/ruff format --check app/ tests/ alembic/versions/015_add_dream_write_statuses.py alembic/versions/016_add_voice_transcript_text.py` -> clean.
- Follow-ups: WS-17.6 regression suite and manual Telegram checklist is next; after that Phase 17 needs final review/doc gate.
- Notes for next agent: transcript text is stored on `voice_media_events` only for operational reply-to-voice behavior; unavailable or failed transcripts produce refusal text and do not call `create_dream`.

### 2026-05-01 — WS-17.6 — Recording Regression Suite and Manual Test Script

- Scope: `docs/RUNBOOK_TELEGRAM_BOT.md`, `docs/USER_GUIDE_RU.md`, `docs/tasks_phase17.md`, `docs/CODEX_PROMPT.md`, `docs/IMPLEMENTATION_JOURNAL.md`
- Why this work happened: Phase 17 needed a final regression and manual verification gate for the user-reported recording failures before moving to Phase 18 search quality work.
- Decisions applied: D-015 — dream recording reliability moves from prompt-only behavior to deterministic intake and state.
- Evidence collected: `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_assistant_facade.py tests/unit/test_feedback_context.py tests/unit/test_gdocs_client.py tests/unit/test_assistant_session.py tests/unit/test_telegram_bot.py tests/unit/test_telegram_voice.py tests/unit/test_transcription_worker.py tests/integration/test_migrations.py -q --tb=short` -> 167 passed; `.venv/bin/ruff check app/ tests/ alembic/versions/015_add_dream_write_statuses.py alembic/versions/016_add_voice_transcript_text.py` -> clean; `.venv/bin/ruff format --check app/ tests/ alembic/versions/015_add_dream_write_statuses.py alembic/versions/016_add_voice_transcript_text.py` -> clean.
- Follow-ups: Phase 18 starts with WS-18.1 user search regression dataset.
- Notes for next agent: Phase 17 gate is complete locally; run the manual Telegram recording smoke checklist in `docs/RUNBOOK_TELEGRAM_BOT.md` on the deployed bot before treating live behavior as verified.

### 2026-05-01 — DOC-WORKFLOW-HARDENING — Local AI Development Workflow

- Scope: `docs/prompts/ORCHESTRATOR.md`, `docs/CODEX_PROMPT.md`, `docs/DECISION_LOG.md`
- Why this work happened: user requested an explicit, strict AI development workflow covering role ownership, separate prompt construction through a shell variable, mandatory review/light review, documentation updates, and ruff/format checks.
- Decisions applied: D-016 — local orchestrator workflow is mandatory and task completion requires prompt-file dispatch, review gate, docs gate, and quality checks.
- Evidence collected: documentation inspection showed `CODEX_PROMPT.md` had checks but stale task references and `docs/prompts/ORCHESTRATOR.md` was only a placeholder; no tests run because this is a docs-only workflow hardening change.
- Follow-ups: future orchestrator runs should start by reading `docs/prompts/ORCHESTRATOR.md`; implementation prompts must be written to `/tmp/orchestrator_codex_prompt.txt` and passed via `PROMPT=$(cat ...)`.
- Notes for next agent: `docs/IMPLEMENTATION_CONTRACT.md` remains unchanged because it is immutable; workflow hardening lives in the local orchestrator prompt and session handoff.

### 2026-05-01 — DOC-PHASE17-20 — User Feedback Task Graphs

- Scope: `docs/tasks_phase17.md`, `docs/tasks_phase18.md`, `docs/tasks_phase19.md`, `docs/tasks_phase20.md`, `docs/CODEX_PROMPT.md`, `docs/DECISION_LOG.md`
- Why this work happened: Тест 5 (26.04.26) showed that Phase 14-16 fixes improved write/search UX but left critical product gaps: natural dream narration not recorded, confirmation flow lacks pending state, retry can target the wrong dream, search remains prompt-dependent, and direct title lookup is absent.
- Decisions applied: D-015 — dream recording reliability must be implemented as deterministic intake/write state, not prompt-only behavior.
- Evidence collected: code inspection of `app/assistant/tools.py`, `app/assistant/facade.py`, `app/assistant/chat.py`, `app/telegram/handlers.py`, `app/workers/transcribe.py`, `app/retrieval/query.py`, `app/services/gdocs_client.py`; no tests run in this doc-only planning update.
- Follow-ups: start orchestrator at `docs/tasks_phase17.md` WS-17.1; after Phase 17, continue with Phase 18 search quality, Phase 19 title search, Phase 20 feedback/notes polish.
- Notes for next agent: `docs/tasks.md` remains historical; new active work lives in phase-specific task graphs. Do not close Phase 17 with prompt changes only — the main requirement is deterministic state and honest write status.

### 2026-04-21 — tasks.md Phase 6 (T21–T25) — Universal Source Intake Pipeline

- Scope: `app/retrieval/types.py`, `app/retrieval/ingestion.py`, `app/services/gdocs_client.py`, `app/services/segmentation.py`, `app/shared/config.py`, `app/workers/ingest.py`, `app/workers/index.py`, `app/models/dream.py`, `alembic/versions/012_add_parser_profile_fields.py`, 9 new test files
- Why this work happened: live Google Docs verification revealed a single doc "Сны" (heading-based, 360 paragraphs); future intake may involve folders and multiple formats — canonical multi-stage pipeline required before ingestion work continues
- Decisions applied: spec.md §12 canonical pipeline enforced — source connector → normalized document → parser profile → dream entry candidates → validated dream entries → embeddings/indexing; no shortcut from connector to embedding allowed
- Evidence collected: T21–T25 all AC PASS; light review PASS each task; 286 → 305 tests passing; ruff clean; live GDocsClient.fetch_document() verified against doc id `1mq5mwCH_VoFsmdBj4V0MeygjqDjjPxEi-IOO1rHIxHs`
- Follow-ups: run live end-to-end ingestion (sync → segment → embed → index) against the real doc; verify heading_based profile correctly segments "Сны" entries; check Alembic migration 012 applies cleanly
- Notes for next agent: parser profiles are deterministic (no LLM); heading_based profile is the correct choice for "Сны"; operator profile can be set via `OPERATOR_PARSER_PROFILES` env var; idempotency guard uses `external_id + content_hash`

### 2026-04-15 — P8-T02 — Controlled Evaluation of Chat Curation

- Scope: `docs/TELEGRAM_INTERACTION_MODEL.md`
- Why this work happened: Phase 8 required an explicit allow/deny decision on chat-driven archive mutations before the phase could close
- Decisions applied: D-007, D-008; defer decision confirmed
- Evidence collected: facade and tool catalog reviewed — no mutation tools present; preconditions for enabling mutations (two-phase UX, audit trail, rollback UX, failure mode docs) are not yet met
- Follow-ups: enabling curation mutations requires four explicit preconditions documented in TELEGRAM_INTERACTION_MODEL.md §11
- Notes for next agent: Telegram remains read-oriented; `confirm_theme`, `reject_theme`, `rollback_theme`, `approve_category` remain absent from TOOLS catalog and AssistantFacade

### 2026-04-15 — P8-T01 — Bot and Voice Observability Hardening

- Scope: `docs/RUNBOOK_TELEGRAM_BOT.md`, `docs/RUNBOOK_VOICE_PIPELINE.md`, `docs/AUTH_SECURITY.md`
- Why this work happened: Runbooks pre-dated Phase 7 implementation and described planned rather than actual behavior; security decisions remained open
- Decisions applied: all Phase 7 security decisions resolved — chat_id allowlist confirmed, immediate audio deletion + sweep confirmed, OpenAI Whisper confirmed as provider, transcript not stored
- Evidence collected: logging audit across `handlers.py`, `transcribe.py`, `cleanup.py` — all use event_id/chat_id/status identifiers, no raw content; 97 tests passing
- Follow-ups: none; all AC met
- Notes for next agent: logging uses structured identifiers throughout; `chars=` in transcription success log is a length count, never the transcript text

### 2026-04-15 — P7-T04 — Voice Test Coverage

- Scope: `tests/unit/test_telegram_voice.py` (extended), `tests/unit/test_voice_cleanup.py`, `tests/unit/test_transcription_worker.py`
- Why this work happened: Phase 7 gate required automated coverage for voice success path, failure path, and cleanup behavior
- Decisions applied: D-009
- Evidence collected: 97 unit tests passing; voice handler, cleanup worker, transcription worker all covered
- Follow-ups: none; all Phase 7 gate conditions met
- Notes for next agent: `asyncio.create_task` mock in voice handler test requires closing coroutines to suppress RuntimeWarning

### 2026-04-15 — P7-T03 — Media Retention and Cleanup

- Scope: `app/workers/cleanup.py`, `app/workers/transcribe.py` (immediate deletion added), `docs/VOICE_PIPELINE.md`, `docs/ENVIRONMENT.md`
- Why this work happened: Phase 7 requires bounded raw audio retention to prevent unbounded disk growth
- Decisions applied: D-009; retention: immediate deletion after transcription + configurable sweep
- Evidence collected: `delete_local_voice_file` called in `transcribe_and_reply` after success; `cleanup_voice_media` sweeps terminal events older than `VOICE_RETENTION_SECONDS`
- Follow-ups: cleanup sweep should be scheduled via cron or arq
- Notes for next agent: `VOICE_RETENTION_SECONDS` env var configures the sweep window (default 3600); immediate deletion is unconditional after a successful reply

### 2026-04-15 — P7-T02 — Async Transcription Pipeline

- Scope: `app/workers/transcribe.py`, `app/telegram/handlers.py` (task enqueue added), `pyproject.toml` (`openai>=1.0` added)
- Why this work happened: Phase 7 requires async transcription that routes transcript through the standard text assistant path
- Decisions applied: D-009; provider: OpenAI Whisper API (`whisper-1`)
- Evidence collected: `transcribe_and_reply` runs as `asyncio.create_task`; Whisper API call in `asyncio.to_thread`; status progression: received → transcribed → done/failed; user notified on both success and failure paths
- Follow-ups: none
- Notes for next agent: the transcription worker sends its reply via a standalone `Bot(token=...)` instance — it does not have access to the polling Application context

### 2026-04-15 — P7-T01 — Voice Ingress and Media Persistence

- Scope: `app/telegram/voice.py`, `app/telegram/handlers.py`, `app/assistant/voice_media.py`, `app/models/voice.py`, `alembic/versions/008_add_voice_media_events.py`
- Why this work happened: Phase 7 foundation — voice update handling, file download, and metadata persistence before transcription
- Decisions applied: D-009
- Evidence collected: `VoiceMediaEvent` model with status lifecycle; `download_voice_file` saves `.ogg` to `VOICE_MEDIA_DIR`; `create_voice_media_event` persists metadata before download
- Follow-ups: P7-T02 (transcription), P7-T03 (cleanup)
- Notes for next agent: `bot_token` is stored in `bot_data` during `build_application` so the background transcription task can construct a standalone `Bot` instance without access to the Application object

### 2026-04-15 — P6-T07 — Phase 6 Test Coverage

- Scope: `tests/unit/test_telegram_bot.py` (extended), `tests/unit/test_assistant_chat.py`, `tests/unit/test_assistant_session.py`
- Why this work happened: Phase 6 gate required automated coverage for auth guard, text routing, and insufficient-evidence behavior
- Decisions applied: D-007
- Evidence collected: all three AC covered; auth guard tested with `ApplicationHandlerStop`; insufficient-evidence reply tested end-to-end
- Follow-ups: none; Phase 6 gate conditions met
- Notes for next agent: `handle_chat` tests mock the Anthropic client entirely; no API key needed for unit tests

### 2026-04-15 — P6-T06 — Deployment and Config Wiring

- Scope: `docker-compose.yml`, `docs/DEPLOY.md`, `docs/ENVIRONMENT.md`, `docs/RUNBOOK_TELEGRAM_BOT.md`
- Why this work happened: Phase 6 deployability requires explicit service topology, env contract, and startup ordering
- Decisions applied: D-011
- Evidence collected: `telegram-bot` service added to Compose; deployment docs reflect actual service names and startup commands; migration requirements documented
- Follow-ups: none
- Notes for next agent: bot process uses long polling; no public webhook endpoint needed for private deployment

### 2026-04-15 — P6-T05 — Session Persistence

- Scope: `app/assistant/session.py`, `app/models/session.py`, `alembic/versions/007_add_bot_sessions.py`, `app/assistant/chat.py` (session integration)
- Why this work happened: bot sessions must survive process restart; Redis is not the sole source of session truth
- Decisions applied: D-010
- Evidence collected: `BotSession` model with `history_json`; upsert via `INSERT ... ON CONFLICT DO UPDATE`; `MAX_HISTORY_MESSAGES=20` trim on each save; `handle_chat` loads and saves history around each request
- Follow-ups: none
- Notes for next agent: history stores only user/assistant role pairs — not the intermediate tool_use/tool_result messages, which keeps history compact for DB storage

### 2026-04-15 — P6-T04 — Text Conversation Flow

- Scope: `app/assistant/chat.py`, `app/assistant/tools.py`, `app/telegram/handlers.py` (text handler wired)
- Why this work happened: Phase 6 requires natural-language text queries to trigger bounded archive tools
- Decisions applied: D-007; bounded tool-use loop with `MAX_TOOL_ROUNDS=5` guard
- Evidence collected: `handle_chat` uses Anthropic `messages.create(tools=TOOLS)`, loops on `tool_use` stop reason, falls back to last captured text after guard fires; `execute_tool` maps 6 tool names to facade methods
- Follow-ups: P6-T05 (session persistence), P6-T07 (test coverage)
- Notes for next agent: `TOOLS` catalog is read-only plus `trigger_sync`; no mutation tools wired; `_extract_text` handles both string and list content blocks from Anthropic responses

### 2026-04-15 — P6-T03 — Telegram Bot Runtime

- Scope: `app/telegram/bot.py`, `app/telegram/handlers.py`, `app/telegram/__main__.py`, `app/shared/config.py`
- Why this work happened: Phase 6 requires an independent bot process that authenticates, routes, and responds
- Decisions applied: D-006; TypeHandler at group=-1000 as chat guard
- Evidence collected: `chat_guard` raises `ApplicationHandlerStop` for unauthorized chat_id; text and voice handlers registered; `build_application` wires all bot_data
- Follow-ups: P6-T04 (conversation flow), P6-T05 (persistence), P6-T06 (deployment)
- Notes for next agent: `allowed_chat_id` is stored in `bot_data` so handlers don't need env access directly

### 2026-04-15 — P6-T02 — Assistant Service Facade

- Scope: `app/assistant/facade.py`
- Why this work happened: Telegram must not call raw ORM or domain services directly; a bounded gateway is required
- Decisions applied: D-007; facade exposes only read + sync-trigger operations
- Evidence collected: `AssistantFacade` wraps 6 methods; returns DTO-style frozen dataclasses; no raw ORM objects cross the boundary; `trigger_sync` requires an explicit `SyncJobEnqueuer` dependency
- Follow-ups: P6-T03 (bot runtime), P6-T04 (tool loop)
- Notes for next agent: `AssistantFacade` is the only object the Telegram layer is allowed to import from the assistant package; raw service imports from telegram/ are prohibited by the CF contract

### 2026-04-15 — P6-T01 — Reconcile Backend Execution Boundary

- Scope: `app/workers/ingest.py`, `app/workers/index.py`, `app/services/analysis.py`, `tests/integration/test_workers.py`, `docs/ARCHITECTURE.md`
- Why this work happened: Phase 6 planning could not safely proceed while the documented sync -> analyse -> index path was ambiguous in the runtime wiring
- Decisions applied: keep the backend in a bounded workflow shape; the ingest worker now owns orchestration of downstream analysis and indexing instead of leaving that path implicit
- Evidence collected: `python3 -m pytest tests/integration/test_workers.py -q --tb=short` → `6 passed`; the worker path now stores dream entries, detects missing downstream artifacts, runs `AnalysisService` for missing themes, and runs `RagIngestionService` through `app/workers/index.py` for missing chunks
- Follow-ups: none for the execution-boundary ambiguity; newly synced dreams are now automatically analysed and indexed, and resync skips already-complete downstream stages
- Notes for next agent: the ingest worker is the canonical execution boundary for Phase 6 assumptions; if a dream exists but is missing themes or chunks, a later sync run repairs only the missing stage instead of duplicating stored records

### 2026-04-14 — DOC-PHASE6 — Telegram and Voice Documentation Rewrite

- Scope: `README.md`, `docs/ARCHITECTURE.md`, `docs/spec.md`, `docs/PHASE_PLAN.md`, `docs/PRODUCT_OVERVIEW.md`, `docs/ENVIRONMENT.md`, `docs/DEPLOY.md`, `docs/TELEGRAM_INTERACTION_MODEL.md`, `docs/VOICE_PIPELINE.md`, `docs/AUTH_SECURITY.md`, `docs/TESTING_STRATEGY.md`, `docs/RUNBOOK_TELEGRAM_BOT.md`, `docs/RUNBOOK_VOICE_PIPELINE.md`, `docs/DECISION_LOG.md`, `docs/CODEX_PROMPT.md`, and ADRs 003-007
- Why this work happened: The project needed a documentation rewrite for the post-Phase-5 evolution so implementation can proceed against a coherent Telegram-enabled architecture instead of a backend-only maintenance framing
- Decisions applied: D-005 through D-011; ADR-003 through ADR-007 proposed
- Evidence collected: manual repo analysis of Dream Motif Interpreter and the Telegram-first reference repository; documentation consistency pass across architecture, phase plan, env, deploy, auth, testing, and runbooks
- Follow-ups: implementation should resolve the open decisions around Phase 6 write scope, transcription provider, session persistence, Telegram ingress mode, and Google Docs credential mode before coding starts
- Notes for next agent: the docs now explicitly separate current observed backend state from planned Telegram and voice target state; do not describe service-account JSON auth or Telegram runtime as already implemented until code exists

### 2026-04-14 — DOC-PHASE6-TASKGRAPH — Active Execution Graph Added

- Scope: `docs/tasks_phase6.md`, `docs/CODEX_PROMPT.md`, `docs/IMPLEMENTATION_CONTRACT.md`, and planning/ops docs that now reference the new execution graph
- Why this work happened: Phase 6+ needed an explicit active execution graph so AI implementation can preserve historical context without treating the old Phase 1-5 backend task graph as the live roadmap
- Decisions applied: D-008 through D-011
- Evidence collected: consistency pass across README, architecture, phase plan, product overview, deploy, testing, Telegram, voice, and prompt/contract docs
- Follow-ups: implementation agents should use `docs/tasks_phase6.md` as the active source of execution truth for Telegram, voice, and Phase 6+ work
- Notes for next agent: `docs/tasks.md` is now historical; do not append new Telegram work there unless you are explicitly documenting history rather than defining active execution

### 2026-04-14 — FIX-C9 — Technical Debt — P3 Findings

- Scope: `app/main.py`, `app/services/segmentation.py`, `alembic/versions/003_seed_categories.py`, `scripts/eval.py`, `app/retrieval/query.py`, `app/api/search.py`, `app/api/dreams.py`, `app/api/patterns.py`, `app/api/versioning.py`, `app/api/themes.py`, `app/shared/database.py`, ADR docs, and targeted retrieval/eval/API tests
- Why this work happened: Maintenance closure required resolving all remaining P3 findings around localhost binding defaults, stale comments, eval history persistence, retrieval query expansion, fragment citation metadata, duplicated session-factory wiring, and missing ADR documentation
- Decisions applied: D-005, D-007, ADR-001, ADR-002
- Evidence collected: `pytest -q tests/unit/test_rag_query.py tests/unit/test_rag_query_expansion.py tests/unit/test_eval_script.py tests/integration/test_search_api.py tests/integration/test_workers.py` → `17 passed`; `pytest -q` → `98 passed, 9 skipped`; `ruff check app/ tests/ scripts/` → clean; `ruff format --check app/ tests/ scripts/` → clean
- Follow-ups: none; all carry-forward P3 findings are closed
- Notes for next agent: async session-factory ownership now lives in `app/shared/database.py`; ASGI tests that reload the app need `get_session_factory.cache_clear()` to avoid reusing cached async engines across event loops; query expansion is best-effort and falls back cleanly when Anthropic is unavailable

### 2026-04-14 — FIX-C8 — Technical Debt — P2 Findings

- Scope: `app/workers/ingest.py`, `app/api/dreams.py`, `app/api/themes.py`, `app/main.py`, targeted integration tests, and prompt continuity updates
- Why this work happened: Cycle 8 left three P2 runtime hardening gaps open around Redis status writes, Redis client shutdown, and malformed bulk-confirm token parsing
- Decisions applied: D-008, D-009
- Evidence collected: `pytest -q tests/integration/test_workers.py tests/integration/test_curation_api.py` → `11 passed`; `pytest -q` → `95 passed, 9 skipped`; `ruff check app/ tests/` → clean; `ruff format --check app/ tests/` → clean
- Follow-ups: no new findings introduced; remaining open findings are carry-forward P3 items only
- Notes for next agent: Redis client ownership now lives in `app/api/dreams.py` as a lazy module-level singleton, and the app lifespan closes it when the concrete client exposes `aclose()`

### 2026-04-14 — T20 — End-to-End Integration Test

- Scope: `tests/integration/test_e2e.py` and seeded fixture-driven pipeline test coverage
- Why this work happened: Phase 5 T20 required a final gate test that drives the archive through sync, analysis, retrieval, curation approval, pattern inspection, rollback, and cleanup in one integrated workflow
- Decisions applied: D-003, D-007, D-009
- Evidence collected: `pytest -q tests/integration/test_e2e.py` → `2 passed`; `pytest -q` → `93 passed, 9 skipped`; `ruff check app/ tests/` → clean; `ruff format --check app/ tests/` → clean
- Follow-ups: no new findings from T20; existing carry-forward findings remain (`CODE-7`, `CODE-13`, `CODE-16`, `CODE-40`, `CODE-41`, `ARCH-10`, `ARCH-11`, `ARCH-12`, `ARCH-15`, `CODE-48`, `CODE-49`, `CODE-50`)
- Notes for next agent: the e2e harness uses a test-only job enqueuer that preserves production behavior while exercising the real ingest, analysis, indexing, curation, versioning, and pattern service stack through the public API surface

### 2026-04-14 — T19 — Annotation Versioning and Rollback

- Scope: `app/services/versioning.py`, `app/api/versioning.py`, versioning-related refactors in analysis/taxonomy/theme mutation paths, and T19 integration/unit coverage
- Why this work happened: Phase 5 T19 required annotation history retrieval, authenticated rollback for dream themes, and an explicit guard that `annotation_versions` remains append-only
- Decisions applied: D-007
- Evidence collected: `pytest -q tests/unit/test_versioning.py tests/integration/test_versioning.py tests/integration/test_taxonomy.py` → `8 passed`; `pytest -q` → `91 passed, 9 skipped`; `ruff check app/ tests/` → clean; `ruff format --check app/ tests/` → clean
- Follow-ups: T20 is next; existing carry-forward findings remain (`CODE-7`, `CODE-13`, `CODE-16`, `CODE-40`, `CODE-41`, `ARCH-10`, `ARCH-11`, `ARCH-12`, `ARCH-15`, `CODE-48`, `CODE-49`, `CODE-50`)
- Notes for next agent: rollback restores the persisted DreamTheme fields from the selected `AnnotationVersion.snapshot` and writes a new append-only version row that captures the restored state plus rollback transition metadata

### 2026-04-14 — T18 — Archive-Level Pattern Detection

- Scope: `app/services/patterns.py`, `app/api/patterns.py`, `app/main.py`, `tests/integration/test_patterns_api.py`
- Why this work happened: Phase 5 T18 required archive-level recurring-pattern, co-occurrence, and timeline APIs framed as computational pattern signals rather than authoritative interpretations
- Decisions applied: none
- Evidence collected: `pytest -q tests/integration/test_patterns_api.py` → `4 passed`; `pytest -q` → `87 passed, 9 skipped`; `ruff check app/ tests/` → clean; `ruff format --check app/ tests/` → clean
- Follow-ups: T19 is next; `ARCH-12`, `ARCH-15`, `CODE-48`, `CODE-49`, and `CODE-50` remain open carry-forwards
- Notes for next agent: pattern aggregation uses confirmed, non-deprecated themes only; recurring percentages are computed against the distinct dream count represented in the confirmed-theme archive; timeline excludes undated dreams because the response contract requires ISO dates

### 2026-04-14 — T17 — Background Worker Setup with Idempotency

- Scope: `app/workers/ingest.py`, `app/workers/index.py`, worker registration and integration coverage
- Why this work happened: T17 established Redis-backed worker execution and job status handling for ingestion and indexing with idempotent processing semantics
- Decisions applied: D-009
- Evidence collected: `pytest -q` baseline advanced to `83 passed, 9 skipped`; worker integration coverage added for queued, done, and failed job outcomes
- Follow-ups: worker lifecycle robustness findings remained open for later hardening (`CODE-48`)
- Notes for next agent: sync jobs and worker status updates are now first-class runtime paths; check Redis error handling before extending the worker surface

### 2026-04-14 — T16 — User Curation API

- Scope: `app/api/themes.py`, curation integration coverage, supporting config and tracing updates
- Why this work happened: T16 introduced authenticated theme confirmation/rejection, category approval, and the Redis-backed bulk-confirm approval flow with annotation version writes before mutations
- Decisions applied: D-007, D-008
- Evidence collected: `pytest -q` baseline advanced to `79 passed, 9 skipped`; curation integration tests cover confirm/reject, bulk approval, auth, and version-write behavior
- Follow-ups: bulk-confirm token validation hardening (`CODE-50`) and Redis client lifecycle cleanup (`CODE-49`) remained open
- Notes for next agent: theme and category mutations now rely on append-only `AnnotationVersion` writes; keep that invariant if rollback work changes these paths

### 2026-04-14 — T15 — Dream Browsing and Theme Search API

- Scope: `app/api/search.py`, search integration coverage, retrieval framing
- Why this work happened: T15 exposed authenticated search and per-dream theme listing on top of the T11 retrieval layer
- Decisions applied: D-003, D-005
- Evidence collected: `pytest -q` baseline advanced to `74 passed, 9 skipped`; search integration tests cover ranked results, insufficient-evidence, theme filters, and salience ordering
- Follow-ups: retrieval contract gaps `ARCH-10` and `ARCH-11` remained open carry-forwards
- Notes for next agent: search responses already carry interpretation framing; keep new interpretive endpoints aligned with that API-level disclaimer pattern

### 2026-04-14 — T14 — Ingestion and Sync API Endpoints

- Scope: `app/api/dreams.py`, sync/dream listing integration coverage, config validation tests
- Why this work happened: T14 exposed the authenticated sync trigger, sync job status, dream pagination, and dream detail endpoints
- Decisions applied: D-009
- Evidence collected: `pytest -q` baseline advanced to `70 passed, 9 skipped`; integration coverage added for sync, pagination, and missing-dream handling; config fail-fast tests added
- Follow-ups: T15 was next; session-factory reuse and Redis client lifecycle were still deferred
- Notes for next agent: `app/api/dreams.py` owns the shared API-key validation path and currently provides the session factory reused by newer routers

### 2026-04-13 — T13 — Health Endpoint and Observability

- Scope: `app/api/health.py`, `app/shared/tracing.py`, `app/main.py`, `app/services/analysis.py`, `app/services/taxonomy.py`, `app/services/gdocs_client.py`, `app/llm/client.py`, `app/retrieval/types.py`, `app/retrieval/ingestion.py`, `app/retrieval/query.py`, tracing/health test files
- Why this work happened: Phase 4 T13 required health freshness semantics, structured request logging, and consistent OpenTelemetry span coverage across DB and external API boundaries
- Decisions applied: none
- Evidence collected: `python3 -m pytest -q` → `57 passed, 9 skipped`; `python3 -m pytest tests/unit/test_tracing.py tests/integration/test_health.py -q` → `5 passed`; `ruff check app/ tests/` → clean
- Follow-ups: T14 is next; CODE-38 and CODE-39 remain open before the authenticated API work expands
- Notes for next agent: `app/retrieval/types.py` is now the shared OpenAI embedding client; request logs are JSON via structlog and derive `trace_id`/`span_id` from the active OTel span

### 2026-04-10 — STRATEGIST — Architecture Package Initialized

- Scope: `docs/ARCHITECTURE.md`, `docs/spec.md`, `docs/tasks.md`, `docs/CODEX_PROMPT.md`, `docs/IMPLEMENTATION_CONTRACT.md`, `docs/DECISION_LOG.md`, `docs/EVIDENCE_INDEX.md`, `docs/retrieval_eval.md`, `.github/workflows/ci.yml`, operational prompt files
- Why this work happened: Initial project bootstrap via STRATEGIST.md — full architecture package produced from PROJECT_BRIEF.md
- Decisions applied: D-001 through D-010 (see DECISION_LOG.md)
- Evidence collected: none yet — pre-implementation
- Follow-ups: T01 Project Skeleton is next
- Notes for next agent: RAG profile is ON. Ingestion and query pipelines must be in separate modules. Annotation versioning is mandatory for all DreamTheme and ThemeCategory mutations. Dream content must never appear in logs or spans. Human approval gate is required for taxonomy promotion.

### 2026-04-17 — Phase 10 — Research Augmentation

- Scope: WS-10.1–WS-10.5 (Research Augmentation)
- Why this work happened: Phase 10 required the research augmentation path, storage, service orchestration, API surface, and assistant tool gating for external motif parallels
- Decisions applied: D-013 (provider-agnostic retriever), ADR-009 (research trust boundary), ADR-010 (feature flag gating)
- Evidence collected: 216 unit tests pass; research_results migration (010); ResearchRetriever + ResearchSynthesizer; ResearchService; GET/POST /motifs/{id}/research; research_motif_parallels assistant tool gated by RESEARCH_AUGMENTATION_ENABLED
- Follow-ups: FIX-7/FIX-8 OTel instrumentation; ARCHITECTURE.md doc drift (FIX-9c)
- Notes for next agent: Research augmentation is an external trust-boundary path separate from dream-archive RAG and remains gated behind `RESEARCH_AUGMENTATION_ENABLED`

### 2026-04-18 — Phase 11 — Feedback Loop

- Scope: WS-11.1–WS-11.3 (Feedback Loop)
- Why this work happened: Phase 11 required the feedback capture persistence, deterministic digit-reply handling, and a read-only admin API for stored ratings
- Decisions applied: D-014 (WS-11.4 deferred), ADR-006 (session state in bot_sessions — in-memory dict used as pragmatic single-user trade-off)
- Evidence collected: 225 unit tests pass; assistant_feedback migration 011; FeedbackService; digit-reply capture in handlers.py; GET /feedback paginated API
- Follow-ups: FIX-10/11/12 OTel+ORM fixes; WS-11.4 comment capture deferred to future phase
- Notes for next agent: Phase 11 adds a rating-only feedback loop; optional comment capture remains intentionally deferred

### 2026-04-20 — Local Setup Checkpoint — Service Account Auth and Universal Ingestion Plan

- Scope: `app/services/gdocs_client.py`, `app/shared/config.py`, Google Docs auth tests, `docs/spec.md`, `docs/tasks.md`, `prompts/ORCHESTRATOR.md`
- Why this work happened: local environment had to be brought to a runnable test state, Google Docs access needed to switch from OAuth refresh-token flow to an approved service-account JSON, and future ingestion work needed a fixed canonical plan for multi-format, multi-source intake
- Decisions applied: Google Docs auth now supports service-account JSON via `GOOGLE_SERVICE_ACCOUNT_FILE`; future ingestion must preserve the canonical pipeline `source connector -> normalized document -> parser profile -> dream entry candidates -> validated dream entries -> embeddings/indexing`
- Evidence collected: `.venv` created and dependencies installed; local Postgres reachable on `127.0.0.1:5433`; Redis reachable on `127.0.0.1:6379`; application DB `dream_motif` created; Alembic upgraded to head; `GET /health` returned `{"status":"ok","index_last_updated":null}`; `pytest tests/unit/test_config.py -q` → `8 passed`; `pytest tests/unit/test_gdocs_client.py -q` → `7 passed`; service-account credentials loaded successfully for `dream-180@dream-493107.iam.gserviceaccount.com`
- Follow-ups: set a real `GOOGLE_DOC_ID` in local `.env`; verify live `GDocsClient.fetch_document()` against the approved Google Doc; inspect actual source layout to confirm whether intake is a single doc or folder-style container; only then continue with parsing, segmentation, embeddings, and retrieval indexing
- Notes for next agent: local `.env` and the copied service-account JSON are runtime setup artifacts and may be gitignored; one smoke test that expects missing `DATABASE_URL` can fail locally when `.env` is loaded, so config tests should be run with `_env_file=None` isolation where appropriate

### 2026-04-21 — DOC-CHECKPOINT — Installation and Testing Stop Point Recorded

- Scope: `README.md`, `docs/PHASE_PLAN.md`, `docs/TESTING_STRATEGY.md`, `docs/ENVIRONMENT.md`
- Why this work happened: the repository needed an explicit written checkpoint showing where local setup and testing currently stop after the Phase 11/doc commits, so the next pass starts from facts instead of memory
- Decisions applied: none; this is a status-alignment pass over existing implementation
- Evidence collected: local setup checkpoint from 2026-04-20 reviewed; targeted tests already verified in the prior checkpoint remain `tests/unit/test_config.py` (`8 passed`) and `tests/unit/test_gdocs_client.py` (`7 passed`); `.venv/bin/pytest --collect-only -q` now reports `295 tests collected in 2.91s`
- Follow-ups: set a real `GOOGLE_DOC_ID` and verify live Google Docs fetch; then run the full pytest suite inside `.venv`; only open a new maintenance phase if that verification exposes a concrete fix batch
- Notes for next agent: the collection blocker in `tests/integration/test_gdocs_client.py` has been fixed; the next unknown is no longer syntax, but runtime behavior against real credentials and the full suite
