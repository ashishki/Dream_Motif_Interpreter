# Evidence Index — {{PROJECT_NAME}}

Version: 1.0
Last updated: {{DATE}}

<!--
Purpose:
- index durable proof so agents can retrieve prior evidence quickly
- helps avoid re-running archaeology across tests, evals, review reports, and manual checks

This file is not authoritative by itself.
Every row must point to an actual artifact that is the real evidence.
-->

---

## When To Use

Create and maintain this file when the project has any of:
- heavy-task entries
- active evaluation artifacts
- compliance evidence requirements
- repeated review findings across phases

Lean projects may omit this file until one of the above becomes true.

---

## Evidence Table

| Topic / Finding / Task | Artifact type | Location | Scope covered | Last verified | Canonical? |
|------------------------|---------------|----------|---------------|---------------|------------|
| {{T-NN or topic}} | test | `tests/...::test_name` | {{what this proves}} | {{DATE}} | Yes |
| {{T-NN or topic}} | review | `docs/audit/...` | {{finding or boundary}} | {{DATE}} | Yes |
| {{T-NN or topic}} | eval | `docs/..._eval.md` | {{metric or scenario}} | {{DATE}} | Yes |
| {{T-NN or topic}} | journal note | `docs/IMPLEMENTATION_JOURNAL.md` | {{handoff context}} | {{DATE}} | No |

---

## Retrieval Rules

- Prefer rows that match the current task's `Context-Refs`, open findings, or active profile tags.
- If an evidence row points to a stale or missing artifact, fix the artifact or remove the row.
- Do not treat a journal note as proof when a test, eval, or review report exists.
