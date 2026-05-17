# Phase 23 Review — Test 9

Date: 2026-05-17
Scope: full dream text retrieval, English Google Doc/search coverage, numeric feedback disablement.

## Verdict

No P0/P1/P2 findings remain in the implemented Phase 23 slice.

## Changes Reviewed

- `app/assistant/tools.py`: `get_dream` tool output now includes complete `raw_text`.
- `app/assistant/prompts.py`: full-text requests must use `get_dream` and copy the Text field completely.
- `app/telegram/handlers.py`: long assistant replies split into Telegram-safe chunks; numeric feedback capture is feature-flagged.
- `app/shared/config.py`: `TELEGRAM_NUMERIC_FEEDBACK_ENABLED=false` by default.
- `app/services/segmentation.py`: added short dd.mm.yy dates and date-title heading parsing for English/manual Google Doc entries.
- `app/retrieval/query.py`: exact and hybrid keyword search now combine Russian FTS with `simple` FTS for English recall.
- `app/assistant/chat.py`: explicit full-text dream requests now bypass the final LLM response after
  a full dream tool result is available, preventing `max_tokens=1024` from shortening the archive text.
- `app/assistant/chat.py`: full-text requests that include a title/query are now resolved before the
  LLM call, preventing stale conversation history from answering without an archive lookup.

## Verification

- `.venv/bin/ruff check app/shared/config.py app/telegram/handlers.py app/assistant/tools.py app/assistant/prompts.py app/services/segmentation.py app/retrieval/query.py tests/unit/test_telegram_bot.py tests/unit/test_feedback_capture.py tests/unit/test_assistant_chat.py tests/unit/test_segmentation.py tests/unit/test_rag_query.py tests/unit/test_config.py tests/unit/test_voice_cleanup.py` -> clean
- `.venv/bin/python -m pytest tests/unit/test_telegram_bot.py tests/unit/test_feedback_capture.py tests/unit/test_assistant_chat.py tests/unit/test_segmentation.py tests/unit/test_rag_query.py tests/unit/test_config.py tests/unit/test_voice_cleanup.py -q --tb=short` -> `170 passed, 1 warning`
- `.venv/bin/python -m pytest tests/unit -q --tb=short` -> `452 passed, 1 warning`
- `.venv/bin/ruff check app/assistant/chat.py tests/unit/test_assistant_chat.py` -> clean
- `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py -q --tb=short` -> `90 passed, 1 warning`
- `.venv/bin/python -m pytest tests/unit -q --tb=short` -> `455 passed, 1 warning`
- Local DB smoke: `Приведи полный текст сна dreamwork, three women` -> pre-LLM direct route,
  `search_dreams_by_title` + `get_dream`, `2644` chars returned.

## Findings

- CODE-23-1 (P3, fixed in review): slash-date parsing could match `16/05/26` with the US
  `%m/%d/%y` pattern and raise `ValueError` before trying a day-first fallback. Fixed by making
  `_parse_date_header()` continue after invalid pattern matches and adding `%d/%m/%y` /
  `%d/%m/%Y` fallbacks with regression coverage.
- CODE-23-2 (P2, fixed in follow-up): full dream text was no longer truncated in the `get_dream`
  tool, but it still passed through final LLM generation with `max_tokens=1024`. Long dreams could
  therefore arrive incomplete before Telegram splitting. Fixed by returning explicit full-text
  requests directly from the archive-backed tool result.
- CODE-23-3 (P2, fixed in follow-up): repeated full-text requests could be answered from stale chat
  history without any tool call. Fixed by routing inline full-text title/query requests through
  deterministic archive lookup before the first LLM call.

## Residual Risk

- Direct full-text delivery requires an unambiguous dream resolution. If a title lookup returns
  multiple matches, the user still needs to choose one before the bot can send the full text.
- Live smoke against the newly added English Google Doc entries remains a deployment/runtime check.
- Numeric feedback can be re-enabled by configuration; if re-enabled, the old UX conflict returns unless a different feedback interaction is designed.
