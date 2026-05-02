# Phase 21 Deep Review — Test 6 Recording/Search Regressions

Date: 2026-06-02
Scope: WS-21.1 through WS-21.5
Reviewer: Codex
Verdict: PASS after in-review fix

## Scope Reviewed

- Short natural dream recording for text and voice transcripts.
- Google Doc write confirmation wording and retry-facing tool results.
- Concrete image/object exact recall for queries such as `сон с рыбой`.
- Full dream retrieval by recent-list UUID and title/date lookup.
- Test 6 runbook and Russian user-guide documentation.

## Findings

### CODE-18 [P2] — Exact image recall was still blocked by semantic retrieval failure

Status: Resolved in review.

Files:
- `app/assistant/tools.py`
- `tests/unit/test_assistant_chat.py`

Finding:
The WS-21.3 `search_dreams` augmentation originally called semantic retrieval before returning exact image results. If the semantic/embedding path raised, concrete exact evidence such as `рыба` would not be returned even when `search_dreams_exact("рыба")` could find it.

Fix:
Concrete image/object queries now run exact recall first. If semantic retrieval fails but exact results exist, the tool returns the exact archive-backed evidence. Added regression coverage for `сон с рыбой` with semantic failure.

## No Open Findings

No P0, P1, P2, or P3 issues remain open from this review.

## Evidence

- `.venv/bin/python -m pytest tests/unit/test_assistant_chat.py tests/unit/test_assistant_facade.py tests/unit/test_rag_query.py tests/unit/test_retrieval_eval.py tests/unit/test_telegram_bot.py tests/unit/test_telegram_voice.py tests/unit/test_transcription_worker.py -q --tb=short` -> `174 passed, 1 warning`
- `.venv/bin/ruff check app/assistant/tools.py app/assistant/prompts.py app/assistant/facade.py app/telegram/handlers.py app/workers/transcribe.py app/retrieval/query.py tests/unit/test_assistant_chat.py tests/unit/test_assistant_facade.py tests/unit/test_rag_query.py tests/unit/test_retrieval_eval.py tests/unit/test_telegram_bot.py tests/unit/test_telegram_voice.py tests/unit/test_transcription_worker.py` -> clean
- Matching `.venv/bin/ruff format --check ...` -> clean

## Residual Risk

- Live Telegram and Google Docs behavior still requires operator smoke testing against deployed credentials; the exact Test 6 checklist is documented in `docs/RUNBOOK_TELEGRAM_BOT.md`.
- Emoji reaction semantics remain product-input blocked until concrete emoji meanings are supplied.
