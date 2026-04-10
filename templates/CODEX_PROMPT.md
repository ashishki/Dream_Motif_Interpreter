# CODEX_PROMPT.md

Version: 1.0
Date: {{DATE}}
Phase: 1

<!--
This file is the single source of truth for session state.
Every Codex agent reads this file before starting work.
Every Codex agent updates this file before committing at a phase boundary.
The orchestrator reads this file at the start of every session.

Never delete history from this file. Append; do not replace.
-->

---

## Current State

- **Phase:** 1
- **Baseline:** 0 passing tests (pre-implementation)
- **Ruff:** not yet configured
- **Last CI run:** not yet configured
- **Last updated:** {{DATE}}
- **Session tokens (approx):** not yet tracked
- **Cumulative phase tokens (approx):** not yet tracked

---

## Continuity Pointers

- **Decision log:** `docs/DECISION_LOG.md`
- **Implementation journal:** `docs/IMPLEMENTATION_JOURNAL.md`
- **Evidence index:** `docs/EVIDENCE_INDEX.md` (if present)
- **Task-scoped context:** read `Context-Refs` in `docs/tasks.md` before broad searching

---

## Next Task

**T01: Project Skeleton**

Read T01 in `docs/tasks.md` for the full specification, acceptance criteria, and file list.

---

## Fix Queue

empty

<!--
The Fix Queue contains items that must be addressed before the next phase gate,
but that were deferred from the current task. Format:

- FQ-01: [T-NN] Description of what must be fixed. Added: YYYY-MM-DD.
- FQ-02: [T-NN] Description. Added: YYYY-MM-DD.
-->

---

## Open Findings

none

<!--
Open findings from review cycles. Format:

### P1 Findings (block next phase gate)
- P1-01: [CYCLE-N] Finding description. File: path/to/file.py, line N. Must be resolved before Phase {N+1}.

### P2 Findings (must resolve within 3 cycles)
- P2-01: [CYCLE-N] Finding description. File: path/to/file.py. Opened: YYYY-MM-DD. Age: 0 cycles.

### P3 Findings (optional)
- P3-01: [CYCLE-N] Finding description.

P2 Age Cap: any P2 open for more than 3 review cycles must be resolved, escalated to P1,
or formally deferred to v2 (with ADR) before the next phase gate.
-->

---

## Profile State: RAG

<!--
Include this section only when RAG Status = ON in the ## Capability Profiles table
in docs/ARCHITECTURE.md. If RAG Status = OFF, set the first field accordingly and
leave all others as "n/a".
Updated by the orchestrator at every phase boundary where retrieval-related work occurred.

Retrieval-related next tasks: tasks that happen to involve retrieval (scheduled work).
Retrieval-driven tasks: tasks created as a direct result of open retrieval findings
  (from docs/retrieval_eval.md §Open Retrieval Findings). These exist because retrieval
  quality is insufficient, not because of a feature requirement.
-->

- RAG Status: OFF
- Active corpora: n/a
- Retrieval baseline: n/a
- Open retrieval findings: none
- Index schema version: n/a
- Pending reindex actions: none
- Retrieval-related next tasks: none
- Retrieval-driven tasks: none

---

## Tool-Use State

<!--
This section is ALWAYS present — do not omit it.
If Tool-Use Profile = OFF, keep the block with Tool-Use Profile: OFF and all other fields as n/a.
If Tool-Use Profile = ON, fill in the fields below.
Updated by the orchestrator at every phase boundary where tool-related work occurred.

Task tag that updates this block: Type: tool:schema | tool:call | tool:unsafe
-->

- Tool-Use Profile: OFF
- Registered tool schemas: n/a
- Unsafe-action guardrails: n/a
- Open tool findings: none

---

## Agentic State

<!--
This section is ALWAYS present — do not omit it.
If Agentic Profile = OFF, keep the block with Agentic Profile: OFF and all other fields as n/a.
If Agentic Profile = ON, fill in the fields below.
Updated by the orchestrator at every phase boundary where agent loop work occurred.

Task tags that update this block: Type: agent:loop | agent:handoff | agent:termination
Note: Agentic and Tool-Use are independent profiles. If the system uses tools within
an agent loop, both profiles may be ON and both state blocks must be maintained.
-->

- Agentic Profile: OFF
- Active agent roles: n/a
- Loop termination contract version: n/a
- Cross-iteration state mechanism: n/a
- Open agent findings: none

---

## Planning State

<!--
This section is ALWAYS present — do not omit it.
If Planning Profile = OFF, keep the block with Planning Profile: OFF and all other fields as n/a.
If Planning Profile = ON, fill in the fields below.
Updated by the orchestrator at every phase boundary where plan structure work occurred.

Planning Profile = ON means the application produces structured plans (task graphs,
step-by-step procedures, decision trees) as its primary deliverable. This is not the
same as the ORCHESTRATOR, which controls the development workflow.

Task tags that update this block: Type: plan:schema | plan:validation
-->

- Planning Profile: OFF
- Plan schema version: n/a
- Plan validation method: n/a
- Open plan findings: none

---

## Compliance State

<!--
This section is ALWAYS present — do not omit it.
If Compliance Status = OFF, keep the block with Compliance Status: OFF and all other fields as n/a.
If Compliance Status = ON, fill in the fields below.
Updated by the orchestrator at every phase boundary where compliance-tagged work occurred.

Task tags that update this block: Type: compliance:control | compliance:audit | compliance:evidence
-->

- Compliance Status: OFF
- Active frameworks: n/a
- Controls implemented: n/a
- Controls partial: n/a
- Controls not started: n/a
- Evidence artifact: n/a
- Open compliance findings: none

---

## NFR Baseline

<!--
Include this section when docs/nfr.md exists in the project.
Populated after Phase 1 load tests. Leave values as "not yet measured" until tests run.
Updated by the orchestrator at any phase boundary where load tests produced new measurements.
A regression (measured value exceeds target by >10%) is a P2 finding.
-->

- API p99 latency: not yet measured
- Error rate: not yet measured
- Throughput: not yet measured
- Last measured: —
- NFR regression open: No

---

## Evaluation State

<!--
Tracks evaluation results for all active Capability Profiles.
Updated by the Orchestrator in Step 3.5 after every capability-affecting task.
A task with a capability trigger tag is NOT complete until this section is updated.

Trigger tags: rag:ingestion, rag:query | tool:schema, tool:unsafe, tool:call |
              agent:loop, agent:handoff, agent:termination | plan:schema, plan:validation

The evaluation artifact (e.g. docs/retrieval_eval.md) holds the full detail.
This section holds the summary used by the Orchestrator for decision-making.
-->

### Last Evaluation

- Profile: n/a
- Task: n/a
- Date: n/a
- Eval Source: n/a
- Metric(s): n/a
- Score: n/a
- Baseline: n/a
- Delta: n/a
- Regression: n/a

<!--
Eval Source is REQUIRED. An evaluation entry without Eval Source is invalid.
Acceptable values:
  - "scripts/eval.py against §Evaluation Dataset (10 queries), run YYYY-MM-DD"
  - "manual spot-check: retrieved docs inspected for Q01–Q05, run YYYY-MM-DD"
  - "pytest tests/test_retrieval_eval.py::test_hit_at_3, run YYYY-MM-DD"
"Ran evaluation" or "updated metrics" without specifics is NOT acceptable.
-->

### Open Evaluation Issues

none

<!--
Format:
- EV-01: [PROFILE] [T-NN] Description. Opened: YYYY-MM-DD. Must resolve before phase gate.
-->

### Evaluation History

| Date | Task | Profile | Key metric | Score | Baseline | Delta | Regression? |
|------|------|---------|------------|-------|----------|-------|-------------|

---

## Completed Tasks

none

<!--
Append completed tasks here. Format:

- T01: Project Skeleton — completed YYYY-MM-DD. Baseline after: N tests.
- T02: CI Setup — completed YYYY-MM-DD. Baseline after: N tests.
-->

---

## Phase History

<!--
Append phase summaries here at each phase gate. Format:

### Phase 1 — {Phase Name}
Closed: YYYY-MM-DD
Baseline at gate: N passing tests
Tasks: T01, T02, T03
Review cycle: CYCLE-1 (see docs/audit/CYCLE1_REVIEW.md)
P1s resolved: N
P2s open: N
Gate approved by: {human name or "auto"}
-->

---

## Compaction Protocol

<!--
Governs CODEX_PROMPT.md size management for long-running projects.
The Orchestrator evaluates compaction triggers at the start of each session (Step 0).
Compaction is performed directly by the Orchestrator — no new files, no deletions.
-->

### Compaction triggers

Compact when EITHER condition is true:
- `## Completed Tasks` contains more than 20 entries, OR
- `## Phase History` contains more than 5 phase summaries

### How to compact

1. Create or update a `## Summary State` section immediately after `## Current State`:
   - Current phase and next task
   - Active capability profiles and their status
   - Open findings by severity: P1: N, P2: N
   - Current test baseline
   - Last evaluation result (if any profile is active)
   - This section must be self-sufficient: the Orchestrator must be able to resume from it alone.

2. In `## Completed Tasks`: retain the 5 most recent entries. Move all older entries to `## Archived Tasks` (create the section at the end of the file if it does not exist).

3. In `## Phase History`: retain the 2 most recent phase summaries. Move older summaries to `## Archived Phase History` (create at the end of the file if absent).

4. Rules:
   - Do NOT delete any content — only move older entries to Archive sections.
   - Archive sections are kept in this file; they are not required reading for normal operation.
   - After compaction, `## Summary State` must fit within ~50 lines.

---

## Instructions for Codex

Read these instructions every time you pick up a task. Do not skip steps.

### Pre-Task Protocol (mandatory — do not skip)

1. **Read `docs/IMPLEMENTATION_CONTRACT.md`** — before anything else. Know the rules before touching code.
2. **Read the full task in `docs/tasks.md`** — including all acceptance criteria, file lists, and notes.
3. **Read all Depends-On tasks** — understand the interface contracts your task must satisfy.
4. **Read task `Context-Refs` and continuity artifacts as needed** — required when the task resolves a finding, changes a risky boundary, or depends on prior decisions / evidence.
5. **Run `pytest -q`** — capture the current baseline. Record: `N passing, M failed`. If M > 0, stop and report: you cannot add failures to an already-failing baseline.
6. **Run `ruff check`** — must exit 0. If not, fix ruff issues first. Commit the ruff fix separately with message `chore(lint): resolve ruff issues`. Then re-run the pre-task protocol.
7. **Write tests before or alongside implementation.** Every acceptance criterion has exactly one corresponding test (or more, never zero).

### During Implementation

- Work on one task at a time.
- Read only the files you need. Use `grep` to find relevant sections first.
- Do not modify files outside the task's scope without documenting why.
- If you discover an interface mismatch or missing dependency, stop and report it. Do not silently patch adjacent tasks.
- If you supersede a prior decision or close a repeated finding, update `docs/DECISION_LOG.md`, `docs/IMPLEMENTATION_JOURNAL.md`, and `docs/EVIDENCE_INDEX.md` as applicable.

### Post-Task Protocol

1. Run `pytest -q` — baseline must be ≥ pre-task baseline. If lower, something broke; fix it before committing.
2. Run `ruff check app/ tests/` — must exit 0.
3. Run `ruff format --check app/ tests/` — must exit 0.
4. **If this task has a capability tag** (`rag:*`, `tool:*`, `agent:*`, `plan:*`) — evaluation is required before marking DONE:
   - Update the relevant evaluation artifact (e.g. `docs/retrieval_eval.md`) with current results.
   - Compare against baseline. Document any regression in §Regression Notes.
   - Update `docs/CODEX_PROMPT.md §Evaluation State §Last Evaluation` with the result summary.
   - Do NOT return `IMPLEMENTATION_RESULT: DONE` until this is complete. The Orchestrator will verify it.
5. Update this file (`docs/CODEX_PROMPT.md`):
   - New baseline (number of passing tests)
   - Move this task to "Completed Tasks"
   - Set "Next Task" to the next task
   - Add any new open findings discovered during this task
6. Commit with format: `type(scope): description` — one logical change per commit.
7. If the task produced multiple logical changes (migration + service + tests), use multiple commits.

### Return Format

When done, return exactly:

```
IMPLEMENTATION_RESULT: DONE
New baseline: {N} passing tests
Commits: {list of commit hashes and messages}
Notes: {anything the orchestrator should know — surprises, deviations, decisions made}
```

When blocked, return exactly:

```
IMPLEMENTATION_RESULT: BLOCKED
Blocker: {exact description of what is blocking progress}
Type: dependency | interface_mismatch | environment | ambiguity
Recommended action: {what the orchestrator or human should do}
Progress made: {what was completed before hitting the blocker}
```

### Commit Message Format

```
type(scope): short description (imperative mood, ≤72 chars)

Optional body: explain why, not what. The diff shows the what.
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`, `security`

Do not include:
- `Co-Authored-By` lines
- Credentials or secrets
- TODO comments without a task reference (`# TODO: see T{NN}`)
- Commented-out code
- `print()` debugging statements
