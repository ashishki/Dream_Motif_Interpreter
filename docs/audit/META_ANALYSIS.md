# META_ANALYSIS — Cycle 15
_Date: 2026-05-02 · Type: full_

## Project State
Phase 19 (WS-19.1–WS-19.3) is complete locally. Next: Phase 20 — WS-20.1 Place Notes Under the Target Dream in Google Doc, after Phase 19 deep review archive.

Baseline: 106 pass, 0 fail in targeted assistant slice (`tests/unit/test_assistant_chat.py tests/unit/test_assistant_facade.py`); full local suite remains environment-dependent because live services/DB coverage is broader than this review scope.

## Open Findings
| ID | Sev | Description | Files | Status |
|----|-----|-------------|-------|--------|
| CODE-4 | P3 | Telegram feedback commit failure can suppress FEEDBACK_ACK. | `app/telegram/handlers.py` | Carry-forward; outside Phase 19 scope |
| CODE-5 | P3 | `RESEARCH_API_KEY=""` acceptance is documented but remains a configuration trade-off. | `app/shared/config.py`, ADR-010 | Carry-forward; outside Phase 19 scope |
| CODE-6 | P3 | Feedback pending dict capacity/TTL risk. | `app/telegram/handlers.py` | Carry-forward; outside Phase 19 scope |

## PROMPT_1 Scope (architecture)
- `app/assistant/facade.py`: bounded facade gained deterministic title lookup over `dream_entries.title`.
- `app/assistant/tools.py`: bounded assistant tool catalog gained `search_dreams_by_title` and full title-to-dream flow.
- `app/assistant/prompts.py`: routing rule added for title/name/heading lookup.
- `docs/tasks_phase19.md`, `docs/CODEX_PROMPT.md`, `docs/IMPLEMENTATION_JOURNAL.md`: phase state and continuity updates.

## PROMPT_2 Scope (code, priority order)
1. `app/assistant/tools.py` (changed)
2. `app/assistant/facade.py` (changed)
3. `app/assistant/prompts.py` (changed)
4. `tests/unit/test_assistant_chat.py` (changed)
5. `tests/unit/test_assistant_facade.py` (changed)

## Cycle Type
Full — Phase 19 is complete locally and the next work belongs to Phase 20.

## Notes for PROMPT_3
Phase 19 review found no open P0/P1/P2 after the pre-report robustness fix for invalid `limit` input in `search_dreams_by_title` / `list_recent_dreams` tool execution. The fix is covered by `tests/unit/test_assistant_chat.py::test_execute_tool_search_dreams_by_title_uses_default_for_bad_limit`.
