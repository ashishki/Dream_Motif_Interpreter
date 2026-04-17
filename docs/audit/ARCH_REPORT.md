---
# ARCH_REPORT — Cycle 10
_Date: 2026-04-17_

## Component Verdicts

| Component | Verdict | Note |
|-----------|---------|------|
| `app/api/` | PASS | Thin handlers only; no business logic embedded; auth enforced via middleware; public paths documented per contract |
| `app/services/motif_service.py` | PASS | FIX-1 resolved: no `session.commit()` inside service; caller owns commit. FIX-2 resolved: idempotency guard present at lines 58–65. Does not write to `dream_themes` (ADR-008 compliant). |
| `app/services/imagery.py` | PASS | FIX-5 resolved: OTel counter `motif.imagery_extract_total` with `status` attribute present; span `imagery_extractor.extract` present. |
| `app/services/motif_inductor.py` | PASS | FIX-5 resolved: OTel counter `motif.induction_total` with `status` attribute present; span `motif_inductor.induce` present. |
| `app/services/research_service.py` | PASS | Lives in `app/services/`; orchestrates retrieval and synthesis; does not own commit (caller in `app/api/research.py` calls `session.commit()`). Trust boundary enforced: only runs for confirmed motifs. |
| `app/research/retriever.py` | DRIFT | Correctly isolated as external trust boundary; no cross-import to `app/retrieval/`; no dream archive writes. However: no OTel span or OBS-2 counter/histogram on the external HTTP call. See ARCH-3. |
| `app/research/synthesizer.py` | PASS | Confidence vocabulary enforcement present at parse time; prohibited terms excluded from system prompt; `speculative/plausible/uncertain` validated on every result. |
| `app/retrieval/ingestion.py` | PASS | No import of `app/retrieval/query`. Schema version `v1` declared at line 21. |
| `app/retrieval/query.py` | PASS | No import of `app/retrieval/ingestion`. `InsufficientEvidence` path defined; `retrieval_ms` span attribute set. |
| `app/assistant/chat.py` | PASS | FIX-4 resolved: imports `SYSTEM_PROMPT` from `app/assistant/prompts`; uses `build_tools()` with live flag values at each call. |
| `app/assistant/tools.py` | PASS | FIX-6 resolved: no stale module-level `TOOLS` constant; only `_BASE_TOOLS`, `_GET_DREAM_MOTIFS_TOOL`, `_RESEARCH_MOTIF_PARALLELS_TOOL` private constants; `build_tools()` constructs catalog at call time. |
| `app/assistant/prompts.py` | PASS | FIX-4 resolved: module exists; `SYSTEM_PROMPT` contains motif framing rules and research augmentation framing including prohibited vocabulary (`confirmed`, `verified`). |
| `app/api/research.py` | DRIFT | Doc gap only: `app/research/` and `app/services/research_service.py` absent from `ARCHITECTURE.md §9` component table (ARCH-1). Also: duplicate `## 18` section header in `ARCHITECTURE.md` (ARCH-2). Code is correctly layered. |
| `docs/ARCHITECTURE.md` | DRIFT | Duplicate `## 18` section number (ARCH-2); §9 component table incomplete for Phase 10 modules (ARCH-1); §18 header still reads `Planned` (ARCH-4). |

---

## Contract Compliance

| Rule | Verdict | Note |
|------|---------|------|
| SQL Safety — parameterized queries only | PASS | All reviewed files use ORM or `text()` with bound parameters; no f-string SQL interpolation found. |
| Async Redis — `redis.asyncio` only | PASS | Not exercised in Phase 10 scope files; prior phases unchanged. |
| Authorization — every route enforces auth before data access | PASS | Global middleware in `app/main.py:44–52` enforces `X-API-Key` on all non-public paths. Research routes covered. `GET /health` and `GET /auth/callback` documented as intentionally public. |
| PII Policy — no dream content in logs/spans/errors | PASS | `motif_service.py` logs use `dream_id` (UUID) only; no `raw_text` in log messages in reviewed paths. |
| Credentials and Secrets — env-only | PASS | `RESEARCH_API_KEY` sourced from `Settings`; no hardcoded keys found. |
| Shared Tracing Module — `app/shared/tracing.py` only | PASS | `imagery.py`, `motif_inductor.py`, `motif_service.py`, `research.py` all use `get_tracer`/`get_meter` from `app/shared/tracing`. |
| OBS-1 — external calls wrapped in spans | DRIFT | LLM calls in `ImageryExtractor`, `MotifInductor`, `ResearchSynthesizer` and DB calls in reviewed paths have spans. External HTTP call in `ResearchRetriever.retrieve()` has no span. See ARCH-3. |
| OBS-2 — success/error counters and latency histograms | DRIFT | `imagery.py` and `motif_inductor.py` counters present (FIX-5 closed). `ResearchRetriever` has no counter or latency histogram. `insufficient_evidence` labeled counter missing from `app/retrieval/query.py` (carry-forward gap, not a Phase 10 regression). See ARCH-3. |
| OBS-3 — health endpoint `index_last_updated`, 503 on stale | PASS | `app/api/health.py` returns correct schema; HTTP 503 when stale beyond `MAX_INDEX_AGE_HOURS`. |
| Dream Content Isolation | PASS | Reviewed log calls use `dream_id` only. |
| LLM Output Framing | PASS | `MotifResponse` has literal `interpretation_note` field. `ResearchResultResponse` has literal `interpretation_note` field. `SYSTEM_PROMPT` enforces framing rules. |
| Annotation Versioning | PASS | `app/api/motifs.py` writes `AnnotationVersion` snapshot before commit at every motif status mutation (lines 115–133). |
| Taxonomy Mutation Gate | PASS | Theme category promotion, rename, merge, delete remain behind authenticated API calls; no automated path found in Phase 10 code. |
| Idempotent Workers | PASS | `MotifService.run()` idempotency guard confirmed at `app/services/motif_service.py:58–65`. |
| Ingestion/Query Separation | PASS | No cross-import between `app/retrieval/ingestion.py` and `app/retrieval/query.py` confirmed by code inspection. |
| Insufficient Evidence Path | PASS | `InsufficientEvidence` type defined and returned in `app/retrieval/query.py`; tested in prior cycles. |
| Index Schema Versioning | PASS | `INDEX_SCHEMA_VERSION = "v1"` at `app/retrieval/ingestion.py:21`. |
| Max Index Age Policy (24h, health endpoint) | PASS | `MAX_INDEX_AGE_HOURS` default 24 in config; enforced at `GET /health`. |
| Runtime tier (T1) — no shell mutation, no ad-hoc installs | PASS | No runtime shell invocations found in reviewed files. |

---

## ADR Compliance

| ADR | Verdict | Note |
|-----|---------|------|
| ADR-001: append-only annotation versioning | PASS | `AnnotationVersion` written before motif status mutations; no DELETE/UPDATE on that table found in reviewed code. |
| ADR-002: single-user API key auth | PASS | Middleware enforces `X-API-Key` on all non-public routes. |
| ADR-003: Telegram adapter inside core repo | PASS | `app/telegram/` exists inside the repository; no separate repository introduced. |
| ADR-004: bounded assistant tool facade | PASS | `app/assistant/facade.py` is the sole boundary; tools call facade methods only; no raw ORM access from the assistant layer. |
| ADR-005: managed transcription first | PASS | OpenAI Whisper in use; local Whisper deferred. No change in Phase 10 scope. |
| ADR-006: persisted bot session state | PASS | `bot_sessions` table used via `load_history`/`save_history`; Redis for ephemeral state only. |
| ADR-007: Compose-first deployment | PASS | No deployment topology changes in Phase 10 scope. |
| ADR-008: inducted motifs and taxonomy as separate models | PASS | `MotifService.run()` never writes to `dream_themes` (confirmed by code comment and logic); `motif_inductions` is the exclusive target. |
| ADR-009: research results carry speculative confidence labels | PASS | `ResearchSynthesizer` enforces `{speculative, plausible, uncertain}` at parse time (`synthesizer.py:86–89`); prohibited terms excluded from LLM prompt; `ResearchResultResponse` carries a literal `interpretation_note`; assistant `SYSTEM_PROMPT` prohibits `confirmed`/`verified` framing. |
| ADR-010: feature flag gating, default-off | PASS | `MOTIF_INDUCTION_ENABLED` and `RESEARCH_AUGMENTATION_ENABLED` default `false`; `build_tools()` called at request time with live flag values; `POST /motifs/{id}/research` returns HTTP 503 when flag is false (`app/api/research.py:61–62`). ADR-010 §Consequences explicitly documents the `lru_cache` behavior and process-restart requirement — this is a documented trade-off, not a violation. |

---

## Architecture Findings

### ARCH-1 [P3] — `app/research/` Module and `ResearchService` Absent from §9 Component Table

Symptom: Three Phase 10 components are implemented but not listed in `docs/ARCHITECTURE.md §9 Target Components`.

Evidence:
- `app/research/retriever.py` (`ResearchRetriever`) — implemented, not in §9 table
- `app/research/synthesizer.py` (`ResearchSynthesizer`) — implemented, not in §9 table
- `app/services/research_service.py` (`ResearchService`) — implemented, not in §9 table
- `docs/ARCHITECTURE.md:183–190` — §9 table lists only 6 rows; no `app/research/` row

Root cause: §9 was written before Phase 10 implementation and was not updated when `app/research/` was created and `ResearchService` was added to `app/services/`.

Impact: §9 is the authoritative component map. A reader relying on §9 has an incomplete picture of the module surface. Inconsistency with the documented Phase 10 planned component table in §18.

Fix: Add `app/research/` row to §9 table with `implemented (Phase 10)` status. Expand `app/services/` row description to include `ResearchService`.

---

### ARCH-2 [P3] — Duplicate `## 18` Section Number in `ARCHITECTURE.md`

Symptom: `docs/ARCHITECTURE.md` contains two sections numbered `## 18`.

Evidence:
- `docs/ARCHITECTURE.md:352` — `## 18. Research Augmentation Layer (Planned — Phase 10)`
- `docs/ARCHITECTURE.md:414` — `## 18. Resolved Architectural Decisions`

Root cause: A new §18 was inserted for Research Augmentation without renumbering the legacy §18 (`Resolved Architectural Decisions`), which should now be §22.

Impact: Structural ambiguity; any section-number reference to §18 is ambiguous. Degrades document integrity.

Fix: Renumber `## 18. Resolved Architectural Decisions` to `## 22. Resolved Architectural Decisions` (next available number after §21 ADR Coverage).

---

### ARCH-3 [P2] — `ResearchRetriever` External HTTP Call Has No OTel Span, Counter, or Latency Histogram

Symptom: `app/research/retriever.py` makes an external HTTP call to the research API with no OTel instrumentation.

Evidence:
- `app/research/retriever.py:27–82` — `retrieve()` method executes external HTTP via `asyncio.to_thread`; no `tracer.start_as_current_span(...)` call; no `get_meter(__name__).create_counter(...)` or histogram.
- `docs/IMPLEMENTATION_CONTRACT.md` OBS-1: "Every external call (database, Redis, HTTP, LLM inference, embedding API) must be wrapped in a span."
- `docs/IMPLEMENTATION_CONTRACT.md` OBS-2: "For each external call type, emit a success/error counter and a latency histogram."

Root cause: `ResearchRetriever` was implemented without OTel instrumentation. The existing LLM clients (`ImageryExtractor`, `MotifInductor`) were retrofitted with meters in FIX-5; the same treatment was not applied to `ResearchRetriever`.

Impact: External research API calls are invisible to observability tooling. Timeouts, failures, and latency cannot be detected without log scanning. OBS-1 violation: P2 (escalates to P1 at age cap per IMPLEMENTATION_CONTRACT). OBS-2 violation: P2.

Fix: Wrap `retrieve()` body in `tracer.start_as_current_span("research_retriever.retrieve")`; emit `get_meter(__name__).create_counter("research.retrieve_total")` with `{"status": "success"|"failure"}` attribute; record latency as a span attribute `research_retrieve_ms`. Add to FIX queue as FIX-7.

---

### ARCH-4 [P3] — `ARCHITECTURE.md §18` Header Still Reads `(Planned — Phase 10)` After Implementation

Symptom: Research Augmentation Layer section header indicates `Planned` while the layer is implemented.

Evidence:
- `docs/ARCHITECTURE.md:352` — `## 18. Research Augmentation Layer (Planned — Phase 10)`
- `app/research/retriever.py`, `app/research/synthesizer.py`, `app/services/research_service.py`, `app/api/research.py`, `app/models/research.py` — all exist and are wired into the application.

Root cause: Section header was not updated when Phase 10 implementation was committed.

Impact: Misleads readers into thinking the research layer is not yet active. Minor doc drift, consistent with ARCH-1.

Fix: Update `§18` header to `(Implemented — Phase 10)` and update the planned-components sub-table status column to `implemented`, consistent with the §17 Motif Abstraction Layer pattern.

---

## Right-Sizing / Runtime Checks

| Check | Verdict | Note |
|-------|---------|------|
| Solution shape (Workflow) still appropriate | PASS | Bounded tool-use loop (MAX_TOOL_ROUNDS=5); no autonomous loop; research augmentation is on-demand with explicit confirmation-before-execution per `docs/RESEARCH_AUGMENTATION.md §3`. System remains Workflow, not Agentic. |
| Deterministic-owned subproblems remain deterministic | PASS | Routing, segmentation, taxonomy CRUD, idempotency checks, confidence vocabulary enforcement, session ownership — all remain deterministic code paths. LLMs bounded to interpretation and synthesis tasks with validated output schemas. |
| Runtime tier (T1) unchanged / justified | PASS | `app/research/retriever.py` makes external HTTP via `asyncio.to_thread`; no shell mutation; no ad-hoc package installs at runtime. T1 boundary holds. |
| Human approval boundaries still valid | PASS | Taxonomy promotion remains behind authenticated API. Research augmentation requires confirmed motif status (human must have approved the motif via `PATCH /dreams/{id}/motifs/{id}`) and explicit user confirmation in the assistant flow before any external call executes. |
| Minimum viable control surface still proportionate | PASS | New surface is one API router, one service, two research submodules — all behind existing auth middleware and a default-off feature flag. No privilege escalation. |

---

## Retrieval Architecture Checks

| Check | Verdict | Note |
|-------|---------|------|
| Ingestion / query-time separation (no cross-import) | PASS | `app/retrieval/ingestion.py` does not import from `app/retrieval/query.py` and vice versa. Confirmed by code inspection. Enforcement tests documented in IMPLEMENTATION_CONTRACT. |
| `insufficient_evidence` path defined | PASS | `InsufficientEvidence` dataclass defined in `app/retrieval/query.py:51–53`; returned on empty query and on below-threshold evidence. Documented in `ARCHITECTURE.md §4` and `spec.md §4.3`. |
| Evidence/citation contract defined | PASS | `EvidenceBlock` in `app/retrieval/query.py:41–47` carries `dream_id`, `date`, `chunk_text`, `relevance_score`, `matched_fragments`. Contract is defined and implemented. |
| Freshness / max-index-age policy (24h, health endpoint) | PASS | `MAX_INDEX_AGE_HOURS=24` in `app/shared/config.py:25`; `GET /health` returns HTTP 503 and `status=degraded` when stale. |
| Index schema versioning (v1) | PASS | `INDEX_SCHEMA_VERSION = "v1"` declared at `app/retrieval/ingestion.py:21`. No schema change detected; no new ADR required. |
| Retrieval observability expectations | DRIFT | `retrieval_ms` span attribute set in `app/retrieval/query.py:101,111`. `insufficient_evidence` events logged via `logger.info`. However: no labeled OTel counter for `insufficient_evidence` rate as required by OBS-2 ("For RAG paths: `insufficient_evidence` rate as a labeled counter"). This is a carry-forward gap predating Phase 10, not a new regression. |

---

## Doc Patches Needed

| File | Section | Change |
|------|---------|--------|
| `docs/ARCHITECTURE.md` | §9 Target Components | Add `app/research/` row: `ResearchRetriever`, `ResearchSynthesizer`; status `implemented (Phase 10)`. Expand `app/services/` row to include `ResearchService`. |
| `docs/ARCHITECTURE.md` | §18 Research Augmentation Layer header | Change `(Planned — Phase 10)` to `(Implemented — Phase 10)`. Update planned-components sub-table status to `implemented`. |
| `docs/ARCHITECTURE.md` | §18 (line 414) Resolved Architectural Decisions | Renumber to `## 22. Resolved Architectural Decisions` (next available after §21). |

---

## Fix Queue Status Summary (Cycle 10 Baseline)

| Fix ID | Status | Evidence |
|--------|--------|---------|
| FIX-1 (session double-commit) | CLOSED | `motif_service.py` never calls `session.commit()`; caller owns commit — confirmed. |
| FIX-2 (idempotency guard) | CLOSED | Idempotency check at `motif_service.py:58–65` confirmed. |
| FIX-3 (`lru_cache` flag freeze / CODE-3) | OPEN — documented trade-off | `get_settings()` remains `@lru_cache`; `config.py:37–39`. ADR-010 §Consequences explicitly acknowledges process-restart requirement. Behavior is consistent with ADR. RISK-1 remains operationally relevant but is not an architectural violation. |
| FIX-4 (prompts module absent / CODE-4) | CLOSED | `app/assistant/prompts.py` exists with `SYSTEM_PROMPT` containing motif and research framing. |
| FIX-5 (OTel metrics on LLM paths / CODE-5) | CLOSED for `imagery.py` / `motif_inductor.py`; NEW GAP opened for `ResearchRetriever` (ARCH-3, P2) | |
| FIX-6 (stale TOOLS constant / CODE-6) | CLOSED | No module-level `TOOLS` constant in `tools.py`; `build_tools()` is the only entry point. |
| FIX-7 (new — ResearchRetriever OTel) | OPEN — P2 | `app/research/retriever.py:27–82`; no span, counter, or histogram on external HTTP call. See ARCH-3. |

---
