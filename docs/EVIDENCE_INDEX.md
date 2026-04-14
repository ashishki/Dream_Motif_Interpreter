# Evidence Index — Dream Motif Interpreter

Version: 1.0
Last updated: 2026-04-14
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

---

## Rules

- Append entries; do not delete or update existing rows.
- Every entry must point to a canonical artifact (test file, eval doc, review report).
- "Status: Pending" = the task that produces this evidence has not yet completed.
- "Status: Active" = the artifact exists and was verified in the cited review cycle.
- "Status: Superseded" = a newer artifact replaces this one (link to the replacement).
