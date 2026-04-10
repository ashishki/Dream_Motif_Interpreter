# Decision Log — {{PROJECT_NAME}}

Version: 1.0
Last updated: {{DATE}}

<!--
Purpose:
- lightweight retrieval surface for important decisions
- points to canonical sources such as ARCHITECTURE.md, ADRs, tasks.md, review reports

This file is not the source of truth. If an entry conflicts with a canonical document,
the canonical document wins and this file must be corrected.
-->

---

## Rules

- Keep entries short and link to the authoritative document or section.
- Record why a decision was made and what it replaced.
- Update this file when architecture, runtime, governance, or major implementation direction changes.
- Mark superseded decisions explicitly instead of deleting them.

---

## Decision Index

| ID | Date | Status | Decision | Why it matters | Canonical source | Supersedes |
|----|------|--------|----------|----------------|------------------|------------|
| D-001 | {{DATE}} | Active | {{Initial solution shape / stack / boundary decision}} | {{What future agents need to remember}} | `docs/ARCHITECTURE.md#...` | none |
| D-002 | {{DATE}} | Active | {{Constraint or policy choice}} | {{Why this changes implementation or review}} | `docs/IMPLEMENTATION_CONTRACT.md#...` | none |

---

## Retrieval Notes

- Read this file before revisiting architecture, changing runtime tier, resolving repeated findings, or overriding a prior tradeoff.
- If a task has `Context-Refs`, prefer those entries over scanning this file top-to-bottom.
