---
# STRATEGY_NOTE — Phase 2 Review
_Date: 2026-04-12 · Reviewing: Phase 2 (T06–T09) → Phase 3 (T10–T12)_

## Recommendation: Proceed

## Check Results

| Check | Verdict | Notes |
|-------|---------|-------|
| Phase coherence | COHERENT | Phase 3 goal: segment corpus is indexed, hybrid retrieval works, `insufficient_evidence` path is tested and mandatory, retrieval evaluation baseline is recorded. T10 (rag:ingestion — chunk/embed/index), T11 (rag:query — hybrid retrieval/evidence assembly/staleness), T12 (rag:query — 10-query eval dataset, baseline metrics) map directly and completely to that goal. Dependency chain T10→T11→T12 is correctly ordered. No task addresses a concern outside Phase 3's business goal; no required RAG task is missing. |
| Open findings gate | CLEAR | CODEX_PROMPT.md Fix Queue = "empty". No P0 or P1 findings exist. Open findings are CODE-2, CODE-3, CODE-4, CODE-5, CODE-6 (all P2) and CODE-7, CODE-8, CODE-10 (all P3). None are P0 or P1; the gate is not blocked. |
| Architectural drift | ALIGNED | T06 delivered `app/services/segmentation.py` (deterministic boundary detection + LLM fallback), T07 delivered `app/services/taxonomy.py` and migration `002_seed_categories.py` (approval state machine + 10 seeded active categories), T08 delivered `app/llm/theme_extractor.py` and `app/services/analysis.py` (LLM extraction → draft DreamTheme records), T09 delivered `app/llm/grounder.py` (salience ranking + fragment grounding). All four components are declared in ARCHITECTURE.md §Component Table with correct file paths and responsibilities. Test baseline grew from 17 passing (end of Phase 1) to 32 passing, 4 skipped — consistent with the four tasks and the skipped live-API integration tests. No undeclared components were introduced. |
| Solution shape / governance / runtime drift | ALIGNED | T06: deterministic primary segmentation with LLM fallback only when the deterministic pass finds 0 boundaries in a document > 1000 words — matches ARCHITECTURE.md §Deterministic vs LLM-Owned Subproblems. T07: human approval required before promote/rename/merge/delete — satisfies Standard governance and all five Human Approval Boundaries declared in ARCHITECTURE.md. T08: all LLM-generated theme assignments stored with `status='draft'`; no draft auto-promoted — satisfies Minimum Viable Control Surface. T09: claude-sonnet-4-6 used for salience ranking and fragment grounding — matches ARCHITECTURE.md §Inference / Model Strategy. No agent loops, dynamic tool selection, shell mutation, package installation, or privileged runtime behavior was introduced. Workflow shape is maintained. |
| ADR compliance | N/A | `docs/adr/` does not exist; no ADRs have been filed. No architectural decision changes occurred during Phase 2 that would require an ADR under current rules. |
| RAG Profile gate | READY | Phase 3 correctly carries T10 tagged `rag:ingestion` and T11/T12 tagged `rag:query`. CODEX_PROMPT.md RAG State block is accurate: corpus declared but not yet chunked, embedded, or indexed; no retrieval baseline exists; index schema v1 declared but not yet implemented; next RAG tasks = T10/T11/T12. `docs/retrieval_eval.md` is initialized with the schema, corpus description, and evaluation dataset template — this is the correct state before T10 (the baseline is established in T12, not before). No RAG-specific risks (stale index, schema drift, missing `insufficient_evidence` path) can arise before Phase 3: retrieval components do not yet exist. The `insufficient_evidence` path is scheduled and tested in T11-AC2; its mandatory status is explicit in ARCHITECTURE.md §RAG Architecture. One pre-phase-3 attention item is noted in Warnings. |

## Findings / Blockers

_None. All checks passed. No blockers._

## Warnings

1. **CODE-8 should be resolved before T10 begins** — `DreamTheme.fragments` has no `server_default='[]'::jsonb` (CODEX_PROMPT.md CODE-8, P3, open). T10 does not directly insert `DreamTheme` records, but T10's integration tests run against the same schema. If T08-produced rows with null `fragments` are present when T10 executes JSONB queries that assume non-null fragments, silent failures are possible. Resolve CODE-8 (add `server_default` in a migration patch) as the first act of Phase 3, before T10's implementation begins.

2. **CODE-2 (P2) should be resolved early in Phase 3** — `GDocsClient` non-auth `HttpError` branch is untested (`tests/unit/test_gdocs_client.py`). T10 depends on T05 (`GDocsClient`), and the ingestion worker path calls `fetch_document()`. An unexercised error branch in a direct dependency of a phase's first task is a latent risk. Fixing CODE-2 before T10 is complete is recommended.

3. **ADR directory still absent** — `docs/adr/` does not exist. ARCHITECTURE.md §Continuity and Retrieval Model lists it as a canonical truth artifact. Phase 3 introduces the first concrete index schema version (v1) and fixes the embedding model (`text-embedding-3-small`). If either changes mid-phase (e.g., embedding model swap, chunking strategy revision, relevance threshold change), an ADR is required. The directory should be created before such a decision arises. T10 notes the index schema version must be stored in a config constant — if that constant is changed before a baseline is recorded, an ADR must accompany the change.

4. **CI has still not run against the repository** — CODEX_PROMPT.md records "Last CI run: not yet configured". Phase 3 carries the first `rag:*` tagged tasks; the post-task protocol requires evaluation before marking them DONE. CI green is the phase gate for Phase 1 and is a prerequisite for reliable test baselines throughout. At minimum, Phase 3 should not close its gate without a successful GitHub Actions run.

5. **Retrieval evaluation baseline is Phase 3's only hard gate on retrieval quality** — `docs/retrieval_eval.md` contains no measured metrics; all entries are TBD or blank. T12 establishes the baseline and closes the Phase 3 gate. Any schedule compression that defers T12 would leave the project without a measured retrieval baseline before Phase 4's API layer exposes search to the user. T12 must not be skipped or deferred.
---
