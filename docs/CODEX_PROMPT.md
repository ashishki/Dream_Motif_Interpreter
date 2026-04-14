# CODEX_PROMPT.md

Version: 1.21
Date: 2026-04-14
Phase: 6-planning

---

## Current State

- **Phase:** 6 planning
- **Baseline:** 98 passing tests, 9 skipped
- **Ruff:** clean (0 violations)
- **Last CI run:** not yet configured
- **Last updated:** 2026-04-14 (Phase 6+ documentation rewrite for Telegram and voice evolution)
- **Session tokens (approx):** not yet tracked
- **Cumulative phase tokens (approx):** not yet tracked

---

## Summary State

- **Phases completed:** Phase 1 through Phase 5 complete for the backend platform
- **Current planning state:** Phase 6+ target architecture, roadmap, and operations docs prepared for Telegram text, voice, and deployment evolution
- **Latest completed implementation task:** FIX-C9 — Technical Debt — P3 Findings
- **Current baseline:** 98 passing tests, 9 skipped
- **Archived task history:** older completed-task entries moved to `## Archived Tasks` per compaction protocol

---

## Continuity Pointers

- **Decision log:** `docs/DECISION_LOG.md`
- **Implementation journal:** `docs/IMPLEMENTATION_JOURNAL.md`
- **Evidence index:** `docs/EVIDENCE_INDEX.md`
- **Active task graph:** `docs/tasks_phase6.md`
- **Historical backend task graph:** `docs/tasks.md`
- **Task-scoped context:** read `Context-Refs` in the active task graph before broad searching

---

## Next Task

Implementation planning and execution for the Phase 6 Telegram interaction foundation.
Read first:

- `docs/ARCHITECTURE.md`
- `docs/PHASE_PLAN.md`
- `docs/tasks_phase6.md`
- `docs/TELEGRAM_INTERACTION_MODEL.md`
- `docs/VOICE_PIPELINE.md`
- `docs/ENVIRONMENT.md`
- `docs/AUTH_SECURITY.md`
- `~/Documents/dev/ai-stack/projects/film-school-assistant` as the implementation reference for interaction-layer patterns

Before coding, resolve the documented open decisions around:

- Phase 6 scope boundary
- transcription provider
- Telegram ingress mode
- session persistence
- Google Docs credential mode if service-account JSON is adopted

---

## Fix Queue

### FIX-C9: Closed

All 9 carry-forward P3 findings are now closed. No new tasks remain.

---

**CODE-7** — `app/main.py`
`uvicorn.run()` binds `host="0.0.0.0"` unconditionally. Change to bind `127.0.0.1` when `ENV != "production"` and `0.0.0.0` otherwise. Read `get_settings().ENV` to decide. No new tests required (existing smoke tests cover the app startup path).

**CODE-13** — `app/services/segmentation.py`
`_segment_with_llm_fallback()` raises `NotImplementedError` with a stale comment referencing "T08". Replace the comment and `type: ignore` with: `# TODO(future): implement LLM-based boundary detection fallback; T08 is complete but this path was deferred`. Remove the `type: ignore` annotation if it is no longer needed. No behaviour change; no new tests.

**CODE-16** — `alembic/versions/003_seed_categories.py`
The `status='active'` insert at the bootstrap seed has no governance exception comment. Add the inline comment before the insert block:
```python
# Bootstrap exception: migration-time seed bypasses the approval gate.
# Single-user system; AnnotationVersion records are not written for seed data.
# This is intentional and documented in IMPLEMENTATION_CONTRACT.md §Taxonomy Mutation Gate.
```
No behaviour change; no new tests.

**CODE-40** — `scripts/eval.py`
`TASK_ID = "T12"` is hardcoded. Replace with a CLI argument:
```python
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--task-id", default="T12", help="Task ID to tag this eval run")
args = parser.parse_args()
TASK_ID = args.task_id
```
Keep the `default="T12"` so existing usage without arguments is unchanged. No new tests required.

**CODE-41** — `scripts/eval.py`
`_evaluation_history_table()` (or equivalent) overwrites the full history on every run. Change it to append the new row instead of rebuilding the table from scratch. Read the existing `## Evaluation History` section from `docs/retrieval_eval.md`, append the new row, and write back only the updated section. Do not lose prior rows. Add a unit test `tests/unit/test_eval_script.py::test_eval_history_appends` that verifies calling the append function twice results in two rows, not one.

**ARCH-10** — `app/retrieval/query.py`
LLM query expansion is declared in ARCHITECTURE.md §RAG Architecture but not wired. Wire it:
1. Add a method `_expand_query_terms(query: str) -> str` to `RagQueryService` that calls the Anthropic client (`claude-haiku-4-5-20251001`) with a short system prompt: `"Expand the following dream search query with related symbolic and thematic synonyms. Return only the expanded query, no explanation."` and the user query as the message. Use `max_tokens=100`.
2. Call `_expand_query_terms` at the top of `retrieve()` before embedding, replacing the original query text for embedding purposes only. The original query string must still be logged/spanned as `query_length` (not the expanded version).
3. Guard against API failure: if the Anthropic call raises any exception, log a structured warning and fall back to the original query. Do not propagate the expansion failure to the caller.
4. The Anthropic client should use `get_settings().ANTHROPIC_API_KEY`. Import `anthropic` (already a dependency via `anthropic` package used in `app/services/analysis.py`).
5. Add a unit test `tests/unit/test_rag_query_expansion.py::test_query_expansion_fallback` that verifies: when the Anthropic client raises an exception, `retrieve()` still returns a result using the original query (mock the embedding call to return a fixed vector).
6. Skip tests that make real Anthropic API calls (use `pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY") or os.getenv("ENV") == "test", ...)` or mock the client entirely).

**ARCH-11** — `app/retrieval/query.py`, `app/api/search.py`
`EvidenceBlock.matched_fragments` is `list[str]`; spec requires `match_type` and `char_offset` per fragment. Change the type:
1. In `app/retrieval/query.py`, define a new dataclass:
```python
@dataclass(frozen=True)
class FragmentMatch:
    text: str
    match_type: str  # "keyword" | "semantic"
    char_offset: int  # character offset of the match start within the chunk
```
2. Change `EvidenceBlock.matched_fragments: list[str]` → `matched_fragments: list[FragmentMatch]`.
3. In the retrieval logic, populate `match_type="semantic"` and `char_offset=0` (stub values — exact offsets require full-text alignment which is out of scope; stub is acceptable and honest).
4. Update `app/api/search.py` response models: `matched_fragments` in `SearchResultItem` becomes `list[dict]` (serialised `FragmentMatch`). Or add a `FragmentMatchItem` Pydantic model.
5. Update any test that asserts on `matched_fragments` to use the new structure.
6. No new tests required beyond fixing existing ones.

**ARCH-12 / ARCH-12-E** — Session factory duplication
Extract `_get_session_factory()` to a single shared function. Steps:
1. Create `app/shared/database.py` with:
```python
from functools import lru_cache
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.shared.config import get_settings

@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(get_settings().DATABASE_URL)
    return async_sessionmaker(engine, expire_on_commit=False)
```
2. Replace the private `_get_session_factory()` definitions in `app/api/dreams.py`, `app/api/search.py`, `app/api/patterns.py`, and `app/api/versioning.py` with imports of `get_session_factory` from `app.shared.database`.
3. Remove the now-unused local definitions. Ensure `themes.py` (which imported from `dreams.py`) is also updated.
4. Run all tests to verify nothing broke. No new tests required.

**ARCH-15** — `docs/adr/`
Create the ADR directory and write the first ADR:
1. Create `docs/adr/README.md` with a one-paragraph description of the ADR convention (title, date, status, context, decision, consequences).
2. Create `docs/adr/ADR-001-append-only-annotation-versioning.md` documenting decision D-007 (append-only AnnotationVersion). Use the standard ADR format.
3. Create `docs/adr/ADR-002-single-user-api-key-auth.md` documenting the API key auth approach (decision D-005 or equivalent from DECISION_LOG.md).
No code changes; no tests required.

---

After all fixes:
1. `pytest -q` → baseline ≥ 95 passing, 9 skipped.
2. `ruff check app/ tests/ scripts/` and `ruff format --check app/ tests/ scripts/` → clean.
3. Update `docs/CODEX_PROMPT.md`:
   - Close all 9 P3 findings.
   - Update findings header count.
   - Set Next Task: "No open findings — project complete."
   - Bump version to 1.20.
4. Commit: `fix(debt): FIX-C9 — close all P3 technical debt`

---

## Open Findings

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
2. **Read the full active task in `docs/tasks_phase6.md` for Phase 6+ work, or in `docs/tasks.md` for historical/backend follow-up work** — including all acceptance criteria, file lists, and notes.
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
