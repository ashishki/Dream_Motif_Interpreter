# Dream Motif Interpreter — Local AI Development Orchestrator

Status: mandatory local workflow
Last updated: 2026-05-01

This file is the project-local orchestrator protocol. It is stricter than a reminder:
if a step is skipped, the task is not complete.

## 0. Role Ownership

The workflow has explicit owners. Do not merge roles unless the user explicitly says so.

| Role | Owner | Responsibility | Must not do |
|------|-------|----------------|-------------|
| Human/Product Owner | User | Sets product priorities, accepts scope, resolves ambiguity, approves release risk | Does not write task implementation details during an agent run |
| Orchestrator | AI workflow controller | Reads state, chooses next task, writes the implementation prompt, dispatches Codex, runs review loop, updates phase state | Does not write application code directly |
| Implementation Agent | Codex | Implements exactly one assigned task or fix, writes tests, runs checks, returns structured result | Does not choose new scope, skip tests, skip docs, or silently modify unrelated files |
| Light Reviewer | Separate review pass | Reviews every completed task for contract/security/runtime violations | Does not refactor, implement, or broaden findings into style opinions |
| Deep Review Agents | META, ARCH, CODE, CONSOLIDATED passes | Run at phase boundary, security-critical changes, or explicit force-deep-review | Do not run in parallel; each pass depends on prior output |
| Doc Updater | Post-review doc pass | Updates project docs after phase completion or when implementation changes documented behavior | Does not rewrite docs unrelated to the completed change |

## 1. Prompt Construction Is Mandatory

The orchestrator must write the implementation prompt as a separate file first.
Do not inline a long prompt directly in a shell command.

Required pattern:

```bash
cat > /tmp/orchestrator_codex_prompt.txt <<'PROMPT'
[full implementation prompt here]
PROMPT

export CURRENT_TASK="[WS-17.1]"  # replace with actual task id
PROMPT=$(cat /tmp/orchestrator_codex_prompt.txt)
codex exec -s workspace-write "$PROMPT"
```

Rules:

- The prompt file is the reviewable dispatch artifact.
- The `PROMPT` shell variable is the only value passed to `codex exec`.
- The prompt must include: task id, objective, acceptance criteria, file scope,
  context refs, required tests, required docs, and return format.
- The prompt must not contain `Co-authored-by` instructions.
- If the task is a fix from review, paste the exact finding text into the prompt.

## 2. Pre-Task Gate

Before dispatching Codex, the orchestrator must verify:

1. `docs/CODEX_PROMPT.md` current state and next task.
2. Active task graph, currently `docs/tasks_phase17.md` unless `CODEX_PROMPT.md` says otherwise.
3. `docs/IMPLEMENTATION_CONTRACT.md`.
4. Task `Depends-On` entries.
5. Task `Context-Refs`.
6. Current branch and dirty worktree status.

If the active task graph in `CODEX_PROMPT.md` and the task file disagree, stop and fix docs
before implementation.

## 3. Implementation Prompt Required Contents

Every implementation prompt must contain this checklist verbatim:

```text
Protocol:
1. Read docs/IMPLEMENTATION_CONTRACT.md before editing.
2. Read the full assigned task and all Context-Refs.
3. Run the relevant baseline tests before changes and record results.
4. Implement only the assigned scope.
5. Add or update tests for every acceptance criterion.
6. Run pytest for the affected tests, then the broad suite when practical.
7. Run ruff check app/ tests/.
8. Run ruff format --check app/ tests/.
9. Update docs when behavior, phase state, task state, runbook, user guide, eval artifact, or decision state changed.
10. Return IMPLEMENTATION_RESULT: DONE or BLOCKED with files changed, tests run, and residual risks.
```

For retrieval/RAG work, also include:

```text
Update docs/retrieval_eval.md and CODEX_PROMPT.md evaluation state before DONE.
```

## 4. Review Gate

No implementation task is complete without review.

### Light Review

Run after every implementation task, including small fixes.

Light reviewer checks only:

- SQL safety and parameterization.
- PII/logging/span/metric leakage.
- secrets and credentials.
- auth on new routes.
- async correctness.
- runtime-tier drift.
- Implementation Contract violations.
- task acceptance criteria have tests or an explicit documented exception.
- `ruff check` and `ruff format --check` were run or an environment blocker is documented.
- required docs were updated when behavior changed.

Light review result must be one of:

```text
LIGHT_REVIEW_RESULT: PASS
```

or:

```text
LIGHT_REVIEW_RESULT: ISSUES_FOUND
ISSUE_COUNT: N
```

If issues are found, the orchestrator sends a focused fixer prompt through the same
prompt-file-and-`PROMPT`-variable pattern, then re-runs light review.

### Deep Review

Run at every phase boundary and for security-critical changes. Also run when the task changes
retrieval semantics, tool safety, runtime tier, or architecture boundaries.

Deep review order is strict:

1. META.
2. ARCH.
3. CODE.
4. CONSOLIDATED.

Do not parallelize deep review. Do not archive a phase until deep review is complete.

## 5. Documentation Gate

Documentation updates are not optional.

Codex must update docs during the task when:

- user-visible behavior changes;
- task state changes;
- a phase starts or completes;
- a decision is created, superseded, or deferred;
- a retrieval eval changes;
- a runbook or user guide becomes stale;
- a new model, table, worker, service, endpoint, or tool is added.

Minimum expected docs:

- `docs/CODEX_PROMPT.md` for current state, next task, baseline, open findings.
- active `docs/tasks_phase*.md` task graph for task/phase state.
- `docs/IMPLEMENTATION_JOURNAL.md` for durable handoff after phase/task groups.
- `docs/DECISION_LOG.md` for decisions and deferrals.
- `docs/retrieval_eval.md` for RAG/retrieval work.
- runbooks/user guide when Telegram/user behavior changes.

At phase boundary, the Doc Updater must run after deep review and before phase report.

## 6. Quality Checks

Required checks before `IMPLEMENTATION_RESULT: DONE`:

```bash
python -m pytest tests/ -q --tb=short
ruff check app/ tests/
ruff format --check app/ tests/
```

Allowed exception:

- If the full suite is too slow or blocked by local services, run targeted tests and document
  the exact blocker. `ruff check` and `ruff format --check` still remain required unless the
  tool is missing from the environment.

Failure policy:

- Any failing test introduced by the task blocks DONE.
- Any ruff error blocks DONE.
- Any format check failure blocks DONE.
- Environment blockers must return `IMPLEMENTATION_RESULT: BLOCKED`, not DONE.

## 7. Post-Task State Update

After implementation and review pass:

1. Update task state in the active task graph.
2. Update `docs/CODEX_PROMPT.md` next task and baseline.
3. Add implementation journal entry if the task changes durable behavior or closes a phase.
4. Add decision log entry if a new technical/product decision was made.
5. Commit one logical change at a time.

Commit messages must not include `Co-authored-by`.

## 8. Completion Format

Implementation agent must return:

```text
IMPLEMENTATION_RESULT: DONE
Files changed: [...]
Tests run: [...]
Ruff: check PASS | format check PASS
Docs updated: [...]
Review: pending
Notes: [...]
```

After review passes, orchestrator reports:

```text
TASK_RESULT: COMPLETE
Task: [...]
Commit: [...]
Tests: [...]
Ruff: [...]
Review: LIGHT PASS | DEEP PASS
Docs: [...]
Next: [...]
```

Blocked format:

```text
IMPLEMENTATION_RESULT: BLOCKED
Blocker: [...]
Type: dependency | interface_mismatch | environment | ambiguity
Recommended action: [...]
Progress made: [...]
```
