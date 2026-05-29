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
- WS-26.2 is complete: `app/models/dream_graph.py` defines the reviewable
  code-native graph schema contract for Dream, Motif, Person, Place, Emotion,
  Event nodes and evidence-linked graph edges. No database migration was added.
- WS-26.3 is complete: `docs/mockups/dream_memory_map_prototype.html` provides
  a static browser-openable mini app mockup for the graph workspace and motif
  detail flow. No frontend stack, backend route, database table, or Obsidian
  dependency was added.
- WS-26.4 is complete: `app/models/dream_graph_privacy.py` defines the
  code-native privacy/export contract for deterministic graph export, normal
  graph filtering, hide/delete controls, and rejected AI-suggestion controls
  that preserve source dream fragment references.
- Phase 26 review is complete and archived at `docs/archive/PHASE26_REVIEW.md`.
- Active direction: Dream Memory Map with Obsidian-inspired structure and
  visualization.
- Potential product surface: Telegram mini app after graph schema and privacy
  controls are clear.
- Latest completed task graph: `docs/tasks_phase26.md`.
- Do not treat Obsidian as a dependency; use it as structure/visual reference.

## Active Inputs

- `README.md`
- `docs/PROJECT_PLAN.md`
- `docs/PHASE_PLAN.md`
- `docs/PRODUCT_OVERVIEW.md`
- `docs/tasks_phase26.md`
- `docs/archive/portfolio-cleanup-2026-05-29/CODEX_PROMPT_full_2026-05-29.md`

## Next Task

Plan the next phase for durable Dream Memory Map delivery: persistence,
authenticated Telegram mini app surface, production graph UI, and export/delete
routes.

## Latest Verification

- `python -m pytest tests/ -q --tb=short` blocked locally because `python` is
  not on PATH.
- `.venv/bin/python -m pytest tests/unit/test_dream_memory_map_spec.py -q
  --tb=short` passes (`3 passed`).
- `.venv/bin/python -m pytest tests/unit/test_dream_memory_map_spec.py
  tests/unit/test_dream_graph_schema.py -q --tb=short` passes (`10 passed`).
- `.venv/bin/python -m pytest tests/unit/test_dream_memory_map_spec.py
  tests/unit/test_dream_graph_schema.py
  tests/unit/test_dream_memory_map_prototype.py -q --tb=short` passes
  (`13 passed`).
- `.venv/bin/python -m pytest tests/unit/test_dream_memory_map_spec.py
  tests/unit/test_dream_graph_schema.py tests/unit/test_dream_graph_privacy.py
  tests/unit/test_dream_memory_map_prototype.py -q --tb=short` passes
  (`22 passed`).
- `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest tests/ -q
  --tb=short` passes (`567 passed, 9 skipped, 1 warning`) with local
  Postgres/pgvector on `127.0.0.1:5433` and Redis on `127.0.0.1:6379`.
- `.venv/bin/ruff check app/ tests/` passes.
- `.venv/bin/ruff format --check app/ tests/` passes.

## Rules

- Preserve privacy, export, and deletion controls.
- Keep dream/motif graph claims interpretive, not diagnostic.
- Use visual memory-map direction only after schema boundaries are clear.
- Keep canonical findings, evals, and decisions in this repo before syncing to
  the cognition vault.
