# Task Schema — {{PROJECT_NAME}}

<!--
This file documents the task block format used in docs/tasks.md.
Every task must conform to this schema. PHASE1_VALIDATOR Part A3 checks for structural
completeness; Part C checks for vague acceptance criteria.

The YAML-compatible block format below makes tasks machine-readable without a full YAML parser:
the Orchestrator can extract field values by matching "Key: value" lines within task fences.

Task tags describe capability ownership, not the entire solution shape. A project may be primarily deterministic or workflow-oriented while carrying a small number of capability-tagged tasks. Use `Type: none` when the task belongs to deterministic or ordinary application logic.
-->

---

## Schema Definition

Each task is a fenced block with the following required fields:

```
## T{{NN}}: {{Task Title}}

Owner:      codex
Phase:      {{phase number}}
Type:       {{type tag(s) — see Tag Namespace below; "none" if no capability tag}}
Depends-On: {{T-NN, T-NN | none}}

Objective: |
  {{One paragraph. What the system must do after this task, not how to implement it.
  Start with an action verb. e.g., "Implement the audit log service that records..."}}

Acceptance-Criteria:
  - id: AC-1
    description: "{{Specific, testable. A reviewer must be able to verify by running tests + reading code.}}"
    test: "{{tests/path/test_file.py::test_function_name}}"
  - id: AC-2
    description: "{{...}}"
    test: "{{...}}"

Files:
  - {{path/to/file.py}}         # created or modified
  - {{tests/test_file.py}}      # test file (required)

Context-Refs:
  - {{optional pointer to prior decision / finding / evidence}}
  - {{e.g., docs/DECISION_LOG.md#D-003}}

Notes: |
  {{Optional. Constraints, gotchas, interface contracts from Depends-On tasks.
  Leave blank or omit if nothing notable.}}
```

`Context-Refs` is optional for simple isolated work.
Use it when a task depends on prior decisions, resolves an open finding, changes a risky boundary,
or needs specific evidence from an earlier phase. Prefer a short, scoped list over broad reading.

### Optional heavy-task extension

Use these fields only when the task needs a selective proof-first path. Do not add them to every task.

```
Execution-Mode: heavy
Evidence:
  - {{artifact or check expected from this task}}
  - {{artifact or check expected from this task}}
Verifier-Focus: |
  {{What a fresh verifier must specifically confirm}}
```

Recommended uses:

- security-critical changes
- migrations or destructive state changes
- retrieval semantics changes
- unsafe tool behavior
- refactors where local tests are not enough evidence

For normal tasks, omit these fields.

---

## Tag Namespace

| Tag | Meaning | Profile |
|-----|---------|---------|
| `none` | No capability tag — standard task | — |
| `rag:ingestion` | Builds or modifies the ingestion pipeline | RAG |
| `rag:query` | Builds or modifies query-time retrieval | RAG |
| `tool:schema` | Defines or modifies a tool schema | Tool-Use |
| `tool:unsafe` | Implements unsafe-action controls | Tool-Use |
| `tool:call` | Adds or modifies a tool call site | Tool-Use |
| `agent:loop` | Implements the agent decision loop | Agentic |
| `agent:handoff` | Implements an agent handoff | Agentic |
| `agent:termination` | Implements loop termination contract | Agentic |
| `plan:schema` | Defines or modifies the plan schema | Planning |
| `plan:validation` | Implements plan validation gate | Planning |
| `compliance:control` | Implements a compliance control (auth, encryption, retention) | Compliance |
| `compliance:audit` | Implements audit log infrastructure | Compliance |
| `compliance:evidence` | Collects or updates compliance evidence artifact | Compliance |

Multiple tags are space-separated: `Type: compliance:control compliance:audit`

---

## Acceptance Criteria Rules

A criterion is acceptable if a review agent can verify it by running the tests and reading the code **without asking the implementer**. Apply these rules:

| ✓ Acceptable | ✗ Not acceptable |
|-------------|-----------------|
| `GET /health returns HTTP 200 with body {"status": "ok"}` | "The health endpoint works correctly" |
| `DELETE on audit_log table raises PermissionDenied` | "Audit log is tamper-evident" |
| `pytest tests/test_retention.py::test_ttl_boundary passes` | "Retention policy is implemented" |
| `hit@3 ≥ 0.80 on the 10-query evaluation set` | "Retrieval quality is acceptable" |

Forbidden phrases (automatic BLOCKER in PHASE1_VALIDATOR Part C):
- "works correctly", "handles properly", "is implemented", "functions as expected",
  "behaves as expected", "properly handles", "should work", "is complete"

---

## Worked Example

```
## T06: PHI Field Classification and Enforcement

Owner:      codex
Phase:      1
Type:       compliance:control
Depends-On: T04

Objective: |
  Implement field-level PHI classification enforcement: ensure patient_id, full_name,
  date_of_birth, diagnosis_code, and appointment_notes are never written to log
  messages, span attributes, or metrics labels. Add a PII-scrubbing log formatter
  and a span attribute allowlist enforced at the tracing module boundary.

Acceptance-Criteria:
  - id: AC-1
    description: "Log output for any request containing PHI fields contains no literal PHI values — only hashed identifiers (SHA-256). Verified by tests/test_phi_enforcement.py::test_phi_not_in_logs."
    test: "tests/test_phi_enforcement.py::test_phi_not_in_logs"
  - id: AC-2
    description: "OpenTelemetry span attributes for PHI-touching operations contain no PHI field names or values. Verified by tests/test_phi_enforcement.py::test_phi_not_in_spans."
    test: "tests/test_phi_enforcement.py::test_phi_not_in_spans"
  - id: AC-3
    description: "docs/compliance_eval.md PHI enforcement control row is updated with status=Implemented, evidence=tests/test_phi_enforcement.py, date=today."
    test: "tests/test_compliance_eval.py::test_phi_control_evidence_current"

Files:
  - app/logging/phi_scrubber.py      # created
  - app/tracing/span_allowlist.py    # created
  - tests/test_phi_enforcement.py    # created
  - tests/test_compliance_eval.py    # created or modified
  - docs/compliance_eval.md          # updated

Notes: |
  PHI field list is defined in ARCHITECTURE.md §Data Classification. Do not hardcode
  field names — load from a config constant (app/config/phi_fields.py) so the list
  is maintained in one place. The log formatter wraps the standard logging.Formatter;
  the tracing module integration point is app/tracing/__init__.py::get_tracer().
```
