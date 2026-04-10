# Feature Specification — Dream Motif Interpreter

Version: 1.0
Last updated: 2026-04-10
Status: Draft

---

## Overview

Dream Motif Interpreter is a personal analytical tool for a single user who maintains a long-form dream journal in Google Docs. The system ingests the journal, segments it into individual dream records, assigns structured thematic labels to each dream, links those labels to supporting text fragments, and enables thematic retrieval and archive-level pattern analysis. All AI-generated outputs are explicitly framed as interpretations, not authoritative conclusions.

---

## User Roles

| Role | Description | Permissions |
|------|-------------|-------------|
| Owner | The journal author and primary user | Full access: browse, search, review drafts, approve/reject themes, curate taxonomy, trigger sync |
| Curator | Same user acting in a curation context | Approve/reject draft theme assignments; promote/rename/delete theme categories; approve bulk relabeling |

In v1, both roles are the same person. The distinction exists to make the approval boundaries explicit in the code and UI.

---

## Feature Areas

### 1. Journal Ingestion and Sync

**Description**
The system fetches the user's Google Docs dream journal, segments it into individual dream entries, extracts metadata, and stores records in the archive. Sync is triggered manually or on a schedule. Ingestion is idempotent: re-syncing the same content produces no duplicate records.

**Acceptance Criteria**

1. `POST /sync` enqueues an ingestion job; returns `{"job_id": "...", "status": "queued"}` with HTTP 202.
2. `GET /sync/{job_id}` returns the current job status (`queued`, `running`, `done`, `failed`) and a count of new entries found.
3. After sync completes, each dream entry appears in `GET /dreams` with fields: `id`, `date`, `title`, `raw_text`, `word_count`, `source_doc_id`, `created_at`.
4. Re-syncing a document with no new content produces 0 new entries (deduplication by content hash).
5. If the Google Docs API returns an error, the job status is `failed` with an error message; no partial records are saved.

**Out of scope for v1**
- Automatic scheduled sync (v1 is manual trigger only)
- Sync from sources other than Google Docs
- Deletion of entries detected as removed from the source document

---

### 2. Dream Segmentation

**Description**
Raw document text is split into individual dream entries. Boundaries are detected deterministically (date headers, explicit delimiter lines). For ambiguous boundaries, an LLM call resolves the ambiguity. Each entry is stored as a discrete record with a detected date and optional title.

**Acceptance Criteria**

1. A document with N entries separated by date headers in `YYYY-MM-DD` format is segmented into exactly N `DreamEntry` records.
2. A document with no recognizable date headers results in a single `DreamEntry` record for the entire text, flagged with `segmentation_confidence=low`.
3. Duplicate entries (same content hash as an existing record) are skipped, not duplicated.
4. Each `DreamEntry` record has: `id`, `date` (parsed from header or `null`), `title`, `raw_text`, `word_count`, `segmentation_confidence` (`high` / `low`).

**Out of scope for v1**
- Automatic merging of entries split across multiple sections
- Segmentation from non-text sources

---

### 3. Theme Taxonomy Management

**Description**
The system maintains a semi-structured taxonomy of theme categories. Categories may be predefined or suggested by the LLM. A category has a name, description, and status (`active`, `suggested`, `deprecated`). Only the user (Curator role) may promote `suggested` to `active`, rename, merge, or delete categories. The taxonomy is versioned: all mutations are logged.

**Acceptance Criteria**

1. `GET /themes/categories` returns all categories with fields: `id`, `name`, `description`, `status`, `created_at`, `dream_count`.
2. `POST /themes/categories` with `{"name": "...", "description": "..."}` creates a category with `status=suggested`; returns HTTP 201 with the new record.
3. `PATCH /themes/categories/{id}/approve` transitions `suggested` → `active`; requires Curator role; returns HTTP 200.
4. `DELETE /themes/categories/{id}` transitions status to `deprecated` (soft delete); returns HTTP 200; associated dream themes retain the deprecated category ID with a deprecation flag.
5. Renaming a category via `PATCH /themes/categories/{id}` writes an `AnnotationVersion` record capturing the old name before the change.
6. `GET /themes/categories/{id}/history` returns the mutation log for that category in reverse-chronological order.

**Out of scope for v1**
- Automatic category merging without user approval
- Hierarchical (nested) category structure

---

### 4. Per-Dream Theme Extraction

**Description**
For each dream entry, the system generates a multi-label thematic profile: a list of theme categories with a salience score (0.0–1.0), ranked by importance, and linked to supporting text fragments. All assignments begin with `status=draft` and must be confirmed by the user before they become stable.

**Acceptance Criteria**

1. After ingestion, each `DreamEntry` has an associated `DreamTheme` set with at least one entry (or a `no_themes_found` flag if the LLM returns no themes above the threshold).
2. Each `DreamTheme` record has: `dream_id`, `category_id`, `salience` (0.0–1.0), `status` (`draft`), `match_type` (`literal` / `semantic` / `symbolic`), `fragments` (list of text spans from the dream entry).
3. `GET /dreams/{id}/themes` returns all theme assignments for a dream, sorted by `salience` descending.
4. Theme extraction for a dream that is re-processed produces the same top-3 themes in ≥80% of re-runs (consistency check; tested by running extraction twice on the same fixed input via the LLM client test double).
5. LLM-generated theme assignments reference only categories that exist in the taxonomy (no hallucinated category IDs).

**Out of scope for v1**
- Fully automated promotion of draft themes (always requires user confirmation)
- Theme extraction for entries longer than 8,000 tokens in a single LLM call (chunked path is v2)

---

### 5. Theme Curation

**Description**
The user reviews draft theme assignments and either confirms or rejects them. Confirmed themes become `status=confirmed`. The user may also manually add, edit, or remove theme assignments. All changes are versioned.

**Acceptance Criteria**

1. `PATCH /dreams/{id}/themes/{theme_id}/confirm` transitions `draft` → `confirmed`; returns HTTP 200.
2. `PATCH /dreams/{id}/themes/{theme_id}/reject` transitions `draft` → `rejected`; returns HTTP 200; rejected themes are excluded from retrieval and pattern analysis.
3. `POST /dreams/{id}/themes` with `{"category_id": "...", "salience": 0.8, "match_type": "symbolic", "fragments": [...]}` creates a manual theme assignment with `status=confirmed` directly.
4. `DELETE /dreams/{id}/themes/{theme_id}` removes the assignment; an `AnnotationVersion` record captures the state before deletion.
5. `GET /dreams/{id}/themes/history` returns the full version history of theme assignments for that dream in reverse-chronological order.
6. Bulk confirmation of more than 1 dream at once requires the Curator role approval flow: `POST /curate/bulk-confirm` returns `{"requires_approval": true, "token": "..."}` and does not apply until `POST /curate/bulk-confirm/{token}/approve` is called.

**Out of scope for v1**
- Automated confirmation based on confidence score alone

---

### 6. Semantic and Thematic Retrieval

**Description**
The user can search the archive by thematic query (including metaphorical matches) and receive a list of matching dream entries with the relevant fragments highlighted. Retrieval is hybrid: lexical + embedding-based. If no evidence meets the relevance threshold, the system returns `insufficient_evidence` rather than fabricating a result.

**Acceptance Criteria**

1. `GET /search?q=<query>` returns up to 5 dream entries ranked by relevance, each with: `dream_id`, `date`, `title`, `matched_fragments` (text spans), `relevance_score`, `theme_matches` (associated confirmed themes).
2. A query that matches no entries above the relevance threshold returns `{"result": "insufficient_evidence", "query": "..."}` with HTTP 200 (not an error).
3. `GET /search?q=<query>&theme_ids=<id1>,<id2>` filters results to entries that have at least one confirmed theme in the provided list.
4. `GET /search?q=<query>&date_from=YYYY-MM-DD&date_to=YYYY-MM-DD` filters results to entries within the date range.
5. Query expansion (metaphor-aware) is applied before retrieval; the response includes `{"expanded_terms": [...]}` for transparency.
6. Retrieval p95 latency is below 3 seconds for the standard query path (measured in integration tests against a seeded corpus of 50 entries).

**Out of scope for v1**
- Full-text search UI (API only in v1)
- Image or multimedia retrieval

---

### 7. Archive-Level Pattern Analysis

**Description**
The system detects recurring motifs, dominant themes, and co-occurrence patterns across the full archive. Results are presented as suggestions for the user to review, not conclusions. The system may suggest new theme categories based on detected clusters.

**Acceptance Criteria**

1. `GET /patterns/recurring` returns theme categories sorted by frequency of appearance across confirmed dream themes, with appearance count and percentage of dreams.
2. `GET /patterns/co-occurrence` returns pairs of theme categories that appear together in the same dream, sorted by co-occurrence count.
3. `GET /patterns/timeline?theme_id=<id>` returns a time-series of salience scores for the specified theme across all dreams with that theme, sorted by dream date.
4. `GET /patterns/suggested-categories` returns LLM-suggested new theme categories based on clustering of unthemed or low-confidence entries; each suggestion has a `rationale` field and `status=suggested`.
5. All pattern analysis results include a `generated_at` timestamp and a disclaimer field: `"interpretation_note": "These are computational patterns, not authoritative interpretations."`.

**Out of scope for v1**
- Interactive visualization (API data only)
- Real-time pattern updates (computed on request or scheduled)

---

### § Retrieval

**Sources indexed:** Dream entry text, including raw narrative and confirmed theme annotations.

**Query types supported:**
- Simple keyword — literal match in dream text
- Semantic — embedding similarity over dream chunks
- Thematic — filter by one or more confirmed theme category IDs
- Hybrid — combination of semantic + lexical (default)
- Metaphor-aware — LLM-expanded query terms (automatic for all search requests)

**Citation format:** Each returned entry includes `matched_fragments`: a list of text spans from the original dream entry that matched the query, with character offsets and a `match_type` label (`literal` / `semantic`).

**`insufficient_evidence` behavior:** When 0 chunks survive the relevance threshold (default 0.35), the system returns `{"result": "insufficient_evidence", "query": "..."}` with HTTP 200. No fallback answer is generated. The `expanded_terms` field is still included for debugging.

---

## Non-Goals (v1)

- Clinical diagnosis, psychiatric assessment, or therapeutic guidance
- Authoritative interpretation of dream symbolism
- Multi-user journals or collaborative features
- Social sharing or public export
- Mobile application
- Real-time sync or push notifications
- Automated taxonomy evolution without user approval
