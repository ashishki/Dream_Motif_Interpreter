---
# ARCH_REPORT — Cycle 9
_Date: 2026-04-16_

## Component Verdicts

| Component | Verdict | Note |
|-----------|---------|------|
| `app/services/imagery.py` (`ImageryExtractor`) | PASS | Lives in `app/services/`; no HTTP imports; no `dream_themes` writes |
| `app/services/motif_inductor.py` (`MotifInductor`) | PASS | Lives in `app/services/`; open-vocabulary; no taxonomy reference |
| `app/services/motif_grounder.py` (`MotifGrounder`) | PASS | Lives in `app/services/`; no HTTP or retrieval imports |
| `app/services/motif_service.py` (`MotifService`) | DRIFT | Orchestrator is correctly in `services/`; however it calls `session.commit()` directly rather than leaving commit ownership to the caller — see ARCH-1 |
| `app/api/motifs.py` | PASS | Thin handler; no business logic embedded; delegates reads/writes to ORM directly through session (acceptable for simple CRUD routes) |
| `app/assistant/facade.py` (`AssistantFacade.get_dream_motifs`) | PASS | Returns `MotifInductionItem` dataclass (DTO), no ORM object leakage; session ownership kept inside facade |
| `app/assistant/tools.py` (`build_tools`) | DRIFT | `TOOLS` module-level constant on line 149 is built with `motif_induction_enabled=False` at import time; `handle_chat` in `chat.py` calls `build_tools(get_settings().MOTIF_INDUCTION_ENABLED)` per request — correct for chat, but the stale `TOOLS` constant remains and could mislead future callers — see ARCH-2 |
| `app/assistant/chat.py` | PASS | `build_tools()` called per request inside `handle_chat()` with live settings; `_SYSTEM_PROMPT` includes full motif framing rules inline |
| `app/assistant/prompts.py` | VIOLATION | File does not exist; WS-9.6 Files list names it as a required deliverable — see ARCH-3 |
| `app/workers/ingest.py` | PASS | `get_settings().MOTIF_INDUCTION_ENABLED` checked at ingest time inside `_run_post_store_pipeline()` (line 211); not at import time |
| `app/shared/config.py` | DRIFT | `MOTIF_INDUCTION_ENABLED` defaults to `False` (correct); `get_settings()` is `@lru_cache` — flag changes require process restart; violates ADR-010 runtime-evaluation requirement — see ARCH-4 |
| `app/retrieval/ingestion.py` | PASS | No import from `app/retrieval/query.py`; layer boundary respected |
| `app/retrieval/query.py` | PASS | No import from `app/retrieval/ingestion.py`; layer boundary respected |
| `app/api/patterns.py` | PASS | No motif-related stubs; clean; WS-9.7 not started — confirmed clean deferral |
| `app/services/patterns.py` | PASS | No motif-related stubs; queries `dream_themes` only; WS-9.7 deferral clean |
| `app/main.py` | PASS | `motifs_router` included; all Phase 9 routes registered |
| `docs/ARCHITECTURE.md` §17 | DRIFT | All Phase 9 components still listed as "Planned"; §16 test baseline says "97 unit tests passing" — actual baseline is 238. Doc patch needed — see ARCH-5 |

---

## Contract Compliance

| Rule | Verdict | Note |
|------|---------|------|
| SQL Safety — parameterized queries only | PASS | `app/retrieval/query.py` uses `text()` with named parameters; `app/api/motifs.py` uses ORM (safe) |
| Async Redis — `redis.asyncio` only | PASS | No Redis access added in Phase 9 scope |
| Authorization — every new route handler authenticates | PASS | `app/main.py` middleware enforces `X-API-Key` on all routes; `/health` excluded per design with comment |
| PII Policy — no dream content in logs/spans | PASS | `motif_service.py` logs use `dream_id` only; no raw_text in spans or log messages |
| Shared Tracing Module — `get_tracer()` from `app/shared/tracing.py` | PASS | All Phase 9 services and routes import `get_tracer` from `app/shared/tracing` |
| LLM Output Framing — `interpretation_note` or literal Pydantic field | PASS | `MotifResponse` carries a `Literal` `interpretation_note` field; `PatternResponseEnvelope` carries one too |
| Annotation Versioning — write `AnnotationVersion` before mutation commit | PASS | `app/api/motifs.py:update_motif_status` writes `AnnotationVersion` via `session.flush()` before `session.commit()` |
| Annotation Versioning — `annotation_versions` append-only | PASS | No DELETE or UPDATE on `annotation_versions` found in Phase 9 code |
| Taxonomy Mutation Gate — no automated taxonomy promotion | PASS | Phase 9 pipeline writes only to `motif_inductions`; `dream_themes` / `theme_categories` untouched |
| Idempotent Workers | VIOLATION | `MotifService.run()` does not check for existing `motif_inductions` rows before inserting; re-running ingest for the same dream produces duplicate motif rows — see ARCH-6 |
| Ingestion/Query Separation — no cross-import | PASS | Confirmed by source inspection: no cross-import between `ingestion.py` and `query.py` |
| OBS-1 — every external call wrapped in a span | PASS | `motif_service.py`, `motif_inductor.py`, imagery and grounder stages all use tracer spans via `app/shared/tracing.get_tracer()` |
| OBS-2 — `insufficient_evidence` rate counter and `retrieval_ms` span | PASS | `query.py` sets `retrieval_ms` span attribute and logs `insufficient_evidence` events |
| OBS-3 — `GET /health` freshness check, no auth, HTTP 503 on stale | PASS | `app/api/health.py` implements the full contract; uses `MAX_INDEX_AGE_HOURS`; returns 503 on stale |
| Runtime tier T1 — no shell mutation, no ad-hoc package installs | PASS | No new shell calls or package installations introduced in Phase 9 |
| Credentials — no secrets in source | PASS | No credentials found in Phase 9 source files |

---

## ADR Compliance

| ADR | Verdict | Note |
|-----|---------|------|
| ADR-001: Append-only annotation versioning | PASS | Motif status changes write `AnnotationVersion` via `_annotation_version()`; no delete/update path added |
| ADR-002: Single-user API key auth | PASS | `motifs_router` protected by existing middleware; no new auth bypasses |
| ADR-003: Telegram adapter inside core repo | PASS | Phase 9 does not change Telegram topology; assistant layer extended in place |
| ADR-004: Bounded assistant tool facade | PASS | `get_dream_motifs` exposed through `AssistantFacade`; returns DTOs; no direct ORM exposure in tool handler |
| ADR-005: Managed transcription first | PASS | Not affected by Phase 9 |
| ADR-006: Persisted bot session state | PASS | Not affected by Phase 9 |
| ADR-007: Compose-first deployment | PASS | Not affected by Phase 9 |
| ADR-008: Inducted motifs and taxonomy themes as separate data models | PASS | `MotifService` docstring explicitly states "NEVER writes to dream_themes"; `app/api/motifs.py` writes only to `motif_inductions`; no FK between `motif_inductions` and `dream_themes` |
| ADR-009: Research trust boundary | PASS | Phase 9 does not implement research augmentation; no drift |
| ADR-010: Feature flag gating — flags checked at runtime, not at startup | DRIFT | `get_settings()` uses `@lru_cache(maxsize=1)` — flag value is frozen after first call; a flag change without process restart does not take effect. ADR-010 §Consequences explicitly requires "checked at runtime, not at startup, so that a flag change takes effect on the next operation without restarting the process." The lru_cache breaks this guarantee — see ARCH-4 |

---

## Architecture Findings

### ARCH-1 [P2] — MotifService owns session commit inside the pipeline

Symptom: `MotifService.run()` calls `await session.commit()` on a session opened and passed in by the caller in `ingest.py:_run_post_store_pipeline()`.

Evidence: `app/services/motif_service.py:125` (`await session.commit()`); `app/workers/ingest.py:212` (caller opens session and passes it in).

Root cause: The orchestrator took on commit ownership rather than leaving the transaction boundary to the caller.

Impact: Double-commit risk if the caller also commits. Silent partial writes if an exception occurs between the service commit and the caller's next operation. Makes the service harder to test in a controlled transaction.

Fix: Remove `await session.commit()` from `MotifService.run()`; let the caller in `ingest.py` control the transaction boundary. If the service needs its own transaction, open it internally rather than accepting and then committing a caller-provided session.

---

### ARCH-2 [P3] — Stale `TOOLS` module-level constant in `app/assistant/tools.py`

Symptom: `TOOLS: list[dict[str, Any]] = build_tools(motif_induction_enabled=False)` is built once at module import time (line 149) and never updated. `handle_chat` correctly calls `build_tools(get_settings().MOTIF_INDUCTION_ENABLED)` per request — the constant is not used in the live path.

Evidence: `app/assistant/tools.py:149`.

Root cause: The constant was retained from before per-request flag evaluation was introduced.

Impact: A future caller using the module-level `TOOLS` constant would silently receive the wrong catalog when `MOTIF_INDUCTION_ENABLED=true`. This is a latent defect, not currently active.

Fix: Remove the module-level `TOOLS` constant. All callers should use `build_tools()` directly with explicit flag argument.

---

### ARCH-3 [P2] — `app/assistant/prompts.py` absent; WS-9.6 deliverable unfulfilled

Symptom: `app/assistant/prompts.py` does not exist. The WS-9.6 Files list names it as a required deliverable. Motif framing rules are embedded as an inline string literal in `app/assistant/chat.py:_SYSTEM_PROMPT` (lines 18–42).

Evidence: WS-9.6 Files section in `docs/tasks_phase9.md`; `app/assistant/prompts.py` confirmed absent; `app/assistant/chat.py:18–42` contains framing inline.

Root cause: Framing rules were implemented directly in `chat.py` rather than extracted to the `prompts.py` module named in the task deliverable list.

Impact: WS-9.6 AC-3 ("system prompt includes framing rules") is functionally satisfied — the rules are present and the system prompt is applied correctly. However the deliverable `app/assistant/prompts.py` is missing, and the WS-9.6 file list misrepresents what was delivered. Framing rules are harder to update or test in isolation when embedded in the chat loop.

Fix: Either (a) extract `_SYSTEM_PROMPT` and the framing rules to `app/assistant/prompts.py` and import from there in `chat.py`, or (b) update `docs/tasks_phase9.md §WS-9.6 Files` to remove `app/assistant/prompts.py` with a note that framing lives in `chat.py`. Option (a) is preferred for maintainability.

---

### ARCH-4 [P2] — `get_settings()` lru_cache breaks ADR-010 runtime flag evaluation requirement

Symptom: `app/shared/config.py:get_settings()` is decorated with `@lru_cache(maxsize=1)`. The `Settings` object — including `MOTIF_INDUCTION_ENABLED` — is frozen after the first call. Subsequent environment variable changes do not take effect without a process restart.

Evidence: `app/shared/config.py:33–35`; ADR-010 §Consequences: "Both flags must be checked at runtime, not at startup, so that a flag change takes effect on the next operation without restarting the process."

Root cause: The `lru_cache` was added for performance but contradicts the ADR-010 runtime re-evaluation requirement.

Impact: A flag change (`MOTIF_INDUCTION_ENABLED=true`) does not take effect in a running ingest worker or bot process without a restart. This contradicts ADR-010's stated operational rationale of "rollback by environment variable change without a code deployment."

Fix: Either (a) remove `@lru_cache` from `get_settings()` and accept the small cost of re-reading env vars per call, or (b) document the restart requirement explicitly in `docs/ENVIRONMENT.md` and update ADR-010 §Consequences to reflect the actual behavior. If a restart is acceptable operationally, option (b) keeps the cache but closes the ADR compliance gap by aligning the documented contract with the implementation.

---

### ARCH-5 [P3] — `docs/ARCHITECTURE.md` stale: Phase 9 components listed as Planned; test baseline outdated

Symptom: `docs/ARCHITECTURE.md §17` describes all Phase 9 components as "Planned". `docs/ARCHITECTURE.md §16` records test baseline as "97 unit tests passing". Actual baseline is 238 passing per META_ANALYSIS.md. Document header says "Last updated: 2026-04-15 (Phase 8 complete)".

Evidence: `docs/ARCHITECTURE.md:340` (§17 "Planned components" table); `docs/ARCHITECTURE.md:306` (§16 "97 unit tests passing").

Root cause: Architecture document was not updated when Phase 9 WS-9.1 through WS-9.6 were implemented.

Impact: The architecture document is the primary system-design authority. Listing implemented components as "Planned" misleads reviewers and future implementors about actual system state.

Fix: Update `docs/ARCHITECTURE.md §17` component status to "Implemented (Phase 9)". Update §16 baseline to 238 passing, 9 skipped. Add `app/api/motifs.py` to §9 Component Table. Update document header to reflect Phase 9 completion.

---

### ARCH-6 [P2] — MotifService has no idempotency guard; re-ingesting a dream produces duplicate `motif_inductions` rows

Symptom: `MotifService.run()` inserts new `MotifInduction` rows for every call without checking for existing rows for the given `dream_id`.

Evidence: `app/services/motif_service.py:114–123` (unconditional `session.add(row)` per candidate); `app/workers/ingest.py:211–215` (calls `motif_service.run()` for every target dream on every ingest run when flag is true).

Root cause: The idempotency guard present for `DreamEntry` (content_hash) and `DreamChunk` (dream_id, chunk_index composite key) was not extended to motif induction.

Impact: Re-syncing the same dream with `MOTIF_INDUCTION_ENABLED=true` creates duplicate motif rows. The API response returns duplicate motifs. User-confirmed motif status changes are lost when new draft rows overwrite the logical record on next sync. This violates the Idempotent Workers rule in `docs/IMPLEMENTATION_CONTRACT.md`.

Fix: Add a guard in `MotifService.run()` to skip induction if any `motif_inductions` row already exists for the `dream_id`. Alternatively, add a unique constraint on `(dream_id, label, model_version)` and use an upsert with `on_conflict_do_nothing` to prevent duplicates at the DB level.

---

### ARCH-7 [P3] — WS-9.7 deferral not recorded in `docs/DECISION_LOG.md`

Symptom: `docs/DECISION_LOG.md` contains decisions D-001 through D-011, all from Phase 6–8. WS-9.7 deferral is not recorded.

Evidence: `docs/DECISION_LOG.md` (no WS-9.7 entry); META_ANALYSIS.md CODE-56 (open, requests deferral confirmation); `docs/tasks_phase9.md §WS-9.7` (marked optional, no formal deferral record).

Root cause: The deferral was implicit in the task graph but was never formalized in the decision log.

Impact: Absence of a formal deferral record creates ambiguity before Phase 10 planning about whether WS-9.7 is deferred vs. untracked. CODE-56 remains open.

Fix: Add entry D-012 to `docs/DECISION_LOG.md`: `WS-9.7 Pattern Queries Extension deferred to Phase 9.1 or Phase 10 | docs/tasks_phase9.md §WS-9.7`.

---

## Right-Sizing / Runtime Checks

| Check | Verdict | Note |
|-------|---------|------|
| Solution shape (Workflow) still appropriate | PASS | Phase 9 adds a deterministic pipeline (ImageryExtractor → MotifInductor → MotifGrounder → persist) behind a feature flag. No autonomous loop introduced. Shape remains Workflow. |
| Deterministic-owned subproblems remain deterministic | PASS | Routing, segmentation heuristics, taxonomy CRUD, and calculations remain deterministic. MotifGrounder (offset verification) is deterministic. Open-vocabulary label generation (MotifInductor) is correctly assigned to LLM. No deterministic path has drifted to LLM. |
| Runtime tier (T1) unchanged / justified | PASS | No shell mutation, no ad-hoc package installs, no privileged autonomous execution introduced in Phase 9. Runtime tier remains T1. |
| Human approval boundaries still valid | PASS | Taxonomy promotion, rename, delete still require authenticated API calls. Motif status transitions (confirm/reject) require authenticated PATCH calls via `app/api/motifs.py`. No automated promotion path was introduced. |
| Minimum viable control surface still proportionate | PASS | Phase 9 adds one new router (`motifs_router`), one facade method, and one gated assistant tool. Surface expansion is proportionate to the feature. |

---

## Retrieval Architecture Checks

| Check | Verdict | Note |
|-------|---------|------|
| Ingestion / query-time separation (no cross-import) | PASS | `app/retrieval/ingestion.py` has no import from `query.py`; `app/retrieval/query.py` has no import from `ingestion.py`. Confirmed by source inspection. |
| `insufficient_evidence` path defined | PASS | `InsufficientEvidence` dataclass defined in `app/retrieval/query.py:51–53`; returned when relevance threshold not met; `AssistantFacade.search_dreams()` maps it to `SearchResult(insufficient_reason=...)` and returns it to the chat loop. |
| Evidence/citation contract defined | PASS | `EvidenceBlock` in `query.py` carries `dream_id`, `date`, `chunk_text`, `relevance_score`, `matched_fragments` (list of `FragmentMatch` with `text`, `match_type`, `char_offset`). Contract is complete. |
| Freshness / max-index-age policy (24h, health endpoint) | PASS | `app/api/health.py` checks `MAX_INDEX_AGE_HOURS` (default 24, set in `config.py`); returns HTTP 503 and `status: "degraded"` when stale. Health endpoint is unauthenticated per contract. |
| Index schema versioning (v1) | PASS | `INDEX_SCHEMA_VERSION = "v1"` declared in `app/retrieval/ingestion.py:21`; set as span attribute on index operations. |
| Retrieval observability expectations | PASS | `retrieval_ms` set as span attribute in `query.py:101` and `111`; `insufficient_evidence` logged via `logger.info("insufficient_evidence", ...)` at two code paths in `query.py`. |

---

## Doc Patches Needed

| File | Section | Change |
|------|---------|--------|
| `docs/ARCHITECTURE.md` | §17 "Planned components" table | Change status of all Phase 9 components to "Implemented (Phase 9)" |
| `docs/ARCHITECTURE.md` | §9 Component Table | Add `app/api/motifs.py` row: responsibility "REST API for motif retrieval and status updates", status "implemented (Phase 9)" |
| `docs/ARCHITECTURE.md` | §16 Testing | Update baseline from "97 unit tests passing" to "238 unit tests passing, 9 skipped" |
| `docs/ARCHITECTURE.md` | Version / Last updated header | Update to "Phase 9 WS-9.1–9.6 complete" |
| `docs/DECISION_LOG.md` | Decision Index | Add D-012: WS-9.7 Pattern Queries Extension deferred to Phase 9.1 / Phase 10 |
| `docs/tasks_phase9.md` | §WS-9.6 Files | Either remove `app/assistant/prompts.py` (noting framing lives in `chat.py`) or retain as a pending follow-up task |
| `docs/CODEX_PROMPT.md` | §Current State | Update baseline to 238 passing; mark WS-9.2–WS-9.6 complete; set Next Task to WS-9.7 or Phase 10 planning (CODE-51) |
---
