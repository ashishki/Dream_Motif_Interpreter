# Phase 18 Boundary Review — Search Quality and Hallucination Suppression

Date: 2026-05-02
Scope: WS-18.1 through WS-18.6
Reviewer: local Codex boundary review

## Result

Stop-Ship: No

Findings:

| ID | Severity | Finding | Status |
|----|----------|---------|--------|
| PH18-1 | P3 | Live hybrid embedding recall for the Phase 18 prayer/religion dataset was attempted but blocked by provider authorization. The real archive was checked read-only through FTS-only fallback. | Open follow-up |

## Review Notes

- Deterministic religious/prayer query expansion is covered by unit tests and does not require a live LLM call.
- Broad religious queries now fan out into deterministic church/place-of-worship, prayer/hymn/Christmas, and icon/divine-name probes.
- Probe results are deduplicated by `dream_id`; highest relevance score and distinct evidence chunks are preserved.
- Weak vector-only results without quote or matched fragments are filtered before assistant tool output.
- Search tool output now exposes `result_id`, `date`, `title`, `strength`, and `evidence_text`; the prompt identifies `evidence_text` as the citation boundary.
- Phase 18 eval history records the unit regression suite, the synthetic `scripts/eval.py` run against disposable DB `dream_motif_eval`, and a read-only real archive eval through `scripts/eval_phase18_real.py`.
- The read-only real archive eval does not run migrations, reset schema, or write rows; in local `--mode auto`, it selected FTS-only fallback because the configured OpenAI key is a placeholder.

## Evidence

- `.venv/bin/python -m pytest tests/unit/test_eval_phase18_real.py tests/unit/test_eval_script.py tests/unit/test_retrieval_eval.py tests/unit/test_rag_query_expansion.py tests/unit/test_rag_query.py tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py -q --tb=short` -> 124 passed
- `TEST_DATABASE_URL=postgresql+asyncpg://postgres@localhost:5433/dream_motif_eval OPENAI_API_KEY=test-key EVAL_DATE=2026-05-02 .venv/bin/python scripts/eval.py --task-id WS-18.6` -> hit@3=1.00, MRR=1.00, no-answer accuracy=1.00
- `.venv/bin/python scripts/eval_phase18_real.py --limit 5` -> 6/6 Phase 18 prayer/religion queries returned archive-backed evidence in read-only FTS-only mode
- `.venv/bin/python scripts/eval_phase18_real.py --mode live --limit 5` -> attempted live hybrid path, blocked by Anthropic 401 and OpenAI embedding 401 Unauthorized
- `.venv/bin/python -m ruff check scripts/eval_phase18_real.py scripts/eval.py app/retrieval/query.py app/assistant/facade.py app/assistant/tools.py app/assistant/prompts.py tests/unit/test_eval_phase18_real.py tests/unit/test_eval_script.py tests/unit/test_rag_query.py tests/unit/test_rag_query_expansion.py tests/unit/test_assistant_facade.py tests/unit/test_assistant_chat.py tests/unit/test_retrieval_eval.py` -> clean

## Phase Gate

PASS locally for synthetic and read-only archive evidence. Phase 19 must not start until `scripts/eval_phase18_real.py --mode live --limit 5` is rerun on a machine with valid provider keys and the result is recorded. Remaining P3 follow-up: configure valid provider keys and rerun live hybrid archive eval before treating live hybrid embedding recall as formally verified.
