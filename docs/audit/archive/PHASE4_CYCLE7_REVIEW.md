# Phase 4 Boundary Review — Cycle 7
## Dream Motif Interpreter

**Date:** 2026-04-14
**Scope:** T13–T17 (full Phase 4)
**Phase:** 4 → 5 boundary
**Stop-Ship:** No
**Phase Gate:** PASS

---

## Review Summary

| Severity | Count | Notes |
|----------|-------|-------|
| P0 | 0 | — |
| P1 | 0 | — |
| P2 | 4 | CODE-48, CODE-49, CODE-50 (new); DOC-1 (journal stale) |
| P3 | 9 | All carry-forward from prior cycles |

---

## META_REPORT

### IMPL-CONTRACT
PASS. No violations detected across T13–T17 files:
- SQL uses parameterised `text()` throughout; no interpolation.
- Auth middleware enforces 401/403 on all mutating endpoints; public paths explicitly documented.
- PII redaction chain active: `_redact_pii` strips `raw_text`, `chunk_text`, `justification` before logging.
- All secrets via env vars; config fail-fast enforced.
- `interpretation_note` literal field added to all API response models (ARCH-6 / CODE-44 closed).
- Annotation versioning: no DELETE/UPDATE on `annotation_versions` table; flush-before-mutate confirmed.
- Taxonomy mutation gate: category promotion requires explicit human API call; 403 on unauthorized.
- Idempotent workers: `ON CONFLICT DO NOTHING` on `content_hash` in `ingest_document`.

### DOC-CURRENCY
**GAP — P2:** `docs/IMPLEMENTATION_JOURNAL.md` last entry is T13 (2026-04-13). Entries for T14, T15, T16, T17 are absent. Non-blocking for Phase 5 start; should be backfilled.

All other docs current:
- `ARCHITECTURE.md` §File Layout includes all Phase 4 files including worker modules and `app/retrieval/types.py`.
- `CODEX_PROMPT.md` v1.13: baseline 83/9, T18 next, T13–T17 completed.
- `DECISION_LOG.md`: entries D-001 through D-010 accurate; no new decisions.
- `retrieval_eval.md`: T15 evaluation recorded; no regression.

### PHASE-GATE
**SATISFIED.** Phase 4 gate: "All API endpoints return correct status codes for happy paths and error cases; background workers enqueue and process jobs; full flow from sync trigger to searchable archive works end-to-end."

- All happy-path and error-case tests pass (83 passing, 9 skipped).
- Background workers (`ingest_document`, `index_dream`) both exported with `WorkerSettings.functions`.
- End-to-end flow: sync trigger → worker → DB write → pgvector index → search query verified in integration tests.

### CARRY-FORWARD
- No P2 finding exceeds 3-cycle age cap.
- No RAG-critical P2 exceeds 1-cycle cap.
- All P0/P1 closed.
- ARCH-14 stale: worker files DO exist; finding should be closed.

### CONSTRAINT-DRIFT
PASS. Decisions D-001 (workflow shape), D-003 (RAG on), D-007 (versioning), D-008 (approval gate), OBS-3 (health endpoint) all enforced as specified. No architecture contradictions detected.

---

## ARCH_REPORT

### OBS Compliance
**OBS-1 PASS.** Per-call DB child spans present in all service files (analysis.py, taxonomy.py, health.py, API routers).
**OBS-2 PASS.** `retrieval_ms` span attribute and `insufficient_evidence` structured log counter both present in `query.py`.

### SEC Compliance
**SEC-1 PASS.** Constant-time comparison via `hmac.compare_digest()` in `dreams.py`. All mutating endpoints gated by global middleware (main.py:27–35). Public paths explicitly whitelisted.
**SEC-2 PASS.** Shared `_redact_pii` filter strips `raw_text`, `chunk_text`, `justification`; registered in structlog processor chain.

### Layer / Dependency
PASS. Workers do not import API layer. API → services → models dependency chain flows downward only. No circular imports.

### Worker Architecture
PASS. Both `ingest.py` and `index.py` export `WorkerSettings`. ARQ context injection verified. Idempotency via `ON CONFLICT DO NOTHING` confirmed in integration tests. ARCHITECTURE.md §File Layout aligned.

### Session Factory (ARCH-12)
Still open. `_get_session_factory()` duplicated in `dreams.py` and `search.py`. `themes.py` works around by importing from `dreams.py`. Functional but not DRY; 2–3 cached engine instances. P3 carry-forward; acceptable for single-user v1.

### Router Registration
PASS. All Phase 4 routers (health, dreams, search, themes) registered in `app/main.py`.

### Carry-Forward ARCH Findings

| Finding | Status |
|---------|--------|
| ARCH-10 (query expansion) | Open P3 — not wired; acceptable for v1 |
| ARCH-11 (EvidenceBlock metadata) | Open P3 — partial contract; acceptable for v1 |
| ARCH-12 (session factory dup) | Open P3 — carry-forward |
| ARCH-14 (worker files declared) | **CLOSED** — files exist and wired |
| ARCH-15 (adr/ directory) | Open P3 — no ADR-requiring changes in Phase 4 |

---

## CODE_REPORT

### Error Handling
PASS overall. Typed errors for external I/O; structured logs on failure paths.

**Exception: CODE-48 (P2)** — Initial job status write in `ingest.py:37` not wrapped in try/finally. Transient Redis failure leaves job ID untracked ("orphaned running" state).

### Test Coverage
PASS. All AC criteria have corresponding tests. Primary error paths (auth failure, 404, 410 expired token) covered.

Minor gap: no test for Redis write failure on initial job status. No test for bulk-confirm token race condition (token expires between issue and approval).

### Redis Usage
**CODE-49 (P2)** — `_get_redis_client()` in `themes.py:259-262` and `dreams.py:308-315` uses `lru_cache(maxsize=1)` but never closes the client. No connection pool configured. Potential connection leak in long-running processes.

TTL policy: ✓ Bulk confirm token TTL from `BULK_CONFIRM_TOKEN_TTL_SECONDS` config.

### Async Safety
PASS. Blocking I/O wrapped in `asyncio.to_thread()`. All Redis/DB ops use async clients.

### Type Safety
PASS. All endpoints return typed Pydantic models. No dict returns.

### Log Policy
PASS. PII redaction verified. Only UUIDs (dream_id, job_id) and metadata (status_code, query_length) appear in logs.

### Auth Consistency
PASS. Global middleware covers all routes. Mutating endpoints return 401/403 as appropriate.

### New CODE Findings

**CODE-48 (P2):** `app/workers/ingest.py:37` — initial Redis status write (status="running") not wrapped in try/finally. If write fails, job ID is untracked; subsequent "done"/"failed" writes are orphaned.
- File: `app/workers/ingest.py:37`
- Remediation: Wrap initial status write in try/except; log Redis error and continue (acceptable to miss initial status write as long as final state is written).

**CODE-49 (P2):** Redis connection not pooled or closed in `app/api/themes.py:259-262` and `app/api/dreams.py:308-315`.
- Files: `app/api/themes.py:259-262`, `app/api/dreams.py:308-315`
- Remediation: Create shared Redis client in app startup/shutdown lifecycle (FastAPI lifespan event), similar to DB engine.

**CODE-50 (P2):** Bulk confirm token parsing in `app/api/themes.py:117-121` lacks explicit type guard on `parsed_payload["dream_ids"]`. If the value is non-list (e.g., `123`), `for value in parsed_payload["dream_ids"]` raises `TypeError` which may propagate unhandled.
- File: `app/api/themes.py:117-121`
- Remediation: Add `isinstance(parsed_payload.get("dream_ids"), list)` guard before iteration.

### Carry-Forward CODE Findings
CODE-7 (P3), CODE-13 (P3), CODE-16 (P3), CODE-40 (P3), CODE-41 (P3) — all open, all deferred to Phase 5+.

---

## Consolidated Summary

**Stop-Ship: No**

Phase 4 deliveries (T13–T17) are complete and all acceptance criteria pass. The implementation is architecturally sound with full observability, authentication, PII redaction, annotation versioning, and idempotent background workers.

**New findings requiring CODEX_PROMPT.md update:**
- CODE-48 (P2): Worker status write safety
- CODE-49 (P2): Redis connection lifecycle management
- CODE-50 (P2): Bulk confirm token type guard
- DOC-1 (P2): IMPLEMENTATION_JOURNAL stale for T14–T17

**ARCH-14 to close:** Worker files exist and are wired; finding is stale.

**Phase 5 may proceed.** No P0/P1 findings. Pre-T18 fix queue: empty.

---

## Reviewer Agents
- META: general-purpose explore agent, 2026-04-14
- ARCH: general-purpose explore agent, 2026-04-14
- CODE: general-purpose explore agent, 2026-04-14
