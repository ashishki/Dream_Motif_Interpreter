---
# ARCH_REPORT — Cycle 11
_Date: 2026-04-18_

## Component Verdicts

| Component | Verdict | Note |
|-----------|---------|------|
| `app/telegram/handlers.py` | DRIFT | In-memory `_feedback_pending_by_chat` dict lives in `context.bot_data` (unbounded, no TTL); violates the durable-state principle of ADR-006 for persistent bot state; see ARCH-1 |
| `app/services/feedback_service.py` | PASS | Thin service layer; score validation logic is here, not in the handler or API; no HTTP imports; correct layer placement |
| `app/api/feedback.py` | DRIFT | API layer is thin (layer integrity PASS), but emits no meter counter on the read path — OBS-2 compliance gap (WS11-2); see ARCH finding note |
| `app/models/feedback.py` | DRIFT | ORM model omits `CheckConstraint` on `score` that exists in the DDL migration; ORM layer is inconsistent with the database schema definition; see ARCH-2 |
| `alembic/versions/011_add_feedback.py` | PASS | Migration includes `ck_assistant_feedback_score_range` CHECK constraint; all required columns present per WS-11.1 AC-1 |
| `app/models/__init__.py` | PASS | Exports `AssistantFeedback`; satisfies WS-11.1 AC-5 |
| `app/main.py` | PASS | `feedback_router` registered; `/feedback` not in `PUBLIC_PATHS`; `require_authentication` middleware applies globally; no bypass path exists |
| `app/retrieval/ingestion.py` | PASS | No import of `app.retrieval.query`; ingestion/query layer boundary intact |
| `app/retrieval/query.py` | PASS | No import of `app.retrieval.ingestion`; ingestion/query layer boundary intact |

---

## Contract Compliance

| Rule | Verdict | Note |
|------|---------|------|
| SQL Safety — parameterized queries only | PASS | All SQL in Phase 11 components uses SQLAlchemy ORM `select()`; no string interpolation observed |
| Async Redis — async client only | PASS | No Redis access introduced in Phase 11 components |
| Authorization — every route enforces auth before data access | PASS | `GET /feedback` is not in `PUBLIC_PATHS`; global `require_authentication` middleware at `main.py:46–53` applies; no bypass path exists |
| PII Policy — no dream content in logs/spans/errors | PASS | `response_summary` captures `result.text[:200]` (assistant response text, not raw dream text); `tool_calls_made` stores tool call names only; no `raw_text`, `chunk_text`, or `dream_text` present in Phase 11 code |
| Shared Tracing Module — all spans via `get_tracer()` | PASS | All Phase 11 files that create spans import from `app.shared.tracing` |
| OBS-1 — every external call wrapped in a span | PASS | `db.query.feedback.list` span present at `app/api/feedback.py:33` |
| OBS-2 — success/error counter + latency per external call; RAG `insufficient_evidence` counter | DRIFT | `GET /feedback` emits an OTel span but no meter counter (WS11-2 open finding); all other read routes emit labeled counters per OBS-2; RAG counters unchanged and PASS |
| OBS-3 — Health endpoint returns `index_last_updated`; 503 when stale beyond `MAX_INDEX_AGE_HOURS` | PASS | `app/api/health.py:31–38` enforces this; public and unauthenticated per design |
| Annotation Versioning — append-only `annotation_versions` before mutations | PASS | Phase 11 components make no writes to `dream_themes`, `theme_categories`, or `annotation_versions` |
| Taxonomy Mutation Gate — no automated promotion/rename/delete | PASS | Phase 11 introduces no taxonomy mutation paths |
| Idempotent Workers | PASS | Phase 11 introduces no background workers |
| Ingestion/Query Separation — no cross-imports between `ingestion.py` and `query.py` | PASS | Confirmed by inspection: no cross-imports exist in either module |
| Dream Content Isolation — dream text only via parameterized DB queries | PASS | Phase 11 code does not access `raw_text`, `chunk_text`, or `dream_text` |
| LLM Output Framing | PASS | Phase 11 introduces no new LLM calls |
| Runtime Tier T1 — no shell mutation, no ad-hoc package installs | PASS | Phase 11 code is standard application code; no runtime escalation |
| Credentials and Secrets | PASS | No credentials or secrets found in Phase 11 source files |

---

## ADR Compliance

| ADR | Verdict | Note |
|-----|---------|------|
| ADR-001: Append-Only Annotation Versioning | PASS | `assistant_feedback` has no FK to `dream_themes` or `annotation_versions`; no mutation to versioned tables in Phase 11 |
| ADR-002: Single-User API Key Auth | PASS | `GET /feedback` protected by global API key middleware; `/feedback` is not in `PUBLIC_PATHS` |
| ADR-003: Telegram Adapter Inside Core Repo | PASS | Phase 11 Telegram feedback capture extends `app/telegram/handlers.py` in-repo; no new external service introduced |
| ADR-004: Bounded Assistant Tool Facade | PASS | `handlers.py` continues to call `AssistantFacade` for chat; `FeedbackService` is called directly from the handler as a side-channel capture (not an assistant tool action), which is acceptable |
| ADR-005: Managed Transcription First | PASS | Phase 11 makes no changes to the transcription path |
| ADR-006: Persist Bot Session State Durably | DRIFT | ADR-006 mandates durable PostgreSQL persistence for bot state; `_feedback_pending_by_chat` is in-memory only in `context.bot_data`; state is lost on bot restart; `bot_sessions` table is not used for this pending state; see ARCH-1 |
| ADR-007: Compose-First Telegram Deployment | PASS | Phase 11 makes no deployment topology changes |
| ADR-008: Inducted Motifs and Taxonomy Themes Separate | PASS | Phase 11 does not touch `motif_inductions` or `dream_themes` |
| ADR-009: Research Results Carry Speculative Confidence Labels | PASS | Phase 11 makes no changes to the research layer |
| ADR-010: Feature Flag Gating | PASS | No new feature flag needed for the feedback loop (WS-11.1–11.3 are always-on passive capture; consistent with the flag intent); `RESEARCH_API_KEY` startup validation gap (CODE-5) is a carry-forward, not a new Phase 11 regression |

---

## Architecture Findings

### ARCH-1 [P3] — Feedback Pending State Not Durable (ADR-006 Drift)

Symptom: `_feedback_pending_by_chat` dict is stored in `context.bot_data` in memory only. Bot restart discards all pending feedback state.

Evidence: `app/telegram/handlers.py:44`, `app/telegram/handlers.py:74–79`, `app/telegram/handlers.py:203–204`

Root cause: ADR-006 establishes the principle that bot state requiring restart safety should be persisted in PostgreSQL (`bot_sessions` table). The feedback pending state was implemented as an unbounded in-memory dict rather than as a JSONB column in `bot_sessions` or a separate ephemeral record. This is also the WS11-3 open finding.

Impact: (1) Pending feedback state lost on every bot process restart. (2) Stale entries accumulate indefinitely with no TTL or max-size cap. (3) Multi-instance deployment (if ever introduced) would produce split-brain feedback state.

Fix: Either (a) persist pending feedback context in the `bot_sessions` row via a `feedback_pending` JSONB column, or (b) explicitly accept the ephemeral behavior with a deferral decision recorded in `docs/DECISION_LOG.md` and a bounded max-size cap on the dict.

---

### ARCH-2 [P2] — ORM Model Missing CheckConstraint (Schema / ORM Divergence)

Symptom: `AssistantFeedback` ORM model defines `score` as `SmallInteger()` with no `CheckConstraint`. The migration DDL correctly adds `ck_assistant_feedback_score_range`. Direct ORM usage bypassing `FeedbackService.record()` has no model-level protection.

Evidence: `app/models/feedback.py:22`, `alembic/versions/011_add_feedback.py:47–50`

Root cause: The DDL constraint was applied in the migration but not mirrored in the ORM model's `__table_args__`. This is the WS11-1 open finding.

Impact: Any code path that creates an `AssistantFeedback` instance without going through `FeedbackService.record()` (e.g., future test fixtures, admin scripts, data migrations) will accept out-of-range scores at the application layer and only fail at the database level.

Fix: Add `sa.CheckConstraint("score >= 1 AND score <= 5", name="ck_assistant_feedback_score_range")` to `AssistantFeedback.__table_args__` in `app/models/feedback.py`.

---

### ARCH-3 [P3] — ARCHITECTURE.md §19 Header Still Marks Feedback as Planned

Symptom: `ARCHITECTURE.md §19` header reads `## 19. Feedback Model (Planned — Phase 11)`. WS-11.1, WS-11.2, and WS-11.3 are implemented.

Evidence: `docs/ARCHITECTURE.md:381`

Root cause: Doc patch cycle not applied after Phase 11 partial implementation close.

Impact: New readers cannot determine the implementation status of the feedback layer from the architecture document. The §20 Planned Storage Model table still lists `assistant_feedback` as a planned addition.

Fix: (1) Update §19 header to `## 19. Feedback Loop (Implemented — Phase 11 WS-11.1–11.3)`. (2) Move `assistant_feedback` from the §20 Planned additions table to the Current tables list. (3) Add or annotate the `app/services/` component row in §9 to reflect the Phase 11 `FeedbackService` addition.

---

### ARCH-4 [P3] — WS-11.4 Deferral Not Recorded in DECISION_LOG.md

Symptom: WS-11.4 (optional comment capture) is not yet implemented. There is no decision log entry for this deferral.

Evidence: `docs/audit/META_ANALYSIS.md:47–48`, `docs/DECISION_LOG.md` (ends at D-013; no WS-11.4 entry)

Root cause: The WS-9.7 deferral precedent (D-012) was not followed for WS-11.4.

Impact: Deferred scope is not tracked canonically. Risk of silent omission when Phase 11 gate is declared closed.

Fix: Add D-014 to `docs/DECISION_LOG.md`: WS-11.4 (optional comment capture) deferred; rating-only feedback is sufficient for the current quality signal purpose; comment capture may be added in a future phase.

---

### ARCH-5 [P3] — retrieval_eval.md Missing Cycle 11 Advisory Row

Symptom: `docs/retrieval_eval.md §Evaluation History` ends at the Cycle 10 (2026-04-17) advisory row. No Cycle 11 advisory row exists.

Evidence: `docs/retrieval_eval.md:206` (last row is Cycle 10)

Root cause: The mandatory-each-cycle retrieval evaluation advisory row was not added for Phase 11.

Impact: RET-7 rule violation. Retrieval evaluation history is incomplete for Cycle 11.

Fix: Add a Cycle 11 advisory row to `docs/retrieval_eval.md §Evaluation History` confirming the RAG layer is unchanged in Phase 11 (no modifications to chunking, embedding, ranking, or evidence assembly); T12 baseline metrics carry forward.

---

## Right-Sizing / Runtime Checks

| Check | Verdict | Note |
|-------|---------|------|
| Solution shape (Workflow) still appropriate | PASS | Phase 11 adds a passive feedback capture side-channel only; no autonomous agent behavior introduced; workflow-shaped backend unchanged |
| Deterministic-owned areas remain deterministic | PASS | Score validation, routing, segmentation, taxonomy CRUD all remain deterministic; `FeedbackService.record()` is a simple validation + ORM insert with no LLM involvement |
| Runtime tier (T1) unchanged / justified | PASS | No shell mutation, no ad-hoc package installs, no privileged runtime management in Phase 11 code; T1 maintained |
| Human approval boundaries still valid | PASS | Taxonomy promotion, rename, and delete still require an authenticated API call; Phase 11 introduces no automated mutation paths |
| Minimum viable control surface still proportionate | PASS | The feedback loop is explicitly a quality signal for human review only, not an automated retraining pipeline (`ARCHITECTURE.md §19`); control surface is proportionate to a single-user private deployment |

---

## Retrieval Architecture Checks

| Check | Verdict | Note |
|-------|---------|------|
| Ingestion / query-time separation (no cross-import) | PASS | `ingestion.py` has no import of `query`; `query.py` has no import of `ingestion`; confirmed by code inspection |
| `insufficient_evidence` path defined | PASS | `InsufficientEvidence` dataclass at `app/retrieval/query.py:51–53`; returned when evidence fails `relevance_threshold`; referenced in `ARCHITECTURE.md §11` and `spec.md §4.3` |
| Evidence/citation contract defined | PASS | `EvidenceBlock` at `query.py:42–48` carries `dream_id`, `date`, `chunk_text`, `relevance_score`, `matched_fragments`; `FragmentMatch` at `query.py:34–38` carries `text`, `match_type`, `char_offset`; contract fully defined |
| Freshness / max-index-age policy (24h, health endpoint) | PASS | `app/api/health.py:31–38` enforces `MAX_INDEX_AGE_HOURS`; returns HTTP 503 on stale index; endpoint is unauthenticated and documented public per OBS-3 |
| Index schema versioning (v1) | PASS | `INDEX_SCHEMA_VERSION = "v1"` declared at `app/retrieval/ingestion.py:21`; documented in `docs/retrieval_eval.md §Schema Version`; ADR required before schema change is enforced by contract |
| Retrieval observability expectations | PASS | `retrieval_ms` span attribute set at `app/retrieval/query.py:101` and `query.py:111`; `insufficient_evidence` logged via `logger.info` at `query.py:99` and `query.py:115` |

---

## Doc Patches Needed

| File | Section | Change |
|------|---------|--------|
| `docs/ARCHITECTURE.md` | §19 header | Change `(Planned — Phase 11)` to `(Implemented — Phase 11 WS-11.1–11.3)` |
| `docs/ARCHITECTURE.md` | §20 Planned Storage Model | Move `assistant_feedback` row from Planned additions table to the Current tables list |
| `docs/ARCHITECTURE.md` | §9 Component Table | Add note or row for `app/services/feedback_service.py` (feedback persistence, Phase 11) |
| `docs/DECISION_LOG.md` | Decision Index | Add D-014 recording WS-11.4 (optional comment capture) deferral |
| `docs/retrieval_eval.md` | §Evaluation History | Add Cycle 11 advisory row confirming RAG layer unchanged in Phase 11 |
| `docs/CODEX_PROMPT.md` | §Current State | Update baseline test count from 216 to 225 (DOC-1 carry-forward) |

---
