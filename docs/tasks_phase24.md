# Phase 24 — Test 10 Titles and Dream-Set Pattern Analysis

Last updated: 2026-05-20
Status: Implemented

## 1. User Feedback

Test 10 (2026-05-20) reported two issues:

1. Auto-generated dream titles are still poor. If the user does not provide a title, the bot should
   read the dream and create a meaningful title.
2. When the user asks for common work-related patterns across a search result set, the bot asks
   whether to fetch full texts first. It should perform the full analysis automatically, even if
   this requires loading every dream in the set.

## 2. Findings

- Telegram-created dreams used a deterministic fallback title generator in
  `app.assistant.facade._generate_dream_title()`. It selected the first 2-3 content words and
  produced titles such as `о море мост башня`.
- The `create_dream` tool accepted the model-provided `title` argument even when the user had not
  explicitly supplied a title. This allowed the chat model to invent a title in the tool call.
- Chat history stored only final assistant text, not the hidden search tool result. Follow-up
  requests like "find common patterns in this selection" could therefore lose the dream IDs.
- The system prompt required grounding in search `evidence_text`, but did not require the assistant
  to call `get_dream` for every selected dream before pattern analysis.

## 3. Work Items

### WS-24.1 — LLM Dream Titles

Scope:
- `app/assistant/facade.py`
- `app/assistant/tools.py`
- `tests/unit/test_assistant_facade.py`
- `tests/unit/test_assistant_chat.py`

Acceptance criteria:
- Explicit titles still win: `Название: X`, `назови сон X`, `с названием X`, `title: X`.
- If no explicit title marker exists, `create_dream` ignores model-supplied tool-call titles.
- Missing-title dreams call a narrow title LLM prompt over the full dream text.
- Generated titles are cleaned: no date, no markdown, no label prefix, no command words.
- If title LLM generation fails, deterministic fallback remains available.

### WS-24.2 — Full Dream-Set Pattern Analysis

Scope:
- `app/assistant/chat.py`
- `app/assistant/session.py`
- `app/assistant/prompts.py`
- `tests/unit/test_assistant_chat.py`
- `tests/unit/test_assistant_session.py`

Acceptance criteria:
- Search result IDs are remembered per chat for follow-up analysis.
- Requests for patterns in "this selection/list" use the remembered dream IDs.
- If no recent selection is available, the bot extracts the topic from the request or recent user
  history and reruns `search_dreams`.
- The bot calls `get_dream` for each selected/found dream before analysis.
- The bot does not ask the user whether to fetch full texts first.
- The analysis prompt receives full dream texts and instructs the model to cite supporting dreams.

## 4. Verification

- `.venv/bin/ruff check app/assistant/facade.py app/assistant/tools.py app/assistant/chat.py app/assistant/session.py app/assistant/prompts.py tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py tests/unit/test_assistant_session.py` -> clean
- `.venv/bin/python -m pytest tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py tests/unit/test_assistant_session.py -q --tb=short` -> `158 passed, 1 warning`
- `.venv/bin/python -m pytest tests/unit -q --tb=short` -> `463 passed, 1 warning`

## 5. Residual Risk

- Recent dream-set memory is in-process with a 120-minute TTL. If the bot restarts, the fallback is
  to infer the topic from history and rerun search.
- Pattern analysis is bounded to up to 20 dream IDs from the remembered set or retrieval result.
- Historical poor titles are not renamed in this phase; this phase fixes new Telegram-created dreams.
