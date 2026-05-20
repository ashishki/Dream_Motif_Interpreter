# Phase 25 — Backdated Google Doc Writes and Duplicate Rewrites

Last updated: 2026-05-20
Status: Implemented

## 1. User Feedback

The 2026-05-20 follow-up reported a Google Doc write mismatch:

1. The user asked the bot to add a dream for `19.05`.
2. The bot said the dream was added to the document, but the dream was not visible where the user
   expected it.
3. If a later dream such as `20.05` already exists in the document, a backdated `19.05` dream must
   be inserted before the `20.05` heading, not appended at the physical end of the document.
4. The bot should be allowed to write a dream again even when the same text already exists in the
   archive.

## 2. Findings

- `GDocsClient.append_dream_entry()` always inserted at the document end. It did not inspect
  existing Heading 1 date prefixes, so backdated entries landed after newer entries.
- `AssistantFacade.create_dream()` returned immediately when `content_hash` already existed and
  skipped the Google Doc write.
- The `create_dream` tool accepted ISO and relative dates but its create path did not accept a
  short user date such as `19.05`.
- Direct recording cleanup could leave a leading date directive such as `за 19.05:` in the stored
  dream body.
- `retry_write_to_google_doc` only retried rows marked `failed`, so a user-visible missing Google
  Doc entry could not be repeated when the internal status had already moved past `failed`.
- The duplicate `create_dream` tool result still started with "already exists", so the final model
  could frame a successful repeated Google Doc write as a duplicate-entry clarification.

## 3. Work Items

### WS-25.1 — Date-Sorted Google Doc Write

Scope:
- `app/services/gdocs_client.py`
- `tests/unit/test_gdocs_client.py`

Acceptance criteria:
- New dream headings are still written as Heading 1.
- A dream dated `19.05.26` is inserted before the first later dated heading/paragraph such as
  `20.05.26`.
- A second dream with the same date is inserted after existing dreams for that date and before
  later dates.
- If the target date cannot be parsed, the legacy end-of-document append behavior remains.

### WS-25.2 — Repeat Writes for Existing Archive Dreams

Scope:
- `app/assistant/facade.py`
- `app/assistant/tools.py`
- `app/telegram/handlers.py`
- `tests/unit/test_assistant_facade.py`
- `tests/unit/test_assistant_chat.py`
- `tests/unit/test_telegram_bot.py`

Acceptance criteria:
- Duplicate dream text does not create a second `DreamEntry` archive row.
- Duplicate dream text still attempts a Google Doc write for the existing archive row.
- If that write succeeds, user-facing save confirmation remains `Сон сохранён и добавлен в документ`.
- If that write fails, the bot does not claim a document write.

### WS-25.3 — Short Numeric Date Intake

Scope:
- `app/assistant/facade.py`
- `app/assistant/tools.py`
- `app/assistant/prompts.py`
- `tests/unit/test_assistant_facade.py`
- `tests/unit/test_assistant_chat.py`

Acceptance criteria:
- `create_dream.date` accepts `DD.MM`, `DD.MM.YY`, `DD.MM.YYYY`, ISO dates, and Russian relative
  dates.
- `DD.MM` resolves to the current application year.
- A leading directive such as `Запиши сон за 19.05: ...` sets the dream date and is removed from
  the stored body text.
- The assistant prompt tells the model to pass dates like `19.05` as the tool date argument.

### WS-25.4 — Repeat Latest Visible Save

Scope:
- `app/assistant/facade.py`
- `app/assistant/tools.py`
- `app/assistant/prompts.py`
- `tests/unit/test_assistant_facade.py`
- `tests/unit/test_assistant_chat.py`

Acceptance criteria:
- `повтори` / `повтори запись в Google Doc` still retries the latest failed write first.
- If no failed write exists, the same command repeats the latest dream from the current Telegram
  chat.
- If there is no failed write and no latest chat dream, the bot gives a practical recovery message
  instead of implying that sync status is the issue.

### WS-25.5 — Duplicate Tool Result Framing

Scope:
- `app/assistant/tools.py`
- `app/assistant/prompts.py`
- `tests/unit/test_assistant_chat.py`

Acceptance criteria:
- When duplicate dream text is successfully written to Google Doc, the tool returns only the
  success signal `Запись добавлена в Google Doc.`
- The assistant prompt explicitly treats successful repeated writes as successful saves.
- The final assistant must not suggest notes, another title, or another date after a successful
  duplicate write.

## 4. Verification

- `.venv/bin/python -m ruff check app/services/gdocs_client.py app/assistant/facade.py app/assistant/tools.py app/assistant/prompts.py app/telegram/handlers.py tests/unit/test_gdocs_client.py tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py tests/unit/test_telegram_bot.py` -> clean
- `.venv/bin/python -m ruff format --check app/services/gdocs_client.py app/assistant/facade.py app/assistant/tools.py app/assistant/prompts.py app/telegram/handlers.py tests/unit/test_gdocs_client.py tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py tests/unit/test_telegram_bot.py` -> clean
- `.venv/bin/python -m pytest tests/unit/test_gdocs_client.py tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py tests/unit/test_telegram_bot.py -q --tb=short` -> `196 passed, 1 warning`
- `.venv/bin/python -m pytest tests/unit -q --tb=short` -> `471 passed, 1 warning`

## 5. Residual Risk

- The Google Doc insertion logic relies on dream entry boundaries starting with `DD.MM.YY` or
  `DD.MM.YYYY`; styled Heading 1 is preferred but not required for placement.
- Repeated writes intentionally can create repeated Google Doc entries for the same archived dream
  text; the archive database remains deduplicated by `content_hash`.
