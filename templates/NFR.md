# Non-Functional Requirements — {{PROJECT_NAME}}

Version: 1.0
Last updated: {{DATE}}

<!--
This file is created by the Strategist when the project has explicit performance, reliability,
or throughput constraints. It is updated after Phase 1 with measured baselines.

If the project has no formal NFR obligations, this file may be omitted from the starter package.
If it exists, the SLA Table must contain at least one row with a non-empty Target (PHASE1_VALIDATOR NFR-1).
-->

---

## SLA Table

| Requirement | Target | Measurement method | CI gate threshold | Baseline (Phase 1) |
|-------------|--------|--------------------|-------------------|--------------------|
| API p99 latency | {{e.g., "< 200ms"}} | pytest-benchmark / locust | {{e.g., "fail if p99 > 300ms"}} | — |
| API p50 latency | {{e.g., "< 50ms"}} | pytest-benchmark / locust | — | — |
| Error rate | {{e.g., "< 0.1% over 5 min"}} | Prometheus alert | — | — |
| Throughput | {{e.g., "≥ 500 RPS sustained"}} | locust | — | — |
| DB query p99 | {{e.g., "< 50ms"}} | OpenTelemetry span histogram | — | — |

<!--
CI gate threshold: if set, this value is enforced in .github/workflows/ci.yml (load test step).
Baseline (Phase 1): filled in after Phase 1 load tests. Leave "—" until measured.

A regression (measured value exceeds target by >10%) becomes a P2 finding in the next CODE review.
Track regressions in the History section below.
-->

---

## AI / Inference NFRs

Include this section only if the system uses LLM inference in production behavior.

| Requirement | Target | Measurement method | CI gate threshold | Baseline (Phase 1) |
|-------------|--------|--------------------|-------------------|--------------------|
| Cost per successful AI task | {{e.g., "< $0.02"}} | token accounting + pricing table snapshot | — | — |
| AI path p95 latency | {{e.g., "< 1500ms"}} | app metrics / load test | — | — |
| Strong-model escalation rate | {{e.g., "< 5%"}} | routing / orchestration metrics | — | — |
| Cache hit rate | {{e.g., "> 40%" \| N/A}} | app metrics | — | — |
| AI task success / acceptance rate | {{e.g., "> 95%"}} | eval set / production scorecard | {{optional}} | — |

Guidance:
- if cost is a real constraint, record the pricing source and date used for the estimate
- price aggregators can be used for comparison; measured production cost should override estimates
- if multiple model classes are used, measure escalation rate rather than only average cost

---

## Enforcement

- Requirements with a CI gate threshold are enforced in `.github/workflows/ci.yml` (load test step).
- Requirements without a CI gate are tracked manually; the Baseline field is updated after Phase 1.
- A regression (measured value exceeds target by >10%) is recorded as a P2 finding in `docs/CODEX_PROMPT.md §Open Findings` and surfaced at the next CODE review.
- Baseline values in `docs/CODEX_PROMPT.md §NFR Baseline` are updated after each phase where load tests run.
- For AI systems, cost and escalation-rate regressions are treated as NFR regressions even when functional tests stay green.

---

## History

| Date | Phase | p99 latency | Error rate | Throughput | Notes |
|------|-------|-------------|------------|------------|-------|
| {{DATE}} | Phase 1 baseline | — | — | — | Initial measurement; targets set |

If AI / Inference NFRs are active, include cost source, model classes measured, and escalation-rate notes in `Notes`.
