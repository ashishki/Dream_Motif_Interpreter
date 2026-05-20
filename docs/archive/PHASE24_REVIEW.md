# Phase 24 Review — Test 10

Date: 2026-05-20
Scope: generated dream titles and pattern analysis over search result sets.

## Verdict

No P0/P1/P2 findings found in the implemented Phase 24 slice.

## Changes Reviewed

- `app/assistant/facade.py`: missing-title dreams now use a narrow LLM title generator over the
  full dream text, with deterministic fallback on provider failure.
- `app/assistant/tools.py`: `create_dream` ignores model-supplied titles unless the user's current
  message contains an explicit title marker.
- `app/assistant/session.py`: stores the recent dream result set per chat for follow-up workflows.
- `app/assistant/chat.py`: detects pattern-analysis requests over a selection/topic, loads full
  dream texts via `get_dream`, and runs direct analysis instead of asking the user to choose a path.
- `app/assistant/prompts.py`: fallback tool-loop instructions now require full-text pattern analysis
  without offering options first.

## Verification

- `.venv/bin/ruff check app/assistant/facade.py app/assistant/tools.py app/assistant/chat.py app/assistant/session.py app/assistant/prompts.py tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py tests/unit/test_assistant_session.py` -> clean
- `.venv/bin/python -m pytest tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py tests/unit/test_assistant_session.py -q --tb=short` -> `158 passed, 1 warning`
- `.venv/bin/python -m pytest tests/unit -q --tb=short` -> `463 passed, 1 warning`

## Findings

- CODE-24-1 (fixed): the title fallback was keyword-based (`о ...`) despite earlier docs saying an
  LLM title generator should exist. Added the LLM generator and fallback coverage.
- CODE-24-2 (fixed): the model could pass a non-user-supplied `title` into `create_dream`. Tool
  execution now only forwards title when the current user message has an explicit title marker.
- CODE-24-3 (fixed): follow-up pattern analysis could not see previous hidden search tool results.
  Recent search dream IDs are now remembered per chat and used for full-text analysis.

## Residual Risk

- Recent selection memory is not persisted across bot restarts. The fallback reruns search by topic
  when it can infer the topic from the current request or recent user history.
- The direct pattern route sends up to 20 full dream texts into one analysis request. Very large
  future result sets may need a map-reduce analysis pass.
- Existing historical titles are not backfilled in this slice.
