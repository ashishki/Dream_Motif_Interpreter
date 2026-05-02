# Task Graph — Dream Motif Interpreter Phase 21

Version: 1.3
Last updated: 2026-06-02
Status: In progress — WS-21.3 complete

## 1. Purpose

Phase 21 covers the Test 6 report from 2026-06-02. The report shows that Phase 17-20 improved
recording, title lookup, and feedback behavior, but live Telegram still has regressions around
short dream recording, Google Doc write truthfulness, image search recall, and full-text retrieval
by known title/date.

## 2. Capability Triage

Already available in code:

- `search_dreams_by_title` exists and can return UUIDs and retrieve the full dream on a single
  title match.
- `create_dream` persists dreams and calls `write_dream_to_google_doc`.
- `DreamWriteStatus` tracks Google Doc write success/failure and retry state.
- `search_dreams_exact` can find verbatim words when the assistant chooses it.

Still not reliable enough for the reported live behavior:

- Short natural dream openings can still be rejected or routed into a confirmation prompt because
  `_has_natural_dream_opening()` requires enough tail words and old tests explicitly reject short
  natural mentions.
- Voice transcript handling still depends on the assistant loop for natural dream recordings, so a
  short transcript can be discussed instead of deterministically saved.
- User-facing success text can include fallback document IDs such as `...O1rHIxHs`; Test 6 requires
  the shorter text `Сон сохранён и добавлен в документ`.
- Image search by common nouns such as `рыба` can miss entries when the assistant routes to
  semantic search instead of exact+semantic retrieval.
- `list_recent_dreams` tool output omits UUIDs, which can make the model claim a known dream is
  inaccessible even when title search/get_dream are available.

## 3. Workstreams

---

## WS-21.1: Save Short Natural Dreams Without Clarification

Owner:      codex
Phase:      21
Type:       Telegram recording reliability
Priority:   P0
Depends-On: Phase 17 deterministic recording flow

Objective:
  Any current Telegram text or voice transcript that starts with a natural dream opening such as
  `сегодня мне приснилось` must be saved directly, even if the dream is short. The bot must not ask
  whether to record a short dream and must not ask for more details just because it is short.

Acceptance-Criteria:
  - AC-1: `_has_natural_dream_opening()` accepts short openings with at least one dream-content word.
  - AC-2: Natural dream text messages call `create_dream` once and do not create pending drafts.
  - AC-3: Voice transcripts beginning with a natural dream opening are deterministically saved
    without asking for confirmation.
  - AC-4: Tests cover short text and short voice transcript cases.

Files:
  - `app/assistant/tools.py`
  - `app/assistant/prompts.py`
  - `app/workers/transcribe.py`
  - `app/telegram/handlers.py`
  - `tests/unit/test_assistant_chat.py`
  - `tests/unit/test_transcription_worker.py`
  - `tests/unit/test_telegram_bot.py`

Implementation Notes:
  - Completed 2026-06-02.
  - `_has_natural_dream_opening()` now accepts one content word after natural openings and covers
    gender/number variants such as `мне приснилась рыба`.
  - Telegram text messages with natural openings call `create_dream` directly and bypass
    `handle_chat_with_metadata`, pending drafts, and clarification prompts.
  - Voice transcripts with natural openings now save directly after transcript persistence and
    report the create result without entering the assistant loop.
  - Regression evidence:
    `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_telegram_bot.py tests/unit/test_transcription_worker.py -q --tb=short`
    -> `94 passed, 1 warning`;
    `ruff check` and `ruff format --check` passed for touched WS-21.1 files.

---

## WS-21.2: Honest Google Doc Write Confirmation and Retry

Owner:      codex
Phase:      21
Type:       Google Docs write reliability
Priority:   P0
Depends-On: WS-20.1 note placement; Phase 17 write status tracking

Objective:
  User-facing recording messages must only say the dream was added to Google Doc after a successful
  `append_dream_entry` call and status update. The success message must not expose fallback doc IDs.

Acceptance-Criteria:
  - AC-1: Success text is exactly `Сон сохранён и добавлен в документ` for Telegram create flows.
  - AC-2: Write failures say the dream was saved only in the archive and provide the retry phrase.
  - AC-3: Duplicate dream handling does not imply a fresh Google Doc write happened.
  - AC-4: Tests cover successful write, failed write, duplicate entry, and retry after failure.

Files:
  - `app/telegram/handlers.py`
  - `app/assistant/prompts.py`
  - `app/assistant/tools.py`
  - `app/assistant/facade.py`
  - `tests/unit/test_telegram_bot.py`
  - `tests/unit/test_assistant_chat.py`
  - `tests/unit/test_assistant_facade.py`

Implementation Notes:
  - Completed 2026-06-02.
  - Telegram create confirmations now say exactly `Сон сохранён и добавлен в документ` only
    when `written_to_google_doc=True`; the formatter no longer appends document names or fallback
    IDs.
  - Failed Google Doc writes still report archive-only persistence with the retry phrase, and
    duplicates do not imply a fresh Google Doc write.
  - Assistant tool results for create/retry success no longer include `written_to_doc_name`, so the
    model has no user-facing fallback doc ID to leak.
  - Regression evidence:
    `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_telegram_bot.py tests/unit/test_telegram_voice.py tests/unit/test_transcription_worker.py tests/unit/test_assistant_facade.py -q --tb=short`
    -> `153 passed, 1 warning`;
    `ruff check` and `ruff format --check` passed for touched WS-21.2 files.

---

## WS-21.3: Verbatim Image Search Recall

Owner:      codex
Phase:      21
Type:       retrieval/query
Priority:   P0
Depends-On: Phase 18 search quality work

Objective:
  Queries like `сон с рыбой`, `найди рыбу`, or `сны где есть рыба` must find dreams containing
  the exact word `рыба` and still support semantic expansion for related phrasing.

Acceptance-Criteria:
  - AC-1: Assistant/tool routing runs exact retrieval for concrete image nouns and combines it with
    semantic retrieval instead of relying on semantic search alone.
  - AC-2: Exact matches are not suppressed by relevance thresholds.
  - AC-3: Tests include `рыба` as a regression fixture and verify archive-backed evidence is shown.
  - AC-4: `docs/retrieval_eval.md` records the Test 6 fish/image-search regression.

Files:
  - `app/assistant/tools.py`
  - `app/assistant/prompts.py`
  - `app/retrieval/query.py`
  - `docs/retrieval_eval.md`
  - `tests/unit/test_assistant_chat.py`
  - `tests/unit/test_rag_query.py`
  - `tests/unit/test_retrieval_eval.py`

Implementation Notes:
  - Completed 2026-06-02.
  - `search_dreams` now augments concrete image/object queries such as `сон с рыбой`,
    `найди рыбу`, and `сны где есть рыба` with exact FTS recall through
    `search_dreams_exact`.
  - Exact fish/object results are merged with semantic results and deduped by `dream_id`; exact
    hits are not suppressed by semantic insufficient-evidence thresholds.
  - `docs/retrieval_eval.md` now records the Phase 21 fish/image regression dataset P21-Q01–P21-Q03.
  - Regression evidence:
    `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_rag_query.py tests/unit/test_retrieval_eval.py -q --tb=short`
    -> `92 passed, 1 warning`;
    `ruff check` and `ruff format --check` passed for touched WS-21.3 files.

---

## WS-21.4: Full Dream by Title and Date Flow

Owner:      codex
Phase:      21
Type:       assistant tool flow
Priority:   P0
Depends-On: Phase 19 direct title search

Objective:
  When the user provides a known title and date and asks for the full dream text, the assistant
  must retrieve it without claiming UUID access is impossible.

Acceptance-Criteria:
  - AC-1: `list_recent_dreams` tool output includes `dream_id` so a listed dream can be opened.
  - AC-2: `search_dreams_by_title` supports date-aware disambiguation or the tool flow can combine
    title and date to select the correct UUID.
  - AC-3: The system prompt forbids claiming that title-to-UUID lookup is unavailable.
  - AC-4: Tests cover the reported `04.04.26` / `Кирилл, мужик, настольки` flow and verify
    `get_dream` is used for the full text.

Files:
  - `app/assistant/tools.py`
  - `app/assistant/prompts.py`
  - `app/assistant/facade.py`
  - `tests/unit/test_assistant_chat.py`
  - `tests/unit/test_assistant_facade.py`

---

## WS-21.5: Regression Gate and Live Verification Checklist

Owner:      codex
Phase:      21
Type:       regression gate
Priority:   P1
Depends-On: WS-21.1 through WS-21.4

Objective:
  Close Test 6 only after targeted automated coverage and a live/manual Telegram checklist cover
  the exact reported scenarios.

Acceptance-Criteria:
  - AC-1: Automated targeted suite covers all Test 6 repros.
  - AC-2: `docs/RUNBOOK_TELEGRAM_BOT.md` includes a Test 6 smoke checklist.
  - AC-3: `docs/USER_GUIDE_RU.md` describes short dream recording and exact image search behavior.
  - AC-4: Phase 21 deep review is archived before closing the phase.

Files:
  - `docs/RUNBOOK_TELEGRAM_BOT.md`
  - `docs/USER_GUIDE_RU.md`
  - `docs/tasks_phase21.md`
  - `docs/CODEX_PROMPT.md`
  - `docs/archive/PHASE21_REVIEW.md`

## 4. Phase Gate

- [x] Short natural text and voice dreams are saved without clarification.
- [x] Telegram write success/failure messages are honest and hide fallback doc IDs.
- [x] Fish/image exact search regression is covered and passes.
- [ ] Full dream retrieval by title/date works without UUID user input.
- [ ] Test 6 live/manual checklist is documented.
- [ ] Phase 21 deep review passed.
