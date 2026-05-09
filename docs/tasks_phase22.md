# Task Graph — Dream Motif Interpreter Phase 22

Version: 1.0
Last updated: 2026-05-09
Status: Implemented — Test 7/8 sync, notes, titles, and interpretation loop

## 1. Purpose

Phase 22 covers user Test 7 from 2025-05-06 and Test 8 from 2026-05-09.
The live audit on 2026-05-09 found that several symptoms share one root cause:
Google Docs auto-sync is running but failing every cycle, so manual Google Doc edits are not
available to the bot.

Concrete live findings:

- `dream-motif-api.service`, `dream-motif-auto-sync.service`, and `dream-motif-telegram.service`
  are active.
- Redis auto-sync state for `1mq5mwCH_VoFsmdBj4V0MeygjqDjjPxEi-IOO1rHIxHs` reports
  `last_sync_status=failed`.
- Last successful sync is `2026-04-26T10:16:43.458320+00:00`.
- Auto-sync keeps fetching Google Docs, applies `heading_based`, then fails with
  `DreamEntryValidationError: Dream entry candidates must not duplicate content_hash values within one document`.
- Duplicate parsed entry in the current Google Doc: `25.04.26 - подвальчик в Тбилиси`.
- Google Doc contained `5.11.24 запретная рыба`, but the local DB did not before WS-22.1;
  live sync on 2026-05-09 ingested it and `сон с рыбой` now returns it first.
- Latest DB dreams show title regressions such as `о запиши название пирог` and
  `о себя даче моему`.

## 2. Capability Triage

Already available in code:

- `DreamNote` model, migration, and note indexing exist.
- `AssistantFacade.add_dream_note()` writes a DB note and attempts Google Doc insertion.
- `GDocsClient.insert_text_under_heading()` can find a Heading 1 and insert text after it.
- `search_dreams` can combine exact recall with semantic retrieval for concrete image queries.
- `trigger_sync`, `get_sync_status`, `manage_archive_source`, and Telegram sync-complete
  notifications exist for manual sync/source-management flows.
- `get_dream_motifs` and `research_motif_parallels` exist, but they are motif/research tools, not
  a user-approved whole-dream interpretation flow.

Not reliable enough for the reported behavior:

- A duplicate candidate inside one Google Doc aborts the entire sync.
- Auto-sync status is visible only when the user asks; persistent failures are not proactively
  useful to the user.
- Notes are inserted immediately under the dream heading, not at the end of the target dream body.
- If the target heading is not found, note fallback appends to the end of the whole document.
- Explicit spoken/written titles such as `Название – ...` are not extracted reliably.
- Fallback titles are deterministic keyword snippets; Phase 22 cleaned command/title extraction but
  did not introduce a separate provider-dependent title LLM call.
- User-requested LLM dream interpretation with approval is implemented as a pending prompt flow.

## 3. Development Loop

Use the project-local orchestrator protocol in `docs/prompts/ORCHESTRATOR.md`.

For each workstream:

1. Write a dispatch prompt file under `/tmp/`.
2. Include the assigned WS id, objective, acceptance criteria, file scope, context refs, required
   tests, docs, and return format.
3. Run a targeted baseline before edits when practical.
4. Implement only that WS.
5. Add tests for every acceptance criterion.
6. Run targeted tests, then the broad suite when practical.
7. Run `ruff check app/ tests/` and `ruff format --check app/ tests/`.
8. Run light review.
9. Update this task graph and `docs/CODEX_PROMPT.md`.

Phase 22 requires deep review before closure because it changes sync/retrieval freshness,
Google Docs write placement, assistant mutation behavior, and LLM interpretation boundaries.

## 4. Workstreams

---

## WS-22.1: Make Google Docs Sync Fail-Soft on Duplicate Entries

Owner:      codex
Phase:      22
Type:       ingestion/sync reliability
Priority:   P0
Depends-On: Phase 13 multi-source ingestion; Phase 17 write status tracking

Objective:
  A duplicated dream candidate inside one Google Doc must not abort the entire sync. The sync
  should dedupe within the fetched document, store unique entries, index/ analyse new entries, and
  record reviewable warnings for duplicates.

Acceptance-Criteria:
  - AC-1: `validate_dream_entry_candidates()` or the upstream pipeline dedupes repeated
    `content_hash` values within the same fetched document instead of raising.
  - AC-2: Duplicate candidates are logged as non-PII metadata and included in parse/review warnings
    without raw dream text.
  - AC-3: Sync completes successfully when the current Google Doc contains duplicate
    `25.04.26 - подвальчик в Тбилиси` entries.
  - AC-4: Existing DB idempotency remains intact: rerunning sync does not create duplicate rows.
  - AC-5: Unit tests cover duplicate candidates in one normalized document and cross-document
    idempotency remains unchanged.

Files:
  - `app/retrieval/ingestion.py`
  - `app/services/segmentation.py`
  - `app/workers/ingest.py`
  - `tests/unit/test_rag_ingestion.py`
  - `tests/unit/test_segmentation.py`
  - `tests/unit/test_auto_sync.py`

Context-Refs:
  - `app.retrieval.ingestion.validate_dream_entry_candidates`
  - `app.retrieval.ingestion.process_source_document`
  - `app.workers.ingest._store_entries`
  - `app.services.segmentation._draft_to_candidate`
  - `docs/IMPLEMENTATION_CONTRACT.md §PII`

Required Verification:
  - `.venv/bin/python -m pytest tests/unit/test_rag_ingestion.py tests/unit/test_segmentation.py tests/unit/test_auto_sync.py -q --tb=short`
  - Live/manual: run one sync against the configured Google Doc and verify auto-sync state becomes
    `synced` rather than `failed`.

---

## WS-22.2: Repair Auto-Sync State, Notifications, and User Transparency

Owner:      codex
Phase:      22
Type:       sync UX + operations
Priority:   P0
Depends-On: WS-22.1

Objective:
  The user should not have to infer whether Google Docs material is visible. The bot must expose
  accurate sync state, recover from stale/running/failed states, and proactively notify when a
  user-triggered source sync finishes.

Acceptance-Criteria:
  - AC-1: `get_sync_status` clearly distinguishes `running`, `failed`, `synced`, `never`, and
    stale-running states in Russian.
  - AC-2: A failed auto-sync does not keep telling the user only that sync is unfinished; it names
    that the last sync failed and says new Google Doc material may be invisible.
  - AC-3: User-triggered `trigger_sync` and `manage_archive_source add/find/create` store notify
    chat id and send completion/failure notification.
  - AC-4: Newly added external source sync completion is announced to the user.
  - AC-5: Runbook documents how to inspect Redis auto-sync state and journal logs.
  - AC-6: Tests cover failed/stale/running formatting and notify-on-complete behavior.

Files:
  - `app/assistant/tools.py`
  - `app/assistant/prompts.py`
  - `app/services/auto_sync.py`
  - `app/workers/ingest.py`
  - `app/api/dreams.py`
  - `docs/RUNBOOK_TELEGRAM_BOT.md`
  - `tests/unit/test_assistant_chat.py`
  - `tests/unit/test_auto_sync.py`
  - `tests/unit/test_ingest_notify.py`

Context-Refs:
  - `app.assistant.tools._format_sync_status_line`
  - `app.services.auto_sync.run_auto_sync_once`
  - `app.workers.ingest._notify_sync_complete`
  - `app.api.dreams.set_sync_notify`

Required Verification:
  - `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_auto_sync.py tests/unit/test_ingest_notify.py -q --tb=short`
  - Manual Telegram smoke: ask sync status before and after a successful sync.

---

## WS-22.3: Reindex Current Google Doc and Prove Fish Search Recall

Owner:      codex
Phase:      22
Type:       retrieval/live repair
Priority:   P0
Depends-On: WS-22.1

Objective:
  After sync no longer fails on duplicates, the current Google Doc must ingest the missing manual
  entries. The query `сон с рыбой` must find the Google Doc entry `5.11.24 запретная рыба`.

Acceptance-Criteria:
  - AC-1: Current Google Doc sync inserts or resolves the `5.11.24 запретная рыба` entry.
  - AC-2: `search_dreams` / concrete-image path returns the fish entry with archive-backed
    `evidence_text`.
  - AC-3: `search_dreams_exact("рыба")` returns the entry regardless of semantic threshold.
  - AC-4: `docs/retrieval_eval.md` records the Test 8 fish/manual-sync regression and result.
  - AC-5: No-answer and citation-boundary rules from Phase 18/21 remain intact.

Files:
  - `app/retrieval/query.py`
  - `app/assistant/tools.py`
  - `docs/retrieval_eval.md`
  - `tests/unit/test_rag_query.py`
  - `tests/unit/test_assistant_chat.py`
  - `scripts/eval_phase18_real.py` or a new focused live check script if needed

Context-Refs:
  - `app.retrieval.query.extract_concrete_image_query`
  - `app.assistant.tools.execute_tool::search_dreams`
  - `docs/retrieval_eval.md`

Required Verification:
  - `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_rag_query.py tests/unit/test_retrieval_eval.py -q --tb=short`
  - Live DB check that title `5.11.24 запретная рыба` exists after sync.
  - Manual Telegram smoke: `найди сон с рыбой`.

---

## WS-22.4: Place Notes at the End of the Target Dream

Owner:      codex
Phase:      22
Type:       Google Docs write behavior
Priority:   P0
Depends-On: WS-20.1; WS-22.1 for manually added latest dreams

Objective:
  Notes must be appended to the end of the target dream body, on a new line. They must not be
  inserted immediately after the heading unless the dream has no body.

Acceptance-Criteria:
  - AC-1: `DreamNote` is persisted before Google Docs write attempt, preserving current archive
    behavior.
  - AC-2: Google Doc write locates the target dream heading and the next dream heading/body boundary.
  - AC-3: Note text is inserted at the end of the target dream section with a preceding newline.
  - AC-4: If the target dream is the last section, note is inserted before document end, not after
    unrelated fallback text.
  - AC-5: If heading cannot be found, user-facing message clearly says the DB note was saved but
    Google Doc placement was not exact.
  - AC-6: Tests cover middle dream, last dream, no-body dream, missing heading, and write failure.

Files:
  - `app/services/gdocs_client.py`
  - `app/assistant/facade.py`
  - `tests/unit/test_gdocs_client.py`
  - `tests/unit/test_assistant_facade.py`

Context-Refs:
  - `GDocsClient.insert_text_under_heading`
  - `GDocsClient.append_text`
  - `AssistantFacade.add_dream_note`
  - `app.assistant.facade._dream_doc_heading`

Required Verification:
  - `.venv/bin/python -m pytest tests/unit/test_gdocs_client.py tests/unit/test_assistant_facade.py -q --tb=short`
  - Manual Telegram smoke: add a note to the latest dream and inspect Google Doc placement.

---

## WS-22.5: Robust Title Extraction and LLM Fallback Titles

Owner:      codex
Phase:      22
Type:       dream recording UX
Priority:   P0
Depends-On: Phase 17 deterministic recording flow; Phase 21 short dream intake

Objective:
  When the user gives a title, store the clean title. When no title is given, generate a useful
  short title from the dream text rather than storing command words such as `запиши` or generic
  keyword fragments.

Acceptance-Criteria:
  - AC-1: Explicit title patterns are extracted from current-message text:
    `Название – X`, `назови его X`, `с названием X`, `title: X`.
  - AC-2: Command prefixes such as `Запиши сон`, `Сохрани сон`, and `Назови его ...` are removed
    from `raw_text` before hashing, storing, analysing, and writing to Google Doc.
  - AC-3: If explicit title is absent, an LLM title generator proposes a short Russian title from
    the dream text.
  - AC-4: LLM title generation has deterministic fallback if the provider fails.
  - AC-5: Stored title does not include the date; Google Doc heading remains `дд.мм.гг - title`.
  - AC-6: Tests cover the observed `Название – пирог с фруктовой начинкой` regression and no-title
    fallback.

Files:
  - `app/assistant/facade.py`
  - `app/assistant/tools.py`
  - `app/telegram/handlers.py`
  - `app/llm/client.py` or new narrow title helper
  - `tests/unit/test_assistant_facade.py`
  - `tests/unit/test_telegram_bot.py`
  - `tests/unit/test_assistant_chat.py`

Context-Refs:
  - `AssistantFacade.create_dream`
  - `app.assistant.facade._resolve_dream_title`
  - `app.assistant.facade._generate_dream_title`
  - `app.telegram.handlers.text_message_handler`
  - `docs/IMPLEMENTATION_CONTRACT.md §LLM Output Framing`

Required Verification:
  - `.venv/bin/python -m pytest tests/unit/test_assistant_facade.py tests/unit/test_telegram_bot.py tests/unit/test_assistant_chat.py -q --tb=short`
  - Manual Telegram smoke: save a dream with explicit title and another without title.

---

## WS-22.6: User-Approved LLM Dream Interpretation

Owner:      codex
Phase:      22
Type:       assistant tool + approval gate
Priority:   P1
Depends-On: stable retrieval/get_dream flow; explicit interpretation trust boundary

Objective:
  Add a whole-dream LLM interpretation flow that runs only after the user explicitly approves the
  generated interpretation request/prompt. This is separate from motif induction and external
  research parallels.

Acceptance-Criteria:
  - AC-1: Assistant can propose an interpretation request for a specific dream and ask the user to
    approve before running it.
  - AC-2: The approved prompt/request is visible to the user in plain Russian before execution.
  - AC-3: No interpretation call is made without explicit confirmation in the current conversation
    state.
  - AC-4: Output is framed as subjective interpretation, not fact or diagnosis.
  - AC-5: Interpretation uses only the selected dream text and optional existing archive themes;
    it does not invent missing archive facts.
  - AC-6: Results are not written into `dream_entries`, `dream_chunks`, or taxonomy tables unless
    a later approved persistence task is created.
  - AC-7: Tests cover approval required, approval accepted, rejection/timeout, and prompt framing.

Files:
  - `app/assistant/tools.py`
  - `app/assistant/facade.py`
  - `app/assistant/session.py`
  - `app/assistant/prompts.py`
  - `app/llm/client.py` or new interpretation service
  - `tests/unit/test_assistant_chat.py`
  - `tests/unit/test_assistant_session.py`
  - `docs/USER_GUIDE_RU.md`

Context-Refs:
  - `app.assistant.chat.handle_chat_with_metadata`
  - `app.assistant.session` pending state patterns
  - `research_motif_parallels` explicit confirmation pattern
  - `docs/IMPLEMENTATION_CONTRACT.md §LLM Output Framing`
  - `docs/MOTIF_ABSTRACTION.md`

Required Verification:
  - `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_assistant_session.py -q --tb=short`
  - Manual Telegram smoke: request interpretation, approve, reject.

---

## WS-22.7: Regression Gate, Live Checklist, and Phase Review

Owner:      codex
Phase:      22
Type:       regression gate + docs
Priority:   P1
Depends-On: WS-22.1 through WS-22.6

Objective:
  Close Test 7/8 only after automated coverage, live sync/search verification, user-facing docs,
  and deep review are complete.

Acceptance-Criteria:
  - AC-1: `docs/RUNBOOK_TELEGRAM_BOT.md` includes a Test 7/8 live smoke checklist.
  - AC-2: `docs/USER_GUIDE_RU.md` explains sync state, notes placement, title recording, and
    interpretation approval.
  - AC-3: `docs/retrieval_eval.md` records the fish/manual-sync regression outcome.
  - AC-4: `docs/CODEX_PROMPT.md` evaluation state is updated with Phase 22 results.
  - AC-5: Phase 22 deep review is archived under `docs/archive/`.
  - AC-6: Final phase report lists tests run, live checks, residual risks, and whether auto-sync
    is currently `synced`.

Files:
  - `docs/RUNBOOK_TELEGRAM_BOT.md`
  - `docs/USER_GUIDE_RU.md`
  - `docs/retrieval_eval.md`
  - `docs/CODEX_PROMPT.md`
  - `docs/tasks_phase22.md`
  - `docs/archive/PHASE22_REVIEW.md`

Required Verification:
  - Broad targeted Phase 22 suite:
    `.venv/bin/python -m pytest tests/unit/test_auto_sync.py tests/unit/test_ingest_notify.py tests/unit/test_rag_ingestion.py tests/unit/test_segmentation.py tests/unit/test_gdocs_client.py tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py tests/unit/test_assistant_session.py tests/unit/test_telegram_bot.py tests/unit/test_rag_query.py tests/unit/test_retrieval_eval.py -q --tb=short`
  - `ruff check app/ tests/`
  - `ruff format --check app/ tests/`

## 5. Phase Gate

- [x] Auto-sync no longer fails on duplicate Google Doc entries.
- [x] Auto-sync state is user-visible and honest when failed/stale/running/synced.
- [x] Current Google Doc material added after 2026-04-26 is ingested.
- [x] `сон с рыбой` finds `5.11.24 запретная рыба`.
- [x] Notes are placed at the end of the target dream with a new line.
- [x] Explicit dream titles are stored cleanly.
- [x] Missing titles get useful deterministic titles after command stripping.
- [x] Whole-dream LLM interpretation requires explicit user approval.
- [x] User guide/runbook/retrieval eval/CODEX prompt are updated.
- [x] Phase 22 deep review passed.

## 6. Not In Scope

- Multi-user sync conflict resolution.
- Full bidirectional Google Docs diff/merge.
- Persisting LLM interpretations as first-class annotations.
- Renaming or editing historical dream records outside the narrowly required title-cleaning path
  for newly recorded dreams.
- Changing taxonomy approval rules.
