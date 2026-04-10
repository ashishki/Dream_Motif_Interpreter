# Architecture — {{PROJECT_NAME}}

Version: 1.0
Last updated: {{DATE}}
Status: Draft

---

## System Overview

{{PROJECT_NAME}} is {{ONE_PARAGRAPH_DESCRIPTION}}. It serves {{PRIMARY_USER_TYPES}} and is designed to {{PRIMARY_GOAL}}. The system {{KEY_ARCHITECTURAL_CHARACTERISTIC, e.g., "is stateless at the application layer with all persistent state in PostgreSQL and Redis"}}.

---

## Solution Shape

| Decision | Selection | Justification |
|----------|-----------|---------------|
| Primary shape | {{Deterministic subsystem \| Workflow orchestration \| Bounded ReAct/tool-using agent \| Higher-autonomy agent \| Hybrid}} | {{Why this is the minimum sufficient shape}} |
| Governance level | {{Lean \| Standard \| Strict}} | {{Why this control intensity is proportionate}} |
| Runtime tier | {{T0 \| T1 \| T2 \| T3}} | {{Why this tier is justified and lower tiers are insufficient}} |

### Rejected Lower-Complexity Options

| Rejected option | Why it is insufficient |
|-----------------|------------------------|
| Deterministic-only | {{Why not deterministic everywhere}} |
| Workflow or human-in-the-loop assistant | {{Why a simpler bounded flow is insufficient}} |
| Simple tool use without planning / loops | {{Why this simpler pattern is insufficient}} |

### Minimum Viable Control Surface

List the smallest set of controls that still matches system risk. Keep this short.

- {{CONTROL_1}}
- {{CONTROL_2}}

### Human Approval Boundaries

| Boundary | Human approval required? | Why |
|----------|--------------------------|-----|
| {{e.g., destructive external action}} | {{yes / no}} | {{rationale}} |
| {{e.g., production deployment}} | {{yes / no}} | {{rationale}} |

### Deterministic vs LLM-Owned Subproblems

| Subproblem | Owner | Reason |
|------------|-------|--------|
| Validation / permissions / policy checks | {{Deterministic \| LLM}} | {{Why}} |
| Transformations / calculations / thresholds | {{Deterministic \| LLM}} | {{Why}} |
| Retries / idempotency / audit triggers | {{Deterministic \| LLM}} | {{Why}} |
| {{OPTIONAL_SUBPROBLEM}} | {{Deterministic \| LLM}} | {{Why}} |

### Runtime and Isolation Model

For T0/T1 projects, keep this section concise. For T2/T3 projects, fill every row explicitly.

| Property | Decision |
|----------|----------|
| Isolation boundary | {{managed boundary \| container boundary \| ephemeral isolated runtime \| persistent privileged worker}} |
| Persistence model | {{stateless \| DB-backed \| persistent worker state \| snapshot-backed \| N/A}} |
| Network model | {{required egress, denied egress, service-to-service expectations \| N/A}} |
| Secrets model | {{where secrets live and what each runtime may access \| N/A}} |
| Runtime mutation boundary | {{whether shell/package/toolchain/service mutation is allowed and by whom}} |
| Rollback / recovery model | {{how runtime or state is restored after failure}} |

State explicitly why a lower runtime tier is insufficient if selecting T2 or T3.

#### T3 Reference Implementation: Hermes Agent

<!--
Include this sub-section only when Runtime tier = T3 AND Solution shape = Higher-autonomy agent.
Delete if T0, T1, or T2, or if the T3 runtime is not Hermes-based.
-->

When T3 is selected with a higher-autonomy agent shape, Hermes Agent (NousResearch) is a validated candidate runtime. It provides:

- Persistent server-resident execution with SQLite-backed session history
- Messaging gateway (Telegram, Slack, Discord, and 12+ other platforms) for push notifications and human-in-the-loop interactions
- Cron scheduling with file-lock isolation and configurable delivery targets
- Subagent delegation (depth-2, summary-passing, restricted child toolsets)
- Six execution backends: local, Docker, SSH, Modal, Daytona, Singularity

**Required configuration for playbook compatibility:**

| Rule | Setting | Rationale |
|------|---------|-----------|
| Cron job memory isolation | `skip_memory=True` on all scheduled jobs | Prevents cross-session state contamination |
| Community skills | Disabled or pinned to reviewed versions | Community registry is an unaudited third-party surface |
| Plugin system | In-house only; reviewed as application code | Plugins run in-process with no sandboxing |
| Docker network | `--network none` by default | Egress must be declared and justified in §Network model |
| Credential scope | Scoped per-workload via env allowlist | Subagents must not inherit parent's full credential set |
| Learning loop | Evaluated in `docs/agent_eval.md` before production activation | Autonomous skill creation without review gate is a P1 |

See `docs/IMPLEMENTATION_CONTRACT.md §Conditional Rules for T2 / T3 §Hermes Agent` for the full governance rules and P1/P2 violation thresholds.

---

## Inference / Model Strategy

Include this section only if the system uses LLM inference in production behavior. Omit it for fully deterministic systems.

| Path / Task | Model class | Why this class | Fallback / escalation | Budget / latency constraint |
|-------------|-------------|----------------|-----------------------|-----------------------------|
| {{e.g., routing / classification}} | {{small / fast / reasoning / multimodal / long-context}} | {{Why this is the minimum sufficient choice}} | {{fallback or stronger-model trigger}} | {{e.g., "< $X / 1k calls", "p95 < 800ms"}} |
| {{e.g., extraction / generation / planning}} | {{...}} | {{...}} | {{...}} | {{...}} |

Rules:
- choose models per workload, not one global default unless justified
- record deterministic alternatives considered
- justify stronger models by quality, latency, context, or capability needs
- keep price-source notes in project docs or NFR history with date if cost is an explicit constraint

---

## Capability Profiles

<!--
REQUIRED: Declare which capability profiles are active. This is a Phase 1 architectural decision.
Each profile defaults to OFF. Decide once in Phase 1; changing status requires an ADR.
Capability profiles are separate from the primary solution shape and runtime tier above.
See PLAYBOOK.md §2c for decision criteria and the 9-property profile invariant.
-->

| Profile    | Status        | Evaluation Artifact         | Justification |
|------------|---------------|-----------------------------|---------------|
| RAG        | {{ON \| OFF}} | `docs/retrieval_eval.md`   | {{one paragraph — why retrieval is or is not needed}} |
| Tool-Use   | {{ON \| OFF}} | `docs/tool_eval.md`        | {{one paragraph — why LLM-directed tool calls are or are not needed}} |
| Agentic    | {{ON \| OFF}} | `docs/agent_eval.md`       | {{one paragraph — why a multi-step decision loop is or is not needed}} |
| Planning   | {{ON \| OFF}} | `docs/plan_eval.md`        | {{one paragraph — why structured plan output is or is not needed}} |
| Compliance | {{ON \| OFF}} | `docs/compliance_eval.md` | {{one paragraph — whether a named regulatory framework applies (HIPAA, SOC 2, PCI-DSS, GDPR) and whether compliance evidence collection is a launch gate}} |

<!--
For each profile with Status = ON, fill in its sub-sections below.
For each profile with Status = OFF, delete its sub-sections.

Compatibility notes:
- Agentic ⊄ Tool-Use: an agentic system may call tools, but Tool-Use profile governs the
  tool-specific design contracts (side effects, idempotency, unsafe-action gates). If the
  system has both an agent loop and LLM-directed tool calls, both profiles must be ON.
- Retrieval semantics are owned by RAG: if an agentic system performs retrieval, RAG profile
  (not Agentic) governs ingestion, indexing, corpus isolation, and insufficient_evidence.
- The Orchestrator dispatches deep review on task type tags — keep tags in tasks.md accurate:
  rag:ingestion, rag:query, tool:schema, tool:unsafe, agent:loop, agent:handoff, plan:schema,
  compliance:control, compliance:audit, compliance:evidence.
-->

### Profile: RAG

<!--
Include this sub-section only when RAG Status = ON in the Capability Profiles table above.
If RAG Status = OFF, delete from here through the end of this profile.
-->

#### RAG Architecture

**Ingestion pipeline** (offline / scheduled):
```
extract → normalize → chunk → embed → index
```

| Stage | Description | Technology |
|-------|-------------|------------|
| Extract | {{Where documents come from and how they're fetched}} | {{e.g., S3 sync, API poll, webhook}} |
| Normalize | {{Format normalization — PDF to text, markdown cleaning, etc.}} | {{e.g., pdfplumber, markdownify}} |
| Chunk | {{Chunking strategy — fixed size, semantic, by section}} | {{e.g., LangChain text splitter, custom}} |
| Embed | {{Embedding model and rationale}} | {{e.g., OpenAI text-embedding-3-small}} |
| Index | {{Vector store and index schema version}} | {{e.g., pgvector, Qdrant, Pinecone}} |

**Query-time pipeline** (online / per-request):
```
query analyze → retrieve → rerank/filter → assemble evidence → answer | insufficient_evidence
```

| Stage | Description | Technology |
|-------|-------------|------------|
| Query analyze | {{Query reformulation, intent detection, or HyDE if applicable}} | {{e.g., LLM rewrite, none}} |
| Retrieve | {{Similarity search — top-K, threshold, hybrid if applicable}} | {{e.g., pgvector cosine, BM25 hybrid}} |
| Rerank/filter | {{Reranking model or filter rules}} | {{e.g., cross-encoder, none}} |
| Assemble evidence | {{How retrieved chunks are formatted into context}} | {{e.g., XML-tagged blocks, numbered references}} |
| Answer / insufficient_evidence | {{Decision rule for when to answer vs. return insufficient_evidence}} | {{e.g., confidence threshold, minimum chunk count}} |

The `insufficient_evidence` path is **not optional**. When retrieved evidence does not support an answer, the system must return `insufficient_evidence` rather than fabricating a response.

#### Corpus Description

| Property | Value |
|----------|-------|
| Source documents | {{What documents are indexed}} |
| Update frequency | {{How often the corpus changes}} |
| Estimated size | {{Number of documents / chunks / tokens at index time}} |
| Access control | {{Who/what can query which corpus segments}} |

#### Index Strategy

- **Embedding model:** {{Model name and version}} — rationale: {{why this model}}
- **Chunking:** {{Strategy and chunk size}} — rationale: {{why this chunking approach}}
- **Index schema version:** v1 — changes require ADR; re-indexing required on schema change
- **Max index age:** {{e.g., "24 hours"}} — staleness beyond this threshold must trigger an alert

#### Risks (RAG-specific)

| Risk | Mitigation |
|------|------------|
| Hallucination on weak evidence | Confidence threshold at retrieval; `insufficient_evidence` path required |
| Schema drift (embedding model / chunk format change) | Version index schema; ADR required before model change; full re-index on change |
| Stale index | Max age policy ({{MAX_AGE}}); staleness check on health endpoint |
| Corpus isolation failure | {{Corpus-level ACL strategy — e.g., namespace per tenant, filter at retrieval layer}} |
| Retrieval latency regression | Latency acceptance criteria per RAG task; tracked in baseline |

### Profile: Tool-Use

<!--
Include this sub-section only when Tool-Use Status = ON. Delete if OFF.
-->

#### Tool Catalog

| Tool | Function signature | Side effects | Idempotency | Permission required | Retry policy |
|------|--------------------|-------------|-------------|---------------------|--------------|
| {{TOOL_1}} | `{{signature}}` | {{read / write / destructive}} | {{yes / no}} | {{permission}} | {{strategy}} |

#### Unsafe-Action Policy

_Destructive or irreversible tool calls (delete, send, charge, publish):_

| Tool | Why unsafe | Confirmation mechanism | Rollback path |
|------|-----------|----------------------|---------------|
| {{TOOL_N}} | {{reason}} | {{confirmation step}} | {{rollback or "none — irreversible, require explicit approval"}} |

#### Risks (Tool-Use-specific)

| Risk | Mitigation |
|------|------------|
| Side effect on partial failure | Idempotency keys; retry only idempotent calls |
| Unsafe action without confirmation | Mandatory confirmation step before destructive calls |
| Tool schema drift | Schema versioning; generation-time validation test per schema version |
| Permission escalation via tool chaining | Permission check at each tool boundary, not only at the entry point |

---

### Profile: Agentic

<!--
Include this sub-section only when Agentic Status = ON. Delete if OFF.
-->

#### Agent Roles

| Role | Authority scope | Inputs | Outputs | Termination conditions |
|------|----------------|--------|---------|----------------------|
| {{ROLE_1}} | {{what it may decide and act on}} | {{inputs}} | {{outputs}} | {{how it terminates}} |

#### Loop Termination Contract

- **Maximum iterations:** {{N}}
- **Normal termination:** {{condition — e.g., goal achieved, all tasks complete}}
- **Forced termination:** {{trigger — e.g., timeout, max steps reached, human interrupt}}
- **Non-termination behavior:** {{fallback or error — e.g., return partial result, raise alert}}

#### Agent Handoff Protocol

_How state transfers between agent roles or across loop iterations:_

{{Describe the mechanism — shared state file, message payload, direct structured return, etc.
Specify what the receiving role must validate before proceeding.}}

#### Risks (Agentic-specific)

| Risk | Mitigation |
|------|------------|
| Infinite loop | Hard iteration cap in termination contract; enforced, not advisory |
| Authority boundary violation | Permission check at each role boundary; not delegatable |
| State corruption across iterations | Explicit state schema; validated before each iteration |
| Handoff failure | Handoff integrity test required per agentic task |

---

### Profile: Planning

<!--
Include this sub-section only when Planning Status = ON. Delete if OFF.
-->

#### Plan Schema

_A valid plan produced by this system has the following structure:_

```json
{
  "schema_version": "{{VERSION}}",
  "goal": "string",
  "steps": [
    {
      "id": "string",
      "action": "string",
      "depends_on": ["step_id"],
      "approval_required": false,
      "{{ADDITIONAL_FIELDS}}": "..."
    }
  ]
}
```

Schema version is immutable once published. Changes require an ADR.

#### Plan Validation

- **Validation mechanism:** {{how plans are validated at generation time — e.g., JSON Schema, Pydantic model}}
- **Invalid plan behavior:** {{reject with error / request replan / escalate to human}}
- **Replan trigger conditions:** {{when replanning is allowed — e.g., context hash mismatch, step failure}}

#### Plan-to-Execution Contract

_How a generated plan is consumed downstream:_

{{Describe the interface — API endpoint, file handoff, human review gate, execution engine. Specify
what the consumer must validate before executing any step.}}

#### Risks (Planning-specific)

| Risk | Mitigation |
|------|------------|
| Invalid plan accepted without validation | Schema validation gate before plan leaves the system |
| Stale plan on changed context | Context hash in plan; replan trigger on mismatch |
| Unapproved high-risk step executed | Approval gates declared in schema; enforced at execution |
| Plan schema drift between producer and consumer | Schema versioning; consumers reject unknown versions |

### Profile: Compliance

<!--
Include this sub-section only when Compliance Status = ON in the Capability Profiles table above.
If Compliance Status = OFF, delete from here through the end of this profile.
-->

#### Applicable Frameworks

| Framework | Applicable controls scope | Evidence owner | Attestation deadline |
|-----------|--------------------------|----------------|---------------------|
| {{FRAMEWORK_1}} | {{e.g., "SOC 2 Type II — CC6, CC7, CC8"}} | {{e.g., "Security team"}} | {{DATE or "ongoing / annual"}} |

#### Data Classification

| Field | Classification | Storage control | Transmission control | Retention |
|-------|---------------|-----------------|---------------------|-----------|
| {{FIELD_1}} | {{PHI / PII / PAN / Internal}} | {{e.g., "encrypted at rest (AES-256)"}} | {{e.g., "TLS 1.2+ only; never external"}} | {{e.g., "6 years (HIPAA)"}} |

<!--
At minimum: list every field that is regulated by the declared framework(s).
PHI: Protected Health Information (HIPAA)
PII: Personally Identifiable Information (GDPR, CCPA)
PAN: Primary Account Number / payment card data (PCI-DSS)
-->

#### Audit Log Requirements

- **Required events:** {{list — e.g., "authentication (success/failure), authorization decision, data read (PHI fields), data write, data deletion, admin actions"}}
- **Retention period:** {{e.g., "6 years (HIPAA minimum)"}}
- **Tamper-evidence mechanism:** {{e.g., "append-only PostgreSQL table with DELETE privilege revoked; verified by COMP-3 review check"}}
- **Log format:** `{timestamp, actor_id, action, resource_type, resource_id, result, trace_id}`

#### Risks (Compliance-specific)

| Risk | Mitigation |
|------|------------|
| Regulated field leaked in logs or spans | Data classification table; PII-scrubbing in log formatter; COMP-1 review check at every phase boundary |
| Audit log gap on partial transaction failure | Transactional audit write (same DB transaction as the event) or saga with compensating log entry |
| Evidence not collected before attestation deadline | `docs/compliance_eval.md` lifecycle tied to compliance-tagged task completion gate; COMP-4 check |
| Control implementation drifting from documentation | COMP-4 enforces artifact currency; COMP-5 enforces code-level enforcement of documented policies |
| Retention policy never enforced | Retention boundary test required for each regulated field; COMP-5 check |

---

## Component Table

| Component | File / Directory | Responsibility |
|-----------|-----------------|----------------|
| {{COMPONENT_1}} | `{{PATH_1}}` | {{RESPONSIBILITY_1}} |
| {{COMPONENT_2}} | `{{PATH_2}}` | {{RESPONSIBILITY_2}} |
| {{COMPONENT_3}} | `{{PATH_3}}` | {{RESPONSIBILITY_3}} |
| {{COMPONENT_4}} | `{{PATH_4}}` | {{RESPONSIBILITY_4}} |

<!--
Add a row for every significant component: API layer, service layer, data access layer,
background workers, middleware, shared utilities (tracing, auth), database models/schemas.
-->

---

## Data Flow — Primary Request Path

The following steps describe the end-to-end path for a {{PRIMARY_REQUEST_TYPE, e.g., "standard authenticated API request"}}:

1. Client sends `{{HTTP_METHOD}} {{PATH}}` with {{AUTH_MECHANISM, e.g., "Bearer token in Authorization header"}}.
2. {{MIDDLEWARE_OR_GATEWAY}} validates {{WHAT_IS_VALIDATED}}.
3. {{AUTH_COMPONENT}} verifies {{AUTH_VERIFICATION_DETAIL}}.
4. Request reaches `{{HANDLER_FILE}}`. The handler extracts validated params and delegates to `{{SERVICE}}`.
5. `{{SERVICE}}` {{WHAT_SERVICE_DOES}}.
6. {{DATA_ACCESS_DETAIL, e.g., "SQLAlchemy executes a parameterized query against PostgreSQL"}}.
7. Response is constructed and returned as `{{RESPONSE_SHAPE}}`.

<!--
Write one flow for the primary use case (happy path).
Add additional flows below for background jobs, webhooks, or other significant paths.
-->

---

## Tech Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python {{PYTHON_VERSION}} | {{RATIONALE}} |
| Framework | {{FRAMEWORK, e.g., FastAPI}} | {{RATIONALE}} |
| Database | {{DATABASE, e.g., PostgreSQL 16}} | {{RATIONALE}} |
| ORM / query layer | {{ORM, e.g., SQLAlchemy 2.x}} | {{RATIONALE}} |
| Cache | {{CACHE, e.g., Redis 7}} | {{RATIONALE}} |
| Task queue | {{TASK_QUEUE, e.g., "none in v1"}} | {{RATIONALE}} |
| Observability | {{TRACING, e.g., OpenTelemetry}} | {{RATIONALE}} |
| Lint / format | ruff | Unified linter and formatter; zero configuration drift |
| Test framework | pytest | Industry standard; rich fixture system |
| CI | GitHub Actions | {{RATIONALE}} |
| Deployment | {{DEPLOYMENT_TARGET}} | {{RATIONALE}} |

---

## Security Boundaries

### Authentication

{{DESCRIBE_AUTH_MECHANISM}}

Example: "All API endpoints except `/health` and `/auth/token` require a valid JWT Bearer token. Tokens are issued by `POST /auth/token` and expire after {{EXPIRY_DURATION}}. Revoked tokens are stored in Redis with TTL matching the remaining token lifetime."

### Tenant Isolation

{{IF_MULTI_TENANT: Describe how tenant isolation is enforced at each layer}}
{{IF_SINGLE_TENANT: "This is a single-tenant system. Tenant isolation is not applicable."}}

Example for RLS: "PostgreSQL Row-Level Security is enabled on all tenant-scoped tables. Every database session sets `SET LOCAL app.tenant_id = :tid` before executing any query. RLS policies enforce that `app.tenant_id` matches the `tenant_id` column on every SELECT, INSERT, UPDATE, and DELETE."

### PII Policy

No PII is stored in logs, span attributes, or metrics. The following fields are considered PII in this system: {{LIST_PII_FIELDS, e.g., "email address, full name, phone number"}}. Where these must be referenced in observability, SHA-256 hashes are used.

PII is stored in the database in the following fields: {{LIST_PII_DB_FIELDS}}. Database access to these fields is {{ACCESS_POLICY, e.g., "unrestricted within the application tier; not exposed in logs or API responses beyond what the authenticated user owns"}}.

---

## Observability

<!--
Required section. Fill in before Phase 2.
If a tool is not yet decided, write "TBD — decide by Phase 2" in the relevant field.
Profile-specific metric requirements are defined in IMPLEMENTATION_CONTRACT.md §Observability.
-->

| Dimension | Choice | Notes |
|-----------|--------|-------|
| Tracing | {{e.g., OpenTelemetry + Jaeger \| custom noop tracer}} | Shared module: `{{TRACING_MODULE_PATH}}` |
| Metrics | {{e.g., Prometheus / statsd / CloudWatch}} | Required labels: `service`, `env`, `operation` |
| Logging | {{e.g., structlog JSON \| stdlib JSON formatter}} | Required fields: `trace_id`, `span_id`, `env`, `service` |
| Dashboards | {{link or N/A}} | |
| Alerting | {{P95 latency threshold + error rate threshold, or N/A}} | |

### Observability Invariants

- No PII in spans, metrics labels, or log messages (enforced by §PII Policy above).
- Health endpoint: `GET /health` — see §OBS-3 in `docs/IMPLEMENTATION_CONTRACT.md`.
- All external calls instrumented: spans required for DB, Redis, HTTP, LLM inference.

---

## External Integrations

| Integration | Purpose | Auth method | Rate limit / SLA |
|-------------|---------|-------------|-----------------|
| {{SERVICE_1}} | {{PURPOSE_1}} | {{AUTH_1}} | {{RATE_LIMIT_1}} |
| {{SERVICE_2}} | {{PURPOSE_2}} | {{AUTH_2}} | {{RATE_LIMIT_2}} |

<!--
If there are no external integrations, write: "None in v1."
-->

---

## File Layout

```
{{PROJECT_NAME}}/
├── {{APP_DIR}}/               # Application source
│   ├── __init__.py
│   ├── {{ENTRY_POINT}}.py     # Application entry point / factory
│   ├── {{ROUTER_DIR}}/        # Route handlers (thin — delegate to services)
│   │   └── {{ROUTER_FILE}}.py
│   ├── {{SERVICE_DIR}}/       # Business logic (no HTTP dependencies)
│   │   └── {{SERVICE_FILE}}.py
│   ├── {{MODEL_DIR}}/         # Database models / schemas
│   │   └── {{MODEL_FILE}}.py
│   ├── middleware/             # Request middleware
│   │   └── auth.py
│   └── {{SHARED_UTILS}}/      # Shared utilities (tracing, config, etc.)
│       ├── tracing.py
│       └── config.py
├── tests/
│   ├── conftest.py            # Shared fixtures
│   ├── unit/                  # Unit tests (no I/O)
│   └── integration/           # Integration tests (with DB, cache)
├── {{MIGRATION_DIR}}/         # Database migrations
├── docs/
│   ├── ARCHITECTURE.md        # This file
│   ├── spec.md
│   ├── tasks.md
│   ├── CODEX_PROMPT.md
│   ├── IMPLEMENTATION_CONTRACT.md
│   ├── dev-standards.md
│   ├── audit/                 # Review cycle reports (append-only)
│   └── adr/                   # Architectural Decision Records (append-only)
├── .github/
│   └── workflows/
│       └── ci.yml
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
└── README.md
```

---

## Runtime Contract

These environment variables are required at startup. The application must fail fast with a clear error message if any required variable is absent or malformed.

This section is only for environment variables. Runtime tier, isolation, persistence, network, secrets, and recovery decisions belong in `## Runtime and Isolation Model`.

| Variable | Description | Example value | Required |
|----------|-------------|---------------|----------|
| `{{ENV_VAR_1}}` | {{DESCRIPTION_1}} | `{{EXAMPLE_1}}` | Yes |
| `{{ENV_VAR_2}}` | {{DESCRIPTION_2}} | `{{EXAMPLE_2}}` | Yes |
| `{{ENV_VAR_3}}` | {{DESCRIPTION_3}} | `{{EXAMPLE_3}}` | No (default: `{{DEFAULT}}`) |

<!--
Never put credentials in this table. The "Example value" column shows the FORMAT of the value,
not a real value. Actual values live in environment variables or a secrets manager.
-->

---

## Continuity and Retrieval Model

Define how this project preserves and retrieves prior context without replacing canonical files.

### Canonical Truth

| Artifact | Authority |
|----------|-----------|
| `docs/ARCHITECTURE.md` | architecture and boundary decisions |
| `docs/IMPLEMENTATION_CONTRACT.md` | immutable implementation rules |
| `docs/tasks.md` | execution contract and task graph |
| `docs/CODEX_PROMPT.md` | live session state and open findings |
| `docs/adr/` | formal decision changes |
| `docs/audit/` + eval artifacts | review and proof history |

### Retrieval Convenience

| Artifact | Purpose | Required? |
|----------|---------|-----------|
| `docs/DECISION_LOG.md` | quick recall of why key decisions were made | Yes |
| `docs/IMPLEMENTATION_JOURNAL.md` | cross-session implementation handoff | Yes |
| `docs/EVIDENCE_INDEX.md` | proof lookup across reviews / evals / heavy tasks | {{Yes \| No}} |

### Scoped Retrieval Rules

- Tasks that touch architecture, runtime, auth, retrieval semantics, compliance, migrations, or open findings must include `Context-Refs` in `docs/tasks.md`.
- Agents read task `Context-Refs` first, then only the linked canonical documents.
- Retrieval artifacts summarize and index. They do not overrule canonical files.
- If this project omits `docs/EVIDENCE_INDEX.md`, explain why the current evidence volume does not justify it.

---

## Non-Goals (v1)

The following are explicitly out of scope for v1. They may be addressed in future versions.

- {{NON_GOAL_1}}
- {{NON_GOAL_2}}
- {{NON_GOAL_3}}
- {{ANTI_OVERENGINEERING_NON_GOAL, e.g., "No RAG in v1", "No autonomous planning loop", "No T2/T3 isolated runtime without ADR"}}

<!--
Non-goals are as important as goals. They prevent scope creep and give the review agents
a clear signal when a Codex implementation is going out of scope.

Good non-goals are specific: not "we won't build X" but "we won't support Y because Z —
it will be addressed in v2 when we have ADR-004 approved."
-->
