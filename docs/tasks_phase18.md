# Task Graph — Dream Motif Interpreter Phase 18

Version: 1.0
Last updated: 2026-05-01
Status: In Progress — WS-18.2 implemented locally

## 1. Purpose

Phase 18 improves search quality and eliminates hallucinated or ultra-weak results.

The concrete user pain:

- query "найди сны, где упоминается молитва" should find a dream containing the
  Christmas prayer/song text even when the literal word "молитва" is absent;
- query "найди сны с религиозными сюжетами" should find dreams with church, prayer,
  icons, liturgy, divine names, Christmas hymnody, and adjacent religious scenes;
- the bot must never present dream fragments that are not present in retrieved evidence;
- very weak non-evidence matches should be suppressed instead of presented as
  "низкая релевантность".

## 2. Current Implemented Baseline

Already implemented in Phase 16:

- prompt routing says "упоминается X" should use semantic `search_dreams`;
- exact search falls back to semantic when exact returns 0 results;
- broad motif/theme queries are prompt-instructed to make 2-3 searches;
- prompt grounding rules forbid invented dream text.

Remaining risk:

- multi-query behavior is prompt-owned, not deterministic;
- retrieval thresholding can still surface low-signal vector neighbors;
- output grounding is enforced by instructions, not by a response contract;
- no retrieval eval set exists for the user's religious/mолитва cases.

## 3. Workstreams

---

## WS-18.1: User Search Regression Dataset

Owner:      codex
Phase:      18
Type:       eval
Priority:   P0
Depends-On: none
Status:     Implemented locally — 2026-05-01

Objective:
  Add a focused retrieval evaluation slice from user-reported failures.

Acceptance-Criteria:
  - AC-1: `docs/retrieval_eval.md` contains a Phase 18 dataset section with at least:
    "молитва", "где упоминается молитва", "где фигурирует молитва",
    "религиозные сюжеты", "церковь", "рождественское песнопение".
  - AC-2: Dataset marks the Christmas hymn/prayer dream as expected relevant for prayer.
  - AC-3: Dataset marks church/icon/prayer dreams as expected relevant for religious plots.
  - AC-4: Includes false-positive policy: no result may be counted correct without a real
    evidence fragment from the archive.

Files:
  - `docs/retrieval_eval.md`
  - `scripts/eval.py` if needed

Context-Refs:
  - `docs/retrieval_eval.md`
  - `tests/unit/test_retrieval_eval.py`
  - user feedback from Тест 4-5 summarized in this task graph

Implementation Notes:
  - Added `docs/retrieval_eval.md §Phase 18 User Search Regression Dataset`.
  - Dataset covers `молитва`, `где упоминается молитва`, `где фигурирует молитва`,
    `религиозные сюжеты`, `церковь`, and `рождественское песнопение`.
  - The Christmas hymn/prayer dream is explicitly marked expected relevant for prayer
    queries, and church/icon/prayer dreams are marked expected relevant for religious
    plot queries.
  - False-positive policy requires archive-backed evidence fragments from `quote`,
    `chunk_text`, or `matched_fragments`; weak semantic adjacency without evidence is
    counted as a false positive.
  - Verification: `.venv/bin/python -m pytest tests/unit/test_retrieval_eval.py -q --tb=short`
    -> 3 passed.

---

## WS-18.2: Deterministic Query Expansion Profiles

Owner:      codex
Phase:      18
Type:       retrieval
Priority:   P1
Depends-On: WS-18.1
Status:     Implemented locally — 2026-05-01

Objective:
  Add deterministic domain-aware expansion for common symbolic/thematic search classes before
  calling vector/FTS retrieval.

Acceptance-Criteria:
  - AC-1: Prayer/religion queries expand to a bounded profile including terms such as:
    молитва, песнопение, богослужение, церковь, храм, икона, Христос, Бог, Рождество.
  - AC-2: Expansion is transparent in tests and does not require a live LLM call.
  - AC-3: Existing LLM query expansion remains best-effort but is not the only recall path.
  - AC-4: Unit tests prove "молитва" expands to prayer/hymn/church-related terms.

Files:
  - `app/retrieval/query.py`
  - `tests/unit/test_rag_query_expansion.py`

Context-Refs:
  - `app/retrieval/query.py::retrieve`
  - `app/retrieval/query.py::_expand_query_terms`
  - `docs/MOTIF_ABSTRACTION.md` for motif/thematic vocabulary boundaries

Implementation Notes:
  - Added a deterministic religious/prayer expansion profile in `app/retrieval/query.py`.
  - Profile terms include `молитва`, `песнопение`, `богослужение`, `церковь`, `храм`,
    `икона`, `Христос`, `Бог`, and `Рождество`.
  - Matching queries include prayer, hymnody, church, religious, icon, divine-name, and
    Christmas hymn markers.
  - The deterministic profile is applied before embedding and FTS search; LLM expansion
    remains best-effort and is merged with deterministic terms when available.
  - Verification: `.venv/bin/python -m pytest tests/unit/test_rag_query_expansion.py tests/unit/test_rag_query.py tests/unit/test_retrieval_eval.py -q --tb=short`
    -> 13 passed; `ruff check` and `ruff format --check` passed for the touched retrieval/test files.

---

## WS-18.3: Multi-Query Retrieval in Code, Not Prompt Only

Owner:      codex
Phase:      18
Type:       retrieval + assistant facade
Priority:   P1
Depends-On: WS-18.2
Status:     Implemented locally — 2026-05-02

Objective:
  Make broad motif/theme search issue multiple retrieval probes deterministically and merge by
  `dream_id`, instead of relying on the assistant to call `search_dreams` several times.

Acceptance-Criteria:
  - AC-1: `search_dreams` or a new retrieval method can accept/query-generate multiple probes.
  - AC-2: Results are deduplicated by `dream_id`.
  - AC-3: The highest score and all valid evidence chunks are preserved per dream.
  - AC-4: Religious motif query runs probes equivalent to church/prayer/hymn/icon/divine-name.
  - AC-5: Unit tests cover merge and dedupe behavior.

Files:
  - `app/retrieval/query.py`
  - `app/assistant/facade.py`
  - `app/assistant/tools.py`
  - `tests/unit/test_rag_query.py`
  - `tests/unit/test_assistant_facade.py`

Context-Refs:
  - `app/assistant/facade.py::search_dreams`
  - `app/retrieval/query.py::_search`
  - `app/assistant/prompts.py` search routing rules

Implementation Notes:
  - `RagQueryService.retrieve()` now builds deterministic retrieval probes for broad
    religious motif/theme queries instead of relying on the assistant to issue repeated
    `search_dreams` calls.
  - Religious broad queries run probes equivalent to church/place-of-worship,
    prayer/hymn/Christmas, and icon/divine-name variants.
  - Probe results are merged by `dream_id`; the highest relevance score is retained and
    distinct evidence chunks are joined with `---`.
  - Matched fragments are deduplicated while preserving valid `text`, `match_type`, and
    `char_offset` metadata.
  - Light review: PASS — no blocking findings in retrieval contract, ordering, or merge
    behavior.
  - Verification: `.venv/bin/python -m pytest tests/unit/test_rag_query_expansion.py tests/unit/test_rag_query.py tests/unit/test_retrieval_eval.py tests/unit/test_assistant_facade.py -q --tb=short`
    -> 54 passed; `ruff check` and `ruff format --check` passed for touched retrieval/test files.

---

## WS-18.4: Evidence Verification and Weak-Result Suppression

Owner:      codex
Phase:      18
Type:       retrieval + output contract
Priority:   P0
Depends-On: WS-18.3
Status:     Implemented locally — 2026-05-02

Objective:
  Suppress results that cannot expose a real evidence fragment connected to the query.
  The bot should not show "weak" results when the actual relation is absent.

Acceptance-Criteria:
  - AC-1: Every search result returned to the assistant includes at least one evidence field:
    `quote`, `chunk_text`, or `matched_fragments`.
  - AC-2: Low-score vector neighbors with no query-related evidence are filtered out.
  - AC-3: Tool output distinguishes `strong`, `moderate`, `weak` only after verification.
  - AC-4: If the user asks for extra results and no verified results remain, tool output says
    no more archive-backed matches exist.
  - AC-5: Regression test covers the previous "false weak prayer results" failure mode.

Files:
  - `app/retrieval/query.py`
  - `app/assistant/facade.py`
  - `app/assistant/tools.py`
  - `tests/unit/test_rag_query.py`
  - `tests/unit/test_assistant_chat.py`

Context-Refs:
  - `app/assistant/prompts.py §Search Grounding Rules`
  - `app/assistant/tools.py::execute_tool search_dreams`
  - `app/assistant/facade.py::_extract_quote`

Implementation Notes:
  - `AssistantFacade.search_dreams()` now suppresses weak results (`score < 0.4`) when
    they have no query quote and no matched fragments, preventing low-signal vector-only
    neighbors from reaching the assistant.
  - If filtering removes all candidates, the facade returns an insufficient-evidence reason
    for missing verified archive-backed matches.
  - `execute_tool("search_dreams")` maps that condition to `No more archive-backed matches found.`
  - Search tool output now labels verified results with `strength=strong|moderate|weak`
    after facade verification.
  - Light review: PASS — no blocking findings in exact-search behavior, verified result
    preservation, or no-more-matches messaging.
  - Verification: `.venv/bin/python -m pytest tests/unit/test_rag_query_expansion.py tests/unit/test_rag_query.py tests/unit/test_retrieval_eval.py tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py -q --tb=short`
    -> 114 passed; `ruff check` and `ruff format --check` passed for touched retrieval/facade/tool/test files.

---

## WS-18.5: Grounded Search Response Contract

Owner:      codex
Phase:      18
Type:       assistant tool contract
Priority:   P0
Depends-On: WS-18.4
Status:     Implemented locally — 2026-05-02

Objective:
  Reduce the LLM's opportunity to invent fragments by giving it a stricter, citation-like
  search result payload and response instruction.

Acceptance-Criteria:
  - AC-1: Search tool output includes stable result IDs or dream IDs for every result.
  - AC-2: Tool output uses explicit fields: title, date, strength, evidence_text.
  - AC-3: Assistant prompt says final answers must cite only `evidence_text`.
  - AC-4: Tests assert tool output never contains invented text in the no-result path.
  - AC-5: Existing user-facing Telegram response remains concise and Russian.

Files:
  - `app/assistant/tools.py`
  - `app/assistant/prompts.py`
  - `tests/unit/test_assistant_chat.py`

Context-Refs:
  - `docs/tasks_phase16.md §WS-16.1`
  - `app/assistant/tools.py::execute_tool`
  - `app/assistant/prompts.py §Search Grounding Rules`

Implementation Notes:
  - Search tool output now uses a citation-like payload for each result:
    `result_id`, `date`, `title`, `strength`, and `evidence_text`.
  - `evidence_text` is selected from `quote`, then matched fragment text, then chunk text.
  - `SYSTEM_PROMPT` now defines `evidence_text` as the citation boundary and instructs final
    answers to cite only `evidence_text` from search tool results.
  - No-result and no-more-matches paths contain no invented dream text.
  - Light review: PASS — no blocking findings; stale prompt wording around exact-search
    `quote` was updated to `evidence_text`.
  - Verification: `.venv/bin/python -m pytest tests/unit/test_rag_query_expansion.py tests/unit/test_rag_query.py tests/unit/test_retrieval_eval.py tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py -q --tb=short`
    -> 115 passed; `ruff check` and `ruff format --check` passed for touched retrieval/facade/tool/prompt/test files.

---

## WS-18.6: Retrieval Eval Run and Phase Gate

Owner:      codex
Phase:      18
Type:       eval + docs
Priority:   P0
Depends-On: WS-18.1, WS-18.2, WS-18.3, WS-18.4, WS-18.5
Status:     Implemented locally — 2026-05-02

Objective:
  Run and record the Phase 18 retrieval eval before closing the phase.

Acceptance-Criteria:
  - AC-1: Phase 18 eval row is added to `docs/retrieval_eval.md`.
  - AC-2: Metrics include recall on prayer/religious queries and false-positive count.
  - AC-3: False-positive count for fabricated/non-evidence fragments is 0.
  - AC-4: If live corpus is unavailable, document the limitation and run the synthetic/unit
    regression suite instead.

Files:
  - `docs/retrieval_eval.md`
  - `docs/CODEX_PROMPT.md`
  - `docs/IMPLEMENTATION_JOURNAL.md`
  - `scripts/eval_phase18_real.py`
  - `tests/unit/test_eval_phase18_real.py`

Implementation Notes:
  - Added `docs/retrieval_eval.md §Phase 18 Evaluation Run` and an `Evaluation History`
    row for WS-18.6.
  - Ran `scripts/eval.py --task-id WS-18.6` against disposable PostgreSQL database
    `dream_motif_eval`; synthetic retrieval metrics are hit@3=1.00, MRR=1.00, and
    no-answer accuracy=1.00.
  - Recorded the unit regression suite as additional Phase 18 gate evidence:
    124 passed after the WS-18.6 eval script/doc/test update.
  - Added read-only real archive eval script `scripts/eval_phase18_real.py`. It never runs
    migrations or resets schema; with the local placeholder OpenAI key, `--mode auto` used
    the FTS-only fallback and confirmed all 6 Phase 18 prayer/religion queries returned
    archive-backed evidence fragments.
  - Live hybrid embedding recall remains deferred until a real `OPENAI_API_KEY` is configured;
    `.venv/bin/python scripts/eval_phase18_real.py --mode live --limit 5` was attempted on
    2026-05-02 and reached providers, but failed with Anthropic 401 and OpenAI embedding
    401 Unauthorized.
  - False-positive count for fabricated/non-evidence fragments is recorded as 0 in unit
    regression coverage.
  - Light review: PASS — limitation is explicit and eval source/date are present.
  - Verification: `.venv/bin/python -m pytest tests/unit/test_eval_phase18_real.py tests/unit/test_eval_script.py tests/unit/test_retrieval_eval.py tests/unit/test_rag_query_expansion.py tests/unit/test_rag_query.py tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py -q --tb=short`
    -> 124 passed; `ruff check` passed for touched retrieval/facade/tool/prompt/eval/test files.

## 4. Phase Gate

- [x] Prayer query finds prayer-like hymn/text even without the literal word "молитва" in deterministic expansion/unit coverage; synthetic retrieval eval passes.
- [x] Religious motif query runs church/icon/hymn/divine-name retrieval probes in deterministic unit coverage; synthetic retrieval eval passes.
- [x] No result is shown without archive-backed evidence text.
- [x] Very weak/no-evidence matches are suppressed.
- [x] Phase 18 retrieval eval recorded with local environment limitation.
- [ ] Before Phase 19 starts, rerun `scripts/eval_phase18_real.py --mode live --limit 5`
  on a machine with valid `ANTHROPIC_API_KEY` and `OPENAI_API_KEY`, then record the result.

## 5. Not In Scope

- Direct title search; see Phase 19.
- Dream recording flow; see Phase 17.
- External mythological/cultural research; this phase is only archive retrieval.
