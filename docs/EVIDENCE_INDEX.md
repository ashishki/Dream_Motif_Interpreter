# Evidence Index — Dream Motif Interpreter

Version: 1.4
Last updated: 2026-05-20
Status: append-only

---

## Purpose

Lookup table for proof artifacts across review cycles, retrieval evaluations, and heavy tasks. Each entry points to a canonical artifact. This file does not replace the artifact; it indexes it.

---

## Index

| ID | Type | Task | Date | Artifact | What it proves | Status |
|----|------|------|------|----------|----------------|--------|
| EV-001 | retrieval-baseline | T12 | TBD | `docs/retrieval_eval.md §Baseline Metrics` | Initial hit@3, MRR, no-answer accuracy on seeded 20-entry corpus | Pending |
| EV-002 | test-coverage | T10 | 2026-04-13 | `tests/unit/test_rag_ingestion.py::test_ingestion_does_not_import_query_module` | Ingestion and query-time code are in separate modules | Active |
| EV-003 | test-coverage | T11 | 2026-04-13 | `tests/integration/test_rag_query.py::test_retrieve_returns_insufficient_evidence_for_zero_match` | `insufficient_evidence` path is implemented and tested | Active |
| EV-004 | test-coverage | T09 | TBD | `tests/unit/test_grounder.py::test_fragment_text_matches_source_offsets` | Fragment grounding offsets are verified against source text | Pending |
| EV-005 | test-coverage | T19 | 2026-04-14 | `tests/unit/test_versioning.py::test_no_delete_or_update_on_annotation_versions` | annotation_versions table is append-only in all code paths | Active |
| EV-006 | test-coverage | T13 | 2026-04-13 | `tests/integration/test_health.py::test_health_returns_ok_with_fresh_index` | Health endpoint returns 200 with ISO8601 freshness timestamp for a fresh index | Active |
| EV-007 | test-coverage | T13 | 2026-04-13 | `tests/unit/test_tracing.py::test_log_fields_present_and_no_pii` | Request logs include trace metadata and exclude `raw_text` PII | Active |
| EV-008 | test-coverage | T18 | 2026-04-14 | `tests/integration/test_patterns_api.py::test_patterns_include_disclaimer` | Pattern endpoints include the required computational-pattern disclaimer and generation timestamp | Active |
| EV-009 | test-coverage | T20 | 2026-04-14 | `tests/integration/test_e2e.py::test_full_ingestion_to_search_flow` | Sync, analysis, search, curation approval, pattern APIs, rollback, and cleanup all interoperate in one end-to-end workflow | Active |
| EV-010 | live-audit | Phase 22 planning | 2026-05-09 | `docs/tasks_phase22.md §1`, `docs/IMPLEMENTATION_JOURNAL.md §2026-05-09 — Phase 22 Planning` | Primary Google Doc auto-sync is failing because duplicate parsed content aborts ingestion; last successful sync was 2026-04-26 | Active |
| EV-011 | live-audit | Phase 22 planning | 2026-05-09 | `docs/tasks_phase22.md §WS-22.3` | Google Doc contains `5.11.24 запретная рыба`, but the DB/search index does not until sync is repaired | Active |
| EV-012 | planning | Phase 22 planning | 2026-05-09 | `docs/tasks_phase22.md` | Development loop, task order, acceptance criteria, and verification plan for Test 7/8 are documented before implementation | Active |
| EV-013 | live-check | Phase 22 implementation | 2026-05-09 | `docs/retrieval_eval.md §Phase 22 Manual Google Doc Freshness Regression` | Live sync recovered to `synced`; DB/search now finds `5.11.24 запретная рыба` for `сон с рыбой` | Active |
| EV-014 | review | Phase 22 implementation | 2026-05-09 | `docs/archive/PHASE22_REVIEW.md` | Deep review findings, verification commands, live checks, and residual risks for Test 7/8 closure | Active |
| EV-015 | test-coverage | Phase 22 follow-up | 2026-05-14 | `tests/unit/test_auto_sync.py`, `tests/unit/test_assistant_chat.py`, `tests/unit/test_ingest_notify.py`, `tests/integration/test_workers.py` | Multi-doc sync fetches the requested Google Doc ID; sync status hides `job_id`, explains stale/failed/zero-entry states, and notifications use user-readable copy | Active |
| EV-016 | test-coverage | Phase 23 implementation | 2026-05-15 | `tests/unit/test_assistant_chat.py`, `tests/unit/test_telegram_bot.py`, `tests/unit/test_feedback_capture.py`, `tests/unit/test_segmentation.py`, `tests/unit/test_rag_query.py`, `tests/unit/test_config.py`, full `tests/unit` | Full dream text is not truncated, long Telegram replies split safely, English/manual headings parse, English exact FTS is present, numeric feedback is disabled by default, and full unit suite passes | Active |
| EV-017 | review | Phase 23 implementation | 2026-05-15 | `docs/archive/PHASE23_REVIEW.md` | Deep review found no P0/P1/P2 issues for Test 9 closure and records residual risks | Active |
| EV-018 | test-coverage | Phase 24 implementation | 2026-05-20 | `tests/unit/test_assistant_facade.py`, `tests/unit/test_assistant_chat.py`, `tests/unit/test_assistant_session.py`, full `tests/unit` | Missing-title dream saves use LLM title generation, model-supplied implicit titles are ignored, and dream-set pattern analysis loads full texts automatically | Active |
| EV-019 | test-coverage | Phase 25 implementation | 2026-05-20 | `tests/unit/test_gdocs_client.py`, `tests/unit/test_assistant_facade.py`, `tests/unit/test_assistant_chat.py`, `tests/unit/test_telegram_bot.py`, full `tests/unit` | Short numeric save dates parse, backdated Google Doc entries are inserted before later dated headings/paragraphs, duplicate archive dreams can be written to Google Doc again, and the full unit suite passes | Active |

---

---

## Trust Levels

Evidence and model output in this system carry three distinct trust levels. These must not be conflated.

### 1. Archive evidence

Source: local PostgreSQL archive.
Trust level: **high**.
Description: results retrieved from `dream_entries`, `dream_themes`, `dream_chunks`, and related tables via RAG query or direct lookup. This content has been ingested from the user's own journal and, where applicable, curated via the approval and versioning pipeline. It is the canonical system of record.

### 2. Inducted motifs

Source: Phase 9 motif induction pipeline (model-derived).
Trust level: **medium**.
Description: abstract motif labels produced by `MotifInductor` from concrete imagery in a dream entry. These are computational abstractions, not curated facts. They are stored in `motif_inductions`, never in `dream_themes`. Default status is `draft`. A motif must be explicitly confirmed by the user before carrying any weight in analysis. The assistant must always present inducted motifs as model suggestions, not as conclusions. Confidence values: `high`, `moderate`, `low` — but even `high` confidence here means high confidence in the model's abstraction, not high confidence that the motif is analytically correct.

### 3. External research

Source: Phase 10 external search API (internet sources).
Trust level: **explicitly low / speculative**.
Description: structural parallels retrieved by `ResearchRetriever` from external mythology, folklore, and cultural material. This content is never verified against the archive. It is always labeled as external and unverified. Confidence vocabulary is restricted to: `speculative`, `plausible`, `uncertain`. The words `confirmed` and `high confidence` are prohibited for research results. Source URL and retrieval timestamp are required on every item. Research results must never be presented as findings.

---

## Rules

- Append entries; do not delete or update existing rows.
- Every entry must point to a canonical artifact (test file, eval doc, review report).
- "Status: Pending" = the task that produces this evidence has not yet completed.
- "Status: Active" = the artifact exists and was verified in the cited review cycle.
- "Status: Superseded" = a newer artifact replaces this one (link to the replacement).
