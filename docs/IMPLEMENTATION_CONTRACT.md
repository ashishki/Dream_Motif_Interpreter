# Implementation Contract — Dream Motif Interpreter

Status: **IMMUTABLE** — changes to this document require an Architectural Decision Record filed in `docs/adr/`.
Version: 1.0
Effective date: 2026-04-10

Any agent (Codex or review) may cite this document as the authority on implementation rules. Any finding that this contract was violated is automatically P1.

---

## Universal Rules

These rules apply to every project using the AI Workflow Playbook. They are not negotiable and are not changed without an ADR.

### SQL Safety

- All SQL is parameterized. Use `text()` with named parameters: `text("SELECT ... WHERE id = :id")` with `{"id": value}`.
- Never interpolate variables into SQL strings. This includes f-strings, `%` formatting, and `+` concatenation.
- Never use string concatenation to build any part of a query, including table names, column names, or `ORDER BY` clauses.
- Violation: automatic P1.

### Multi-Tenant Systems

_This is a single-tenant system. This section does not apply._

### Async Redis

- Redis is accessed only in `async def` functions.
- Use `redis.asyncio`, not the synchronous `redis` client.
- Never call synchronous Redis methods from async code paths.
- Violation: automatic P1.

### Authorization

- Every new route handler enforces authentication before accessing any data.
- Routes that are intentionally public (`GET /health`, `GET /auth/callback`) must be explicitly documented in the route handler with a comment citing the design decision.
- Violation: automatic P1.

### PII Policy

- No sensitive personal data in log messages, span attributes, metrics labels, or error messages returned to clients.
- Fields classified as sensitive personal data in this project: `dream_text`, `raw_text`, `chunk_text`, `dream_title`, `theme_notes`, `fragment_text`, `justification` (when it contains dream content).
- Where dream entries must appear in observability, use `dream_id` (UUID) only.
- Violation: automatic P1.

### Credentials and Secrets

- No credentials, API keys, tokens, passwords, or secrets in source code.
- No credentials in comments.
- No credentials in test fixtures (use test-key or equivalent placeholder strings in tests; real values come from environment variables).
- All secrets come from environment variables. Required env vars documented in `docs/ARCHITECTURE.md §Runtime Contract`.
- `.env` files are in `.gitignore` and are never committed.
- Violation: automatic P1 (and a security incident).

### Shared Tracing Module

- One shared tracing module: `app/shared/tracing.py` with a single `get_tracer()` function.
- All code that creates spans imports from this module.
- No inline noop span implementations in individual files.
- No copy-pasted tracer initialization in individual modules.
- Violation: P2 (accumulates; becomes P1 at age cap).

### CI Gate

- CI must pass before any PR is merged.
- A PR with failing CI is never merged, regardless of deadline pressure.
- If CI is flaky, the flakiness is fixed before the PR is merged — not bypassed.
- Violation: automatic P1.

### Observability

**OBS-1 — Instrumentation.** Every external call (database, Redis, HTTP, LLM inference, embedding API) must be wrapped in a span with `trace_id` and `operation_name`. Use `app/shared/tracing.py::get_tracer()`. Inline noop spans or copy-pasted tracer initializations are forbidden. Violation: P2 (escalates to P1 at age cap).

**OBS-2 — Metrics.** For each external call type, emit a success/error counter and a latency histogram. For RAG paths: `insufficient_evidence` rate as a labeled counter; `retrieval_ms` and `generation_ms` as separate spans. Violation for missing RAG metrics: P2.

**OBS-3 — Health endpoint.** `GET /health` returns `{"status": "ok", "index_last_updated": "<ISO8601>"}` (HTTP 200) when healthy, HTTP 503 when the index is stale beyond `MAX_INDEX_AGE_HOURS`. This endpoint must not log PII, must not count toward rate limits, and must not require authentication. Violation: P1.

---

## Project-Specific Rules

_The following rules are tailored to Dream Motif Interpreter based on its stack and constraints._

### Dream Content Isolation

Dream content (`raw_text`, `chunk_text`, `fragment_text`) must never appear in:
- Log messages at any level
- OpenTelemetry span attributes
- HTTP error response bodies
- Redis keys or values (Redis stores only job IDs, statuses, and session tokens)

References in observability must use `dream_id` (UUID) only. A dream's text is accessed only through the database via parameterized queries.

Violation: automatic P1.

### LLM Output Framing

Any system response that includes LLM-generated interpretation, theme assignment, or pattern analysis must include an explicit framing: outputs are suggestions or interpretations, not authoritative conclusions. API responses must include either an `"interpretation_note"` field or the framing must be enforced at the API response schema level (Pydantic model with a literal field).

Violation: P2.

### Annotation Versioning

Every mutation to a `DreamTheme` or `ThemeCategory` record must write an `AnnotationVersion` snapshot **before** the mutation is committed. This includes: confirm, reject, update, rollback, and any bulk operation. The `annotation_versions` table is append-only: no DELETE or UPDATE queries against it are permitted anywhere in the codebase.

Violation: automatic P1.

### Taxonomy Mutation Gate

Theme categories may not be promoted (`suggested` → `active`), renamed, merged, or deprecated through any automated code path that does not pass through an explicit human approval check. Background workers and LLM outputs must not call taxonomy mutation methods directly; they may only suggest (create `suggested` records). Actual promotion requires an explicit API call from an authenticated session.

Violation: automatic P1.

### Idempotent Workers

All background workers (ingestion, indexing) must be idempotent. Re-queuing the same job with the same input must not produce duplicate records. Use content hashes for dream entries and (dream_id, chunk_index) composite keys for chunks.

Violation: P1.

### Ingestion/Query Separation

Ingestion pipeline code (`app/retrieval/ingestion.py`) and query-time retrieval code (`app/retrieval/query.py`) must not import from each other. A function that mixes ingestion logic (chunk, embed, upsert) with query-time logic (retrieve, rerank, assemble) is a P2 finding.

This rule is enforced by tests: `tests/unit/test_rag_ingestion.py::test_ingestion_does_not_import_query_module` and `tests/unit/test_rag_query.py::test_query_does_not_import_ingestion_module`.

Violation: P2.

---

## Control Surface and Runtime Boundaries

| Boundary | Rule |
|----------|------|
| Secrets scope | All secrets via environment variables only. No secrets in source, migrations, fixtures, or Redis. |
| Network egress | Allowed: Google Docs API, Anthropic API, OpenAI Embeddings API. All other egress denied by default in production. |
| Privileged actions | Theme category promotion, rename, merge, delete — all require authenticated API call. No automated path for these. |
| Runtime mutation | No shell mutation at runtime. Package installation is build-time only. Workers execute job handlers only. |
| Persistence | DreamEntry, DreamTheme, ThemeCategory, AnnotationVersion, DreamChunk — all in PostgreSQL. Redis: job queue and session tokens only. |
| Auditability | All taxonomy mutations logged via AnnotationVersion. All API calls logged with trace_id (no dream content in logs). |

### Runtime Tier Guardrails

- T1 runtime. No shell mutation, no ad-hoc package installs, no privileged runtime management.
- Any expansion toward T2/T3 behavior requires an ADR before implementation.

---

## Profile Rules: RAG

_Applies because `docs/ARCHITECTURE.md` declares RAG Status = ON._

### Corpus Isolation

- Single-user system. No cross-user corpus isolation needed.
- If multi-user is ever added (requires ADR), corpus isolation must be enforced at the retrieval layer (namespace or metadata filter on `dream_chunks`), not only at the application layer.

### insufficient_evidence Path

- Every query-time handler must implement the `insufficient_evidence` path.
- When retrieved evidence does not meet the relevance threshold (default 0.35), the system must return `InsufficientEvidence` — not a hallucinated answer.
- This path must have at least one explicit test in the integration test suite.
- Omitting this path is an automatic P1.

### Index Schema Versioning

- The index schema (embedding model, chunking strategy, vector dimensions, metadata fields) is versioned as v1.
- Changing any schema parameter requires an ADR. After the ADR is filed, the full corpus must be re-indexed before the new schema goes to production.
- A partial index (some chunks using old schema, some using new) is forbidden.

### Max Index Age

- The maximum allowed age for indexed documents is 24 hours.
- The health endpoint must expose `index_last_updated`. A stale index beyond 24h produces HTTP 503.
- Violation: P2 (escalates to P1 if index age exceeds 48 hours).

### Retrieval-Generation Separation

- `app/retrieval/ingestion.py` and `app/retrieval/query.py` are separate modules with no cross-imports.
- Violation: P2.

### RAG P2 Age Cap Override

For retrieval-critical findings (`insufficient_evidence` path, schema drift), the P2 Age Cap is **1 cycle** (not 3).

### Retrieval Evaluation Gate

A retrieval-related task (tagged `Type: rag:ingestion` or `Type: rag:query`) is **not complete** unless:

1. `docs/retrieval_eval.md` is updated with current retrieval metrics.
2. Current metrics are compared to the baseline row.
3. Any regressions are documented in §Regression Notes with a justification.
4. `docs/retrieval_eval.md §Answer Quality Metrics` is updated (Phase 2+).
5. Evaluation History row records the corpus version.

Submitting `IMPLEMENTATION_RESULT: DONE` without fulfilling these conditions is a P1 finding.

### Retrieval Regression Policy

A regression in hit@3, MRR, citation precision, or no-answer accuracy vs. baseline is a **P1 finding** unless documented in `docs/retrieval_eval.md §Regression Notes` with a trade-off justification and accepted by the human reviewer before the phase gate passes.

---

## Continuity and Retrieval Rules

- Canonical authority: `docs/ARCHITECTURE.md`, `docs/IMPLEMENTATION_CONTRACT.md`, `docs/tasks.md`, `docs/tasks_phase6.md`, `docs/CODEX_PROMPT.md`, ADRs, review reports, eval artifacts, code, tests.
- `docs/DECISION_LOG.md`, `docs/IMPLEMENTATION_JOURNAL.md`, and `docs/EVIDENCE_INDEX.md` are retrieval aids. They summarize and point; they do not overrule canonical files.
- A task with `Context-Refs` must read those references before implementation begins.

Violation: P2. Repeated violation becomes P1 at age cap.

---

## Mandatory Pre-Task Protocol

Every Codex agent must execute these steps before writing any implementation code. No exceptions.

1. Read `docs/IMPLEMENTATION_CONTRACT.md` (this file) from top to bottom.
2. Read the full active task in `docs/tasks_phase6.md` for Phase 6+ work, or in `docs/tasks.md` for historical/backend follow-up work, including all acceptance criteria, the Depends-On list, and the Notes section.
3. Read all Depends-On tasks to understand the interface contracts your implementation must satisfy.
4. Read the task's `Context-Refs` and relevant entries in continuity artifacts when the task depends on prior decisions, proof, or findings.
5. Run `pytest -q`. Record: `{N} passing, {M} failed`. If M > 0, stop and report.
6. Run `ruff check`. Must exit 0. If not, create a separate commit with ruff fixes, then restart the protocol.
7. Confirm that every acceptance criterion will have a corresponding test before implementation is complete.

Skipping any step in this protocol is a P1 finding in the next review cycle.

---

## Forbidden Actions

| Forbidden Action | Reason |
|-----------------|--------|
| String interpolation in SQL | SQL injection; parameterized queries are unconditional |
| Writing dream content to log messages, span attributes, or error responses | Sensitive personal data isolation; PII policy violation |
| Promoting, merging, or deleting theme categories via automated code paths | Taxonomy mutation gate; requires explicit human approval |
| DELETE or UPDATE on `annotation_versions` table | Append-only; mutation destroys the audit trail |
| Cross-import between `app/retrieval/ingestion.py` and `app/retrieval/query.py` | Ingestion/query separation is a retrieval architecture rule |
| Skipping the pre-task baseline capture | Cannot verify implementation did not break existing tests |
| Self-closing a review finding without showing the code change | Findings are verified by reading code, not by assertion |
| Modifying this document without an ADR | The contract is immutable by design |
| Deferring CI setup past Phase 1 | Every commit must be CI-verified |
| Merging a PR with failing CI | The CI gate is non-negotiable |
| Committing credentials or secrets of any kind | Irreversible exposure |
| Expanding runtime tier or privilege surface without updating ARCHITECTURE.md / ADRs | Runtime escalation is a governance change |
| Treating retrieval convenience docs as authority over canonical docs | Retrieval surfaces are convenience, not source of truth |
| Leaving commented-out code in a commit | Dead code degrades readability |
| Adding a TODO without a task reference | Orphaned TODOs accumulate and are never addressed |

---

## Quality Process Rules

### P2 Age Cap

Any P2 finding open for more than 3 consecutive review cycles must be: Closed, Escalated to P1, or Formally deferred to v2 (with ADR). RAG-critical P2 findings: age cap is **1 cycle**.

### Commit Granularity

One logical change per commit. "Misc fixes" is not a commit message.

### Sandbox Isolation

Tests do not share state. Each integration test that touches the database uses a transaction rolled back at test end, or a fresh database per test run.

### Evaluation Validity

An evaluation artifact entry in `docs/retrieval_eval.md` is **invalid** if `Eval Source` or `Date` is absent. An invalid entry is treated as a missing evaluation.

### Review Cycle Integrity

Review agents close findings only after verifying the fix in code (file:line exists, test exists that would fail without the fix).

---

## Governing Documents

| Document | Path | Role |
|----------|------|------|
| Architecture | `docs/ARCHITECTURE.md` | System design authority |
| Specification | `docs/spec.md` | Feature authority |
| Task graph | `docs/tasks.md`, `docs/tasks_phase6.md` | Historical backend authority + active Phase 6+ implementation authority |
| Session handoff | `docs/CODEX_PROMPT.md` | State authority |
| This document | `docs/IMPLEMENTATION_CONTRACT.md` | Rule authority |
| Review reports | `docs/audit/CYCLE{N}_REVIEW.md` | Finding authority |
| ADRs | `docs/adr/ADR{NNN}.md` | Decision authority |
| Retrieval eval | `docs/retrieval_eval.md` | Retrieval quality authority |

Precedence: IMPLEMENTATION_CONTRACT > ADRs > ARCHITECTURE > spec > tasks > CODEX_PROMPT
