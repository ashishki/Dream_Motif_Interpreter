# Phase 13 Deep Review Report

Date: 2026-04-24
Phase: 13 — Multi-source, Search Recall, UX Polish (Тест 2)
Workstreams: WS-13.1 through WS-13.8
Reviewers: META · ARCH · CODE · CONSOLIDATED (4-agent deep review)

---

## Overall Verdict: PASS (all defects closed)

D2 fixed before release. D1/D3/D4/D5 fixed in follow-up commit (2026-04-24).

---

## META Review: PASS

All 8 workstreams complete. All acceptance criteria met.

| Workstream | Status |
|---|---|
| WS-13.1 Multi-source config (GOOGLE_DOC_IDS, get_all_doc_ids) | COMPLETE |
| WS-13.2 manage_archive_source list/add/remove | COMPLETE |
| WS-13.3 Terminology: архив/база = Google Docs | COMPLETE |
| WS-13.4 Rating prompt Russian localization | COMPLETE |
| WS-13.5 search_dreams_exact (pure FTS, no threshold) | COMPLETE |
| WS-13.6 Quote extraction per search result | COMPLETE |
| WS-13.7 RESULT_LIMIT=20, multi-fragment grouping | COMPLETE |
| WS-13.8 SYSTEM_PROMPT updates for new tools and formats | COMPLETE |

Test baseline: 294 unit tests passing (up from 276 at Phase 12 start).

---

## ARCH Review: PASS

No architectural issues. Key confirmations:

- Config override pattern (_google_doc_ids_override module-level global) is correct for single-process deployment.
- search_dreams grouping preserves descending score order (Python dict insertion order = DB result order).
- Frozen dataclass mutation handled correctly (new instance created, not mutated).
- exact_search SQL uses parameterized queries — no SQL injection risk.
- SearchResultItem.quote None-safety handled in both tool output paths.
- search_dreams_exact bypass of InsufficientEvidence is intentional and clean.

---

## CODE Review: 5 defects found

### D2 — BLOCK (fixed before release)

trigger_sync tool schema had doc_id in "required" list but facade accepts doc_id as optional
(default empty string = sync all sources). Claude would always be forced to provide a doc_id,
breaking the "sync all sources" use case.

Fix applied: app/assistant/tools.py — removed doc_id from "required": [], updated description
to document the omit-to-sync-all behavior.

### D1 — DEFER (pre-existing, not a Phase 13 regression)

FTS ranking language mismatch in hybrid search CTE (query.py): WHERE uses 'russian' morphology
but ORDER BY ts_rank_cd uses 'english'. Results enter the pool correctly (Russian WHERE), but
rank order may be suboptimal. Phase 13 added search_dreams_exact with correct Russian morphology
throughout — provides the correct path for word-level searches. Defer to Phase 14.

### D3 — DEFER (Phase 13 regression, cosmetic impact)

When search_dreams groups multiple chunks from the same dream, the quote field is preserved
from the first chunk even after chunk_text is merged. The quote may not correspond to the merged
text. Impact is cosmetic — quotes are advisory. Defer to Phase 14.

### D4 — DEFER (Phase 13 regression, known limitation)

_extract_quote uses substring matching (word in sentence_lower) rather than word-boundary
matching. Russian morphology makes strict word boundaries non-trivial without a full morphological
analyzer (e.g. pymorphy2). The false positive rate is low in practice. Defer to Phase 14.

### D5 — DEFER (Phase 13 regression, edge case)

_parse_google_doc_ids validator strips elements for CSV strings but not for list input. Only
manifests if a list with whitespace elements is provided programmatically (not via env var). Defer.

---

## Deferred Fixes (all closed 2026-04-24)

- D1: Fixed — ts_rank_cd now uses 'russian' morphology in fts_candidates CTE
- D3: Fixed — quote re-extracted from merged chunk_text after grouping
- D4: Fixed — _extract_quote uses Cyrillic-safe word-boundary regex lookaround
- D5: Fixed — _parse_google_doc_ids normalizes list elements (strip + type filter)

---

## Commits included in Phase 13

- aee4135 feat(phase13/ws-13.2+13.3+13.4): multi-doc archive management, terminology, rating prompt
- 6af110b feat(phase13/ws-13.5+13.6): exact FTS search tool with Russian morphology and quote extraction
- 9c781f0 feat(phase13/ws-13.7+13.8): increase result limit, group multi-fragment search results, finalize prompt
- d8333dc fix(phase13/review): trigger_sync schema — doc_id is optional, not required
- c05a573 fix(phase13/deferred): close D1/D3/D4/D5 from deep review
