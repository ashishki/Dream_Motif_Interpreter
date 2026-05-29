# Dream Motif Interpreter - Compact Session State

Version: 2.0
Date: 2026-05-29
Status: active-creative-experiment

Full historical prompt archived at
`docs/archive/portfolio-cleanup-2026-05-29/CODEX_PROMPT_full_2026-05-29.md`.

## Current State

- Phase 25 is closed after backdated Google Doc writes and duplicate rewrites.
- WS-26.1 is complete: `docs/DREAM_MEMORY_MAP.md` defines the Dream Memory Map
  product spec for Telegram mini app screens, non-diagnostic framing, and the
  bot/mini-app split.
- Active direction: Dream Memory Map with Obsidian-inspired structure and
  visualization.
- Potential product surface: Telegram mini app after graph schema and privacy
  controls are clear.
- Latest planned task graph: `docs/tasks_phase26.md`.
- Do not treat Obsidian as a dependency; use it as structure/visual reference.

## Active Inputs

- `README.md`
- `docs/PROJECT_PLAN.md`
- `docs/PHASE_PLAN.md`
- `docs/PRODUCT_OVERVIEW.md`
- `docs/tasks_phase26.md`
- `docs/archive/portfolio-cleanup-2026-05-29/CODEX_PROMPT_full_2026-05-29.md`

## Next Task

`WS-26.2`: Graph Schema For Dreams And Motifs.

## Latest Verification

- `python -m pytest tests/ -q --tb=short` blocked locally because `python` is
  not on PATH.
- `.venv/bin/python -m pytest tests/unit/test_dream_memory_map_spec.py
  tests/unit/test_eval_script.py tests/integration/test_retrieval_eval.py -q
  --tb=short` passes (`5 passed, 2 skipped`; integration eval tests skip
  without `TEST_DATABASE_URL`).
- `.venv/bin/python -m pytest tests/ -q --tb=short` no longer fails at
  retrieval-eval collection; the broad suite is locally blocked by Postgres
  connectivity. Fail-fast probe:
  `timeout 120s .venv/bin/python -m pytest tests/ -q --tb=short -x` errors in
  `tests/integration/test_analysis.py::test_analysis_saves_draft_themes` with
  asyncpg `TimeoutError` while connecting during schema reset.
- `.venv/bin/ruff check app/ tests/` passes.
- `.venv/bin/ruff format --check app/ tests/` passes.

## Rules

- Preserve privacy, export, and deletion controls.
- Keep dream/motif graph claims interpretive, not diagnostic.
- Use visual memory-map direction only after schema boundaries are clear.
- Keep canonical findings, evals, and decisions in this repo before syncing to
  the cognition vault.
