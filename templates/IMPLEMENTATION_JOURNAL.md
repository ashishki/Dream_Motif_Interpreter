# Implementation Journal — {{PROJECT_NAME}}

Version: 1.0
Last updated: {{DATE}}
Status: append-only

<!--
Purpose:
- durable task and session continuity across agents and sessions
- records what changed, why, what evidence was collected, and what remains open

This file is not the source of truth for architecture or policy.
Use it as a retrieval surface and handoff log.
-->

---

## Journal Entry Template

```markdown
### {{DATE}} — {{SESSION_OR_TASK_ID}} — {{SHORT_TITLE}}

- Scope: {{files / directories / task IDs}}
- Why this work happened: {{reason or trigger}}
- Decisions applied: {{Decision Log / ADR refs or "none"}}
- Evidence collected: {{tests / evals / review reports / manual checks}}
- Follow-ups: {{next task, open risk, or "none"}}
- Notes for next agent: {{only the context worth carrying forward}}
```

---

## Entries

### {{DATE}} — T01 — Bootstrap

- Scope: `docs/`, `.github/workflows/ci.yml`
- Why this work happened: Phase 1 initialization
- Decisions applied: `D-001`
- Evidence collected: `docs/audit/PHASE1_AUDIT.md` once available
- Follow-ups: next planned task
- Notes for next agent: keep entries brief and point to canonical docs where possible
