# Task Graph — Dream Motif Interpreter Phase 19

Version: 1.0
Last updated: 2026-05-01
Status: Planned — source: Тест 5 "Поиск конкретного сна"

## 1. Purpose

Phase 19 adds direct lookup of a specific dream by title.

The user-reported failure is accurate: current `search_dreams` searches dream content chunks,
not `dream_entries.title`; `get_dream` requires a UUID; there is no tool that maps a title to
a dream ID.

## 2. Workstreams

---

## WS-19.1: Title Search Facade Method

Owner:      codex
Phase:      19
Type:       facade + query
Priority:   P1
Depends-On: none

Objective:
  Add a title-search method that returns dream IDs and enough metadata for disambiguation.

Acceptance-Criteria:
  - AC-1: `AssistantFacade` exposes `search_dreams_by_title(query, limit=10)`.
  - AC-2: Search checks `dream_entries.title`, not only `dream_chunks.chunk_text`.
  - AC-3: Supports exact, case-insensitive partial, and fuzzy-ish punctuation-insensitive match.
  - AC-4: Result includes `dream_id`, `date`, `title`, and short preview.
  - AC-5: Unit tests cover "Я и дети. Тайное общество" style lookup.

Files:
  - `app/assistant/facade.py`
  - `tests/unit/test_assistant_facade.py`

Context-Refs:
  - `app/models/dream.py::DreamEntry`
  - `app/assistant/facade.py::list_recent_dreams`
  - `app/assistant/facade.py::get_dream`

---

## WS-19.2: Assistant Tool `search_dreams_by_title`

Owner:      codex
Phase:      19
Type:       assistant tools
Priority:   P1
Depends-On: WS-19.1

Objective:
  Expose title lookup to the assistant and route title-like requests to it.

Acceptance-Criteria:
  - AC-1: Tool catalog includes `search_dreams_by_title`.
  - AC-2: Tool output includes UUID so the assistant can call `get_dream`.
  - AC-3: Prompt instructs title/name lookup to use title search first.
  - AC-4: Ambiguous matches are presented as options, not guessed.
  - AC-5: Unit tests cover tool output and prompt routing text.

Files:
  - `app/assistant/tools.py`
  - `app/assistant/prompts.py`
  - `tests/unit/test_assistant_chat.py`

Context-Refs:
  - `app/assistant/tools.py::build_tools`
  - `app/assistant/tools.py::execute_tool`
  - `app/assistant/prompts.py §Response Formatting Rules`

---

## WS-19.3: Full Dream Retrieval by Title Flow

Owner:      codex
Phase:      19
Type:       assistant integration
Priority:   P1
Depends-On: WS-19.1, WS-19.2

Objective:
  User asks for a specific dream title and receives the correct full dream or a clarification.

Acceptance-Criteria:
  - AC-1: If title search returns exactly one strong match, assistant retrieves full dream via `get_dream`.
  - AC-2: If multiple matches exist, assistant asks the user to choose.
  - AC-3: If no title match exists, assistant may fall back to content search but clearly says no title match was found.
  - AC-4: Tests cover single match, multiple matches, and no match.

Files:
  - `app/assistant/tools.py`
  - `app/assistant/prompts.py`
  - `tests/unit/test_assistant_chat.py`

## 3. Phase Gate

- [ ] User can find a dream by exact title.
- [ ] User can find a dream by partial/punctuation-varied title.
- [ ] Tool returns UUID and supports `get_dream`.
- [ ] Ambiguous title matches are not guessed.

## 4. Not In Scope

- Semantic motif search quality; see Phase 18.
- Editing or renaming dreams.
