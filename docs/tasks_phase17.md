# Task Graph — Dream Motif Interpreter Phase 17

Version: 1.0
Last updated: 2026-05-01
Status: Planned — source: Тест 5 (26.04.26) + post-Phase 16 code review

## 1. Purpose

Phase 17 stabilizes the dream-recording path in Telegram.

The product requirement is now stronger than Phase 14-16 assumed:

- if the user records a dream in the bot, it should be written to the Google Doc;
- the user should not need to say exactly "запиши сон";
- the bot must never say that a dream was recorded unless the write actually succeeded;
- retry must target the failed dream, not whichever dream was last saved.

This phase intentionally moves core intake behavior out of prompt-only control and into
deterministic state and service logic.

## 2. Current Implemented Baseline

Already implemented:

- `create_dream` saves a dream entry, runs analysis/indexing, and then calls
  `write_dream_to_google_doc`.
- Google Doc headings are formatted as `дд.мм.гг - Название`.
- The system prompt receives today's date, so the LLM can resolve relative dates.
- The chat loop blocks more than one `create_dream` call per user turn.
- Duplicate exact content hashes are not written to Google Doc again.
- Telegram voice messages are transcribed and routed through the normal chat path.

Known gaps:

- `create_dream` is still gated by `_is_explicit_create_request`; natural dream openings
  such as "сегодня мне приснилось" are rejected.
- There is no pending dream draft state for "записать?" → "да".
- Retry without `dream_id` writes the most recently created dream, not the last failed write.
- Missing titles become `без названия`; they are not auto-generated from 2-3 main themes.
- Text replies to a previous voice message do not retrieve the replied-to voice transcript.
- Success messaging is still mediated by the LLM after tool output; product-level honesty
  needs deterministic enforcement.

## 3. Defects

D1 (P0): Natural dream narration is not recorded.
  Example: user sends a voice note beginning "сегодня мне приснилось"; bot asks whether to
  record it, then says it was recorded after confirmation, but no Google Doc write happened.

D2 (P0): Confirmation after "record this?" has no reliable pending candidate.
  Root: the previous transcript is only chat history, not a typed pending dream draft.

D3 (P0): Bot may claim success when Google Doc write failed or did not run.
  Root: user-facing final response is LLM-generated from tool output; there is no hard
  Telegram response guard for write success/failure.

D4 (P0): Retry can write the wrong dream.
  Root: `retry_write_to_google_doc(dream_id=None)` resolves to latest `DreamEntry`.

D5 (P1): Missing date/title handling is too weak.
  Root: date is mostly prompt-driven; title fallback is `без названия`, not a useful
  "date + 2-3 themes" heading.

D6 (P1): Reply-to-voice "запиши сон" is unsupported.
  Root: text handler sees only the text reply and does not resolve `reply_to_message.voice`
  or a stored transcription event.

## 4. Workstreams

---

## WS-17.1: Deterministic Dream Intake Classifier

Owner:      codex
Phase:      17
Type:       telegram + assistant tool guard
Priority:   P0
Depends-On: none
Status:     Implemented locally — 2026-05-01

Objective:
  Detect likely dream-recording messages before the LLM tool guard rejects them.
  Natural openings must count as explicit dream intake when the message contains enough
  narrative content.

Acceptance-Criteria:
  - AC-1: `_is_explicit_create_request` accepts Russian natural openings:
    "сегодня мне приснилось", "мне приснилось", "мне снилось", "приснился сон",
    "приснилось, что".
  - AC-2: Classifier has a minimum-content guard so short casual mentions like
    "мне приснилось?" do not create empty dreams.
  - AC-3: Voice transcripts use the same classifier path as text.
  - AC-4: Unit tests cover explicit command, natural dream opening, and negative examples.

Files:
  - `app/assistant/tools.py`
  - `tests/unit/test_assistant_tools.py` or existing assistant tool tests
  - `tests/unit/test_transcription_worker.py`

Context-Refs:
  - `app/assistant/tools.py::_is_explicit_create_request`
  - `app/workers/transcribe.py::transcribe_and_reply`
  - `docs/tasks_phase17.md §2-3`

Implementation Notes:
  - `_is_explicit_create_request` accepts the listed natural Russian dream openings only when
    at least two narrative words follow the opening.
  - Short mentions such as "мне приснилось?" remain rejected by the tool guard.
  - Voice transcripts are unchanged at the worker layer and continue to route through
    `handle_chat`, so they use the same assistant tool guard as text.
  - Verification on the local non-live machine:
    `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_transcription_worker.py -q --tb=short`
    -> 60 passed.
  - Full local suite requires the live/test infrastructure: PostgreSQL was unavailable at
    `127.0.0.1:5433`, and `tests/unit/test_ci.py::test_ruff_check_passes` expects `ruff` on PATH.

---

## WS-17.2: Pending Dream Draft State for Confirmation

Owner:      codex
Phase:      17
Type:       session state + Telegram UX
Priority:   P0
Depends-On: WS-17.1

Objective:
  If the assistant asks whether to record a dream, the candidate dream must be stored as a
  typed pending draft. A later "да" must create that exact dream, not infer from history.

Design:
  Store ephemeral pending state per `chat_id`:

  - `raw_text`
  - optional `title`
  - optional resolved `dream_date`
  - source Telegram message id
  - source kind: `text` / `voice_transcript`
  - created_at

  The state can live in `context.bot_data` for first implementation if bounded by TTL, or in
  PostgreSQL if reuse after restart is required. Prefer smallest implementation that satisfies
  the acceptance criteria.

Acceptance-Criteria:
  - AC-1: When bot asks "записать?", the candidate text is persisted outside LLM history.
  - AC-2: User reply "да" calls `create_dream` with the pending candidate text.
  - AC-3: User reply "нет" clears pending state and does not create a dream.
  - AC-4: Pending state expires or is cleared after use; stale candidates cannot be saved.
  - AC-5: Unit tests prove "да" saves the pending dream after a prior candidate.

Files:
  - `app/telegram/handlers.py`
  - `app/assistant/session.py` if persisted state is chosen
  - `tests/unit/test_telegram_bot.py`

Context-Refs:
  - `app/telegram/handlers.py::text_message_handler`
  - `app/assistant/prompts.py §Archive Mutation Rules`
  - ADR-006 (`docs/adr/ADR-006-persisted-bot-session-state.md`)

---

## WS-17.3: Deterministic Relative Date and Auto-Title Resolution

Owner:      codex
Phase:      17
Type:       assistant facade
Priority:   P1
Depends-On: WS-17.1

Objective:
  Resolve "сегодня", "вчера", "позавчера" outside the LLM, and generate a useful title when
  the user does not provide one.

Acceptance-Criteria:
  - AC-1: Russian relative dates resolve from application date in Asia/Tbilisi deployment
    context unless a different runtime timezone is explicitly configured.
  - AC-2: If the user provides no date, default to the recording date.
  - AC-3: If the user provides no title, generate `о <2-3 основные темы>` from the dream text.
  - AC-4: Google Doc heading remains `дд.мм.гг - <title>` and contains date exactly once.
  - AC-5: Unit tests cover no title, title with embedded date, today/yesterday/day-before.

Implementation notes:
  Use a deterministic, lightweight title heuristic first. A later LLM title generator is allowed
  only if it is covered by fallback behavior and never blocks saving.

Files:
  - `app/assistant/facade.py`
  - `app/assistant/tools.py`
  - `tests/unit/test_assistant_facade.py`

Context-Refs:
  - `app/assistant/facade.py::_resolve_dream_title`
  - `app/assistant/chat.py` date header injection
  - `app/services/gdocs_client.py::append_dream_entry`

---

## WS-17.4: Write Outbox and Honest Success Messages

Owner:      codex
Phase:      17
Type:       data model + tool behavior
Priority:   P0
Depends-On: WS-17.1

Objective:
  Track Google Doc write attempts per dream and make retry target a failed write record.
  The bot must not claim success unless the Google Doc append succeeded.

Design:
  Add a write-status model or minimal outbox table:

  - `id`
  - `dream_id`
  - `target_doc_id`
  - `status`: `pending` / `succeeded` / `failed`
  - `attempt_count`
  - `last_error`
  - `created_at`
  - `updated_at`

Acceptance-Criteria:
  - AC-1: `create_dream` creates or updates write status for the dream.
  - AC-2: Successful Google Doc append records `succeeded`.
  - AC-3: Failed Google Doc append records `failed` with sanitized error metadata.
  - AC-4: `retry_write_to_google_doc(dream_id=None)` retries the latest failed write for the
    current chat/source, not the latest dream globally.
  - AC-5: If no failed write exists, retry returns a clear "nothing to retry" message.
  - AC-6: Tool output is explicit enough that final user response cannot truthfully say
    "записано" on failure.
  - AC-7: Unit tests cover success, failure, retry exact target, and no failed write.

Files:
  - `app/models/` new write-status model
  - `alembic/versions/` new migration
  - `app/assistant/facade.py`
  - `app/assistant/tools.py`
  - `tests/unit/test_assistant_facade.py`
  - `tests/integration/test_migrations.py`

Context-Refs:
  - `app/assistant/facade.py::create_dream`
  - `app/assistant/facade.py::retry_write_to_google_doc`
  - `app/assistant/tools.py::execute_tool`

---

## WS-17.5: Reply-to-Voice "запиши сон"

Owner:      codex
Phase:      17
Type:       telegram + voice media
Priority:   P1
Depends-On: WS-17.1, WS-17.4

Objective:
  Allow the user to reply to an existing Telegram voice message with "запиши сон"; the bot
  should use the replied-to voice transcript as the dream text.

Acceptance-Criteria:
  - AC-1: Voice media events retain enough metadata to map Telegram `message_id` to transcript.
  - AC-2: Text handler detects `reply_to_message.voice` plus save command.
  - AC-3: If transcript already exists, save it immediately.
  - AC-4: If transcript is still processing, tell the user it is still processing and save after
    transcript is ready, or ask them to retry with a clear message.
  - AC-5: If transcript failed/unavailable, do not claim success.
  - AC-6: Unit tests cover reply-to-voice success and unavailable transcript.

Files:
  - `app/models/voice.py`
  - `app/assistant/voice_media.py`
  - `app/telegram/handlers.py`
  - `app/workers/transcribe.py`
  - `tests/unit/test_telegram_voice.py`
  - `tests/unit/test_transcription_worker.py`

Context-Refs:
  - `app/models/voice.py`
  - `app/assistant/voice_media.py`
  - `app/telegram/handlers.py::text_message_handler`
  - `app/workers/transcribe.py::transcribe_and_reply`

---

## WS-17.6: Recording Regression Suite and Manual Test Script

Owner:      codex
Phase:      17
Type:       tests + docs
Priority:   P0
Depends-On: WS-17.1, WS-17.2, WS-17.3, WS-17.4, WS-17.5

Objective:
  Freeze the user-reported recording scenarios as regression tests and a manual Telegram
  verification checklist.

Acceptance-Criteria:
  - AC-1: Automated tests cover natural dream opening, confirmation flow, relative dates,
    duplicate prevention, failed-write honesty, retry target, and reply-to-voice.
  - AC-2: `docs/RUNBOOK_TELEGRAM_BOT.md` includes a short recording smoke-test checklist.
  - AC-3: `docs/USER_GUIDE_RU.md` reflects the new "just tell the dream" behavior.
  - AC-4: Phase gate records which tests were run.

Files:
  - `tests/unit/test_telegram_bot.py`
  - `tests/unit/test_assistant_facade.py`
  - `tests/unit/test_transcription_worker.py`
  - `docs/RUNBOOK_TELEGRAM_BOT.md`
  - `docs/USER_GUIDE_RU.md`

## 5. Phase Gate

- [ ] Natural dream narration creates a dream without exact "запиши сон" wording.
- [ ] Confirmation "да" saves the exact pending dream candidate.
- [ ] Today/yesterday/day-before dates resolve without user clarification.
- [ ] Missing title becomes a useful 2-3-topic title, not only `без названия`.
- [ ] Failed Google Doc writes are not reported as success.
- [ ] Retry targets a failed write, not the latest dream globally.
- [ ] Reply-to-voice "запиши сон" works or fails honestly.
- [ ] User docs and runbook updated.

## 6. Not In Scope

- Editing existing dream text through chat.
- Deleting dream entries through chat.
- Semantic search quality changes; those are Phase 18.
- Direct title search; that is Phase 19.
