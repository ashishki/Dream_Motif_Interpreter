# CODEX_PROMPT.md

Version: 1.43
Date: 2026-04-25
Phase: Phase 16 planning — search quality, hallucination prevention, UX (Тест 4)

---

## Current State

- **Phase:** Phase 16 planning (WS-16.1–16.6)
- **Baseline:** 300 unit tests passing, 0 failed
- **Ruff:** clean (0 violations)
- **Last CI run:** passing (2026-04-25)
- **Last updated:** 2026-04-25 (Phases 13–15 complete — multi-source docs, write flow, doc-name clarity)

---

## Summary State

- **Phases completed:** Phase 1 through Phase 15 complete
- **Current planning state:** Phase 16 planning — search quality, hallucination prevention, sync notification, dream notes; see `docs/tasks_phase16.md`
- **Latest completed implementation task:** Phase 15 — doc-name clarity across all write paths (write_dream_to_google_doc → tuple[bool, str], CreatedDreamItem.written_to_doc_name, manage_archive_source list shows human-readable names)
- **Current baseline:** 300 unit tests passing
- **Archived task history:** older completed-task entries moved to `## Archived Tasks` per compaction protocol

---

## Continuity Pointers

- **Decision log:** `docs/DECISION_LOG.md`
- **Implementation journal:** `docs/IMPLEMENTATION_JOURNAL.md`
- **Evidence index:** `docs/EVIDENCE_INDEX.md`
- **Active task graph:** `docs/tasks_phase16.md` (Phase 16: WS-16.1–16.6)
- **Previous task graph (Phase 15):** `docs/tasks_phase15.md` (complete)
- **Previous task graph (Phase 14):** `docs/tasks_phase14.md` (complete)
- **Previous task graph (Phase 13):** `docs/tasks_phase13.md` (complete)
- **Previous task graph (Phase 12):** `docs/tasks_phase12.md` (complete)
- **Previous task graph (Phases 6–11):** `docs/tasks_phase6.md` through `docs/tasks_phase11.md`
- **Historical backend task graph:** `docs/tasks.md`
- **Task-scoped context:** read `Context-Refs` in the active task graph before broad searching

## Prompt Economy Rule

> Prefer pre-digested implementation prompts. Do not make Codex reconstruct narrow task context from multiple long docs unless the task genuinely needs broad retrieval.

For each WS: extract the exact `Context-Refs` lines, quote the relevant `old_string`, and pass Codex a surgical prompt with file paths, line numbers, and acceptance criteria. This rule applies to tasks where context is narrow and well-bounded. For tasks that genuinely require understanding of cross-cutting concerns (e.g. schema changes, ADR compliance, architectural drift), full doc retrieval is appropriate.

---

## Next Task

**WS-16.1 + WS-16.2 + WS-16.3 + WS-16.4 + WS-16.7 complete (2026-04-25). Next: WS-16.5.**

WS-16.5: Sync completion notification.
Baseline: 306 unit tests passing.
Design:
  1. trigger_sync → save in Redis sync_notify:{job_id} = chat_id, TTL 1h.
  2. app/workers/ingest.py after completion → read Redis, if chat_id → Bot API sendMessage.

Context refs:
- `docs/tasks_phase16.md` — Phase 16 task graph (WS-16.5–16.6 open)
- `app/assistant/tools.py` — trigger_sync tool
- `app/assistant/facade.py` — facade layer
- `app/workers/ingest.py` — ingest worker

---

## Fix Queue

─── Fix Queue (resolve before Phase 12 queue) ────────────────────────

✅ FIX-10 [P2] — GET /feedback missing OTel meter counter (OBS-2 violation)
  File: app/api/feedback.py · Change: add get_meter(__name__).create_counter("feedback.list_total") with {"status": "success"|"error"} attribute; emit on success path and on exception path; follow OBS-2 pattern in app/api/research.py · Test: assert counter is incremented with status="success" in test_feedback_api.py unit test after GET /feedback call with stub DB

✅ FIX-11 [P2] — AssistantFeedback ORM model missing score CheckConstraint
  File: app/models/feedback.py · Change: add __table_args__ = (sa.CheckConstraint("score >= 1 AND score <= 5", name="ck_assistant_feedback_score_range"),) to AssistantFeedback — mirrors the DDL constraint already present in alembic/versions/011_add_feedback.py · Test: assert that constructing AssistantFeedback with score=0 or score=6 and flushing to a test DB session raises IntegrityError (or that the constraint is present in model metadata)

✅ FIX-12 [P2] — retrieval_eval.md missing Cycle 11 advisory row (RET-7 violation)
  File: docs/retrieval_eval.md · Change: add Cycle 11 (2026-04-18) advisory row to §Evaluation History confirming RAG layer unchanged in Phase 11 (no modifications to chunking, embedding, ranking, or evidence assembly); T12 baseline metrics carry forward · Test: doc review — no automated test required

─── P3 findings (Fix Queue pass — resolve before Phase 12 gate) ──────

  CODE-4 [P3] — handlers.py feedback commit not guarded; DB failure suppresses FEEDBACK_ACK
    File: app/telegram/handlers.py:54–58 · Change: wrap session.commit() in try/except; log DB error; still send FEEDBACK_ACK reply
  CODE-5 [P3] — RESEARCH_API_KEY empty-string not validated at startup (Cycle 10 carry-forward — third cycle)
    File: app/shared/config.py:31 · Change: add model_validator that raises if RESEARCH_AUGMENTATION_ENABLED=True and RESEARCH_API_KEY="" — OR formally document acceptance in ADR-010 §Consequences and close the finding with a decision reference
  CODE-6 [P3] — _feedback_pending_by_chat dict unbounded, no TTL or size cap
    File: app/telegram/handlers.py:44, 74–79, 203–204 · Change: add max-size cap (e.g. maxsize=10_000) or TTL eviction — OR defer with DECISION_LOG entry
  CODE-7 [P3] — DECISION_LOG.md missing WS-11.4 deferral entry (D-014)
    File: docs/DECISION_LOG.md · Change: add D-014 entry recording WS-11.4 (optional comment capture) as explicitly deferred following D-012 pattern
  CODE-9 [P3] — ARCHITECTURE.md §19 header reads "(Planned — Phase 11)" despite WS-11.1–11.3 implemented
    File: docs/ARCHITECTURE.md:381 · Change: update §19 header to "(Implemented — Phase 11 WS-11.1–11.3)"; move assistant_feedback row from §20 Planned table to Current tables; annotate FeedbackService in §9 component table
  CODE-10 [P3] — IMPLEMENTATION_JOURNAL.md has no Phase 11 entry
    File: docs/IMPLEMENTATION_JOURNAL.md · Change: append Phase 11 entry covering WS-11.1–11.3 scope, D-014 deferral of WS-11.4, and test baseline 225

─── Closed Fix Queue items (Cycle 10 → Cycle 11) ──────────────────────

✅ FIX-7 [P2] — ResearchRetriever external HTTP call missing OTel span and counter
  File: app/research/retriever.py:27–82 · Change: wrap retrieve() body in tracer.start_as_current_span("research_retriever.retrieve"); emit get_meter(__name__).create_counter("research.retrieve_total") with {"status": "success"|"failure"} attribute; record latency as span attribute research_retrieve_ms · Test: assert counter incremented and span created after stub HTTP call

✅ FIX-8 [P2] — ResearchSynthesizer LLM call missing OTel span and counter
  File: app/research/synthesizer.py · Change: wrap synthesize() body in tracer.start_as_current_span("research_synthesizer.synthesize"); emit get_meter(__name__).create_counter("research.synthesis_total") with {"status": "success"|"failure"} attribute · Test: assert counter incremented and span created after stub LLM call

✅ FIX-9 [P3] — Doc patches: retrieval_eval advisory row + IMPLEMENTATION_JOURNAL Phase 10 entry + ARCHITECTURE.md drift
  Files: docs/retrieval_eval.md, docs/IMPLEMENTATION_JOURNAL.md, docs/ARCHITECTURE.md · Change: (a) add Cycle 10 advisory row to retrieval_eval.md Evaluation History confirming RAG layer unchanged in Phase 10; (b) append Phase 10 journal entry with WS-10.1–10.5 scope, decisions D-013/ADR-009/ADR-010, test baseline 216; (c) add app/research/ row and ResearchService to ARCHITECTURE.md §9; update §18 header to (Implemented — Phase 10); renumber duplicate §18 (Resolved Architectural Decisions) to §22 · Test: doc review — no automated test required

─── Closed Fix Queue items (Cycle 9 → Cycle 10) ──────────────────────

✅ FIX-1 [P2] — CLOSED — MotifService double-commit: `motif_service.py` never calls `session.commit()`; caller owns commit (confirmed Cycle 10)
✅ FIX-2 [P2] — CLOSED — Idempotency guard: confirmed at `motif_service.py:58–65` (confirmed Cycle 10)
✅ FIX-3 [P2] — CLOSED (documented trade-off) — `lru_cache` behavior acknowledged in ADR-010 §Consequences; process-restart requirement documented; not an architectural violation
✅ FIX-4 [P2] — CLOSED — `app/assistant/prompts.py` exists with full SYSTEM_PROMPT including motif and research framing (confirmed Cycle 10)
✅ FIX-5 [P2] — CLOSED — OTel counters and spans present on ImageryExtractor and MotifInductor LLM paths (confirmed Cycle 10)
✅ FIX-6 [P2] — CLOSED — No module-level `TOOLS` constant; `build_tools()` is the sole entry point (confirmed Cycle 10)

## Open Findings

_Cycle 12 — 2026-04-18 · 10 new findings: P0: 0, P1: 0, P2: 3, P3: 7 (CODE-8 resolved in this cycle; 9 Open); Cycle 11 findings: CODE-1/CODE-2/CODE-3/CODE-4/ARCH-1/ARCH-2/ARCH-4 all Closed (FIX-7/FIX-8/FIX-9 applied 2026-04-17); DOC-1 carry-forward resolved in this CODEX_PROMPT patch_

| ID | Sev | Description | Files | Status |
|----|-----|-------------|-------|--------|
| CODE-1 | P2 | `GET /feedback` emits an OTel span but no meter counter. OBS-2 requires a labeled counter per read route. | `app/api/feedback.py` | **Open** — new Cycle 12; see FIX-10 |
| CODE-2 | P2 | `AssistantFeedback` ORM model missing `sa.CheckConstraint` on `score` column. DDL constraint exists in migration `011_add_feedback.py`; ORM model omits it in `__table_args__`. | `app/models/feedback.py` | **Open** — new Cycle 12; see FIX-11 |
| CODE-3 | P2 | `docs/retrieval_eval.md §Evaluation History` missing Cycle 11 advisory row. RET-7 mandatory each cycle. RAG layer unchanged in Phase 11; T12 baseline metrics carry forward. | `docs/retrieval_eval.md` | **Open** — new Cycle 12; see FIX-12 |
| CODE-4 | P3 | `handlers.py` calls `session.commit()` after `FeedbackService.record()` with no try/except. Transient DB failure suppresses `FEEDBACK_ACK` reply to user. | `app/telegram/handlers.py:54–58` | **Open** — new Cycle 12 |
| CODE-5 | P3 | When `RESEARCH_AUGMENTATION_ENABLED=True`, `RESEARCH_API_KEY` defaults to `""` with no `model_validator` at startup. ADR-010 acknowledges deferral; no FIX assigned. Third cycle carry-forward. | `app/shared/config.py:31` | **Open** — Cycle 10 carry-forward (third cycle) |
| CODE-6 | P3 | `_feedback_pending_by_chat` dict in `context.bot_data` is unbounded. No TTL or max-size cap. Also triggers ADR-006 drift. | `app/telegram/handlers.py:44, 74–79, 203–204` | **Open** — new Cycle 12 |
| CODE-7 | P3 | `docs/DECISION_LOG.md` missing D-014 entry for WS-11.4 deferral. DECISION_LOG ends at D-013. GOV-5 violation. | `docs/DECISION_LOG.md` | **Open** — new Cycle 12 |
| CODE-9 | P3 | `docs/ARCHITECTURE.md §19` header reads `(Planned — Phase 11)`. WS-11.1–11.3 implemented. GOV-5 violation. | `docs/ARCHITECTURE.md:381` | **Open** — new Cycle 12 |
| CODE-10 | P3 | `docs/IMPLEMENTATION_JOURNAL.md` has no Phase 11 entry. WS-11.1–11.3 scope and test baseline 225 not recorded. GOV-5 violation. | `docs/IMPLEMENTATION_JOURNAL.md` | **Open** — new Cycle 12 |

_Cycle 9 findings (all Closed):_

| ID | Sev | Description | Files | Status |
|----|-----|-------------|-------|--------|
| CODE-1 (C9) | P2 | `MotifService.run()` calls `await session.commit()` on caller-provided session; double-commit risk | `app/services/motif_service.py:126` | **Closed** — FIX-1 confirmed in code (Cycle 10) |
| CODE-2 (C9) | P2 | No idempotency guard in `MotifService.run()` | `app/services/motif_service.py:114–123` | **Closed** — FIX-2 confirmed: guard at lines 58–65 (Cycle 10) |
| CODE-3 (C9) | P2 | `get_settings()` `@lru_cache` freezes `MOTIF_INDUCTION_ENABLED`; violates ADR-010 | `app/shared/config.py:33` | **Closed** — FIX-3: documented trade-off per ADR-010 §Consequences (Cycle 10) |
| CODE-4 (C9) | P2 | `app/assistant/prompts.py` absent; WS-9.6 deliverable unmet | `app/assistant/chat.py:18–42` | **Closed** — FIX-4 confirmed: prompts.py exists with full SYSTEM_PROMPT (Cycle 10) |
| CODE-5 (C9) | P2 | No OTel metrics counters on ImageryExtractor / MotifInductor LLM paths | `app/services/imagery.py`, `app/services/motif_inductor.py` | **Closed** — FIX-5 confirmed: counters and spans present (Cycle 10) |
| CODE-6 (C9) | P2 | Stale `TOOLS` module-level constant in tools.py | `app/assistant/tools.py:149` | **Closed** — FIX-6 confirmed: no TOOLS constant; build_tools() only (Cycle 10) |
| CODE-7 (C9) | P3 | No idempotency test for `MotifService.run()` | `tests/unit/test_motif_service.py` | **Closed** — idempotency guard present and covered (Cycle 10) |
| CODE-8 (C9) | P3 | No test asserting `handle_chat` uses `build_tools()` not `TOOLS` | `tests/unit/test_assistant_chat.py` | **Closed** — TOOLS constant removed; build_tools() is only path (Cycle 10) |
| CODE-9 (C9) | P3 | `docs/retrieval_eval.md` missing Cycle 9 advisory row | `docs/retrieval_eval.md` | **Closed** — advisory row added 2026-04-16 by Doc Updater |
| CODE-10 (C9) | P3 | No test for `facade.get_dream_motifs()` rejected-motifs filter | `tests/unit/test_assistant_facade.py` | **Closed** — WS-10.5 extended facade and tests (Cycle 10) |
| ARCH-5 (C9) | P3 | `docs/ARCHITECTURE.md` §17 Phase 9 listed as Planned; §16 baseline stale | `docs/ARCHITECTURE.md:306,340` | **Closed** — doc patch applied 2026-04-16 by Doc Updater |
| ARCH-7 (C9) | P3 | WS-9.7 deferral not recorded in `docs/DECISION_LOG.md` | `docs/DECISION_LOG.md` | **Closed** — D-012 added 2026-04-16 by Doc Updater |

_Cycle 8 findings (all Closed — archived below):_

_Cycle 8 — 2026-04-14 · 58 findings total: P1: 3, P2: 33, P3: 15 (58 Closed, 0 Open)_

| ID | Sev | Description | Files | Status |
|----|-----|-------------|-------|--------|
| CODE-1 | P2 | `dream_themes.status` has no CHECK constraint — invalid values persist silently. | `app/models/theme.py`, `alembic/versions/001_initial_schema.py` | **Closed** — FIX-1 applied 2026-04-12; `ck_dream_themes_status` added via migration 004; IntegrityError test passing |
| CODE-2 | P2 | Non-auth `HttpError` (e.g. 500) branch in `GDocsClient.fetch_document()` is untested. | `tests/unit/test_gdocs_client.py:39-49` | **Closed** — FIX-C5-2 applied 2026-04-13; `test_non_auth_http_error_propagates` added |
| CODE-3 | P2 | `app/api/health.py` stub `index_last_updated=None` has no `# TODO(T13):` comment. Add: `# TODO(T13): replace stub with real index_last_updated from DB; add HTTP 503 on staleness > MAX_INDEX_AGE_HOURS`. | `app/api/health.py:18` | **Closed** — T13 implemented real DB query; stub replaced; OTel span present; 503 staleness path wired; CODE-6 also resolved |
| CODE-4 | P2 | Config fail-fast test covers only `DATABASE_URL`; `tests/unit/test_config.py` absent; other 8 required secrets untested. Create file with parametrised `ValidationError` test for all 9 required secrets. | `tests/unit/test_config.py` (absent) | **Closed** — T14 applied 2026-04-14; `tests/unit/test_config.py` created with parametrised test for all required secrets |
| CODE-5 | P2 | Migration test missing `fragments IS NOT NULL` + CHECK domain assertions. | `tests/integration/test_migrations.py` | **Closed** — FIX-C5-2 applied 2026-04-13; NOT NULL assertion + positive-domain INSERT test added |
| CODE-6 | P2 | `test_health_index_last_updated_is_none` has no `# TODO(T13): update to assert ISO8601 timestamp` comment. | `tests/integration/test_health.py:38–49` | **Closed** — T13 resolves underlying stub; health tests updated to assert ISO8601 timestamp (closed with CODE-3) |
| CODE-7 | P3 | `app/main.py` binds `host="0.0.0.0"` unconditionally. Should default to `127.0.0.1` for non-production ENV. | `app/main.py` | **Closed** — FIX-C9 applied 2026-04-14; startup host now depends on `get_settings().ENV` |
| CODE-8 | P2 | `dream_themes.fragments` missing `server_default='[]'::jsonb` in migration 001. | `alembic/versions/001_initial_schema.py:143` | **Partially Closed** — migration 005 applied 2026-04-12; model-level `server_default` confirmed; migration test assertion (CODE-5) still absent |
| CODE-9 | P3 | `dream_themes` missing `deprecated` boolean column. | `app/models/theme.py`, `alembic/versions/001_initial_schema.py` | **Closed** — FIX-2 applied 2026-04-12; `002_add_deprecated_flag.py` migration added; column present |
| CODE-10 | P3 | `app/shared/tracing.py` dual-path singleton: `_get_provider()` uses mutable global; `get_tracer()` uses `lru_cache`. Inconsistent thread-safety semantics. Resolve at T13. | `app/shared/tracing.py` | **Closed** — T13 applied 2026-04-13; tracing provider now uses a single cached initialization path |
| CODE-11 | P2 | Three integration tests in `test_analysis.py` gated on `ANTHROPIC_API_KEY` despite using stubs. | `tests/integration/test_analysis.py` | **Closed** — FIX-C5-2 applied 2026-04-13; skipif guards removed; all 3 tests pass |
| CODE-12 | P2 | `StubGrounder` hardcodes `verified=True`; no `verified=False` path tested. | `tests/integration/test_analysis.py` | **Closed** — FIX-C5-2 applied 2026-04-13; second fragment set `verified=False`; assertion added |
| CODE-13 | P3 | `_segment_with_llm_fallback` in `segmentation.py` raises `NotImplementedError` referencing "T08" (now complete). Comment stale; no LLM fallback path test. Remove `type:ignore`; update comment to reference correct future task. | `app/services/segmentation.py:214–222` | **Closed** — FIX-C9 applied 2026-04-14; stale T08 reference removed and future-work TODO updated |
| CODE-14 | P2 | `docs/retrieval_eval.md` §Evaluation Dataset contains only placeholder rows; §Baseline Metrics all empty. Initialised from template (Cycle 3 partial fix); zero-corpus placeholder row acceptable for T10 gate; dataset must be populated before T12. | `docs/retrieval_eval.md` | **Closed** — T12 applied 2026-04-13; 10-query dataset and baseline metrics recorded |
| CODE-15 | P2 | DB calls in `analysis.py` and `taxonomy.py` not individually spanned (OBS-1 drift). Add per-call child spans for `session.get`, `session.execute`, `session.commit`. Resolve at T13. | `app/services/analysis.py:33–125`, `app/services/taxonomy.py:80–121` | **Closed** — T13 applied 2026-04-13; per-call DB child spans added for query and commit boundaries |
| CODE-16 | P3 | `003_seed_categories.py` inserts with `status='active'` with no governance exception comment. Add inline: "Bootstrap exception: migration-time seed bypasses approval gate; single-user system; AnnotationVersion records written." | `alembic/versions/003_seed_categories.py:46` | **Closed** — FIX-C9 applied 2026-04-14; governance exception comment added above the bootstrap seed insert |
| CODE-17 | P2 | `docs/CODEX_PROMPT.md` baseline and Next Task stale (was: 32 pass, 4 skip / T10 next). Updated to 35 pass, 6 skip by Cycle 3 consolidation. | `docs/CODEX_PROMPT.md` | **Closed** — baseline updated to 35 pass, 6 skip; Next Task updated; version bumped to v1.4 by Cycle 3 consolidation |
| CODE-18 | P2 | `docs/retrieval_eval.md §Evaluation Dataset` uses placeholder rows (Q01–Q03, Q-NA-01 with `{{query}}`). T12-AC-1 requires at least 10 real queries covering all four query types. | `docs/retrieval_eval.md` | **Closed** — T12 applied 2026-04-13; dataset now covers simple, multi-doc, multi-hop, and no-answer |
| CODE-19 | P1 | `OpenAIEmbeddingClient.embed()` has no HTTP error handling — uncaught `urllib.error.HTTPError` propagates to caller. No typed `EmbeddingServiceError`. No 429/500 tests. | `app/retrieval/ingestion.py:58–66` | **Closed** — FIX-C3-1 applied 2026-04-13; `EmbeddingServiceError` defined; 429/500 tests passing |
| CODE-20 | P1 | `_token_count()` uses `len(text.split())` (word count) instead of tiktoken token count. 512-token boundary contract violated; chunks can exceed context window by ~33%. | `app/retrieval/ingestion.py:238–239` | **Closed** — FIX-C3-2 applied 2026-04-13; tiktoken cl100k_base encoder; tests passing |
| CODE-21 | P2 | `EMBEDDING_MODEL = "text-embedding-ada-002"` contradicts ARCHITECTURE.md §Index Strategy (`text-embedding-3-small`). Must be fixed before any corpus embeddings are generated. | `app/retrieval/ingestion.py:19` | **Closed** — FIX-C3 applied 2026-04-13; model changed to `text-embedding-3-small` |
| CODE-22 | P2 | Integration RAG tests skip only on missing `OPENAI_API_KEY`; should also guard on DB availability. | `tests/integration/test_rag_ingestion.py:85–88, 117–120` | **Closed** — superseded by CODE-30 (DB guard added FIX-C4); formally closed Cycle 6 |
| CODE-23 | P2 | `test_chunking_boundary` missing 0-based `chunk_index` assertions for each produced chunk. | `tests/unit/test_rag_ingestion.py:13–27` | **Closed** — FIX-C3 applied 2026-04-13; chunk_index assertions added |
| CODE-24 | P2 | No per-request HTTP span on OpenAI call; OTel context not propagated into `asyncio.to_thread`. | `app/retrieval/ingestion.py:64–66, 122–126` | **Closed** — T13 applied 2026-04-13; shared OpenAI client adds request spans and propagates context into worker threads |
| CODE-25 | P2 | AC-4 cross-import test uses relative path — brittle in non-root CWD. Use `Path(__file__).resolve().parents[2] / "app/retrieval/ingestion.py"`. | `tests/unit/test_rag_ingestion.py:31` | **Closed** — FIX-C3 applied 2026-04-13; absolute path used |
| ARCH-1 | P2 | `app/retrieval/query.py` absent — T11 blocked; T10-AC-4 cross-import test cannot fully validate query-side. | `app/retrieval/query.py` | **Closed** — T11 complete 2026-04-13; `query.py` exists; cross-import tests passing |
| ARCH-2 | P2 | No HNSW index on `dream_chunks.embedding` — `006_add_hnsw_index.py` absent. T11 hard dependency for p95 < 3 s retrieval latency. | `alembic/versions/` | **Closed** — T11 pre-patch complete 2026-04-13; `006_add_hnsw_index.py` present; `autocommit_block()` pattern confirmed |
| ARCH-6 | P2 | LLM output framing at prompt level only; `"interpretation_note"` literal field not enforced in API response Pydantic models. | `app/llm/grounder.py:67`, `app/llm/theme_extractor.py:63` | **Closed** — T16 applied 2026-04-14; `interpretation_note` literal fields added to search and curation API response models |
| CODE-26 | P1 | `query.py` `_send_embedding_request()` has no `try/except urllib.error.HTTPError`; no typed `QueryEmbeddingError`; raw HTTP errors propagate to caller. Log policy: log `status_code` and `query_length`, NOT query text. | `app/retrieval/query.py:9, 256–258, 63` | **Closed** — FIX-C4-1 applied 2026-04-13; `QueryEmbeddingError` defined; 429/500 tests passing |
| CODE-27 | P2 | `query.py` missing `retrieval_ms` span attribute on `rag_query.retrieve` and `insufficient_evidence` structured log counter (OBS-2 RAG violation). **RAG P2 age cap: 1 cycle — must resolve in Cycle 5.** | `app/retrieval/query.py:84–110` | **Closed** — T12 applied 2026-04-13; `retrieval_ms` span attribute and structured insufficient-evidence logs added |
| CODE-28 | P2 | `CODEX_PROMPT.md` stale after T11: baseline 41/6, Next Task T11, version v1.4. | `docs/CODEX_PROMPT.md:12,32` | **Closed** — resolved by Cycle 4 consolidation 2026-04-13; baseline → 42/10, Next Task → T12, version → v1.5 |
| CODE-29 | P2 | `EVIDENCE_INDEX.md` EV-002/EV-003 still Pending after T10/T11; IMPLEMENTATION_JOURNAL T11 entry absent. | `docs/EVIDENCE_INDEX.md:20–21` | **Closed** — FIX-C4 applied 2026-04-13; EV-002/EV-003 set Active |
| CODE-30 | P2 | Integration RAG tests skip only on missing `OPENAI_API_KEY`; `or not os.getenv("TEST_DATABASE_URL")` guard absent. (Carry-forward CODE-22.) | `tests/integration/test_rag_ingestion.py:85–88, 117–120` | **Closed** — FIX-C4 applied 2026-04-13; DB guard added |
| CODE-31 | P2 | `tests/unit/test_rag_query.py` has only the cross-import test; no unit test for empty-query `InsufficientEvidence` path (no DB or API needed). | `tests/unit/test_rag_query.py` | **Closed** — FIX-C4 applied 2026-04-13; empty-query test added |
| CODE-32 | P2 | `OpenAIEmbeddingClient` duplicated across `ingestion.py` and `query.py` with diverging implementations. Create `app/retrieval/types.py` shared client. | `app/retrieval/query.py:23–66`, `app/retrieval/ingestion.py:32–80` | **Closed** — T13 applied 2026-04-13; shared OpenAI embedding client moved to `app/retrieval/types.py` |
| ARCH-7 | P3 | `app/api/health.py` missing `# TODO(T13): instrument _fetch_index_last_updated with a dedicated OTel span and p95 latency tracking` comment before the DB call in the `health()` handler. | `app/api/health.py:27–61` | **Closed** — T13 implementation confirmed; OTel span present in `health.py`; instrumentation wired |
| ARCH-8 | P2 | `retrieval_ms` span attribute and `insufficient_evidence` rate counter absent from `query.py` — OBS-2 RAG violation. **RAG P2 age cap: 1 cycle.** (Same root as CODE-27; tracked together.) | `app/retrieval/query.py:84–110` | **Closed** — resolved with CODE-27 in T12 on 2026-04-13 |
| ARCH-9 | P3 | `ARCHITECTURE.md §File Layout` migration listing ends at `004_fix_status_ck.py`; `005_add_fragments_default.py` and `006_add_hnsw_index.py` absent from diagram. | `docs/ARCHITECTURE.md:366–370` | **Closed** — migrations 005 and 006 now correctly listed in ARCHITECTURE.md §File Layout (verified Cycle 6 ARCH_REPORT) |
| ARCH-10 | P3 | Query expansion (LLM call to `claude-haiku-4-5`) not wired in `query.py`; declared in ARCHITECTURE.md §RAG Architecture and spec.md §6 AC-5. Not a T11 AC violation. | `app/retrieval/query.py:84–110` | **Closed** — FIX-C9 applied 2026-04-14; retrieval now attempts Anthropic query expansion and falls back to the original query on failure |
| ARCH-11 | P3 | `EvidenceBlock.matched_fragments` is `list[str]`; spec.md §Retrieval requires `match_type` labels and character offsets per fragment. Partial contract. | `app/retrieval/query.py:28–34` | **Closed** — FIX-C9 applied 2026-04-14; `FragmentMatch` metadata now flows through retrieval and search responses |
| CODE-33 | P1 | `_send_embedding_request` double-raises; async `except HTTPError` is dead code in both `query.py` and `ingestion.py`. The sync helper already converts HTTPError to typed error; the async guard can never fire. Remove `except urllib_error.HTTPError` from `embed()` in both files. | `app/retrieval/query.py:77–81`, `app/retrieval/ingestion.py:73–77` | **Closed** — FIX-C5-1 applied 2026-04-13; dead guard removed; typed errors propagate correctly |
| CODE-34 | P2 | `health.py` bare `except Exception` without logging; silently swallows DB failure; health reports ok/null instead of degraded. Add `logger.warning("health.fetch_index_last_updated failed", exc_info=True)` before `return None`. | `app/api/health.py:56–61` | **Closed** — T13 applied 2026-04-13; failure path now logs with `exc_info=True` before returning `None` |
| CODE-35 | P2 | Migration test missing `fragments IS NOT NULL` assertion and positive CHECK domain INSERT test (draft/confirmed/rejected). Supersedes CODE-5. | `tests/integration/test_migrations.py` | **Closed** — FIX-C5-2 applied 2026-04-13 (same fix batch as CODE-5) |
| CODE-36 | P2 | Three analysis integration tests skip on `ANTHROPIC_API_KEY` despite using stub doubles. Remove all three `@pytest.mark.skipif` decorators. Supersedes CODE-11. | `tests/integration/test_analysis.py:167–170, 213–216, 250–253` | **Closed** — FIX-C5-2 applied 2026-04-13 (same fix batch as CODE-11) |
| CODE-37 | P2 | `StubGrounder verified=True` hardcoded; no `verified=False` path. Set `verified=False` for second fragment; assert it. Supersedes CODE-12. | `tests/integration/test_analysis.py:110, 118` | **Closed** — FIX-C5-2 applied 2026-04-13 (same fix batch as CODE-12) |
| CODE-38 | P2 | `tests/unit/test_config.py` absent; 8 required secrets untested for `ValidationError`. Create parametrised test for all 8 required secrets. Supersedes CODE-4. | `tests/unit/test_config.py` (absent) | **Closed** — T14 applied 2026-04-14; parametrised config test created (same fix batch as CODE-4) |
| CODE-39 | P2 | `docs/retrieval_eval.md §Answer Quality Metrics` all rows show `—`; no completed answer quality eval run against synthetic corpus. Run before T14. | `docs/retrieval_eval.md` | **Closed** — T14 applied 2026-04-14; answer quality metrics populated in retrieval_eval.md |
| CODE-40 | P3 | `scripts/eval.py` hard-codes `TASK_ID = "T12"`. Should be a runtime argument or derived from context. | `scripts/eval.py` | **Closed** — FIX-C9 applied 2026-04-14; eval runs now accept `--task-id` with `T12` as the default |
| CODE-41 | P3 | `_evaluation_history_table` overwrites full history on every write run instead of appending. | `scripts/eval.py` | **Closed** — FIX-C9 applied 2026-04-14; evaluation history rows are appended in place and covered by a unit test |
| CODE-42 | P2 | T16 primary deliverable `app/api/themes.py` absent — pre-implementation expected; assigned to T16. | `app/api/themes.py` | **Closed** — T16 applied 2026-04-14; curation router implemented and registered in `app/main.py` |
| CODE-43 | P2 | `BULK_CONFIRM_TOKEN_TTL_SECONDS` config slot absent from `app/shared/config.py`; T16 bulk-confirm TTL has no config home. Must add before T16. | `app/shared/config.py` | **Closed** — T16 verified config slot present and bulk confirm flow uses it for Redis token TTL |
| CODE-44 | P2 | `interpretation_note` absent from all API response Pydantic models (`SearchResultItem`, `SearchResultsResponse`, `DreamThemeResponseItem`). ARCH-6 carry-forward. Assign to T16; escalates to P1 if not closed Cycle 7. | `app/api/search.py:27–57`, `app/llm/theme_extractor.py:63`, `app/llm/grounder.py:67` | **Closed** — T16 applied 2026-04-14; literal framing field added to the affected API response models |
| CODE-45 | P2 | `tests/integration/test_curation_api.py` absent — T16 integration test file does not yet exist. | `tests/integration/test_curation_api.py` | **Closed** — T16 applied 2026-04-14; curation integration suite added with AC coverage for confirm/reject, bulk approval, auth, and version writes |
| CODE-46 | P2 | `_redact_pii` strips only `raw_text`; `chunk_text` and `justification` not stripped. PII policy gap. | `app/api/search.py` (redact helper) | **Closed** — T16 applied 2026-04-14; shared tracing redaction now strips `raw_text`, `chunk_text`, and `justification` |
| CODE-47 | P2 | CODE-22 explicit disposition absent — formally closed as superseded by CODE-30. | `tests/integration/test_rag_ingestion.py` | **Closed** — superseded by CODE-30 (Cycle 6 disposition) |
| ARCH-10 | P3 | LLM query expansion not wired in `query.py`; declared in ARCHITECTURE.md §RAG Architecture. | `app/retrieval/query.py:84–110` | **Closed** — FIX-C9 applied 2026-04-14; query expansion is wired with graceful fallback semantics |
| ARCH-11 | P3 | `EvidenceBlock.matched_fragments` is `list[str]`; spec requires `match_type` labels and character offsets. Partial contract. | `app/retrieval/query.py:28–34` | **Closed** — FIX-C9 applied 2026-04-14; evidence fragments now include `text`, `match_type`, and `char_offset` |
| ARCH-12 | P3 | Session factory duplicated in `search.py` and `dreams.py` — private `lru_cache` per module; no shared DB module. | `app/api/search.py:151–163`, `app/api/dreams.py:166–173` | **Closed** — FIX-C9 applied 2026-04-14; shared session factory extracted to `app/shared/database.py` |
| ARCH-13 | P2 | `BULK_CONFIRM_TOKEN_TTL_SECONDS` absent from `app/shared/config.py` (same root as CODE-43). | `app/shared/config.py` | **Closed** — resolved with CODE-43 in T16 on 2026-04-14 |
| ARCH-14 | P3 | Worker files `app/workers/ingest.py` and `app/workers/index.py` declared in ARCHITECTURE.md but absent. | `app/workers/` | **Closed** — T17 applied 2026-04-14; both worker files created and registered in ARCHITECTURE.md §File Layout |
| ARCH-15 | P3 | `docs/adr/` directory does not exist; IMPLEMENTATION_CONTRACT requires ADRs for schema changes and runtime tier expansion. | `docs/adr/` | **Closed** — FIX-C9 applied 2026-04-14; ADR directory, README, and initial ADRs were added |
| ARCH-12-E | P3 | Session factory `_get_session_factory()` now imported into 4 API modules (dreams, search, patterns, versioning). Should be extracted to `app/shared/database.py`. Worsened by T18/T19. | `app/api/patterns.py:10`, `app/api/versioning.py:9`, `app/api/search.py:179`, `app/api/dreams.py:201` | **Closed** — FIX-C9 applied 2026-04-14; all affected routers now import the shared `get_session_factory()` helper |
| CODE-48 | P2 | `ingest_document` initial Redis status write (status="running") not in try/finally block. Transient Redis failure leaves job ID untracked; subsequent "done"/"failed" writes orphaned. | `app/workers/ingest.py:37` | **Closed** — FIX-C8 applied 2026-04-14; initial Redis write now logs and continues on failure; worker completion test added |
| CODE-49 | P2 | Redis client in `themes.py` and `dreams.py` uses `lru_cache(maxsize=1)` but is never closed. No connection pool configured. Potential connection leak in long-running processes. | `app/api/themes.py:259-262`, `app/api/dreams.py:308-315` | **Closed** — FIX-C8 applied 2026-04-14; Redis client is now a shared module-level singleton with FastAPI shutdown close path |
| CODE-50 | P2 | Bulk confirm token parsing in `themes.py` lacks explicit `isinstance(..., list)` type guard on `parsed_payload["dream_ids"]`. Non-list value raises unhandled `TypeError`. | `app/api/themes.py:117-121` | **Closed** — FIX-C8 applied 2026-04-14; non-list `dream_ids` now returns HTTP 410; malformed-token integration test added |
| DOC-1 | P2 | `docs/IMPLEMENTATION_JOURNAL.md` last entry is T13 (2026-04-13); entries for T14, T15, T16, T17 absent. Retrieval continuity degraded for future agents. | `docs/IMPLEMENTATION_JOURNAL.md` | **Closed** — T14 through T20 journal entries are present as of 2026-04-14 |

---

## Profile State: RAG

- RAG Status: ON
- Active corpora: dream_entries (full pipeline implemented — ingestion, chunking, embedding, pgvector indexing complete at T10; hybrid query pipeline complete at T11; HNSW index live)
- Retrieval baseline: synthetic-20-entries baseline established at T12 (`hit@3=1.00`, `MRR=1.00`, `no-answer accuracy=1.00`)
- Open retrieval findings: none
- Index schema version: v1 (implemented in ingestion.py; HNSW index migration 006 applied)
- Pending reindex actions: none
- Retrieval-related next tasks: none
- Retrieval-driven tasks: none

---

## Tool-Use State

- Tool-Use Profile: OFF
- Registered tool schemas: n/a
- Unsafe-action guardrails: n/a
- Open tool findings: none

---

## Agentic State

- Agentic Profile: OFF
- Active agent roles: n/a
- Loop termination contract version: n/a
- Cross-iteration state mechanism: n/a
- Open agent findings: none

---

## Planning State

- Planning Profile: OFF
- Plan schema version: n/a
- Plan validation method: n/a
- Open plan findings: none

---

## Compliance State

- Compliance Status: OFF
- Active frameworks: n/a
- Controls implemented: n/a
- Controls partial: n/a
- Controls not started: n/a
- Evidence artifact: n/a
- Open compliance findings: none

---

## NFR Baseline

- API p99 latency: not yet measured
- Error rate: not yet measured
- Throughput: not yet measured
- Last measured: —
- NFR regression open: No

---

## Evaluation State

### Last Evaluation

- Profile: RAG
- Task: T15
- Date: 2026-04-14
- Eval Source: `scripts/eval.py` against `docs/retrieval_eval.md §Evaluation Dataset` (10 queries), run 2026-04-14 against `synthetic-20-entries`; stub embeddings (test-key)
- Metric(s): hit@3, MRR, no-answer accuracy
- Score: `hit@3=1.00`, `MRR=1.00`, `no-answer accuracy=1.00`
- Baseline: T12 baseline (1.00 / 1.00 / 1.00)
- Delta: 0 (no change — search API layer does not modify retrieval semantics)
- Regression: No

### Open Evaluation Issues

none

### Evaluation History

| Date | Task | Profile | Key metric | Score | Baseline | Delta | Regression? |
|------|------|---------|------------|-------|----------|-------|-------------|
| 2026-04-12 | T10 | RAG | hit@3, MRR | N/A (zero corpus) | N/A | N/A | No |
| 2026-04-13 | T12 | RAG | hit@3, MRR, no-answer accuracy | 1.00 / 1.00 / 1.00 | initial seeded baseline | N/A | No |
| 2026-04-14 | T15 | RAG | hit@3, MRR, no-answer accuracy | 1.00 / 1.00 / 1.00 | T12 baseline | 0 | No |

---

## Completed Tasks

- **WS-11.3** — GET /feedback API Route — 2026-04-17 — 225 tests passing — GET /feedback endpoint implemented in app/api/feedback.py; pagination (limit/offset); protected by global X-API-Key middleware; not in PUBLIC_PATHS; OTel span present; WS-11.3 AC-1 through AC-5 met; unit tests in tests/unit/test_feedback_api.py
- **WS-11.2** — Telegram Digit-Reply Capture — 2026-04-17 — 225 tests passing — digit-reply detection in app/telegram/handlers.py; FeedbackService.record() in app/services/feedback_service.py; "Rate this response: reply with 1–5." appended after substantive responses; "Thanks, noted." on capture; context JSONB stores message_id, response_summary, tool_calls_made (no raw dream text); WS-11.2 AC-1 through AC-6 met
- **WS-11.1** — DB Migration and ORM Model — 2026-04-17 — 225 tests passing — 011_add_feedback.py migration creates assistant_feedback table; AssistantFeedback ORM model in app/models/feedback.py; exported from app/models/__init__.py; score CHECK constraint in DDL; assistant_feedback excluded from RAG ingestion pipeline; WS-11.1 AC-1 through AC-5 met
- **WS-10.5** — Assistant Tool + Facade Method — 2026-04-17 — 216 tests passing — AssistantFacade.research_motif_parallels() added; research_motif_parallels tool registered in build_tools() gated by RESEARCH_AUGMENTATION_ENABLED; SYSTEM_PROMPT updated with confirmation-before-execution rule and speculative framing requirements; tool absent when flag is false; WS-10.5 AC-1 through AC-5 met
- **WS-10.4** — API Routes — 2026-04-17 — 216 tests passing — GET /motifs/{id}/research and POST /motifs/{id}/research implemented in app/api/research.py; POST returns 503 when RESEARCH_AUGMENTATION_ENABLED=false; response carries literal interpretation_note; routes covered by unit tests; registered in app/main.py
- **WS-10.3** — ResearchService Orchestrator + Persistence — 2026-04-17 — 216 tests passing — ResearchService.run() orchestrates retriever and synthesizer; raises on non-confirmed motif; caller owns session commit; does not write to dream_entries/dream_themes/dream_chunks; triggered_by propagated from caller
- **WS-10.2** — ResearchRetriever + ResearchSynthesizer — 2026-04-17 — 216 tests passing — ResearchRetriever wraps external HTTP via asyncio.to_thread; 5-result limit; 5-second timeout; ResearchAPIError on failure; ResearchSynthesizer enforces {speculative, plausible, uncertain} confidence vocabulary; ResearchSynthesisError on LLM parse failure; both testable with stubs
- **WS-10.1** — DB Migration and ORM Model — 2026-04-17 — 216 tests passing — 010_add_research_results migration adds research_results table with all required columns; ResearchResult ORM model in app/models/research.py; no existing table modified; research_results excluded from RAG ingestion pipeline
- **P6-T02** — Assistant Service Facade — 2026-04-15 — 104 tests passing, 9 skipped — AssistantFacade created in app/assistant/; exposes search_dreams, get_dream, list_recent_dreams, get_patterns, get_theme_history, trigger_sync; returns dataclass DTOs; no ORM leakage; mutation methods absent; 5 unit tests added
- **P6-T01** — Reconcile Backend Execution Boundary — 2026-04-15 — 99 tests passing, 9 skipped — ingest worker now calls AnalysisService and index_dream after storing entries; _collect_pipeline_targets detects missing themes/chunks; resync skips complete stages; fetch_document offloaded via asyncio.to_thread; ARCHITECTURE.md §4 updated with explicit runtime contract
- **FIX-C9** — Technical Debt — P3 Findings — 2026-04-14 — 98 tests passing, 9 skipped — CODE-7/13/16/40/41 and ARCH-10/11/12/12-E/15 closed via environment-aware host binding, retrieval query expansion fallback, structured fragment metadata, shared DB session factory extraction, eval history append logic, and ADR documentation
- **FIX-C8** — Technical Debt — P2 Findings — 2026-04-14 — 95 tests passing, 9 skipped — CODE-48/49/50 closed via guarded initial Redis status writes, shared Redis client shutdown, and malformed bulk-confirm token handling; prompt continuity refreshed
- **T20** — End-to-End Integration Test — 2026-04-14 — 93 tests passing, 9 skipped — end-to-end sync-to-search coverage added with test-only pipeline orchestration; flow now exercises sync, analysis, search, bulk curation approval, pattern APIs, rollback history, and cleanup assertions
- **T19** — Annotation Versioning and Rollback — 2026-04-14 — 91 tests passing, 9 skipped — authenticated theme history and rollback APIs implemented; rollback appends a new AnnotationVersion; append-only guard coverage added
- **T18** — Archive-Level Pattern Detection — 2026-04-14 — 87 tests passing, 9 skipped — `/patterns/recurring`, `/patterns/co-occurrence`, and `/patterns/timeline` implemented with computational-pattern disclaimer framing and generated timestamps

---

## Archived Tasks

- **T17** — Background Worker Setup with Idempotency — 2026-04-14 — 83 tests passing, 9 skipped — Redis-backed sync job status, idempotent ingest/index workers, and integration coverage for done/failed worker outcomes implemented
- **T16** — User Curation API — Theme Confirmation and Taxonomy Management — 2026-04-14 — 79 tests passing, 9 skipped — confirm/reject theme mutations, Redis-backed bulk confirm approval flow, category approval auth gate, and write-ahead AnnotationVersion coverage implemented
- **T15** — Dream Browsing and Theme Search API — 2026-04-14 — 74 tests passing, 9 skipped — GET /search and GET /dreams/{id}/themes implemented; authenticated search returns ranked evidence with theme matches; insufficient_evidence and theme filter paths covered
- **T14** — Ingestion and Sync API Endpoints — 2026-04-14 — 70 tests passing, 9 skipped — POST /sync, GET /sync/{job_id}, GET /dreams, GET /dreams/{id}; API key auth; CODE-4/38/39 closed
- **T01** — Project Skeleton — 2026-04-12 — 3 tests passing — Light review PASS
- **T02** — CI Setup — 2026-04-12 — 5 tests passing — Light review PASS
- **T03** — Smoke Tests — 2026-04-12 — 8 tests passing — Light review PASS
- **T04** — Database Schema — 2026-04-12 — 13 tests passing — Cycle 1 review PASS (P2/P3 findings CODE-1, CODE-5, CODE-8, CODE-9 logged; no P0/P1)
- **T05** — Google Docs Ingestion Client — 2026-04-12 — 17 tests passing, 1 skipped — Cycle 1 review PASS (P2 finding CODE-2 logged; no P0/P1)
- **T06** — Dream Segmentation Service — 2026-04-12 — 21 tests passing, 1 skipped — Light review PASS
- **T07** — Theme Taxonomy System — 2026-04-12 — 27 tests passing, 1 skipped — Light review PASS
- **T08** — Per-Dream Theme Extraction (LLM) — 2026-04-12 — 30 tests passing, 2 skipped — Light review PASS
- **T09** — Salience Ranking and Fragment Grounding — 2026-04-12 — 32 tests passing, 4 skipped — Light review PASS
- **T10** — RAG Ingestion Pipeline — 2026-04-13 — 41 tests passing, 6 skipped — Cycle 3 deep review PASS (P1: CODE-19/CODE-20 resolved; P2: CODE-21/CODE-23/CODE-25 resolved; ARCH-2 still open)
- **T11** — RAG Query Pipeline — 2026-04-13 — 42 tests passing, 10 skipped — Cycle 4 deep review PASS (ARCH-1/ARCH-2 closed; P1: CODE-26 open/FIX-C4-1 required; P2: CODE-27 open RAG age-cap 1 cycle)
- **FIX-C4** — Query HTTP error handling + CODE-29/30/31 — 2026-04-13 — 46 tests passing, 10 skipped
- **T12** — Retrieval Evaluation Baseline — 2026-04-13 — 48 tests passing, 12 skipped — synthetic-20-entries baseline recorded (`hit@3=1.00`, `MRR=1.00`, `no-answer accuracy=1.00`); CODE-27 / ARCH-8 closed; Phase 3 gate PASS
- **FIX-C5** — Dead HTTPError guard + aging P2 group (CODE-2/5/11/12/33) — 2026-04-13 — 55 tests passing, 9 skipped
- **Cycle 5 consolidation** — 2026-04-13 — FIX-C5-1 (CODE-33, P1) and FIX-C5-2 (CODE-2/5/11/12 aging group) assigned; CODE-3/CODE-6/ARCH-7 closed by T13 implementation; REVIEW_REPORT.md Cycle 4 archived to docs/audit/archive/PHASE3_CYCLE4_REVIEW.md; CODEX_PROMPT.md bumped to v1.7; Phase 4 begins
- **T13** — Health Endpoint and Observability — 2026-04-13 — 57 tests passing, 9 skipped — health freshness semantics finalized; request JSON logs include trace metadata; CODE-10/15/24/32/34 closed

---

## Phase History

---

## Compaction Protocol

### Compaction triggers

Compact when EITHER condition is true:
- `## Completed Tasks` contains more than 20 entries, OR
- `## Phase History` contains more than 5 phase summaries

### How to compact

1. Create or update a `## Summary State` section immediately after `## Current State`.
2. In `## Completed Tasks`: retain the 5 most recent entries. Move older entries to `## Archived Tasks`.
3. In `## Phase History`: retain the 2 most recent phase summaries. Move older to `## Archived Phase History`.
4. Do NOT delete any content — only move older entries to Archive sections.

---

## Instructions for Codex

Read these instructions every time you pick up a task. Do not skip steps.

### Pre-Task Protocol (mandatory — do not skip)

1. **Read `docs/IMPLEMENTATION_CONTRACT.md`** — before anything else. Know the rules before touching code.
2. **Read the full active task in `docs/tasks_phase16.md`** — including all acceptance criteria, file lists, and notes. For historical reference use `docs/tasks_phase15.md` (Phase 15) or earlier phase files.
3. **Read all Depends-On tasks** — understand the interface contracts your task must satisfy.
4. **Read task `Context-Refs` and continuity artifacts as needed** — required when the task resolves a finding, changes a risky boundary, or depends on prior decisions / evidence.
5. **Run `pytest -q`** — capture the current baseline. Record: `N passing, M failed`. If M > 0, stop and report: you cannot add failures to an already-failing baseline.
6. **Run `ruff check`** — must exit 0. If not, fix ruff issues first. Commit the ruff fix separately with message `chore(lint): resolve ruff issues`. Then re-run the pre-task protocol.
7. **Write tests before or alongside implementation.** Every acceptance criterion has exactly one corresponding test (or more, never zero).

### During Implementation

- Work on one task at a time.
- Read only the files you need. Use `grep` to find relevant sections first.
- Do not modify files outside the task's scope without documenting why.
- If you discover an interface mismatch or missing dependency, stop and report it. Do not silently patch adjacent tasks.
- If you supersede a prior decision or close a repeated finding, update `docs/DECISION_LOG.md`, `docs/IMPLEMENTATION_JOURNAL.md`, and `docs/EVIDENCE_INDEX.md` as applicable.

### Post-Task Protocol

1. Run `pytest -q` — baseline must be ≥ pre-task baseline. If lower, something broke; fix it before committing.
2. Run `ruff check app/ tests/` — must exit 0.
3. Run `ruff format --check app/ tests/` — must exit 0.
4. **If this task has a capability tag** (`rag:*`) — evaluation is required before marking DONE:
   - Update `docs/retrieval_eval.md` with current results.
   - Compare against baseline. Document any regression in §Regression Notes.
   - Update `docs/CODEX_PROMPT.md §Evaluation State §Last Evaluation` with the result summary.
   - Do NOT return `IMPLEMENTATION_RESULT: DONE` until this is complete.
5. Update this file (`docs/CODEX_PROMPT.md`):
   - New baseline (number of passing tests)
   - Move this task to "Completed Tasks"
   - Set "Next Task" to the next task
   - Add any new open findings discovered during this task
6. Commit with format: `type(scope): description` — one logical change per commit.
7. If the task produced multiple logical changes (migration + service + tests), use multiple commits.

### Return Format

When done, return exactly:

```
IMPLEMENTATION_RESULT: DONE
New baseline: {N} passing tests
Commits: {list of commit hashes and messages}
Notes: {anything the orchestrator should know — surprises, deviations, decisions made}
```

When blocked, return exactly:

```
IMPLEMENTATION_RESULT: BLOCKED
Blocker: {exact description of what is blocking progress}
Type: dependency | interface_mismatch | environment | ambiguity
Recommended action: {what the orchestrator or human should do}
Progress made: {what was completed before hitting the blocker}
```

### Commit Message Format

```
type(scope): short description (imperative mood, ≤72 chars)

Optional body: explain why, not what. The diff shows the what.
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`, `security`

Do not include:
- `Co-Authored-By` lines
- Credentials or secrets
- TODO comments without a task reference (`# TODO: see T{NN}`)
- Commented-out code
- `print()` debugging statements
