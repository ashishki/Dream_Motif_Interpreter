---
# REVIEW_REPORT — Cycle 5
_Date: 2026-04-13 · Scope: T12–T13 (Retrieval Evaluation Baseline + Health/Observability)_

## Executive Summary

- **Stop-Ship: No** — one P1 finding (CODE-33) must be resolved as FIX-C5-1 before T13 closes. No P0 issues.
- Phase 3 (T10–T12) is complete. RAG evaluation baseline recorded: `hit@3=1.00`, `MRR=1.00`, `no-answer accuracy=1.00` against synthetic-20-entries corpus. FIX-C4-1 (CODE-26) closed prior to T12 gate.
- Baseline: **48 passing, 12 skipped** — net +2 pass, +2 skip from Cycle 4 close (46/10). No regressions.
- CODE-3 and ARCH-7 closed: T13 implementation confirmed `app/api/health.py` with real DB query for `index_last_updated`, 503 staleness path, and OTel span present.
- New CODE findings this cycle: CODE-33 (P1, dead `except HTTPError` code in both query.py and ingestion.py), CODE-34 (P2, health.py bare `except Exception` without logging), CODE-35 (P2, migration test missing IS NOT NULL and CHECK domain assertions), CODE-36 (P2, three analysis integration tests with spurious skipif guards), CODE-37 (P2, StubGrounder verified=True hardcoded), CODE-38 (P2, test_config.py absent), CODE-39 (P2, retrieval_eval.md §Answer Quality Metrics incomplete), CODE-40 (P3, eval.py hardcodes TASK_ID), CODE-41 (P3, evaluation history table overwrites on every run).
- Four aging P2 carry-forwards (CODE-2, CODE-5, CODE-11, CODE-12) have exceeded the 3–4 cycle age cap. These are grouped into FIX-C5-2 and must be resolved before T13 closes. CODE-35/CODE-36/CODE-37 overlap with and supersede their respective aging entries.
- Phase 4 begins with T13. Pre-T13 fix tasks FIX-C5-1 (P1, CODE-33) and FIX-C5-2 (aging P2 group) must close before T13 is marked DONE.

---

## P0 Issues

_None._

---

## P1 Issues

### P1-1 — CODE-33: `_send_embedding_request` Double-Raises; async `except HTTPError` is Dead Code in Both `query.py` and `ingestion.py`

**Symptom:** The async `embed()` methods in both `OpenAIEmbeddingClient` classes contain an `except urllib_error.HTTPError` guard that can never fire. The sync helper `_send_embedding_request()` already converts `HTTPError` into a typed exception (`QueryEmbeddingError` / `EmbeddingServiceError`). By the time the async caller's `except urllib_error.HTTPError` block is reached, the typed error has already been raised. The dead `except` block creates false confidence that two-level error handling exists when only one level is active.

**Evidence:**
- `app/retrieval/query.py:77–81` — async `embed()` `except urllib_error.HTTPError` (dead)
- `app/retrieval/query.py:283–289` — same pattern in `_send_embedding_request` wrapper
- `app/retrieval/ingestion.py:73–77` — async `embed()` `except urllib_error.HTTPError` (dead)
- `app/retrieval/ingestion.py:83–89` — same pattern in `_send_embedding_request` wrapper

**Root Cause:** When FIX-C3-1 and FIX-C4-1 were applied to add typed error handling in the sync helper, the async caller's `except HTTPError` guard was not removed. The typed conversion now fires first; the dead guard has never been reachable since those fixes.

**Impact:** P1 — dead error-handling code at the async boundary. If the sync helper is ever refactored to re-raise `HTTPError` directly (e.g. during CODE-32 shared-client refactor), the dead guard becomes silently active with unexpected behavior. It creates false confidence in error coverage and is a latent correctness risk entering Phase 4.

**Fix:** Remove the `except urllib_error.HTTPError` guard in `OpenAIEmbeddingClient.embed()` in both `app/retrieval/query.py` and `app/retrieval/ingestion.py`. Let the typed error from the sync helper propagate directly to callers. Verify: the existing 429/500 unit tests (`test_query_embed_raises_on_429`, `test_query_embed_raises_on_500`, `test_embed_raises_on_429`, `test_embed_raises_on_500`) continue to pass — they test the sync helper path, which is unchanged.

**Verify:** All four existing embed error unit tests pass. Grep confirms no `except urllib_error.HTTPError` in `embed()` method bodies in either file.

---

## P2 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-34 | `health.py` bare `except Exception` without logging; silently swallows DB failure causing health to report ok/null instead of degraded. Add `logger.warning("health.fetch_index_last_updated failed", exc_info=True)` before `return None`. | `app/api/health.py:56–61` | Open — new Cycle 5 |
| CODE-35 | Migration test missing `fragments IS NOT NULL` assertion and positive CHECK domain insert test (draft/confirmed/rejected). Supersedes CODE-5 carry-forward assertion gap. | `tests/integration/test_migrations.py` | Open — new Cycle 5; carry-forward CODE-5 (4 cycles) now assigned FIX-C5-2 |
| CODE-36 | Three analysis integration tests skip on `ANTHROPIC_API_KEY` despite using stub doubles. Remove all three `@pytest.mark.skipif` decorators. Supersedes CODE-11 carry-forward. | `tests/integration/test_analysis.py:167–170, 213–216, 250–253` | Open — new Cycle 5; carry-forward CODE-11 (4 cycles) now assigned FIX-C5-2 |
| CODE-37 | `StubGrounder verified=True` hardcoded; no `verified=False` path exercised. Make one stub fragment `verified=False`; assert it. Supersedes CODE-12 carry-forward. | `tests/integration/test_analysis.py:110, 118` | Open — new Cycle 5; carry-forward CODE-12 (4 cycles) now assigned FIX-C5-2 |
| CODE-38 | `tests/unit/test_config.py` absent; 8 required secrets untested for `ValidationError`. Create parametrised test for all 8 required secrets. Supersedes CODE-4 carry-forward. | `tests/unit/test_config.py` (absent) | Open — carry-forward CODE-4 (4 cycles); must resolve before T14 |
| CODE-39 | `docs/retrieval_eval.md §Answer Quality Metrics` has all rows showing `—`; no completed answer quality eval run. Run against synthetic corpus before T14. | `docs/retrieval_eval.md` | Open — new Cycle 5; RET-7 violation |
| CODE-2 | Non-auth `HttpError` (e.g. 500) branch in `GDocsClient.fetch_document()` untested; no parametrised re-raise test. | `tests/unit/test_gdocs_client.py:39–49` | Open — carry-forward 4 cycles; now assigned FIX-C5-2 |

---

## Carry-Forward Status

| ID | Sev | Description | Status | Change |
|----|-----|-------------|--------|--------|
| CODE-2 | P2 | Non-auth `HttpError` (e.g. 500) branch in `GDocsClient.fetch_document()` untested | Open — assigned FIX-C5-2 | Assigned; was unassigned 4 cycles |
| CODE-3 | P2 | `app/api/health.py` stub `index_last_updated=None` missing `# TODO(T13):` comment | **Closed** — T13 implemented real DB query; stub replaced; OTel span confirmed present | Closed by T13 |
| CODE-4 | P2 | `tests/unit/test_config.py` absent; 8 required secrets untested | Open — superseded by CODE-38 (FIX-C5-2 boundary) | Reassigned; must resolve before T14 |
| CODE-5 | P2 | Migration test missing `fragments IS NOT NULL` and CHECK constraint domain assertions | Open — superseded by CODE-35 (FIX-C5-2) | Assigned; was unassigned 4 cycles |
| CODE-6 | P2 | `test_health_index_last_updated_is_none` missing `# TODO(T13):` comment | **Closed** — T13 resolves the underlying stub; health tests updated to assert ISO8601 timestamp | Closed by T13 |
| CODE-7 | P3 | `app/main.py` binds `host="0.0.0.0"` unconditionally | Open — carry-forward | No change; schedule before T14 deploy |
| CODE-10 | P3 | `app/shared/tracing.py` dual-path singleton inconsistent thread-safety | Open — resolves at T13 | No change; T13 in scope |
| CODE-11 | P2 | Three integration tests gated on `ANTHROPIC_API_KEY` despite using stubs | Open — superseded by CODE-36 (FIX-C5-2) | Assigned; was unassigned 4 cycles |
| CODE-12 | P2 | `StubGrounder verified=True` hardcoded; `verified=False` path not tested | Open — superseded by CODE-37 (FIX-C5-2) | Assigned; was unassigned 4 cycles |
| CODE-13 | P3 | `_segment_with_llm_fallback` stale `NotImplementedError` T08 reference | Open — carry-forward | No change |
| CODE-15 | P2 | DB calls in `analysis.py` and `taxonomy.py` not individually OTel-spanned | Open — resolves at T13 | No change; T13 in scope |
| CODE-16 | P3 | `003_seed_categories.py` missing governance exception comment | Open — carry-forward | No change; trivial doc fix |
| CODE-24 | P2 | No per-request HTTP span on OpenAI call in `ingestion.py`; OTel not propagated into `asyncio.to_thread` | Open — resolves at T13 | No change; T13 in scope |
| CODE-32 | P2 | `OpenAIEmbeddingClient` duplicated across `ingestion.py` and `query.py` with diverging implementations | Open — must ship with T13 or as FIX-C5-1; deferred past T14 is not acceptable | P2 age cap applies |
| ARCH-4 | P3 | `docs/adr/` directory absent; no ADR governance records | Open — governance gap | No change; no assigned task |
| ARCH-6 | P2 | `interpretation_note` literal field not enforced in Pydantic response models | Open — resolves at T15/T16 | No change |
| ARCH-7 | P3 | `app/api/health.py` missing T13 OTel span handoff comment | **Closed** — T13 implementation confirmed OTel span present in `health.py` | Closed by T13 |
| ARCH-9 | P3 | `ARCHITECTURE.md §File Layout` migration listing incomplete (005, 006 absent) | Open — doc drift | No change |
| ARCH-10 | P3 | Query expansion (LLM) not wired in `query.py` | Open — resolves at T15 | No change |
| ARCH-11 | P3 | `EvidenceBlock.matched_fragments` lacks `match_type` and character offsets | Open — must resolve before T15 | No change |

---

## Stop-Ship Decision

**No** — Stop-Ship criteria are not met. There are no P0 findings. One P1 finding (CODE-33) must be resolved as FIX-C5-1 before T13 closes. The four aging P2 carry-forwards (CODE-2/CODE-5/CODE-11/CODE-12, now superseded by CODE-35/36/37 and grouped under FIX-C5-2) must also close before T13 is marked DONE. All Phase 3 (T10–T12) acceptance criteria are verified PASS. The system is in a stable state entering Phase 4.

---
_Cycle 5 complete. Cycle 4 REVIEW_REPORT archived to `docs/audit/archive/PHASE3_CYCLE4_REVIEW.md`._
_Next: archive this file to `docs/audit/archive/PHASE4_CYCLE5_REVIEW.md` before Cycle 6._
